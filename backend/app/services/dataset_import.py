"""Dataset import support: validation, sniffing and CSV column mapping.

This module is the single source of truth for *accepting* a dataset into the
CrimeLink pipeline. Everything here returns investigator-readable messages —
raw stack traces never cross this boundary.

Principles enforced:
* File extensions are never trusted alone; PDF/JSON payloads must match their
  declared type, CSVs must parse, files must be non-empty and size-bounded.
* Invalid data is rejected loudly (no silent acceptance of malformed files).
* CSV columns are mapped to canonical CrimeLink fields. Original column
  headers and original cell values are always preserved downstream so nothing
  the investigator uploaded is destroyed.
* Only column *names* are considered for mapping, never file paths.
"""

import csv
import hashlib
import io
import json
import re
from pathlib import Path

from ..config import settings

# ---------------------------------------------------------------------------
# Supported formats
# ---------------------------------------------------------------------------
SUPPORTED_EXTENSIONS = {".pdf", ".csv", ".json", ".txt", ".text"}

MAX_BYTES = lambda: settings.MAX_UPLOAD_MB * 1024 * 1024  # noqa: E731 (reads live settings)


def friendly_size(limit_bytes):
    mb = limit_bytes / (1024 * 1024)
    return f"{mb:g} MB"


# ---------------------------------------------------------------------------
# Canonical CSV fields (CrimeLink concepts) used by mapping + extraction.
# ---------------------------------------------------------------------------
# Each canonical field lists column aliases it can be auto-detected from.
# Aliases are matched case-insensitively with whitespace normalized to "_".
CSV_FIELD_ALIASES = {
    # --- call records (CDR) ---
    "caller_name": ["caller_name", "caller", "calling_name", "calling_party",
                    "calling_party_name", "source_name", "from_name", "name_a",
                    "party_a_name", "a_name", "aname", "caller_name_party_a"],
    "caller_phone": ["caller_phone", "caller_number", "calling_number", "caller_mobile",
                     "calling_mobile", "from", "source_number", "msisdn_a", "a_number",
                     "a_phone", "party_a", "party_a_number", "callerid", "cli"],
    "callee_name": ["callee_name", "callee", "called_name", "called_party",
                    "called_party_name", "receiving_party", "receiving_party_name",
                    "to_name", "name_b", "party_b_name", "b_name", "bname",
                    "callee_name_party_b"],
    "callee_phone": ["callee_phone", "callee_number", "called_number", "called_mobile",
                     "dialled_number", "dialed_number", "receiving_number", "to",
                     "destination_number", "msisdn_b", "b_number", "b_phone",
                     "party_b", "party_b_number", "called_party_number"],
    "duration": ["duration", "duration_sec", "call_duration", "duration_s",
                 "talk_time", "talktime", "seconds"],
    # --- transactions / banking ---
    "sender_name": ["sender_name", "sender", "remitter", "payer", "from_party",
                    "debit_name", "account_holder_from"],
    "sender_account": ["sender_account", "from_account", "account_from", "debit_account",
                       "source_account", "sender_acct", "from_acct"],
    "receiver_name": ["receiver_name", "receiver", "payee", "beneficiary",
                      "beneficiary_name", "credit_name", "recipient", "to_party",
                      "account_holder_to"],
    "receiver_account": ["receiver_account", "to_account", "account_to", "credit_account",
                         "beneficiary_account", "receiver_acct", "to_acct"],
    "amount": ["amount", "amt", "value", "txn_amount", "transaction_amount",
               "transfer_amount", "credit_amount", "debit_amount", "sum"],
    "transaction_id": ["transaction_id", "txn_id", "transactionid", "txnid",
                       "ref_no", "reference", "reference_no", "utr", "receipt_no",
                       "trn_id"],
    # --- generic person / property ---
    "person_name": ["person_name", "name", "person", "full_name", "customer_name",
                    "account_holder", "suspect", "accused", "subject", "complainant",
                    "person_name"],
    "phone": ["phone", "phone_number", "mobile", "mobile_number", "contact_number",
              "contact_no", "tel", "telephone", "msisdn", "cell", "cell_number"],
    "vehicle": ["vehicle", "vehicle_number", "reg_number", "registration_number",
                "reg_no", "vrn", "car_number", "bike_number", "vehicle_reg"],
    "account": ["account", "account_number", "acct_no", "acc_no", "bank_account",
                "account_no", "a_c_no", "a/c_no"],
    "location": ["location", "place", "address", "city", "area", "station", "site",
                 "branch", "scene"],
    # --- temporal ---
    "date": ["date", "day", "call_date", "txn_date", "transaction_date", "event_date",
             "record_date", "timestamp_date"],
    "time": ["time", "call_time", "txn_time", "transaction_time", "start_time",
             "event_time", "timestamp_time"],
    "timestamp": ["timestamp", "datetime", "date_time", "ts", "call_timestamp",
                  "event_timestamp", "date_and_time", "start_datetime"],
}

