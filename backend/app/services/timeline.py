"""Timeline construction.

Uses only known dates/times. Missing times are rendered as "unavailable" and
never invented. Supports filtering by case, person, event type and date range.
"""


def build_timeline(events, case_id=None, person_id=None, event_type=None,
                   start=None, end=None):
    items = []
    for e in events:
        if case_id and e.get("case_id") != case_id:
            continue
        if event_type and e.get("type") != event_type:
            continue
        if person_id:
            if e.get("person_a_id") != person_id and e.get("person_b_id") != person_id:
                continue
        date = e.get("date")
        if not date:
            continue
        if start and date < start:
            continue
        if end and date > end:
            continue
        items.append(e)
    # sort by date, then time (None times last within a day)
    def sort_key(x):
        t = x.get("time")
        return (x.get("date") or "", t if t else "99:99")
    items.sort(key=sort_key)
    return items
