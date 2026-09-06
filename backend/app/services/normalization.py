"""Canonical value normalization.

Every normalization keeps the original value intact: the Entity row stores both
`original_value` and `normalized_value` together with the method used.
"""
import re
from datetime import datetime


def normalize_phone(value):
    s = re.sub(r"\D", "", value or "")
    # strip a leading trunk/international prefix "0" if present
    if s.startswith("0"):
        s = s[1:]
    # strip the country code "91" when it precedes a 10-digit number
    if s.startswith("91") and len(s) == 12:
        s = s[2:]
    return s


def normalize_name(value):
    s = (value or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_vehicle(value):
    return re.sub(r"[\s\-\.]", "", (value or "")).upper()


def normalize_account(value):
    return re.sub(r"[^a-zA-Z0-9]", "", (value or "")).upper()


def normalize_location(value):
    return re.sub(r"\s+", " ", (value or "")).strip().title()


_DATE_FORMATS = (
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d-%B-%Y",
    "%d %b %Y", "%d %B %Y", "%d-%m-%y", "%d/%m/%y", "%Y/%m/%d",
    "%b %d %Y", "%B %d %Y", "%d %b %y",
)


def normalize_date(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # datetime strings ("20-Aug-2026 10:15", "2026-08-20T10:15:00", …) are
    # normalized to their date component only; the time part is handled by
    # normalize_time().
    if "T" in s or " " in s:
        s = re.split(r"[T ]+", s, maxsplit=1)[0]
        if not s:
            return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    m = re.match(r"^(\d{1,2})[-/ ]([A-Za-z]{3,9})[-/ ](\d{2,4})$", s)
    if m:
        d, mon, y = m.groups()
        try:
            return datetime.strptime(f"{d}-{mon}-{y}", "%d-%b-%Y").strftime("%Y-%m-%d")
        except ValueError:
            pass
    return s


def normalize_time(value):
    if value is None:
        return None
    s = str(value).strip()
    # accept "10:15", "2:10 PM", "10:15:00" (seconds dropped) and full
    # datetime strings like "20-Aug-2026 10:15" / "2026-08-20T10:15:00"
    m = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2})?\s*(am|pm)?$", s, re.I)
    if not m:
        # strip a leading date part and try again (datetime values)
        tail = re.split(r"[T ]+", s, maxsplit=1)[-1]
        if tail != s:
            return normalize_time(tail)
        return s
    h = int(m.group(1))
    mm = int(m.group(2))
    ap = (m.group(3) or "").lower()
    if ap == "pm" and h != 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mm:02d}"


_NORMALIZERS = {
    "PHONE": normalize_phone,
    "PERSON": normalize_name,
    "VEHICLE": normalize_vehicle,
    "BANK_ACCOUNT": normalize_account,
    "ACCOUNT": normalize_account,
    "LOCATION": normalize_location,
    "ORGANIZATION": normalize_name,
    "CASE": normalize_name,
    "DATE": normalize_date,
    "TIME": normalize_time,
}


def normalize_value(entity_type, value):
    fn = _NORMALIZERS.get(entity_type)
    if fn:
        return fn(value)
    return (value or "").strip()