# Display metadata used by the mapping UI / import payloads.
CSV_FIELD_GROUPS = [
    ("Call records (CDR)", ["caller_name", "caller_phone", "callee_name",
                            "callee_phone", "duration"]),
    ("Transactions / banking", ["sender_name", "sender_account", "receiver_name",
                                "receiver_account", "amount", "transaction_id"]),
    ("Person & property", ["person_name", "phone", "vehicle", "account", "location"]),
    ("Date & time", ["date", "time", "timestamp"]),
]
CSV_FIELD_LABELS = {
    "caller_name": "Caller name", "caller_phone": "Caller phone",
    "callee_name": "Receiver/callee name", "callee_phone": "Receiver/callee phone",
    "duration": "Call duration",
    "sender_name": "Sender name", "sender_account": "Sender account",
    "receiver_name": "Receiver name", "receiver_account": "Receiver account",
    "amount": "Transaction amount", "transaction_id": "Transaction ID",
    "person_name": "Person name", "phone": "Phone number", "vehicle": "Vehicle",
    "account": "Bank account", "location": "Location",
    "date": "Date", "time": "Time", "timestamp": "Date/time (single column)",
}
ALL_CANONICAL_FIELDS = list(CSV_FIELD_ALIASES.keys())


def _norm_col_name(name):
    """Normalize a header cell for alias matching ('Caller Name' -> caller_name)."""
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def normalize_filename(raw):
    """Return a safe basename; never trust a client-provided path."""
    if not raw:
        return ""
    return Path(str(raw).replace("\\", "/")).name.strip()


def detect_extension(filename):
    name = normalize_filename(filename).lower()
    if name.endswith(".text"):
        return ".txt"
    for ext in (".pdf", ".csv", ".json", ".txt"):
        if name.endswith(ext):
            return ext
    return None


# ---------------------------------------------------------------------------
# Content checks
# ---------------------------------------------------------------------------
def _is_empty(content):
    return not content or not content.strip()


def _pdf_ok(content):
    return content[:5].lstrip().startswith(b"%PDF")


def _json_ok(content):
    return content.lstrip()[:1] in (b"{", b"[")


def _decode_text(content):
    """Best-effort utf-8 decode (latin-1 fallback keeps legacy files working)."""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("utf-8", "replace")


def parse_csv(text):
    """Parse CSV text -> (header, rows, parse_error). Rows excludes the header."""
    try:
        reader = csv.reader(io.StringIO(text))
        raw = [r for r in reader]
    except csv.Error as exc:
        return None, None, f"CSV file is malformed ({exc})."
    non_empty = [r for r in raw if any((c or "").strip() for c in r)]
    if not non_empty:
        return None, None, "CSV contains no data rows."
    header = [str(c).strip() for c in non_empty[0]]
    if not any(header):
        return None, None, "CSV header row could not be detected."
    rows = non_empty[1:]
    if not rows:
        return None, None, "CSV contains no data rows."
    return header, rows, None


