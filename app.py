import io
import csv
import os
import secrets
import sqlite3

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    Response,
    jsonify,
)
from PIL import Image, UnidentifiedImageError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

import db
import functions as fn
import uuid


app = Flask(__name__)
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
    x_prefix=1,
)

if os.environ.get("FLASK_ENV") == "production" and not os.environ.get("FLASK_SECRET_KEY"):
    raise RuntimeError("FLASK_SECRET_KEY must be set in production")

app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production",
)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def is_registered_user():
    uid = session.get("uid")
    return uid and not str(uid).startswith("anon_")


def is_allowed_image(filename):
    return os.path.splitext(filename.lower())[1] in ALLOWED_EXTENSIONS


def csrf_token():
    token = session.get("_csrf_token")

    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token

    return token


def is_valid_csrf():
    token = (
        request.form.get("_csrf_token")
        or request.headers.get("X-CSRFToken")
    )
    return token and token == session.get("_csrf_token")


@app.context_processor
def inject_csrf_token():
    return {"csrf_token": csrf_token}


def is_valid_password(password):
    return len(password) >= 8


def is_valid_image(path):
    try:
        with Image.open(path) as img:
            img.verify()
    except (UnidentifiedImageError, OSError):
        return False

    return True


def unique_upload_path(filename):
    base, ext = os.path.splitext(filename)
    path = os.path.join(UPLOAD_DIR, filename)

    while os.path.exists(path):
        filename = f"{base}_{uuid.uuid4().hex[:8]}{ext}"
        path = os.path.join(UPLOAD_DIR, filename)

    return filename, path

@app.before_request
def ensure_anon_id():

    if "uid" not in session:
        session["uid"] = f"anon_{uuid.uuid4().hex[:12]}"

    if request.method == "POST" and not is_valid_csrf():
        if request.is_json:
            return jsonify({"error": "invalid csrf token"}), 400
        return "invalid csrf token", 400
# =========================
# 🏠 HOME
# =========================
@app.route("/")
def home():
    return render_template("home.html")


# =========================
# 👤 REGISTER
# =========================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            return "missing username or password", 400

        if not is_valid_password(password):
            return "password must contain at least 8 characters", 400

        try:
            fn.create_user(
                username,
                password,
                0
            )
        except sqlite3.IntegrityError:
            return "username already exists", 409

        return redirect(url_for("login"))
    return render_template("register.html")


# =========================
# 🔐 LOGIN
# =========================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")

        if not username or not password:
            return "missing username or password", 400

        # FIX: was called twice — once before and once after the guard above
        user = fn.get_user(username, password)

        if user:
            session["uid"] = user["id"]
            session["admin"] = user["is_admin"]
            return redirect(url_for("home"))

        return "invalid login", 401

    return render_template("login.html")


# =========================
# 🚪 LOGOUT
# =========================
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# =========================
# 📤 UPLOAD (ADMIN ONLY)
# =========================
@app.route("/upload", methods=["GET", "POST"])
def upload():
    if not session.get("admin"):
        return "403 admin only", 403

    if request.method == "POST":
        files = [
            f for f in request.files.getlist("img")
            if f and f.filename
        ]

        if not files:
            return "missing image", 400

        uploaded_count = 0

        for f in files:
            filename = secure_filename(f.filename)

            if not is_allowed_image(filename):
                return "unsupported image type", 400

            filename, path = unique_upload_path(filename)
            f.save(path)

            if not is_valid_image(path):
                os.remove(path)
                return "invalid image file", 400

            conn = db.get_db()
            cur = conn.execute(
                "INSERT INTO maps(filename) VALUES(?)", (filename,)
            )
            map_id = cur.lastrowid
            conn.commit()
            conn.close()

            fn.split_image(path, map_id)
            uploaded_count += 1

        flash(f"{uploaded_count} map(s) uploaded and split.")

        return redirect(url_for("home"))

    return render_template("upload.html")


# =========================
# ✍️ TRANSCRIPTION TASK
# =========================
@app.route("/task")
def task():
    if "uid" not in session:
        return redirect(url_for("login"))

    t = fn.get_next_transcription_task(session["uid"])

    if not t:
        flash("✅ All transcription tasks are completed.")
        return redirect(url_for("home"))

    ann = fn.get_annotations(t["id"])
    return render_template("task.html", t=t, annotations=ann)

@app.route("/add/<int:cid>", methods=["POST"])
def add(cid):

    uid = session.get("uid")

    if not uid:
        return "login required", 401

    fn.add_transcription(
        cid,
        uid,
        request.form["survey_id"],
        request.form["word"]
    )

    fn.mark_chunk_done(cid, uid)

    return redirect(url_for("task"))


