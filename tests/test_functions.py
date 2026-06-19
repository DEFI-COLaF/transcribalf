from pathlib import Path

from PIL import Image


def test_split_image_creates_chunks_and_database_rows(app_client, tmp_path):
    import db
    import functions

    image_path = tmp_path / "map.png"
    Image.new("RGB", (100, 50), "white").save(image_path)

    functions.split_image(str(image_path), map_id=42)

    conn = db.get_db()
    rows = conn.execute(
        "SELECT map_id, idx, image FROM chunks ORDER BY idx"
    ).fetchall()
    conn.close()

    assert len(rows) == 72
    assert rows[0]["map_id"] == 42
    assert rows[0]["idx"] == 0
    assert rows[0]["image"] == "chunks/42_0.png"
    assert Path(functions.CHUNK_DIR, "42_0.png").exists()


def test_transcription_task_is_resumable_and_done_chunks_reach_review(app_client):
    import db
    import functions

    conn = db.get_db()
    conn.execute("INSERT INTO chunks(map_id, idx, image) VALUES (1, 0, 'chunks/a.png')")
    conn.execute("INSERT INTO chunks(map_id, idx, image) VALUES (1, 1, 'chunks/b.png')")
    conn.commit()
    conn.close()

    first = functions.get_next_transcription_task("anon_1")
    again = functions.get_next_transcription_task("anon_1")
    assert again["id"] == first["id"]

    functions.add_transcriptions(
        first["id"],
        "anon_1",
        [{"survey_id": "001", "word": "pain"}],
    )

    review_task = functions.assign_review_task(2)
    assert review_task["id"] == first["id"]
    assert functions.assign_review_task(2)["id"] == first["id"]


def test_review_excludes_own_transcriptions(app_client):
    import db
    import functions

    conn = db.get_db()
    conn.execute(
        """
        INSERT INTO chunks(map_id, idx, image, transcriber_id, status)
        VALUES (1, 0, 'chunks/a.png', 7, 'done')
        """
    )
    conn.commit()
    conn.close()

    assert functions.assign_review_task(7) is None
    assert functions.assign_review_task(8) is not None


def test_export_joins_corrections_by_survey_id(app_client):
    import db
    import functions

    conn = db.get_db()
    cur = conn.execute("INSERT INTO maps(filename) VALUES ('map.png')")
    map_id = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO chunks(map_id, idx, image) VALUES (?, 0, 'chunks/a.png')",
        (map_id,),
    )
    chunk_id = cur.lastrowid
    conn.execute(
        """
        INSERT INTO transcriptions(chunk_id, user_id, survey_id, word_form)
        VALUES (?, 1, '001', 'pan')
        """,
        (chunk_id,),
    )
    conn.execute(
        """
        INSERT INTO review_entries(
            chunk_id, survey_id, original_word, corrected_word, reviewer_id
        )
        VALUES (?, '001', 'pan', 'pain', 2)
        """,
        (chunk_id,),
    )
    conn.commit()
    conn.close()

    rows = functions.get_map_export(map_id)

    assert rows[0]["word_form"] == "pan"
    assert rows[0]["corrected_word"] == "pain"
