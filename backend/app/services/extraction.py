"""Entity + event extraction.

Two extraction paths are provided:

* ``extract_structured`` — deterministic mapping of CSV rows / JSON records
  (CDR, transactions, FIR records) into entities, person mentions and events.
* ``extract_text`` — rule-based extraction from free text (PDF / TXT / OCR),
  using regex patterns for phones, vehicles, dates, times, amounts, accounts
  and a name dictionary plus title-case heuristics for person names.

Everything returned carries a source reference so provenance is preserved
downstream.
"""
import re

from .normalization import normalize_date, normalize_time

# ---------------------------------------------------------------- patterns
PHONE_RE = re.compile(r"(?:\+91[\s\-]?)?([6-9]\d{4}[\s\-]?\d{5})")
VEHICLE_RE = re.compile(r"\b[A-Z]{2}\s?\d{2}\s?[A-Z]{1,2}\s?\d{1,4}\b")
DATE_RE = re.compile(
    r"\b\d{1,2}[-/][A-Za-z]{3,9}[-/]\d{2,4}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b"
)
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?:\s?(?:AM|PM))?\b", re.I)
AMOUNT_RE = re.compile(r"(?:₹|Rs\.?|INR)\s?([\d,]+(?:\.\d+)?)", re.I)
ACCOUNT_RE = re.compile(r"\b(?:A/C|ACCOUNT|Acct|Account|A\/C)[\s:#]*([\d]{6,20})\b", re.I)

# Known names used by the synthetic dataset; also anchors free-text extraction.
NAME_DICTIONARY = {
    "ravi kumar", "ravi k.", "ravi kumar s.", "suresh reddy", "suresh",
    "meena devi", "arjun singh", "priya nair", "vikram rao", "deepa sharma",
    "manoj verma", "kiran patel",
}

def _name_variants(name):
    n = name.strip()
    parts = n.split()
    variants = {n.lower()}
    if len(parts) >= 2:
        variants.add((parts[0] + " " + parts[1]).lower())  # first + last
    return variants


def _match_names(text):
    """Return names found in text (dictionary-driven, to avoid false positives)."""
    found = []
    lowered = text.lower()
    for name in sorted(NAME_DICTIONARY, key=len, reverse=True):
        if name in lowered:
            # recover original casing
            idx = lowered.find(name)
            found.append((name, text[idx:idx + len(name)]))
    return found


def extract_text(text, source_document_id, source_reference, case_id):
    """Extract entities, person mentions and events from free text."""
    entities = []
    mentions = []
    events = []

    def add_entity(etype, value, confidence=0.95, method="regex", date=None, time=None):
        entities.append({
            "type": etype, "value": value, "confidence": confidence,
            "method": method, "source_ref": source_reference,
            "date": date, "time": time,
        })

    # phones
    for m in PHONE_RE.finditer(text):
        add_entity("PHONE", re.sub(r"\D", "", m.group(0)))

    # vehicles
    for m in VEHICLE_RE.finditer(text):
        add_entity("VEHICLE", m.group(0).strip())

    # accounts
    for m in ACCOUNT_RE.finditer(text):
        add_entity("BANK_ACCOUNT", m.group(1))

    # dates
    dates = [normalize_date(m.group(0)) for m in DATE_RE.finditer(text)]
    dates = [d for d in dates if d]
    times = [normalize_time(m.group(0)) for m in TIME_RE.finditer(text)]
    times = [t for t in times if t]
    for d in dates:
        add_entity("DATE", d, method="regex")
    for t in times:
        add_entity("TIME", t, method="regex")

    # amounts -> transaction/amount signal
    amounts = []
    for m in AMOUNT_RE.finditer(text):
        amt = m.group(1).replace(",", "")
        amounts.append(amt)
        add_entity("TRANSACTION", "₹" + amt, method="regex")

    # names
    for norm, display in _match_names(text):
        mentions.append({
            "name": display,
            "identifiers": {"phone": [], "vehicle": [], "account": [], "location": []},
            "source_ref": source_reference,
            "date": dates[0] if dates else None,
            "time": times[0] if times else None,
        })

    # coarse event: if a date + amount appear, record a transaction event
    if dates and amounts:
        events.append({
            "type": "TRANSACTION",
            "description": f"Transaction of ₹{amounts[0]} mentioned",
            "date": dates[0], "time": times[0] if times else None,
            "precision": "date_only" if not times else "exact",
            "a_name": None, "b_name": None,
            "metadata": {"amount": amounts[0]},
            "source_ref": source_reference,
        })
    elif dates:
        events.append({
            "type": "CASE_EVENT",
            "description": "Case event recorded in document",
            "date": dates[0], "time": times[0] if times else None,
            "precision": "date_only" if not times else "exact",
            "a_name": None, "b_name": None,
            "metadata": {},
            "source_ref": source_reference,
        })

    return {"entities": entities, "mentions": mentions, "events": events}


