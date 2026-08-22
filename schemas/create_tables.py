"""Idempotently create every table in table_definitions.TABLES on the DB Service.

Usage:
    python schemas/create_tables.py
"""
import dbservice_client as dbs

from table_definitions import TABLES


def main() -> None:
    session = dbs.Session()
    existing = set(session.list_tables())
    print(f"Existing tables: {sorted(existing)}")

    for name, definition in TABLES.items():
        if name in existing:
            print(f"[skip] {name} already exists")
            continue
        print(f"[create] {name} ...")
        session.create_table(**definition)
        print(f"[done] {name}")

    print(f"Final tables: {sorted(session.list_tables())}")


if __name__ == "__main__":
    main()
