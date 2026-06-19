import os
import sqlite3

DB = os.environ.get("TRANSCRIPTALF_DB", "alf.db")


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn          # FIX: was outside the function body (IndentationError)


def init_db():
    conn = get_db()
    c = conn.cursor()

    # USERS
    c.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            is_admin INTEGER DEFAULT 0
        )
    """)

    # MAPS
    c.execute("""
        CREATE TABLE IF NOT EXISTS maps(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT
        )
    """)

    # CHUNKS
    c.execute("""
        CREATE TABLE IF NOT EXISTS chunks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            map_id INTEGER,
            idx INTEGER,
            image TEXT,
            transcriber_id INTEGER,
            reviewer_id INTEGER,
            status TEXT DEFAULT 'free'
        )
    """)

    # TRANSCRIPTIONS
    c.execute("""
        CREATE TABLE IF NOT EXISTS transcriptions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id INTEGER,
            user_id INTEGER,
            survey_id TEXT,
            word_form TEXT
        )
    """)

    # REVIEW ENTRIES
    c.execute("""
        CREATE TABLE IF NOT EXISTS review_entries(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id INTEGER,
            survey_id TEXT,
            original_word TEXT,
            corrected_word TEXT,
            reviewer_id INTEGER
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS keyboard_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            character TEXT NOT NULL,
            note TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
