import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    import db
    import functions
    import app as app_module

    monkeypatch.chdir(tmp_path)
    db.DB = str(tmp_path / "test.db")
    functions.CHUNK_DIR = str(tmp_path / "static" / "chunks")
    functions.CHUNK_URL_PREFIX = "chunks"
    app_module.UPLOAD_DIR = str(tmp_path / "uploads")
    os.makedirs(app_module.UPLOAD_DIR, exist_ok=True)

    db.init_db()

    app_module.app.config.update(
        TESTING=True,
        SECRET_KEY="test-secret",
    )

    return app_module.app.test_client()


def seed_user(username, password, is_admin=0):
    import functions

    functions.create_user(username, password, is_admin)


def csrf_headers(client):
    token = "test-csrf-token"

    with client.session_transaction() as session:
        session["_csrf_token"] = token

    return {"X-CSRFToken": token}


def csrf_form(client, data=None):
    token = "test-csrf-token"

    with client.session_transaction() as session:
        session["_csrf_token"] = token

    form = {"_csrf_token": token}
    form.update(data or {})
    return form


def login(client, username, password):
    return client.post(
        "/login",
        data=csrf_form(client, {"username": username, "password": password}),
        follow_redirects=False,
    )
