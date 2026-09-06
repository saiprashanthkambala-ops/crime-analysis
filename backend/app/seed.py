"""Synthetic demo dataset + seeding.

Builds a coherent investigation ("Operation Red River" + a vehicle-theft case)
across an FIR (PDF), CDR (CSV) and transactions (JSON), then runs the full
pipeline so the app is demonstrable out of the box.
"""
import csv
import io
import json
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from .config import settings, DATA_DIR
from .database import Base, engine, SessionLocal
from .models import Case, Document, User
from .security import hash_password
from .services.pipeline import process_document

SYNTH_DIR = DATA_DIR / "synthetic"


def _make_fir_pdf(path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=A4)
    lines = [
        "FIRST INFORMATION REPORT — FIR NO. FIR/2026/0841",
        "Police Station: Cyberabad (Hyderabad)",
        "Date of offence: 20-Aug-2026",
        "Complainant: Inspector D. Rao",
        "",
        "Complaint: On 20-Aug-2026, Ravi Kumar was reported to have called",
        "9876543210 from Hyderabad and transferred Rs 50,000 to an account",
        "held by Suresh Reddy. The vehicle TS09AB1234 was observed at the",
        "location near Banjara Hills. Meena Devi was also present on 21-Aug-2026.",
        "Accused known to police: Ravi Kumar, Suresh Reddy, Meena Devi.",
        "Sections: 420, 120B IPC. Status: Under investigation.",
    ]
    y = 800
    for line in lines:
        c.drawString(60, y, line)
        y -= 20
    c.showPage()
    c.save()


def _cdr_rows():
    header = ["caller_name", "caller_phone", "callee_name", "callee_phone", "timestamp", "duration"]
    rows = [
        ["Ravi K.", "9876543210", "Suresh Reddy", "9123456780", "20-Aug-2026 10:15", "124"],
        ["Ravi K.", "9876543210", "Suresh Reddy", "9123456780", "20-Aug-2026 11:05", "318"],
        ["Suresh Reddy", "9123456780", "Ravi K.", "9876543210", "21-Aug-2026 09:40", "87"],
        ["Ravi Kumar", "9876543210", "Suresh", "9123456780", "21-Aug-2026 14:10", "205"],
        ["Ravi Kumar", "9876543210", "Suresh", "9123456780", "22-Aug-2026 18:22", "452"],
        ["Suresh Reddy", "9123456780", "Arjun Singh", "9000001111", "22-Aug-2026 19:01", "150"],
        ["Suresh Reddy", "9123456780", "Arjun Singh", "9000001111", "23-Aug-2026 08:15", "96"],
        ["Ravi Kumar", "9876543210", "Meena Devi", "9888001122", "23-Aug-2026 12:30", "60"],
        ["Arjun Singh", "9000001111", "Suresh Reddy", "9123456780", "24-Aug-2026 10:05", "133"],
        ["Ravi Kumar", "9876543210", "Suresh Reddy", "9123456780", "25-Aug-2026 16:45", "289"],
        ["Meena Devi", "9888001122", "Ravi Kumar", "9876543210", "25-Aug-2026 17:20", "41"],
    ]
    return header, rows


def _transactions():
    return [
        {"type": "transaction", "timestamp": "20-Aug-2026 11:05",
         "sender": "Ravi Kumar S.", "sender_account": "5010001234",
         "receiver": "Suresh Reddy", "receiver_account": "6020005678",
         "amount": 50000, "location": "Hyderabad"},
        {"type": "transaction", "timestamp": "21-Aug-2026 10:30",
         "sender": "Ravi Kumar", "sender_account": "5010001234",
         "receiver": "Suresh Reddy", "receiver_account": "6020005678",
         "amount": 75000, "location": "Hyderabad"},
        {"type": "transaction", "timestamp": "22-Aug-2026 09:00",
         "sender": "Suresh Reddy", "sender_account": "6020005678",
         "receiver": "Arjun Singh", "receiver_account": "7030009012",
         "amount": 40000, "location": "Hyderabad"},
        {"type": "transaction", "timestamp": "23-Aug-2026 11:15",
         "sender": "Suresh Reddy", "sender_account": "6020005678",
         "receiver": "Arjun Singh", "receiver_account": "7030009012",
         "amount": 30000, "location": "Hyderabad"},
        {"type": "transaction", "timestamp": "24-Aug-2026 12:00",
         "sender": "Ravi Kumar", "sender_account": "5010001234",
         "receiver": "Meena Devi", "receiver_account": "8040003456",
         "amount": 12000, "location": "Hyderabad"},
    ]


