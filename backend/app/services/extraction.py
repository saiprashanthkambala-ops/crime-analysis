"""Entity + event extraction.

Two extraction paths are provided:

* ``extract_structured`` — deterministic mapping of CSV rows / JSON records
  (CDR, transactions, FIR records) into entities, person mentions and events.
  CSV columns can be mapped to canonical Crime Analysis fields (see
  services/dataset_import.py); when no mapping is supplied the columns are
  auto-detected from the header.
* ``extract_text`` — rule-based extraction from free text (PDF / TXT / OCR),
  using regex patterns for phones, vehicles, dates, times, amounts, accounts
  and a name dictionary plus title-case heuristics for person names.

Everything returned carries a source reference so provenance is preserved
downstream. Original values are never rewritten in place — normalization
happens separately and the raw value is kept alongside.
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

_TIME_ONLY_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?(?:\s*(?:am|pm))?$", re.I)


def _split_datetime(value):
    """Return (date, time) from a raw datetime/date/time cell value.

    Accepts '20-Aug-2026 10:15', '2026-08-20T10:15:00', '20-Aug-2026', '10:15'.
    Unparseable values stay None — missing information is never invented.
    """
    if value is None:
        return None, None
    s = str(value).strip()
    if not s:
        return None, None
    if _TIME_ONLY_RE.match(s):
        return None, normalize_time(s)
    if "T" in s or " " in s:
        parts = [p for p in re.split(r"[T ]+", s) if p]
        date, time = None, None
        for p in parts:
            if _TIME_ONLY_RE.match(p):
                time = normalize_time(p)
            else:
                date = normalize_date(p)
        return date or None, time or None
    date = normalize_date(s)
    # a date-looking value that normalization could not understand is left
    # unknown rather than mis-filed as a date or time
    if date and not _TIME_ONLY_RE.match(str(date)):
        return date, None
    return None, None


def _merge_into_mention(mention_by_name, name, **identifiers):
    key = name.strip().lower()
    m = mention_by_name.get(key)
    if not m:
        m = {
            "name": name.strip(),
            "identifiers": {"phone": [], "vehicle": [], "account": [], "location": []},
            "source_ref": None,
            "meta": {},
        }
        mention_by_name[key] = m
    for kind, value in identifiers.items():
        if not value:
            continue
        bucket = m["identifiers"].setdefault(kind, [])
        if value not in bucket:
            bucket.append(value)
    return m


def _norm_cell(value):
    """Cell to a comparable string; numbers/None handled safely."""
    if value is None:
        return ""
    return str(value).strip()


def auto_detect_csv_mapping(header):
    """Detect a canonical-field -> column mapping for a CSV header."""
    from .dataset_import import auto_detect_mapping
    return auto_detect_mapping(header)


def extract_csv_rows(rows, filename, source_document_id, case_id, mapping=None):
    """Map CSV rows to a structured bundle.

    ``rows``    : list of parsed rows; row 0 is the header.
    ``mapping`` : optional {canonical_field: column_name}. When omitted (or
                  empty) the header is auto-detected against canonical aliases.
    """
    if not rows:
        return {"entities": [], "mentions": [], "events": [], "warnings": []}
    header = [str(c).strip() for c in rows[0]]
    from .dataset_import import _norm_col_name
    norm_header = [_norm_col_name(c) for c in header]

    if mapping:
        # resolve user mapping values (column names or indexes) to positions
        col_by_field = {}
        for field, colname in mapping.items():
            if isinstance(colname, int) or (isinstance(colname, str)
                                            and colname.strip().isdigit()):
                pos = int(colname)
                if 0 <= pos < len(header):
                    col_by_field[field] = pos
                continue
            try:
                pos = norm_header.index(_norm_col_name(colname))
            except ValueError:
                continue
            col_by_field[field] = pos
    else:
        auto = auto_detect_csv_mapping(header)
        col_by_field = {f: norm_header.index(_norm_col_name(c))
                        for f, c in auto.items()}
    data_rows = rows[1:]

    entities = []
    mentions = []
    events = []
    mention_by_name = {}
    warnings = []

    def value(row, field):
        pos = col_by_field.get(field)
        if pos is None:
            return ""
        # ragged rows are padded the way the legacy pipeline did
        return _norm_cell(row[pos] if pos < len(row) else "")

    def add_entity(etype, raw, method="csv", date=None, time=None, row_no=None):
        if raw == "":
            return
        entities.append({
            "type": etype, "value": raw, "confidence": 1.0,
            "method": method, "source_ref": filename,
            "date": date, "time": time, "row": row_no,
        })

    for ri, row in enumerate(data_rows):
        if len(row) < len(header):
            row = list(row) + [""] * (len(header) - len(row))
        row_no = ri + 2  # 1-based including the header

        # ---- temporal cell handling
        date, time = None, None
        ts = value(row, "timestamp")
        if ts:
            date, time = _split_datetime(ts)
        else:
            d_raw, t_raw = value(row, "date"), value(row, "time")
            if d_raw:
                date, _ = _split_datetime(d_raw)
            if t_raw:
                _, time = _split_datetime(t_raw)

        has_call_shape = any(f in col_by_field for f in
                             ("caller_name", "caller_phone", "callee_name",
                              "callee_phone", "duration"))
        has_txn_shape = any(f in col_by_field for f in
                            ("sender_name", "sender_account", "receiver_name",
                             "receiver_account", "amount", "transaction_id"))

        if has_call_shape:
            caller_name = value(row, "caller_name")
            caller_phone = value(row, "caller_phone")
            callee_name = value(row, "callee_name")
            callee_phone = value(row, "callee_phone")
            duration = value(row, "duration")
            if caller_phone:
                add_entity("PHONE", caller_phone, date=date, time=time, row_no=row_no)
            if callee_phone:
                add_entity("PHONE", callee_phone, date=date, time=time, row_no=row_no)
            if not (caller_name or caller_phone or callee_name or callee_phone):
                continue  # fully empty row — nothing to record
            if caller_name:
                m = _merge_into_mention(mention_by_name, caller_name,
                                        phone=caller_phone or None)
                m["source_ref"] = filename
                m["meta"].setdefault("rows", []).append(row_no)
            if callee_name:
                m = _merge_into_mention(mention_by_name, callee_name,
                                        phone=callee_phone or None)
                m["source_ref"] = filename
                m["meta"].setdefault("rows", []).append(row_no)
            events.append({
                "type": "CALL",
                "description": f"Call {caller_name or caller_phone} → "
                               f"{callee_name or callee_phone}",
                "date": date, "time": time,
                "precision": "exact" if time else ("date_only" if date else "unknown"),
                "a_name": caller_name or None, "b_name": callee_name or None,
                "metadata": {"caller_phone": caller_phone,
                             "callee_phone": callee_phone,
                             "duration": duration,
                             "record_index": row_no},
                "source_ref": filename,
            })
            continue

        if has_txn_shape:
            sender = value(row, "sender_name") or None
            receiver = value(row, "receiver_name") or None
            sender_acc = value(row, "sender_account") or None
            receiver_acc = value(row, "receiver_account") or None
            amount = value(row, "amount") or None
            txn_id = value(row, "transaction_id") or None
            location = value(row, "location") or None
            if sender_acc:
                add_entity("BANK_ACCOUNT", sender_acc, date=date, time=time,
                           row_no=row_no)
            if receiver_acc:
                add_entity("BANK_ACCOUNT", receiver_acc, date=date, time=time,
                           row_no=row_no)
            if location:
                add_entity("LOCATION", location, date=date, time=time, row_no=row_no)
            if not (sender or receiver or sender_acc or receiver_acc or amount
                    or txn_id):
                continue
            if sender:
                m = _merge_into_mention(mention_by_name, sender,
                                        account=sender_acc)
                m["source_ref"] = filename
                m["meta"].setdefault("rows", []).append(row_no)
            if receiver:
                m = _merge_into_mention(mention_by_name, receiver,
                                        account=receiver_acc)
                m["source_ref"] = filename
                m["meta"].setdefault("rows", []).append(row_no)
            desc = f"Transaction {sender or ''} → {receiver or ''}"
            if amount:
                desc += f" ₹{amount}"
            events.append({
                "type": "TRANSACTION",
                "description": desc,
                "date": date, "time": time,
                "precision": "exact" if time else ("date_only" if date else "unknown"),
                "a_name": sender, "b_name": receiver,
                "metadata": {"amount": amount or None,
                             "transaction_id": txn_id,
                             "sender_account": sender_acc,
                             "receiver_account": receiver_acc,
                             "location": location,
                             "record_index": row_no},
                "source_ref": filename,
            })
            continue

        # ---- generic person / property registry rows
        person_name = value(row, "person_name") or None
        phone = value(row, "phone") or None
        vehicle = value(row, "vehicle") or None
        account = value(row, "account") or None
        location = value(row, "location") or None
        has_any = any(v is not None for v in
                      (person_name, phone, vehicle, account, location))
        if not has_any:
            continue
        if phone:
            add_entity("PHONE", phone, date=date, time=time, row_no=row_no)
        if vehicle:
            add_entity("VEHICLE", vehicle, date=date, time=time, row_no=row_no)
        if account:
            add_entity("BANK_ACCOUNT", account, date=date, time=time, row_no=row_no)
        if location:
            add_entity("LOCATION", location, date=date, time=time, row_no=row_no)
        if person_name:
            m = _merge_into_mention(mention_by_name, person_name,
                                    phone=phone, vehicle=vehicle,
                                    account=account, location=location)
            m["source_ref"] = filename
            m["meta"].setdefault("rows", []).append(row_no)
        # A dated row is a real observation from the dataset: surface it on the
        # timeline as a record event. Undated rows only register identifiers.
        if date and (person_name or phone or vehicle or account or location):
            events.append({
                "type": "CASE_EVENT",
                "description": "Dataset record" + (f" — {person_name}" if person_name
                                                   else " — " + (phone or vehicle
                                                                 or account
                                                                 or location)),
                "date": date, "time": time,
                "precision": "exact" if time else ("date_only" if date else "unknown"),
                "a_name": person_name,
                "b_name": None,
                "metadata": {"phone": phone or None, "vehicle": vehicle or None,
                             "account": account or None, "location": location or None,
                             "record_index": row_no},
                "source_ref": filename,
            })

    # mentions from the registry rows keep row-level provenance in meta
    out_mentions = []
    for key, m in mention_by_name.items():
        m["meta"] = m.get("meta") or {}
        out_mentions.append(m)

    if not col_by_field:
        warnings.append("No columns could be matched to known Crime Analysis fields; no "
                        "records were extracted from this CSV. Use the column "
                        "mapping editor and re-import.")
    return {"entities": entities, "mentions": out_mentions, "events": events,
            "warnings": warnings}


def extract_json_records(records, filename, source_document_id, case_id):
    """Map JSON records (transactions / CCTV / structured events) to a bundle."""
    entities = []
    mentions = []
    events = []
    mention_by_name = {}

    def mention(name, phone=None, account=None, location=None, vehicle=None):
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
        if vehicle and vehicle not in m["identifiers"]["vehicle"]:
            m["identifiers"]["vehicle"].append(vehicle)
        if location and location not in m["identifiers"]["location"]:
            m["identifiers"]["location"].append(str(location))
        return m

    for rec_index, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        rec = {k.strip().lower().replace(" ", "_"): v for k, v in rec.items()}
        etype = str(rec.get("type", rec.get("record_type", "transaction"))).lower()

        # Location / co-observation records (CCTV sightings)
        if etype in ("location_observation", "sighting", "cctv", "co_location"):
            person = rec.get("person") or rec.get("person_name") or rec.get("subject")
            other = rec.get("other_person") or rec.get("with") or rec.get("accompanied_by")
            loc = rec.get("location") or rec.get("place")
            vehicle = rec.get("vehicle")
            phone = rec.get("phone") or rec.get("mobile")
            ts = rec.get("timestamp") or rec.get("date") or rec.get("datetime")
            date, time = _split_datetime(ts) if ts else (None, None)
            if loc:
                entities.append({"type": "LOCATION", "value": str(loc), "confidence": 0.9,
                                 "method": "json", "source_ref": filename, "date": date,
                                 "time": time, "row": rec_index + 1})
            if vehicle:
                entities.append({"type": "VEHICLE", "value": str(vehicle), "confidence": 0.9,
                                 "method": "json", "source_ref": filename, "date": date,
                                 "time": time, "row": rec_index + 1})
            if phone:
                entities.append({"type": "PHONE", "value": str(phone), "confidence": 0.95,
                                 "method": "json", "source_ref": filename, "date": date,
                                 "time": time, "row": rec_index + 1})
            mention(person, location=loc and str(loc), vehicle=vehicle and str(vehicle),
                    phone=phone and str(phone))
            if other:
                mention(other, location=loc and str(loc), vehicle=vehicle and str(vehicle))
                events.append({
                    "type": "LOCATION_OBSERVATION",
                    "description": f"{person} and {other} observed together at {loc}",
                    "date": date, "time": time,
                    "precision": "exact" if time else ("date_only" if date else "unknown"),
                    "a_name": person or None, "b_name": other or None,
                    "metadata": {"location": str(loc) if loc else None,
                                 "vehicle": str(vehicle) if vehicle else None,
                                 "record_index": rec_index + 1},
                    "source_ref": filename,
                })
            continue

        sender = rec.get("sender") or rec.get("sender_name") or rec.get("from_name")
        receiver = rec.get("receiver") or rec.get("receiver_name") or rec.get("to_name")
        sender_acc = (rec.get("sender_account") or rec.get("from_account")
                      or rec.get("account_from"))
        receiver_acc = (rec.get("receiver_account") or rec.get("to_account")
                        or rec.get("account_to"))
        amount = rec.get("amount")
        txn_id = (rec.get("transaction_id") or rec.get("txn_id")
                  or rec.get("reference_no") or rec.get("utr"))
        ts = rec.get("timestamp") or rec.get("date") or rec.get("datetime")
        location = rec.get("location") or rec.get("city")
        vehicle = rec.get("vehicle")

        date, time = _split_datetime(ts) if ts else (None, None)

        for acc in (sender_acc, receiver_acc):
            if acc:
                entities.append({"type": "BANK_ACCOUNT", "value": str(acc),
                                 "confidence": 1.0, "method": "json",
                                 "source_ref": filename, "date": date, "time": time,
                                 "row": rec_index + 1})
        if location:
            entities.append({"type": "LOCATION", "value": str(location),
                             "confidence": 0.9, "method": "json",
                             "source_ref": filename, "date": date, "time": time,
                             "row": rec_index + 1})
        if vehicle:
            entities.append({"type": "VEHICLE", "value": str(vehicle),
                             "confidence": 0.9, "method": "json",
                             "source_ref": filename, "date": date, "time": time,
                             "row": rec_index + 1})

        a = mention(sender, account=sender_acc and str(sender_acc),
                    vehicle=vehicle and str(vehicle))
        b = mention(receiver, account=receiver_acc and str(receiver_acc))

        if etype in ("transaction", "payment", "transfer", "case_event",
                     "call", "event", "incident", "record"):
            if etype in ("transaction", "payment", "transfer"):
                evtype = "TRANSACTION"
                desc = (f"Transaction {sender or ''} → {receiver or ''}"
                        + (f" ₹{amount}" if amount else ""))
            elif etype == "call":
                evtype = "CALL"
                desc = f"Call {sender or ''} → {receiver or ''}"
            else:
                evtype = "CASE_EVENT"
                desc = str(rec.get("description") or rec.get("summary")
                           or f"Dataset record {rec_index + 1}")[:500]
            events.append({
                "type": evtype,
                "description": desc,
                "date": date, "time": time,
                "precision": "exact" if time else ("date_only" if date else "unknown"),
                "a_name": sender or None, "b_name": receiver or None,
                "metadata": {"amount": str(amount) if amount else None,
                             "transaction_id": str(txn_id) if txn_id else None,
                             "sender_account": str(sender_acc) if sender_acc else None,
                             "receiver_account": str(receiver_acc) if receiver_acc else None,
                             "location": str(location) if location else None,
                             "record_index": rec_index + 1},
                "source_ref": filename,
            })

    return {"entities": entities, "mentions": mentions, "events": events,
            "warnings": []}