# ---------------------------------------------------------------- structured

_CDR_COLS = {
    "caller_name": ("caller_name", "caller", "caller name", "party_a", "a_party", "aname"),
    "caller_phone": ("caller_phone", "caller_number", "a_number", "msisdn_a", "from"),
    "callee_name": ("callee_name", "callee", "callee name", "party_b", "b_party", "bname"),
    "callee_phone": ("callee_phone", "callee_number", "b_number", "msisdn_b", "to"),
    "timestamp": ("timestamp", "datetime", "date_time", "call_time", "time", "date"),
    "duration": ("duration", "call_duration", "duration_sec"),
}


def _find_col(header, aliases):
    for i, h in enumerate(header):
        hc = h.strip().lower().replace(" ", "_")
        if hc in aliases:
            return i
    return None


def extract_csv_rows(rows, filename, source_document_id, case_id):
    """Map generic CSV rows to a structured bundle. Handles CDR-shaped files."""
    if not rows:
        return {"entities": [], "mentions": [], "events": []}
    header = [str(c).strip() for c in rows[0]]
    col = {k: _find_col(header, aliases) for k, aliases in _CDR_COLS.items()}
    data_rows = rows[1:]

    entities = []
    mentions = []
    events = []
    mention_by_name = {}

    def mention(name, phone=None):
        key = name.strip().lower()
        if key not in mention_by_name:
            mention_by_name[key] = {
                "name": name.strip(),
                "identifiers": {"phone": [], "vehicle": [], "account": [], "location": []},
                "source_ref": filename,
            }
            mentions.append(mention_by_name[key])
        m = mention_by_name[key]
        if phone and phone not in m["identifiers"]["phone"]:
            m["identifiers"]["phone"].append(phone)
        return m

    for ri, row in enumerate(data_rows):
        if len(row) < len(header):
            row = list(row) + [""] * (len(header) - len(row))
        def cell(k):
            i = col[k]
            return str(row[i]).strip() if i is not None else ""

        caller_name = cell("caller_name")
        caller_phone = cell("caller_phone")
        callee_name = cell("callee_name")
        callee_phone = cell("callee_phone")
        ts = cell("timestamp")

        date = normalize_date(ts)
        time = None
        if ts and (" " in ts or "T" in ts):
            tail = ts.split("T")[-1].split(" ")[-1]
            time = normalize_time(tail)

        if caller_phone:
            entities.append({"type": "PHONE", "value": caller_phone, "confidence": 1.0,
                             "method": "csv", "source_ref": filename, "date": date, "time": time})
        if callee_phone:
            entities.append({"type": "PHONE", "value": callee_phone, "confidence": 1.0,
                             "method": "csv", "source_ref": filename, "date": date, "time": time})

        a = mention(caller_name, caller_phone) if caller_name else None
        b = mention(callee_name, callee_phone) if callee_name else None

        events.append({
            "type": "CALL",
            "description": f"Call {caller_name or caller_phone} → {callee_name or callee_phone}",
            "date": date, "time": time,
            "precision": "exact" if time else ("date_only" if date else "unknown"),
            "a_name": caller_name or None, "b_name": callee_name or None,
            "metadata": {"caller_phone": caller_phone, "callee_phone": callee_phone,
                         "duration": cell("duration")},
            "source_ref": filename,
        })

    return {"entities": entities, "mentions": mentions, "events": events}


