from types import SimpleNamespace

from app.routers import graph as graph_router


def test_entity_details_returns_provenance(monkeypatch):
    case = SimpleNamespace(id="C1", name="Case One", description="", status="open")
    document = SimpleNamespace(
        id="DOC1", filename="report.pdf", file_type="pdf", status="completed",
        created_at=None, processed_at=None, file_size=123, source_text="source",
    )
    entity = SimpleNamespace(
        id=7, case_id="C1", entity_type="VEHICLE", original_value="ABC-123",
        normalized_value="abc123", confidence=0.98, extraction_method="parser",
        source_reference="report.pdf:p4", source_document_id="DOC1",
        observed_date="2026-01-01", observed_time="12:00", date_precision="exact",
        meta={"color": "blue"},
    )
    person = SimpleNamespace(id="P1", name="Person One")

    class Query:
        def __init__(self, items): self.items = items
        def filter(self, *args, **kwargs): return self
        def join(self, *args, **kwargs): return self
        def all(self): return self.items
        def first(self): return self.items[0] if self.items else None
        def order_by(self, *args, **kwargs): return self

    class DB:
        def get(self, cls, key):
            name = getattr(cls, "__name__", "")
            return {"Case": case, "Document": document, "Entity": entity}.get(name)
        def query(self, cls):
            name = getattr(cls, "__name__", "")
            return Query([person] if name == "Person" else [])

    user = SimpleNamespace(role="investigator")
    monkeypatch.setattr(graph_router, "ensure_case_access", lambda db, user, cid: None)

    # The route only uses SQLAlchemy query/filter methods, so lightweight test doubles
    # keep this regression test independent of the local database service.
    result = graph_router.entity_details("7", "C1", DB(), user)

    assert result["entity"]["id"] == 7
    assert result["entity"]["entity_type"] == "VEHICLE"
    assert result["case"]["id"] == "C1"
    assert result["document"]["filename"] == "report.pdf"
    assert result["document"]["source_available"] is True
