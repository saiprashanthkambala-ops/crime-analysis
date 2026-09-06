"""SQLAlchemy models.

The schema mirrors the flexible, provenance-heavy document model described in
the PRD. JSON columns are used where Mongo-style documents would be used, so
swapping the persistence layer does not require changing the domain logic.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import relationship

from .database import Base


case_users = Table(
    "case_users",
    Base.metadata,
    Column("case_id", String, ForeignKey("cases.id"), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String)
    full_name = Column(String)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="investigator")  # investigator | admin
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def as_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Case(Base):
    __tablename__ = "cases"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    status = Column(String, default="open")  # open | closed | archived
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    users = relationship("User", secondary=case_users, backref="assigned_cases")
    documents = relationship("Document", back_populates="case")


class Document(Base):
    __tablename__ = "documents"
    id = Column(String, primary_key=True)
    case_id = Column(String, ForeignKey("cases.id"))
    filename = Column(String)
    file_type = Column(String)          # pdf | csv | json | txt
    status = Column(String, default="uploaded")
    error = Column(Text)
    source_text = Column(Text)
    uploaded_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime)
    # ---- dataset-import metadata (see services/dataset_import.py) ----
    file_size = Column(Integer, default=0)          # original size in bytes
    sha256 = Column(String(64), index=True)         # content hash (duplicate detection)
    records_processed = Column(Integer, default=0)  # events/records persisted
    entities_discovered = Column(Integer, default=0)
    persons_discovered = Column(Integer, default=0)
    relationships_discovered = Column(Integer, default=0)
    evidence_discovered = Column(Integer, default=0)
    warnings = Column(JSON, default=list)
    mapping = Column(JSON, default=dict)            # CSV column mapping used (field -> column)
    detected_columns = Column(JSON, default=list)   # CSV header detected at import time
    retry_count = Column(Integer, default=0)
    case = relationship("Case", back_populates="documents")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    id = Column(Integer, primary_key=True)
    document_id = Column(String, ForeignKey("documents.id"))
    status = Column(String, default="queued")
    stage = Column(String)
    message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Entity(Base):
    __tablename__ = "entities"
    id = Column(Integer, primary_key=True)
    entity_type = Column(String, index=True)
    original_value = Column(String)
    normalized_value = Column(String, index=True)
    confidence = Column(Float, default=1.0)
    extraction_method = Column(String)
    source_document_id = Column(String, ForeignKey("documents.id"))
    source_reference = Column(String)
    case_id = Column(String, ForeignKey("cases.id"))
    observed_date = Column(String)
    observed_time = Column(String)
    date_precision = Column(String, default="exact")
    meta = Column(JSON, default=dict)


class Person(Base):
    __tablename__ = "persons"
    id = Column(String, primary_key=True)
    name = Column(String, index=True)
    resolution = Column(JSON, default=dict)  # merged variants + signals + confidence
    created_at = Column(DateTime, default=datetime.utcnow)

    entities = relationship("Entity", secondary="person_entities", backref="persons")


person_entities = Table(
    "person_entities",
    Base.metadata,
    Column("person_id", String, ForeignKey("persons.id"), primary_key=True),
    Column("entity_id", Integer, ForeignKey("entities.id"), primary_key=True),
    Column("role", String),  # name | alias | phone | vehicle | account | location | organization
)


class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True)
    case_id = Column(String, ForeignKey("cases.id"))
    event_type = Column(String, index=True)
    description = Column(Text)
    observed_date = Column(String, index=True)
    observed_time = Column(String)
    date_precision = Column(String, default="exact")
    person_a_id = Column(String, ForeignKey("persons.id"))
    person_b_id = Column(String, ForeignKey("persons.id"))
    source_document_id = Column(String, ForeignKey("documents.id"))
    source_reference = Column(String)
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class Evidence(Base):
    __tablename__ = "evidence"
    id = Column(String, primary_key=True)
    type = Column(String, index=True)
    person_a_id = Column(String, ForeignKey("persons.id"))
    person_b_id = Column(String, ForeignKey("persons.id"))
    source_document_id = Column(String, ForeignKey("documents.id"))
    source_reference = Column(String)  # filename / human-readable source reference
    observed_date = Column(String)
    observed_time = Column(String)
    date_precision = Column(String, default="exact")
    confidence = Column(Float, default=1.0)
    case_id = Column(String, ForeignKey("cases.id"))
    details = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class Relationship(Base):
    __tablename__ = "relationships"
    id = Column(String, primary_key=True)
    person_a_id = Column(String, ForeignKey("persons.id"), index=True)
    person_b_id = Column(String, ForeignKey("persons.id"), index=True)
    score = Column(Float)
    strength = Column(String)  # STRONG | MODERATE | WEAK | INSUFFICIENT EVIDENCE
    signals = Column(JSON, default=list)
    decision = Column(String)  # relevant | incorrect | needs_review
    decided_by = Column(Integer, ForeignKey("users.id"))
    decided_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


relationship_evidence = Table(
    "relationship_evidence",
    Base.metadata,
    Column("relationship_id", String, ForeignKey("relationships.id"), primary_key=True),
    Column("evidence_id", String, ForeignKey("evidence.id"), primary_key=True),
)


class Feedback(Base):
    __tablename__ = "feedback"
    id = Column(Integer, primary_key=True)
    relationship_id = Column(String, ForeignKey("relationships.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    decision = Column(String)
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    action = Column(String)
    entity_type = Column(String)
    entity_id = Column(String)
    details = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