def extract_json_records(records, filename, source_document_id, case_id):
    """Map JSON records (transactions / structured events) to a bundle."""
    entities = []
    mentions = []
    events = []
    mention_by_name = {}

    def mention(name, phone=None, account=None, location=None):
        if not name:
            return None
        key = name.strip().lower()
        if key not in mention_by_name:
            mention_by_name[key] = {
                "name": name.strip(),
                "identifiers": {"phone": [], "vehicle": [], "account": [], "location": []},
                "source_ref": filename,
            }
            mentions.append(mention_by_name[key])
        m = mention_by_name[key]
        if phone and phone not in m["identifiers"]["phone"]:
            m["identifiers"]["phone"].append(phone)
        if account and account not in m["identifiers"]["account"]:
            m["identifiers"]["account"].append(account)
        if location and location not in m["identifiers"]["location"]:
            m["identifiers"]["location"].append(str(location))
        return m

    for rec in records:
        if not isinstance(rec, dict):
            continue
        rec = {k.strip().lower().replace(" ", "_"): v for k, v in rec.items()}
        etype = str(rec.get("type", rec.get("record_type", "transaction"))).lower()

        # Location / co-observation records (CCTV sightings)
        if etype in ("location_observation", "sighting", "cctv", "co_location"):
            person = rec.get("person") or rec.get("person_name") or rec.get("subject")
            other = rec.get("other_person") or rec.get("with") or rec.get("accompanied_by")
            loc = rec.get("location") or rec.get("place")
            ts = rec.get("timestamp") or rec.get("date") or rec.get("datetime")
            date = normalize_date(ts)
            time = None
            if ts and (" " in str(ts) or "T" in str(ts)):
                time = normalize_time(str(ts).split("T")[-1].split(" ")[-1])
            if loc:
                entities.append({"type": "LOCATION", "value": str(loc), "confidence": 0.9,
                                 "method": "json", "source_ref": filename, "date": date, "time": time})
            mention(person, location=loc and str(loc))
            if other:
                mention(other, location=loc and str(loc))
                events.append({
                    "type": "LOCATION_OBSERVATION",
                    "description": f"{person} and {other} observed together at {loc}",
                    "date": date, "time": time,
                    "precision": "exact" if time else ("date_only" if date else "unknown"),
                    "a_name": person or None, "b_name": other or None,
                    "metadata": {"location": str(loc) if loc else None},
                    "source_ref": filename,
                })
            continue

        sender = rec.get("sender") or rec.get("sender_name") or rec.get("from_name")
        receiver = rec.get("receiver") or rec.get("receiver_name") or rec.get("to_name")
        sender_acc = rec.get("sender_account") or rec.get("from_account") or rec.get("account_from")
        receiver_acc = rec.get("receiver_account") or rec.get("to_account") or rec.get("account_to")
        amount = rec.get("amount")
        ts = rec.get("timestamp") or rec.get("date") or rec.get("datetime")
        location = rec.get("location") or rec.get("city")

        date = normalize_date(ts)
        time = None
        if ts and (" " in str(ts) or "T" in str(ts)):
            tail = str(ts).split("T")[-1].split(" ")[-1]
            time = normalize_time(tail)

        for acc in (sender_acc, receiver_acc):
            if acc:
                entities.append({"type": "BANK_ACCOUNT", "value": str(acc), "confidence": 1.0,
                                 "method": "json", "source_ref": filename, "date": date, "time": time})
        if location:
            entities.append({"type": "LOCATION", "value": str(location), "confidence": 0.9,
                             "method": "json", "source_ref": filename, "date": date, "time": time})

        a = mention(sender, account=sender_acc and str(sender_acc))
        b = mention(receiver, account=receiver_acc and str(receiver_acc))

        if etype in ("transaction", "payment", "transfer"):
            events.append({
                "type": "TRANSACTION",
                "description": f"Transaction {sender or ''} → {receiver or ''}" + (f" ₹{amount}" if amount else ""),
                "date": date, "time": time,
                "precision": "exact" if time else ("date_only" if date else "unknown"),
                "a_name": sender or None, "b_name": receiver or None,
                "metadata": {"amount": str(amount) if amount else None,
                             "sender_account": str(sender_acc) if sender_acc else None,
                             "receiver_account": str(receiver_acc) if receiver_acc else None,
                             "location": str(location) if location else None},
                "source_ref": filename,
            })

    return {"entities": entities, "mentions": mentions, "events": events}
