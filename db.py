import sqlite3

DB = "alf.db"


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn          # FIX: was outside the function body (IndentationError)


def init_db():
    conn = sqlite3.connect(DB)
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

    conn.commit()
    conn.close()