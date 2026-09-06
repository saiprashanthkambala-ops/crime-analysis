"""Dataset import tests: validation, mapping, duplicates, provenance, RBAC,
retry and end-to-end ingestion through the CrimeLink pipeline.
"""
import io
import json
import os
import stat
import time

import pytest

# ---------------------------------------------------------------- fixtures & helpers

CSV_CDR = (
    "caller_name,caller_phone,callee_name,callee_phone,timestamp,duration\n"
    "Zoya Khan,9876000011,Farhan Ali,9812000022,20-Aug-2026 09:00,120\n"
    "Zoya Khan,9876000011,Farhan Ali,9812000022,21-Aug-2026 09:00,180\n"
    "Zoya Khan,9876000011,Farhan Ali,9812000022,22-Aug-2026 09:00,90\n"
)

TXN_JSON = json.dumps([
    {"type": "transaction", "timestamp": "20-Aug-2026 11:05",
     "sender": "Imran Qureshi", "sender_account": "5011112222",
     "receiver": "Farhan Ali", "receiver_account": "6022223333",
     "amount": 45000, "transaction_id": "TXN-9981"},
    {"type": "transaction", "timestamp": "21-Aug-2026 12:30",
     "sender": "Imran Qureshi", "sender_account": "5011112222",
     "receiver": "Farhan Ali", "receiver_account": "6022223333",
     "amount": 23000, "transaction_id": "TXN-9982"},
])

TXT_RECORD = (
    "Statement of witness recorded on 20-Aug-2026. Vikram Rao stated he met "
    "Deepa Sharma near Banjara Hills. Vehicle TS09XY4321 was seen parked "
    "outside the building. Contact number 9876500011.\n"
)

FIR_TEXT = [
    "Complaint registered on 20-Aug-2026.",
    "Vikram Rao reported that Rs 12000 was transferred from his account 123456789012",
    "to an unknown beneficiary on 21-Aug-2026. He received a call from 9876500011.",
    "Vehicle TS09XY4321 was involved. Status: under investigation.",
]


