from __future__ import annotations

import sqlite3
from pathlib import Path


def migrate_accounts(db_path: Path | str) -> None:
    """Add authentication tables atomically, retaining all legacy rows/files."""
    connection = sqlite3.connect(db_path, timeout=30)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        if not connection.execute("SELECT 1 FROM schema_migrations WHERE version = 1").fetchone():
            connection.execute("""CREATE TABLE accounts (
                account_id TEXT PRIMARY KEY, account_name TEXT NOT NULL,
                phone TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL)""")
            connection.execute("""CREATE TABLE account_sessions (
                token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(account_id),
                expires_at INTEGER NOT NULL, created_at INTEGER NOT NULL)""")
            connection.execute("CREATE INDEX session_account ON account_sessions(account_id)")
            connection.execute("""CREATE TABLE course_ownership (
                course_id TEXT PRIMARY KEY REFERENCES courses(id) ON DELETE CASCADE,
                account_id TEXT NOT NULL REFERENCES accounts(account_id))""")
            connection.execute("CREATE INDEX ownership_account ON course_ownership(account_id)")
            connection.execute("INSERT INTO schema_migrations VALUES (1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
