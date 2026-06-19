from io import BytesIO

from PIL import Image

from conftest import csrf_form, csrf_headers, login, seed_user


def test_register_and_login(app_client):
    response = app_client.post(
        "/register",
        data=csrf_form(app_client, {"username": "alice", "password": "secret123"}),
        follow_redirects=False,
    )
    assert response.status_code == 302

    response = login(app_client, "alice", "secret123")
    assert response.status_code == 302


def test_register_rejects_weak_password(app_client):
    response = app_client.post(
        "/register",
        data=csrf_form(app_client, {"username": "alice", "password": "short"}),
    )

    assert response.status_code == 400


def test_post_requires_csrf_token(app_client):
    response = app_client.post(
        "/register",
        data={"username": "alice", "password": "secret123"},
    )

    assert response.status_code == 400


def test_admin_routes_are_forbidden_for_non_admin(app_client):
    response = app_client.get("/admin/evolution")
    assert response.status_code == 403

    response = app_client.get("/export_csv/1")
    assert response.status_code == 403


def test_add_many_saves_multiple_transcriptions(app_client):
    import db

    conn = db.get_db()
    cur = conn.execute("INSERT INTO chunks(map_id, idx, image) VALUES (1, 0, 'chunks/a.png')")
    chunk_id = cur.lastrowid
    conn.commit()
    conn.close()

    with app_client.session_transaction() as session:
        session["uid"] = "anon_test"

    app_client.get("/task")
    response = app_client.post(
        f"/add_many/{chunk_id}",
        json=[
            {"survey_id": "001", "word": "pain"},
            {"survey_id": "002", "word": "vin"},
        ],
        headers=csrf_headers(app_client),
    )
    assert response.status_code == 200
    assert response.get_json()["saved"] == 2

    conn = db.get_db()
    count = conn.execute("SELECT COUNT(*) FROM transcriptions").fetchone()[0]
    status = conn.execute(
        "SELECT status FROM chunks WHERE id=?", (chunk_id,)
    ).fetchone()[0]
    conn.close()

    assert count == 2
    assert status == "done"


def test_add_many_rejects_chunk_assigned_to_another_user(app_client):
    import db

    conn = db.get_db()
    cur = conn.execute(
        """
        INSERT INTO chunks(map_id, idx, image, transcriber_id, status)
        VALUES (1, 0, 'chunks/a.png', 'other_user', 'assigned')
        """
    )
    chunk_id = cur.lastrowid
    conn.commit()
    conn.close()

    with app_client.session_transaction() as session:
        session["uid"] = "anon_test"

    response = app_client.post(
        f"/add_many/{chunk_id}",
        json=[{"survey_id": "001", "word": "pain"}],
        headers=csrf_headers(app_client),
    )

    assert response.status_code == 403


def test_submit_review_creates_review_entries(app_client):
    import db

    seed_user("reviewer", "secret")
    login(app_client, "reviewer", "secret")

    conn = db.get_db()
    cur = conn.execute(
        """
        INSERT INTO chunks(map_id, idx, image, transcriber_id, reviewer_id, status)
        VALUES (1, 0, 'chunks/a.png', 99, 1, 'done')
        """
    )
    chunk_id = cur.lastrowid
    conn.commit()
    conn.close()

    response = app_client.post(
        f"/review/{chunk_id}",
        data={
            **csrf_form(app_client),
            "survey_id": ["001"],
            "original_word": ["pan"],
            "corrected_word": ["pain"],
        },
        follow_redirects=False,
    )

    assert response.status_code == 302

    conn = db.get_db()
    row = conn.execute(
        "SELECT corrected_word FROM review_entries WHERE chunk_id=?",
        (chunk_id,),
    ).fetchone()
    status = conn.execute(
        "SELECT status FROM chunks WHERE id=?", (chunk_id,)
    ).fetchone()[0]
    conn.close()

    assert row["corrected_word"] == "pain"
    assert status == "reviewed"


def test_submit_review_rejects_chunk_assigned_to_another_reviewer(app_client):
    import db

    seed_user("second-reviewer", "secret")
    login(app_client, "second-reviewer", "secret")

    conn = db.get_db()
    cur = conn.execute(
        """
        INSERT INTO chunks(map_id, idx, image, transcriber_id, reviewer_id, status)
        VALUES (1, 0, 'chunks/a.png', 99, 999, 'done')
        """
    )
    chunk_id = cur.lastrowid
    conn.commit()
    conn.close()

    response = app_client.post(
        f"/review/{chunk_id}",
        data={
            **csrf_form(app_client),
            "survey_id": ["001"],
            "original_word": ["pan"],
            "corrected_word": ["pain"],
        },
    )

    assert response.status_code == 403


def test_keyboard_request_is_saved(app_client):
    import db

    with app_client.session_transaction() as session:
        session["uid"] = "anon_keyboard"

    response = app_client.post(
        "/keyboard/request",
        json={"character": "ã", "note": "nasal a needed"},
        headers=csrf_headers(app_client),
    )

    assert response.status_code == 200

    conn = db.get_db()
    row = conn.execute(
        "SELECT user_id, character, note, status FROM keyboard_requests"
    ).fetchone()
    conn.close()

    assert row["user_id"] == "anon_keyboard"
    assert row["character"] == "ã"
    assert row["note"] == "nasal a needed"
    assert row["status"] == "pending"


def test_keyboard_request_requires_character(app_client):
    with app_client.session_transaction() as session:
        session["uid"] = "anon_keyboard"

    response = app_client.post(
        "/keyboard/request",
        json={"character": ""},
        headers=csrf_headers(app_client),
    )

    assert response.status_code == 400


def test_upload_rejects_non_image_content(app_client, monkeypatch):
    import app as app_module

    seed_user("admin", "secret", is_admin=1)
    login(app_client, "admin", "secret")

    monkeypatch.setattr(app_module.fn, "split_image", lambda path, map_id: None)

    response = app_client.post(
        "/upload",
        data={
            **csrf_form(app_client),
            "img": (BytesIO(b"not really an image"), "map.jpg"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400


def test_upload_accepts_real_image(app_client, monkeypatch):
    import app as app_module

    seed_user("admin", "secret", is_admin=1)
    login(app_client, "admin", "secret")

    image = BytesIO()
    Image.new("RGB", (10, 10), "white").save(image, format="PNG")
    image.seek(0)
    monkeypatch.setattr(app_module.fn, "split_image", lambda path, map_id: None)

    response = app_client.post(
        "/upload",
        data={
            **csrf_form(app_client),
            "img": (image, "map.png"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