def _wait_for_status(client, headers, doc_id, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/documents/{doc_id}/status", headers=headers)
        st = r.json()
        if st["status"] in ("completed", "failed"):
            return st
        time.sleep(0.15)
    return {"status": "timeout"}


def _make_text_pdf(path, lines):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    for line in lines:
        c.drawString(60, y, line)
        y -= 20
    c.showPage()
    c.save()
    return path.read_bytes()


def _make_image_only_pdf(path):
    """PDF whose pages carry no text layer (simulates a scanned document)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFillColorRGB(0.9, 0.9, 0.9)
    c.rect(60, 700, 460, 60, stroke=0, fill=1)
    c.showPage()
    c.save()
    return path.read_bytes()


def _new_case(client, headers, name):
    r = client.post("/api/cases", headers=headers, json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _post_imports(client, headers, case_id, files, mapping=None):
    data = None
    if mapping is not None:
        data = {"mapping": json.dumps(mapping)}
    return client.post(f"/api/cases/{case_id}/imports", headers=headers,
                       files=files, data=data)


# ---------------------------------------------------------------- valid imports

def test_valid_csv_import_flows_through_pipeline(client, auth_headers):
    case_id = _new_case(client, auth_headers, "CSV Import Case")
    r = _post_imports(client, auth_headers, case_id,
                      [("files", ("cdr_zoya.csv", io.BytesIO(CSV_CDR.encode()), "text/csv"))])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    doc_id = body["imports"][0]["id"]

    st = _wait_for_status(client, auth_headers, doc_id)
    assert st["status"] == "completed", st
    assert st["records_processed"] == 3            # 3 CALL events
    assert st["entities_discovered"] >= 2          # the two phone numbers
    assert st["persons_discovered"] >= 2
    assert st["evidence_discovered"] >= 3
    assert st["file_type"] == "csv"
    assert st["uploaded_by_name"] == "investigator1"

    persons = client.get("/api/persons", headers=auth_headers).json()
    names = {p["name"] for p in persons}
    assert {"Zoya Khan", "Farhan Ali"} <= names

    rels = client.get("/api/relationships", headers=auth_headers).json()
    pair = None
    for rel in rels:
        n = {rel["person_a"]["name"], rel["person_b"]["name"]}
        if n == {"Zoya Khan", "Farhan Ali"}:
            pair = rel
            break
    assert pair is not None and pair["signals"]["calls"] == 3
    assert any(e["source"] == "cdr_zoya.csv" for e in pair["evidence"])


def test_valid_json_import(client, auth_headers):
    case_id = _new_case(client, auth_headers, "JSON Import Case")
    r = _post_imports(client, auth_headers, case_id,
                      [("files", ("txn.json", io.BytesIO(TXN_JSON.encode()), "application/json"))])
    assert r.status_code == 200, r.text
    doc_id = r.json()["imports"][0]["id"]
    st = _wait_for_status(client, auth_headers, doc_id)
    assert st["status"] == "completed", st
    assert st["records_processed"] == 2
    # transaction identifiers appear as entities (accounts) with provenance
    rels = client.get("/api/relationships", headers=auth_headers).json()
    assert any(
        {x["person_a"]["name"], x["person_b"]["name"]} == {"Imran Qureshi", "Farhan Ali"}
        for x in rels
    )


def test_valid_txt_import(client, auth_headers):
    case_id = _new_case(client, auth_headers, "TXT Import Case")
    r = _post_imports(client, auth_headers, case_id,
                      [("files", ("statement.txt", io.BytesIO(TXT_RECORD.encode()), "text/plain"))])
    assert r.status_code == 200, r.text
    st = _wait_for_status(client, auth_headers, r.json()["imports"][0]["id"])
    assert st["status"] == "completed", st
    persons = {p["name"] for p in client.get("/api/persons", headers=auth_headers).json()}
    assert "Vikram Rao" in persons


def test_valid_pdf_import_with_text_layer(client, auth_headers, tmp_path):
    pdf = _make_text_pdf(tmp_path / "fir.pdf", FIR_TEXT)
    case_id = _new_case(client, auth_headers, "PDF Import Case")
    r = _post_imports(client, auth_headers, case_id,
                      [("files", ("fir_vikram.pdf", io.BytesIO(pdf), "application/pdf"))])
    assert r.status_code == 200, r.text
    doc_id = r.json()["imports"][0]["id"]
    st = _wait_for_status(client, auth_headers, doc_id)
    assert st["status"] == "completed", st
    persons = {p["name"] for p in client.get("/api/persons", headers=auth_headers).json()}
    assert "Vikram Rao" in persons
    # provenance: the phone entity is traceable to this exact document
    found = client.get("/api/search?q=9876500011", headers=auth_headers).json()
    assert any(e["case_id"] == case_id and e["type"] == "PHONE" for e in found["entities"])


# ---------------------------------------------------------------- OCR / scanned PDFs

def test_scanned_pdf_fails_cleanly_when_ocr_unavailable(client, auth_headers, tmp_path,
                                                        monkeypatch):
    monkeypatch.setattr("app.services.pipeline.settings.TESSERACT_CMD",
                        "/no/such/tesseract-binary")
    pdf = _make_image_only_pdf(tmp_path / "scan.pdf")
    case_id = _new_case(client, auth_headers, "Scanned PDF Case (no OCR)")
    r = _post_imports(client, auth_headers, case_id,
                      [("files", ("scan1.pdf", io.BytesIO(pdf), "application/pdf"))])
    assert r.status_code == 200, r.text
    st = _wait_for_status(client, auth_headers, r.json()["imports"][0]["id"])
    assert st["status"] == "failed"
    assert "OCR failed" in st["error"] or "OCR" in st["error"]


def test_scanned_pdf_ocr_fallback_and_retry(client, auth_headers, tmp_path,
                                            monkeypatch):
    pdf = _make_image_only_pdf(tmp_path / "scan.pdf")
    case_id = _new_case(client, auth_headers, "Scanned PDF OCR Case")

    # first attempt: OCR binary missing -> clean failure
    monkeypatch.setattr("app.services.pipeline.settings.TESSERACT_CMD",
                        "/no/such/tesseract-binary")
    r = _post_imports(client, auth_headers, case_id,
                      [("files", ("scan_ocr.pdf", io.BytesIO(pdf), "application/pdf"))])
    assert r.status_code == 200, r.text
    doc_id = r.json()["imports"][0]["id"]
    st = _wait_for_status(client, auth_headers, doc_id)
    assert st["status"] == "failed"
    assert "OCR" in st["error"]

    # install a fake tesseract, then retry the SAME document
    fake = tmp_path / "tesseract"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "sys.stdin.buffer.read()\n"
        "sys.stdout.write('Statement 20-Aug-2026. Vikram Rao reported contact "
        "number 9876500022 vehicle TS09XY9876.\\n')\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr("app.services.pipeline.settings.TESSERACT_CMD", str(fake))

    r = client.post(f"/api/documents/{doc_id}/retry", headers=auth_headers)
    assert r.status_code == 200, r.text
    st = _wait_for_status(client, auth_headers, doc_id)
    assert st["status"] == "completed", st
    assert st["retry_count"] == 1
    # OCR-derived data is now in the graph (no duplication from the failed run)
    persons = {p["name"] for p in client.get("/api/persons", headers=auth_headers).json()}
    assert "Vikram Rao" in persons


def test_retry_only_for_failed_imports(client, auth_headers):
    case_id = _new_case(client, auth_headers, "Retry Guard Case")
    r = _post_imports(client, auth_headers, case_id,
                      [("files", ("ok.txt", io.BytesIO(b"Vikram Rao 20-Aug-2026\n"),
                                  "text/plain"))])
    assert r.status_code == 200
    doc_id = r.json()["imports"][0]["id"]
    st = _wait_for_status(client, auth_headers, doc_id)
    assert st["status"] == "completed"
    r = client.post(f"/api/documents/{doc_id}/retry", headers=auth_headers)
    assert r.status_code == 400


# ---------------------------------------------------------------- invalid inputs

def test_invalid_csv_rejected_synchronously(client, auth_headers):
    case_id = _new_case(client, auth_headers, "Bad CSV Case")
    # header only -> no data rows
    r = _post_imports(client, auth_headers, case_id,
                      [("files", ("empty_data.csv", io.BytesIO(b"a,b,c\n"), "text/csv"))])
    assert r.status_code == 400
    body = r.json()["detail"]
    assert "CSV contains no data rows." in body["errors"][0]["error"]


def test_invalid_json_rejected_synchronously(client, auth_headers):
    case_id = _new_case(client, auth_headers, "Bad JSON Case")
    r = _post_imports(client, auth_headers, case_id,
                      [("files", ("bad.json", io.BytesIO(b"{not valid"), "application/json"))])
    assert r.status_code == 400
    assert "JSON structure is invalid" in r.json()["detail"]["errors"][0]["error"]


def test_empty_and_unsupported_files_rejected(client, auth_headers):
    case_id = _new_case(client, auth_headers, "Rejections Case")
    r = _post_imports(client, auth_headers, case_id,
                      [("files", ("empty.txt", io.BytesIO(b""), "text/plain"))])
    assert r.status_code == 400
    assert r.json()["detail"]["errors"][0]["error"] == "File is empty."

    r = _post_imports(client, auth_headers, case_id,
                      [("files", ("evil.exe", io.BytesIO(b"MZ...."), "application/octet-stream"))])
    assert r.status_code == 400
    assert "Unsupported file type" in r.json()["detail"]["errors"][0]["error"]

    # a .pdf that is not a PDF must be rejected (extension not trusted)
    r = _post_imports(client, auth_headers, case_id,
                      [("files", ("fake.pdf", io.BytesIO(b"hello world"), "application/pdf"))])
    assert r.status_code == 400
    assert "does not match" in r.json()["detail"]["errors"][0]["error"]

    # batch semantics: one invalid file rejects the whole batch (nothing stored)
    r = _post_imports(client, auth_headers, case_id,
                      [("files", ("ok.csv", io.BytesIO(CSV_CDR.encode()), "text/csv")),
                       ("files", ("bad.csv", io.BytesIO(b"h\n"), "text/csv"))])
    assert r.status_code == 400
    history = client.get(f"/api/cases/{case_id}/imports", headers=auth_headers).json()
    assert history["imports"] == []


def test_large_file_validation(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.config.settings.MAX_UPLOAD_MB", 0)
    case_id = _new_case(client, auth_headers, "Large File Case")
    r = _post_imports(client, auth_headers, case_id,
                      [("files", ("big.csv", io.BytesIO(b"x" * 100), "text/csv"))])
    assert r.status_code == 400
    assert "maximum allowed size" in r.json()["detail"]["errors"][0]["error"]


# ---------------------------------------------------------------- duplicates

def test_duplicate_upload_detected_by_content_hash(client, auth_headers):
    case_id = _new_case(client, auth_headers, "Duplicate Case")
    files = [("files", ("cdr_dup.csv", io.BytesIO(CSV_CDR.encode()), "text/csv"))]
    r1 = _post_imports(client, auth_headers, case_id, files)
    assert r1.status_code == 200
    first_id = r1.json()["imports"][0]["id"]

    # identical content under a DIFFERENT filename in the same case -> blocked
    r2 = _post_imports(client, auth_headers, case_id,
                       [("files", ("renamed_copy.csv", io.BytesIO(CSV_CDR.encode()), "text/csv"))])
    assert r2.status_code == 409
    err = r2.json()["detail"]["errors"][0]
    assert "Duplicate import" in err["error"]
    assert err["document_id"] == first_id

    # same filename, genuinely different content -> allowed
    r3 = _post_imports(client, auth_headers, case_id,
                       [("files", ("cdr_dup.csv", io.BytesIO(b"caller_name,x\nZoya,1\n"), "text/csv"))])
    assert r3.status_code == 200

    # same content imported into a different case -> allowed (cross-case datasets)
    case2 = _new_case(client, auth_headers, "Other Case Same Data")
    r4 = _post_imports(client, auth_headers, case2, files)
    assert r4.status_code == 200


# ---------------------------------------------------------------- column mapping

def test_column_mapping_and_original_value_preserved(client, auth_headers):
    weird_csv = (
        "calling party,mobile no,receiving party,dialled number,date of call,time of call\n"
        "Ali Raza,+91-98765-00001,Nadia Syed,098120 00002,20-Aug-2026,10:05\n"
        "Ali Raza,9876500001,Nadia Syed,9812000002,21-Aug-2026,11:30\n"
    )
    mapping = {
        "caller_name": "calling party",
        "caller_phone": "mobile no",
        "callee_name": "receiving party",
        "callee_phone": "dialled number",
        "date": "date of call",
        "time": "time of call",
    }
    case_id = _new_case(client, auth_headers, "Mapping Case")
    r = _post_imports(client, auth_headers, case_id,
                      [("files", ("mapped_cdr.csv", io.BytesIO(weird_csv.encode()), "text/csv"))],
                      mapping=[mapping])
    assert r.status_code == 200, r.text
    doc_id = r.json()["imports"][0]["id"]
    st = _wait_for_status(client, auth_headers, doc_id)
    assert st["status"] == "completed", st
    # the exact mapping used is stored for provenance
    assert st["mapping"]["caller_phone"] == "mobile no"

    rels = client.get("/api/relationships", headers=auth_headers).json()
    assert any(
        {x["person_a"]["name"], x["person_b"]["name"]} == {"Ali Raza", "Nadia Syed"}
        and x["signals"]["calls"] == 2
        for x in rels
    )
    # original value preserved (with separators), normalized value canonical
    s = client.get("/api/search?q=9876500001", headers=auth_headers).json()
    hits = [e for e in s["entities"] if e["case_id"] == case_id and e["type"] == "PHONE"]
    assert hits and hits[0]["value"] in ("+91-98765-00001", "9876500001")
    assert hits[0]["normalized"] == "9876500001"


def test_column_mapping_validation_rejects_unknown_columns(client, auth_headers):
    csv_data = "foo,bar\n1,2\n"
    case_id = _new_case(client, auth_headers, "Bad Mapping Case")
    mapping = [{"caller_phone": "no_such_column", "made_up_field": "bar"}]
    r = _post_imports(client, auth_headers, case_id,
                      [("files", ("m.csv", io.BytesIO(csv_data.encode()), "text/csv"))],
                      mapping=mapping)
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert any("no such column" in e["error"] for e in detail["errors"])
    assert any("Unknown CrimeLink field" in e["error"] for e in detail["errors"])


# ---------------------------------------------------------------- provenance / RBAC

def test_provenance_columns_and_history(client, auth_headers):
    case_id = _new_case(client, auth_headers, "History Case")
    r = _post_imports(client, auth_headers, case_id,
                      [("files", ("hist.csv", io.BytesIO(CSV_CDR.encode()), "text/csv"))])
    assert r.status_code == 200
    doc_id = r.json()["imports"][0]["id"]
    _wait_for_status(client, auth_headers, doc_id)
    hist = client.get(f"/api/cases/{case_id}/imports", headers=auth_headers).json()
    assert len(hist["imports"]) == 1
    item = hist["imports"][0]
    assert item["filename"] == "hist.csv"
    assert item["sha256"] and len(item["sha256"]) == 64
    assert item["uploaded_by_name"] == "investigator1"
    assert item["records_processed"] == 3
    assert item["detected_columns"] == ["caller_name", "caller_phone", "callee_name",
                                        "callee_phone", "timestamp", "duration"]
    assert item["created_at"] is not None


def test_case_level_authorization_for_imports(client, auth_headers, investigator2_headers,
                                              admin_headers):
    # investigator2 is assigned to C101 but NOT to C204: all import operations
    # on C204 must be denied for them.
    assert client.post("/api/cases/C204/imports",
                       headers=investigator2_headers,
                       files=[("files", ("x.csv", io.BytesIO(CSV_CDR.encode()), "text/csv"))]).status_code == 403
    assert client.post("/api/cases/C204/imports/preflight",
                       headers=investigator2_headers,
                       files=[("files", ("x.csv", io.BytesIO(CSV_CDR.encode()), "text/csv"))]).status_code == 403
    assert client.get("/api/cases/C204/imports", headers=investigator2_headers).status_code == 403

    # an admin imports a document into C204; per-document endpoints must still
    # respect case assignment for investigator2
    doc = client.post("/api/cases/C204/imports",
                      headers=admin_headers,
                      files=[("files", ("rbac.csv", io.BytesIO(CSV_CDR.encode()), "text/csv"))]).json()
    doc_id = doc["imports"][0]["id"]
    assert client.post(f"/api/documents/{doc_id}/retry",
                       headers=investigator2_headers).status_code == 403
    assert client.get(f"/api/documents/{doc_id}/status",
                      headers=investigator2_headers).status_code == 403
    # admins bypass case assignment everywhere
    assert client.get("/api/cases/C204/imports", headers=admin_headers).status_code == 200
    _wait_for_status(client, admin_headers, doc_id)


def test_preflight_detects_duplicates_and_columns(client, auth_headers):
    case_id = _new_case(client, auth_headers, "Preflight Case")
    r = client.post(f"/api/cases/{case_id}/imports/preflight", headers=auth_headers,
                    files=[("files", ("pre.csv", io.BytesIO(CSV_CDR.encode()), "text/csv"))])
    assert r.status_code == 200
    item = r.json()["files"][0]
    assert item["ok"] is True
    assert item["file_type"] == "csv"
    assert item["columns"][0] == "caller_name"
    assert item["mapping"]["caller_phone"] == "caller_phone"

    # upload for real, then preflight the same content again -> duplicate flag
    _post_imports(client, auth_headers, case_id,
                  [("files", ("pre.csv", io.BytesIO(CSV_CDR.encode()), "text/csv"))])
    r = client.post(f"/api/cases/{case_id}/imports/preflight", headers=auth_headers,
                    files=[("files", ("pre.csv", io.BytesIO(CSV_CDR.encode()), "text/csv"))])
    item = r.json()["files"][0]
    assert item["ok"] is False
    assert "duplicate" in item


# ---------------------------------------------------------------- end-to-end

def test_end_to_end_multi_dataset_ingestion(client, auth_headers, tmp_path):
    pdf = _make_text_pdf(tmp_path / "doc.pdf", FIR_TEXT)
    case_id = _new_case(client, auth_headers, "E2E Import Case")

    # preflight everything first
    files = [
        ("files", ("e2e_cdr.csv", io.BytesIO(CSV_CDR.encode()), "text/csv")),
        ("files", ("e2e_txn.json", io.BytesIO(TXN_JSON.encode()), "application/json")),
        ("files", ("e2e_fir.pdf", io.BytesIO(pdf), "application/pdf")),
    ]
    r = client.post(f"/api/cases/{case_id}/imports/preflight", headers=auth_headers, files=files)
    assert r.status_code == 200
    results = r.json()["files"]
    assert all(f["ok"] for f in results)
    assert [f["file_type"] for f in results] == ["csv", "json", "pdf"]

    # import the batch
    r = _post_imports(client, auth_headers, case_id, files)
    assert r.status_code == 200, r.text
    docs = r.json()["imports"]
    assert len(docs) == 3
    for d in docs:
        st = _wait_for_status(client, auth_headers, d["id"])
        assert st["status"] == "completed", st

    hist = client.get(f"/api/cases/{case_id}/imports", headers=auth_headers).json()
    assert len(hist["imports"]) == 3
    assert {i["filename"] for i in hist["imports"]} == {"e2e_cdr.csv", "e2e_txn.json",
                                                        "e2e_fir.pdf"}
    # shared actor across all three datasets got linked by the pipeline
    persons = {p["name"] for p in client.get("/api/persons", headers=auth_headers).json()}
    assert "Farhan Ali" in persons and "Zoya Khan" in persons
    # evidence for the case is traceable to the source filenames
    evidence = client.get(f"/api/evidence?case_id={case_id}", headers=auth_headers).json()
    sources = {e["source"] for e in evidence}
    assert "e2e_cdr.csv" in sources and "e2e_txn.json" in sources
    # timeline contains dated events from the datasets
    timeline = client.get(f"/api/timeline?case_id={case_id}", headers=auth_headers).json()
    assert timeline


def test_legacy_upload_invalid_json_still_fails_cleanly(client, auth_headers):
    r = client.post(
        "/api/cases/C101/upload",
        headers=auth_headers,
        files={"file": ("legacy_bad.json", io.BytesIO(b"{oops"), "application/json")},
    )
    assert r.status_code == 200
    st = _wait_for_status(client, auth_headers, r.json()["id"])
    assert st["status"] == "failed"
    assert "JSON structure is invalid" in st["error"]
