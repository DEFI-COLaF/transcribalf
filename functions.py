import os
from PIL import Image
from werkzeug.security import check_password_hash, generate_password_hash
from db import get_db


CHUNK_DIR = os.environ.get("TRANSCRIPTALF_CHUNK_DIR", "static/chunks")
CHUNK_URL_PREFIX = os.environ.get("TRANSCRIPTALF_CHUNK_URL_PREFIX", "chunks")
CHUNK_GRID_COLUMNS = int(os.environ.get("TRANSCRIPTALF_CHUNK_GRID_COLUMNS", "10"))
CHUNK_GRID_ROWS = int(os.environ.get("TRANSCRIPTALF_CHUNK_GRID_ROWS", "5"))
CHUNK_OVERLAP_RATIO = float(os.environ.get("TRANSCRIPTALF_CHUNK_OVERLAP_RATIO", "0.2"))
CHUNK_PNG_COMPRESS_LEVEL = int(os.environ.get("TRANSCRIPTALF_CHUNK_PNG_COMPRESS_LEVEL", "1"))


# =========================
# ✂️ CHUNKING
# =========================
def _axis_positions(length, chunk_size, step):
    if length <= chunk_size:
        return [0]

    positions = list(range(0, length - chunk_size + 1, step))
    last_position = length - chunk_size

    if positions[-1] != last_position:
        positions.append(last_position)

    return positions


def split_image(path, map_id):

    img = Image.open(path)
    w, h = img.size

    os.makedirs(CHUNK_DIR, exist_ok=True)

    conn = get_db()
    cur = conn.cursor()

    chunk_size = max(
        1,
        min(
            w // CHUNK_GRID_COLUMNS,
            h // CHUNK_GRID_ROWS,
        )
    )

    step = max(1, int(chunk_size * (1 - CHUNK_OVERLAP_RATIO)))
    x_positions = _axis_positions(w, chunk_size, step)
    y_positions = _axis_positions(h, chunk_size, step)

    idx = 0

    for y in y_positions:
        for x in x_positions:

            box = (
                x,
                y,
                x + chunk_size,
                y + chunk_size
            )

            chunk = img.crop(box)

            fname = f"{map_id}_{idx}.png"
            out = os.path.join(CHUNK_DIR, fname)

            chunk.save(out, compress_level=CHUNK_PNG_COMPRESS_LEVEL)

            cur.execute("""
                INSERT INTO chunks(map_id, idx, image)
                VALUES (?,?,?)
            """, (map_id, idx, f"{CHUNK_URL_PREFIX}/{fname}"))

            idx += 1

    conn.commit()
    conn.close()

# =========================
# ✍️ TRANSCRIPTION QUEUE
# =========================
def get_next_transcription_task(user_id):

    conn = get_db()

    task = conn.execute("""
        SELECT *
        FROM chunks
        WHERE transcriber_id = ?
        AND status = 'assigned'
        ORDER BY id ASC
        LIMIT 1
    """, (user_id,)).fetchone()

    if task:
        conn.close()
        return task

    task = conn.execute("""
        UPDATE chunks
        SET transcriber_id = ?,
            status = 'assigned'
        WHERE id = (
            SELECT id
            FROM chunks
            WHERE status = 'free'
            AND transcriber_id IS NULL
            ORDER BY id ASC
            LIMIT 1
        )
        RETURNING *
    """, (user_id,)).fetchone()

    conn.commit()
    conn.close()

    return task


def add_transcription(chunk_id, user_id, survey_id, word_form):
    conn = get_db()

    conn.execute("""
        INSERT INTO transcriptions(chunk_id, user_id, survey_id, word_form)
        VALUES (?,?,?,?)
    """, (chunk_id, user_id, survey_id, word_form))

    conn.commit()
    conn.close()


def add_transcriptions(chunk_id, user_id, entries):
    conn = get_db()

    chunk = conn.execute("""
        SELECT id
        FROM chunks
        WHERE id = ?
        AND transcriber_id = ?
        AND status = 'assigned'
    """, (chunk_id, user_id)).fetchone()

    if not chunk:
        conn.close()
        raise ValueError("chunk is not assigned to this transcriber")

    conn.executemany("""
        INSERT INTO transcriptions(chunk_id, user_id, survey_id, word_form)
        VALUES (?,?,?,?)
    """, [
        (chunk_id, user_id, entry["survey_id"], entry["word"])
        for entry in entries
    ])

    conn.execute("""
        UPDATE chunks
        SET status = 'done'
        WHERE id = ?
        AND transcriber_id = ?
    """, (chunk_id, user_id))

    conn.commit()
    conn.close()

def get_annotations(chunk_id):
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM transcriptions WHERE chunk_id=?
    """, (chunk_id,)).fetchall()
    conn.close()
    return rows


# =========================
# ✅ REVIEW QUEUE
# =========================
def assign_review_task(user_id):

    conn = get_db()

    # block anonymous users
    if str(user_id).startswith("anon_"):
        conn.close()
        return None

    task = conn.execute("""
        SELECT *
        FROM chunks
        WHERE reviewer_id = ?
        AND status = 'done'
        ORDER BY id ASC
        LIMIT 1
    """, (user_id,)).fetchone()

    if task:
        conn.close()
        return task

    task = conn.execute("""
        UPDATE chunks
        SET reviewer_id = ?
        WHERE id = (
            SELECT id
            FROM chunks
            WHERE status = 'done'
            AND transcriber_id IS NOT NULL
            AND reviewer_id IS NULL
            AND transcriber_id != ?
            ORDER BY id ASC
            LIMIT 1
        )
        AND reviewer_id IS NULL
        RETURNING *
    """, (user_id, user_id)).fetchone()

    conn.commit()
    conn.close()

    return task


def get_annotations_for_review(chunk_id):
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM transcriptions WHERE chunk_id=?
    """, (chunk_id,)).fetchall()
    conn.close()
    return rows