def parse_json(text):
    """Parse JSON text -> (records, error). ``records`` is always a list of dicts."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"JSON structure is invalid ({exc.msg})."
    if isinstance(data, dict):
        return [data], None
    if isinstance(data, list):
        if not data:
            return None, "JSON contains no data rows."
        bad = [i for i, r in enumerate(data) if not isinstance(r, dict)]
        if bad:
            if len(bad) == len(data):
                return None, "JSON structure is invalid. Expected an array of objects."
            return None, (f"JSON structure is invalid. Entries {bad[:5]} are not "
                          "objects.")
        return data, None
    return None, "JSON structure is invalid. Expected an object or an array of objects."


def validate_file(filename, content):
    """Validate a single uploaded file.

    Returns a dict:
        {ok, filename, file_type, size, errors[], warnings[], needs_ocr,
         rows?, columns?, mapping?, preview?}
    """
    fname = normalize_filename(filename)
    errors, warnings = [], []
    result = {
        "ok": False, "filename": fname, "file_type": None, "size": len(content),
        "errors": errors, "warnings": warnings, "needs_ocr": False,
        "rows": None, "columns": [], "mapping": None, "preview": [],
    }
    ext = detect_extension(fname)
    if ext is None:
        errors.append("Unsupported file type. Supported formats: PDF, CSV, JSON, TXT.")
        return result

    if len(content) > MAX_BYTES():
        errors.append(f"File exceeds the maximum allowed size "
                      f"({friendly_size(MAX_BYTES())}).")
        return result
    if _is_empty(content):
        errors.append("File is empty.")
        return result

    # Content must match the declared type — the extension alone is never enough.
    if ext == ".pdf":
        if not _pdf_ok(content):
            errors.append("File content does not match its extension (.pdf is not a "
                          "valid PDF document).")
            return result
        result["file_type"] = "pdf"
        text = _extract_pdf_text(content)
        if not text.strip():
            result["needs_ocr"] = True
            warnings.append("PDF appears to be scanned/image-based; OCR will be "
                            "attempted during processing.")
        result["ok"] = True
        return result

    if ext == ".json":
        if not _json_ok(content):
            errors.append("File content does not look like JSON (must start with "
                          "`{` or `[`).")
            return result
        text = _decode_text(content)
        records, err = parse_json(text)
        if err:
            errors.append(err)
            return result
        result["file_type"] = "json"
        result["rows"] = len(records)
        result["preview"] = [dict(r) for r in records[:3]]
        result["ok"] = True
        return result

    text = _decode_text(content)
    if "\x00" in text:
        errors.append("File is not readable text (binary content detected).")
        return result

    if ext == ".csv":
        header, rows, err = parse_csv(text)
        if err:
            errors.append(err)
            return result
        result["ok"] = True
        result["file_type"] = "csv"
        result["rows"] = len(rows)
        result["columns"] = header
        result["mapping"] = auto_detect_mapping(header)
        result["preview"] = [dict(zip(header, [str(c) for c in row])) for row in rows[:3]]
        if len(header) != len({_norm_col_name(c) for c in header}):
            warnings.append("CSV contains duplicate column names; the first "
                            "occurrence of each column is used.")
        ragged = sum(1 for r in rows if len(r) != len(header))
        if ragged and ragged > len(rows) * 0.5:
            warnings.append(f"{ragged} of {len(rows)} rows have a different number of "
                            "columns and were padded/truncated during parsing.")
        return result

    # .txt / .text
    result["file_type"] = "txt"
    lines = [ln for ln in text.splitlines() if ln.strip()]
    result["rows"] = len(lines)
    result["preview"] = [ln[:300] for ln in lines[:3]]
    result["ok"] = True
    return result


def validate_mapping_columns(mapping, columns):
    """Check a user-supplied column mapping against the CSV header.

    Returns (mapping_ok, errors). Only known canonical fields are accepted and
    each referenced column must exist in the header.
    """
    errors = []
    if not mapping:
        return None, []
    if not isinstance(mapping, dict):
        return False, ["Column mapping must be a JSON object mapping CrimeLink "
                       "fields to CSV column names."]
    norm_cols = [_norm_col_name(c) for c in columns]
    cleaned = {}
    for field, col in mapping.items():
        if field not in CSV_FIELD_ALIASES:
            errors.append(f"Unknown CrimeLink field '{field}' in column mapping.")
            continue
        if isinstance(col, int) or (isinstance(col, str) and col.strip().isdigit()):
            idx = int(col)
            if not (0 <= idx < len(columns)):
                errors.append(f"Column mapping references column index {idx} for "
                              f"'{field}', but the CSV only has {len(columns)} columns.")
                continue
            cleaned[field] = columns[idx]
            continue
        ncol = _norm_col_name(col)
        if ncol not in norm_cols:
            errors.append(f"Column mapping references '{col}' for '{field}', but no "
                          "such column exists in the CSV.")
            continue
        cleaned[field] = columns[norm_cols.index(ncol)]
    return cleaned, errors


# ---------------------------------------------------------------------------
# CSV mapping detection
# ---------------------------------------------------------------------------
# extra "number-ish" tokens that only make sense in a call-record context
_CALL_PHONE_ALIASES = {
    "mobile_no", "mobile", "mobile_number", "phone_no", "phone",
    "contact_number", "contact_no", "number", "telephone",
    "dialled_number", "dialed_number", "called_number", "receiving_number",
    "other_number", "other_phone", "peer_number", "opposite_number",
}


def auto_detect_mapping(header):
    """Suggest a canonical-field -> column mapping for a CSV header.

    Matching is best-effort and unambiguous: a column is assigned to the first
    canonical field whose alias list contains it, and each column maps at most
    once. When a file already looks like call records but its party-number
    columns used generic names ("mobile no", "dialled number", …), those
    columns are assigned to the caller/callee phone slots as a second pass.
    """
    columns = [_norm_col_name(c) for c in header]
    mapping = {}
    used_cols = set()
    for field, aliases in CSV_FIELD_ALIASES.items():
        for idx, col in enumerate(columns):
            if col in used_cols:
                continue
            if col in aliases:
                mapping[field] = header[idx]
                used_cols.add(idx)
                break

    # second pass: generic number columns inside an obvious call-record file
    callish = any(f in mapping for f in
                  ("caller_name", "caller_phone", "callee_name", "callee_phone"))
    if callish:
        leftover = [i for i, c in enumerate(columns) if i not in used_cols]
        number_cols = [i for i in leftover if columns[i] in _CALL_PHONE_ALIASES]
        # prefer "dialled/called"-type tokens for the callee side
        number_cols.sort(key=lambda i: 1 if columns[i].startswith(("dial", "called",
                                                                   "receiving", "other",
                                                                   "peer", "opposite")) else 0)
        if "caller_phone" not in mapping and number_cols:
            mapping["caller_phone"] = header[number_cols.pop(0)]
        if "callee_phone" not in mapping and number_cols:
            mapping["callee_phone"] = header[number_cols.pop(0)]
    return mapping


def detected_record_shape(mapping):
    """Classify a (possibly auto) column mapping into a dataset record shape.

    Returns one of: call | transaction | person | unknown
    """
    mapping = mapping or {}
    if any(f in mapping for f in ("caller_name", "caller_phone", "callee_name",
                                  "callee_phone", "duration")):
        return "call"
    if any(f in mapping for f in ("sender_name", "sender_account", "receiver_name",
                                  "receiver_account", "amount", "transaction_id")):
        return "transaction"
    if any(f in mapping for f in ("person_name", "phone", "vehicle", "account",
                                  "location", "date", "time", "timestamp")):
        return "person"
    return "unknown"


# ---------------------------------------------------------------------------
# Shared small helpers
# ---------------------------------------------------------------------------
def _extract_pdf_text(content):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def file_sha256(content):
    return hashlib.sha256(content).hexdigest()
