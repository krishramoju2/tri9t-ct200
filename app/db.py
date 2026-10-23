
from pathlib import Path
import sqlite3
from datetime import datetime, timezone


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_ROOT / "data" / "ct200.db"


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def current_time():
    return datetime.now(timezone.utc).isoformat()


def initialize_database():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                version_number INTEGER NOT NULL,
                source_hash TEXT NOT NULL,
                section_count INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(filename, version_number)
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                section_number TEXT NOT NULL,
                heading TEXT NOT NULL,
                page INTEGER NOT NULL,
                document_order INTEGER NOT NULL,
                content TEXT NOT NULL,
                tables_json TEXT NOT NULL,
                lists_json TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                parent_section TEXT,
                warnings_json TEXT NOT NULL,
                FOREIGN KEY(document_id)
                    REFERENCES documents(id)
                    ON DELETE CASCADE
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS selections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(document_id)
                    REFERENCES documents(id)
                    ON DELETE CASCADE
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS selection_sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                selection_id INTEGER NOT NULL,
                section_id INTEGER NOT NULL,
                content_hash_at_selection TEXT NOT NULL,
                UNIQUE(selection_id, section_id),
                FOREIGN KEY(selection_id)
                    REFERENCES selections(id)
                    ON DELETE CASCADE,
                FOREIGN KEY(section_id)
                    REFERENCES sections(id)
                    ON DELETE CASCADE
            )
        """)


initialize_database()