def add_review(chunk_id, user_id, survey_id, original_word, corrected_word):
    conn = get_db()

    conn.execute("""
        INSERT INTO review_entries(
            chunk_id,
            survey_id,
            original_word,
            corrected_word,
            reviewer_id
        )
        VALUES (?,?,?,?,?)
    """, (
        chunk_id,
        survey_id,
        original_word,
        corrected_word,
        user_id
    ))

    conn.commit()
    conn.close()


def add_reviews(chunk_id, user_id, entries):
    conn = get_db()

    chunk = conn.execute("""
        SELECT id
        FROM chunks
        WHERE id = ?
        AND reviewer_id = ?
        AND status = 'done'
    """, (chunk_id, user_id)).fetchone()

    if not chunk:
        conn.close()
        raise ValueError("chunk is not assigned to this reviewer")

    conn.executemany("""
        INSERT INTO review_entries(
            chunk_id,
            survey_id,
            original_word,
            corrected_word,
            reviewer_id
        )
        VALUES (?,?,?,?,?)
    """, [
        (
            chunk_id,
            entry["survey_id"],
            entry["original_word"],
            entry["corrected_word"],
            user_id
        )
        for entry in entries
    ])

    conn.execute("""
        UPDATE chunks
        SET status = 'reviewed'
        WHERE id = ?
        AND reviewer_id = ?
    """, (chunk_id, user_id))

    conn.commit()
    conn.close()

# =========================
# 👤 USER AUTH HELPERS
# =========================
def create_user(username, password, is_admin=0):
    conn = get_db()
    conn.execute(
        "INSERT INTO users(username,password,is_admin) VALUES (?,?,?)",
        (username, generate_password_hash(password), is_admin)
    )
    conn.commit()
    conn.close()


def get_user(username, password):
    conn = get_db()

    user = conn.execute("""
        SELECT * FROM users
        WHERE username=?
    """, (username,)).fetchone()

    conn.close()

    if user and check_password_hash(user["password"], password):
        return user

    return None


def get_evolution_stats():
    conn = get_db()

    maps = conn.execute("""
        SELECT *
        FROM maps
        ORDER BY id
    """).fetchall()

    result = []

    for m in maps:

        total_chunks = conn.execute("""
            SELECT COUNT(*)
            FROM chunks
            WHERE map_id=?
        """, (m["id"],)).fetchone()[0]

        transcribed_chunks = conn.execute("""
            SELECT COUNT(*)
            FROM chunks
            WHERE map_id=?
            AND transcriber_id IS NOT NULL
        """, (m["id"],)).fetchone()[0]

        reviewed_chunks = conn.execute("""
            SELECT COUNT(*)
            FROM chunks
            WHERE map_id=?
            AND reviewer_id IS NOT NULL
        """, (m["id"],)).fetchone()[0]

        details = conn.execute("""
            SELECT
                c.idx,
                t.survey_id,
                t.word_form,

                COALESCE(
                    r.corrected_word,
                    ''
                ) AS corrected_word

            FROM chunks c

            LEFT JOIN transcriptions t
                ON t.chunk_id = c.id

            LEFT JOIN review_entries r
                ON r.chunk_id = c.id
                AND r.survey_id = t.survey_id

            WHERE c.map_id=?

            ORDER BY c.idx
        """, (m["id"],)).fetchall()

        result.append({

            "id": m["id"],
            "filename": m["filename"],

            "total_chunks": total_chunks,

            "transcribed_chunks":
                transcribed_chunks,

            "reviewed_chunks":
                reviewed_chunks,

            "transcribed_percent":
                round(
                    100 * transcribed_chunks / total_chunks,
                    1
                ) if total_chunks else 0,

            "reviewed_percent":
                round(
                    100 * reviewed_chunks / total_chunks,
                    1
                ) if total_chunks else 0,

            "details": details
        })

    conn.close()

    return result

def get_map_export(map_id):

    conn = get_db()

    rows = conn.execute("""
        SELECT
            c.idx,
            t.survey_id,
            t.word_form,
            COALESCE(r.corrected_word, '') AS corrected_word

        FROM chunks c

        LEFT JOIN transcriptions t
            ON t.chunk_id = c.id

        LEFT JOIN review_entries r
            ON r.chunk_id = c.id
            AND r.survey_id = t.survey_id

        WHERE c.map_id = ?

        ORDER BY c.idx, t.survey_id
    """, (map_id,)).fetchall()

    conn.close()

    return rows

def mark_chunk_done(chunk_id, user_id):

    conn = get_db()

    conn.execute("""
        UPDATE chunks
        SET status = 'done'
        WHERE id = ?
        AND transcriber_id = ?
    """, (chunk_id, user_id))

    conn.commit()
    conn.close()


def add_keyboard_request(user_id, character, note=""):
    conn = get_db()

    conn.execute("""
        INSERT INTO keyboard_requests(user_id, character, note)
        VALUES (?,?,?)
    """, (str(user_id), character, note))

    conn.commit()
    conn.close()
