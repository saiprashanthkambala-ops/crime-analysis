"""Ingestion pipeline tests: upload a new file and verify the full flow."""
import io
import time

CDR_CSV = (
    "caller_name,caller_phone,callee_name,callee_phone,timestamp,duration\n"
    "Neha Kapoor,9811112222,Karan Malhotra,9822223333,20-Aug-2026 09:00,120\n"
    "Neha Kapoor,9811112222,Karan Malhotra,9822223333,21-Aug-2026 09:00,180\n"
    "Neha Kapoor,9811112222,Karan Malhotra,9822223333,22-Aug-2026 09:00,90\n"
)


def _wait_for_status(client, headers, doc_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/documents/{doc_id}/status", headers=headers)
        st = r.json()
        if st["status"] in ("completed", "failed"):
            return st
        time.sleep(0.2)
    return {"status": "timeout"}


def test_upload_csv_flows_through_pipeline(client, auth_headers):
    # create a fresh case for the upload
    c = client.post("/api/cases", headers=auth_headers,
                    json={"name": "Ingestion Test Case"}).json()
    case_id = c["id"]

    r = client.post(
        f"/api/cases/{case_id}/upload",
        headers=auth_headers,
        files={"file": ("extra_cdr.csv", io.BytesIO(CDR_CSV.encode()), "text/csv")},
    )
    assert r.status_code == 200
    doc_id = r.json()["id"]

    st = _wait_for_status(client, auth_headers, doc_id)
    assert st["status"] == "completed", st

    # persons should now include Neha Kapoor and Karan Malhotra
    persons = client.get("/api/persons", headers=auth_headers).json()
    names = {p["name"] for p in persons}
    assert "Neha Kapoor" in names
    assert "Karan Malhotra" in names

    # a relationship between them should exist (3 calls)
    rels = client.get("/api/relationships", headers=auth_headers).json()
    pair = None
    for rel in rels:
        n = {rel["person_a"]["name"], rel["person_b"]["name"]}
        if n == {"Neha Kapoor", "Karan Malhotra"}:
            pair = rel
            break
    assert pair is not None
    assert pair["signals"]["calls"] == 3

    # evidence records with source provenance should exist for the pair
    assert any(e["source"] == "extra_cdr.csv" for e in pair["evidence"])


def test_upload_rejects_bad_extension(client, auth_headers):
    r = client.post(
        "/api/cases/C101/upload",
        headers=auth_headers,
        files={"file": ("evil.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
    )
    assert r.status_code == 400


def test_upload_invalid_json_fails_cleanly(client, auth_headers):
    r = client.post(
        "/api/cases/C101/upload",
        headers=auth_headers,
        files={"file": ("bad.json", io.BytesIO(b"{not valid json"), "application/json")},
    )
    assert r.status_code == 200
    st = _wait_for_status(client, auth_headers, r.json()["id"])
    assert st["status"] == "failed"
