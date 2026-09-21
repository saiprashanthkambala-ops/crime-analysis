"""One-time SQLite -> PostgreSQL data migration utility.

Usage:
    python -m scripts.migrate_sqlite_to_postgres ^
        --sqlite sqlite:///C:/path/to/crime_analysis.db ^
        --postgres postgresql+psycopg://user:password@host:5432/crime_analysis

The destination schema must already exist (Phase 1). The script copies rows
without changing primary keys or investigation data and verifies row counts.
It never deletes or modifies the SQLite source.
"""

from __future__ import annotations

import argparse
from collections import OrderedDict

from sqlalchemy import MetaData, create_engine, select, text


TABLE_ORDER = (
    "users",
    "cases",
    "case_users",
    "documents",
    "processing_jobs",
    "entities",
    "persons",
    "person_entities",
    "events",
    "evidence",
    "relationships",
    "relationship_evidence",
    "feedback",
    "audit_logs",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Copy CrimeLink data from SQLite to PostgreSQL.")
    parser.add_argument("--sqlite", required=True, help="SQLite SQLAlchemy URL, e.g. sqlite:///C:/.../crime_analysis.db")
    parser.add_argument("--postgres", required=True, help="PostgreSQL SQLAlchemy URL.")
    parser.add_argument("--replace", action="store_true", help="Delete destination rows before copying. Use only for a fresh migration.")
    return parser.parse_args()


def load_tables(engine):
    metadata = MetaData()
    metadata.reflect(bind=engine)
    return metadata.tables


def copy_table(source_conn, target_conn, source_table, target_table) -> int:
    rows = source_conn.execute(select(source_table)).mappings().all()
    if not rows:
        return 0

    target_columns = {column.name for column in target_table.columns}
    payload = [
        {key: value for key, value in row.items() if key in target_columns}
        for row in rows
    ]
    target_conn.execute(target_table.insert(), payload)
    return len(payload)


def main() -> int:
    args = parse_args()
    if not args.postgres.startswith("postgresql+psycopg://"):
        raise SystemExit("Destination must be a PostgreSQL psycopg URL.")

    source_engine = create_engine(args.sqlite, future=True)
    target_engine = create_engine(args.postgres, future=True, pool_pre_ping=True)

    source_tables = load_tables(source_engine)
    target_tables = load_tables(target_engine)

    missing = [name for name in TABLE_ORDER if name in source_tables and name not in target_tables]
    if missing:
        raise SystemExit("Destination schema is missing tables: " + ", ".join(missing))

    summary: OrderedDict[str, tuple[int, int]] = OrderedDict()

    with source_engine.connect() as source_conn, target_engine.begin() as target_conn:
        if args.replace:
            # Delete in reverse dependency order so foreign keys remain valid.
            for name in reversed(TABLE_ORDER):
                if name in target_tables:
                    target_conn.execute(target_tables[name].delete())

        for name in TABLE_ORDER:
            if name not in source_tables or name not in target_tables:
                continue
            source_count = source_conn.execute(select(source_tables[name]).with_only_columns(source_tables[name].count() if False else source_tables[name].primary_key.columns)).fetchall() if False else None
            copied = copy_table(source_conn, target_conn, source_tables[name], target_tables[name])
            summary[name] = (copied, copied)

    # Re-open connections and compare source/destination row counts.
    with source_engine.connect() as source_conn, target_engine.connect() as target_conn:
        for name in summary:
            source_count = source_conn.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar_one()
            target_count = target_conn.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar_one()
            summary[name] = (int(source_count), int(target_count))

    print("\nSQLite -> PostgreSQL migration summary")
    print("=" * 50)
    failed = False
    for name, (source_count, target_count) in summary.items():
        status = "OK" if source_count == target_count else "MISMATCH"
        print(f"{name:24} source={source_count:6} target={target_count:6} {status}")
        failed = failed or source_count != target_count

    if failed:
        raise SystemExit("Migration completed with row-count mismatches.")
    print("\nMigration completed successfully. SQLite source was not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
