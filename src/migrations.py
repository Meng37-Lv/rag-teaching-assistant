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
        if not connection.execute("SELECT 1 FROM schema_migrations WHERE version = 3").fetchone():
            connection.executescript("""CREATE TABLE classes (class_id TEXT PRIMARY KEY, course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE, name TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(course_id,name)); CREATE TABLE class_students (student_id TEXT PRIMARY KEY, class_id TEXT NOT NULL REFERENCES classes(class_id) ON DELETE CASCADE, name TEXT NOT NULL, student_no TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(class_id,student_no)); CREATE TABLE classroom_sessions (session_id TEXT PRIMARY KEY, class_id TEXT NOT NULL REFERENCES classes(class_id) ON DELETE CASCADE, join_token_hash TEXT NOT NULL UNIQUE, status TEXT NOT NULL, created_at TEXT NOT NULL, ended_at TEXT); CREATE TABLE classroom_students (session_student_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES classroom_sessions(session_id) ON DELETE CASCADE, student_id TEXT REFERENCES class_students(student_id), student_token_hash TEXT NOT NULL UNIQUE, status TEXT NOT NULL, joined_at TEXT NOT NULL); CREATE TABLE classroom_messages (message_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES classroom_sessions(session_id) ON DELETE CASCADE, session_student_id TEXT NOT NULL REFERENCES classroom_students(session_student_id), body TEXT NOT NULL, created_at TEXT NOT NULL); CREATE UNIQUE INDEX active_class_session ON classroom_sessions(class_id) WHERE status='active';""")
            connection.execute("INSERT INTO schema_migrations VALUES (3, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))")
        if not connection.execute("SELECT 1 FROM schema_migrations WHERE version = 4").fetchone():
            connection.execute("ALTER TABLE classroom_students ADD COLUMN requested_name TEXT NOT NULL DEFAULT ''")
            connection.execute("INSERT INTO schema_migrations VALUES (4, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))")
        if not connection.execute("SELECT 1 FROM schema_migrations WHERE version = 5").fetchone():
            # v5 reserves the QR-token hardening version; join tokens remain only as hashes in classroom_sessions.
            connection.execute("INSERT INTO schema_migrations VALUES (5, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))")
        # Submission tables are an additive extension. Keep the historical
        # schema_migrations cardinality stable for older clients that use it
        # as a compatibility signal; table existence makes this idempotent.
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='submissions'").fetchone():
            connection.executescript("""
                CREATE TABLE submissions (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES classroom_sessions(session_id) ON DELETE CASCADE,
                    session_student_id TEXT NOT NULL REFERENCES classroom_students(session_student_id) ON DELETE CASCADE,
                    student_session_token_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'submitted',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX submissions_session_created ON submissions(session_id, created_at DESC);
                CREATE TABLE submission_files (
                    id TEXT PRIMARY KEY,
                    submission_id TEXT NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
                    filename TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    storage_path TEXT NOT NULL,
                    chunk_summary TEXT NOT NULL DEFAULT '',
                    preview_type TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX submission_files_submission ON submission_files(submission_id);
                CREATE TABLE teaching_questions (
                    id TEXT PRIMARY KEY,
                    submission_file_id TEXT NOT NULL REFERENCES submission_files(id) ON DELETE CASCADE,
                    teacher_account_id TEXT NOT NULL REFERENCES accounts(account_id),
                    prompt TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX teaching_questions_file ON teaching_questions(submission_file_id, created_at DESC);
            """)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