@app.route("/add_many/<int:cid>", methods=["POST"])
def add_many(cid):

    uid = session.get("uid")

    if not uid:
        return jsonify({"error": "login required"}), 401

    raw_entries = request.get_json(silent=True) or []

    if not isinstance(raw_entries, list):
        return jsonify({"error": "invalid transcription payload"}), 400

    entries = [
        {
            "survey_id": entry.get("survey_id", "").strip(),
            "word": entry.get("word", "").strip(),
        }
        for entry in raw_entries
        if isinstance(entry, dict)
    ]

    if len(entries) != len(raw_entries):
        return jsonify({"error": "invalid transcription row"}), 400

    for entry in entries:
        has_survey = bool(entry["survey_id"])
        has_word = bool(entry["word"])

        if has_survey != has_word:
            return jsonify({"error": "each row needs both a number and a word"}), 400

        if has_survey and not entry["survey_id"].isdigit():
            return jsonify({"error": "survey number must contain digits only"}), 400

    entries = [entry for entry in entries if entry["survey_id"]]

    try:
        fn.add_transcriptions(cid, uid, entries)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 403

    return jsonify({"saved": len(entries)})


@app.route("/task/<int:cid>/previous", methods=["POST"])
def previous_task(cid):

    uid = session.get("uid")

    if not uid:
        return jsonify({"error": "login required"}), 401

    try:
        previous_id = fn.assign_previous_transcription_task(cid, uid)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 403

    if not previous_id:
        return jsonify({"error": "no previous chunk"}), 404

    return jsonify({"chunk_id": previous_id})
# =========================
# ✅ REVIEW TASK
# =========================
@app.route("/review")
def review():

    if "uid" not in session:
        return redirect(url_for("login"))

    if str(session["uid"]).startswith("anon_"):
        return "Please register to review"

    t = fn.assign_review_task(session["uid"])

    if not t:
        flash("No review tasks available")
        return redirect(url_for("home"))

    ann = fn.get_annotations_for_review(t["id"])
    return render_template("review.html", t=t, annotations=ann)


@app.route("/review/<int:cid>", methods=["POST"])
def submit_review(cid):

    if not is_registered_user():
        return "Please register to review", 403

    entries = []
    survey_ids = request.form.getlist("survey_id")
    original_words = request.form.getlist("original_word")
    corrected_words = request.form.getlist("corrected_word")

    for survey_id, original_word, corrected_word in zip(
        survey_ids,
        original_words,
        corrected_words
    ):
        if survey_id.strip():
            entries.append({
                "survey_id": survey_id.strip(),
                "original_word": original_word.strip(),
                "corrected_word": corrected_word.strip() or original_word.strip(),
            })

    if not entries:
        return "no review entries", 400

    try:
        fn.add_reviews(cid, session["uid"], entries)
    except ValueError as exc:
        return str(exc), 403

    return redirect(url_for("review"))


@app.route("/keyboard/request", methods=["POST"])
def request_keyboard_character():

    uid = session.get("uid")

    if not uid:
        return jsonify({"error": "login required"}), 401

    data = request.get_json(silent=True) or {}
    character = data.get("character", "").strip()
    note = data.get("note", "").strip()

    if not character:
        return jsonify({"error": "missing character"}), 400

    if len(character) > 20:
        return jsonify({"error": "character is too long"}), 400

    fn.add_keyboard_request(uid, character, note[:500])

    return jsonify({"saved": True})

# =========================
# 📊 ADMIN: EVOLUTION
# =========================
@app.route("/admin/evolution")
def evolution():

    if not session.get("admin"):
        return "403", 403

    maps = fn.get_evolution_stats()

    return render_template(
        "evolution.html",
        maps=maps
    )


@app.route("/admin/maps/<int:map_id>/delete", methods=["POST"])
def delete_map(map_id):

    if not session.get("admin"):
        return "403", 403

    try:
        fn.delete_map(map_id, UPLOAD_DIR)
    except ValueError as exc:
        return str(exc), 404

    flash("Map deleted.")
    return redirect(url_for("evolution"))
# =========================
# 📥 EXPORT CSV
# =========================
@app.route("/export_csv/<int:map_id>")
def export_csv(map_id):
    if not session.get("admin"):
        return "403", 403

    rows = fn.get_map_export(map_id)

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "chunk",
        "survey_id",
        "transcription",
        "correction"
    ])

    for r in rows:
        writer.writerow([
            r["idx"],
            r["survey_id"],
            r["word_form"],
            r["corrected_word"],   
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=map_{map_id}.csv"
        }
    )



if __name__ == "__main__":
    db.init_db()
    app.run(debug=True)