def _cctv_observations():
    return [
        {"type": "location_observation", "timestamp": "20-Aug-2026 12:30",
         "person": "Ravi Kumar", "other_person": "Suresh Reddy", "location": "Banjara Hills",
         "vehicle": "TS09AB1234"},
        {"type": "location_observation", "timestamp": "21-Aug-2026 13:45",
         "person": "Ravi Kumar", "other_person": "Suresh Reddy", "location": "Banjara Hills",
         "vehicle": "TS09AB1234"},
        {"type": "location_observation", "timestamp": "24-Aug-2026 15:10",
         "person": "Ravi Kumar", "other_person": "Suresh Reddy", "location": "Banjara Hills",
         "vehicle": "TS09AB1234"},
    ]


def _build_synthetic_files():
    SYNTH_DIR.mkdir(parents=True, exist_ok=True)
    fir = SYNTH_DIR / "FIR_01.pdf"
    _make_fir_pdf(fir)

    cdr = SYNTH_DIR / "CDR_2026_08.csv"
    header, rows = _cdr_rows()
    with open(cdr, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)

    txn = SYNTH_DIR / "Transactions.json"
    with open(txn, "w") as f:
        json.dump(_transactions(), f, indent=2)

    cctv = SYNTH_DIR / "CCTV_Report.json"
    with open(cctv, "w") as f:
        json.dump(_cctv_observations(), f, indent=2)

    return {
        "FIR_01.pdf": fir.read_bytes(),
        "CDR_2026_08.csv": cdr.read_bytes(),
        "Transactions.json": txn.read_bytes(),
        "CCTV_Report.json": cctv.read_bytes(),
    }


def seed(db: Session):
    if db.query(User).count() > 0:
        return

    admin = User(username="admin", email="admin@crimelink.local", full_name="System Admin",
                 role="admin", password_hash=hash_password("admin123"))
    inv1 = User(username="investigator1", email="i1@crimelink.local", full_name="Investigator One",
                role="investigator", password_hash=hash_password("investor1"))
    inv2 = User(username="investigator2", email="i2@crimelink.local", full_name="Investigator Two",
                role="investigator", password_hash=hash_password("investor2"))
    db.add_all([admin, inv1, inv2])
    db.commit()

    c1 = Case(id="C101", name="Operation Red River", description="Suspected drug-trafficking network.",
              status="open", created_by=inv1.id)
    c2 = Case(id="C204", name="Vehicle Theft Ring", description="Organized vehicle theft investigation.",
              status="open", created_by=inv1.id)
    db.add_all([c1, c2])
    db.commit()
    c1.users.append(inv1)
    c1.users.append(inv2)
    c1.users.append(admin)
    c2.users.append(inv1)
    db.commit()

    files = _build_synthetic_files()
    doc_defs = [
        ("DOC001", c1.id, "FIR_01.pdf", "pdf"),
        ("DOC002", c1.id, "CDR_2026_08.csv", "csv"),
        ("DOC003", c1.id, "Transactions.json", "json"),
        ("DOC004", c1.id, "CCTV_Report.json", "json"),
    ]
    for doc_id, case_id, fname, ftype in doc_defs:
        doc = Document(id=doc_id, case_id=case_id, filename=fname, file_type=ftype,
                       uploaded_by=inv1.id)
        db.add(doc)
        db.commit()
        process_document(db, doc, files[fname])


def run_seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
