import io
import csv
import os

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    flash,
    Response
)

import db
import functions as fn
import uuid


app = Flask(__name__)
app.secret_key = "secret"

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.before_request
def ensure_anon_id():

    if "uid" not in session:
        session["uid"] = f"anon_{uuid.uuid4().hex[:12]}"
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
        fn.create_user(
            request.form["username"],
            request.form["password"],
            0
        )
        return redirect("/login")
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
            return "missing username or password"

        # FIX: was called twice — once before and once after the guard above
        user = fn.get_user(username, password)

        if user:
            session["uid"] = user["id"]
            session["admin"] = user["is_admin"]
            return redirect("/")

        return "invalid login"

    return render_template("login.html")


# =========================
# 🚪 LOGOUT
# =========================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# =========================
# 📤 UPLOAD (ADMIN ONLY)
# =========================
@app.route("/upload", methods=["GET", "POST"])
def upload():
    if not session.get("admin"):
        return "403 admin only"

    if request.method == "POST":
        f = request.files["img"]
        path = os.path.join(UPLOAD_DIR, f.filename)
        f.save(path)

        conn = db.get_db()
        cur = conn.execute(
            "INSERT INTO maps(filename) VALUES(?)", (f.filename,)
        )
        map_id = cur.lastrowid
        conn.commit()
        conn.close()

        fn.split_image(path, map_id)

        return redirect("/")

    return render_template("upload.html")


# =========================
# ✍️ TRANSCRIPTION TASK
# =========================
@app.route("/task")
def task():
    if "uid" not in session:
        return redirect("/login")

    t = fn.get_next_transcription_task(session["uid"])

    if not t:
        flash("✅ All transcription tasks are completed.")
        return redirect("/")

    ann = fn.get_annotations(t["id"])
    return render_template("task.html", t=t, annotations=ann)

@app.route("/add/<int:cid>", methods=["POST"])
def add(cid):

    uid = session.get("uid")

    fn.add_transcription(
        cid,
        uid,
        request.form["survey_id"],
        request.form["word"]
    )

    fn.mark_chunk_done(cid, uid)

    return redirect("/task")
# =========================
# ✅ REVIEW TASK
# =========================
@app.route("/review")
def review():

    if "uid" not in session:
        return redirect("/login")

    if str(session["uid"]).startswith("anon_"):
        return "Please register to review"

    t = fn.assign_review_task(session["uid"])

    if not t:
        flash("No review tasks available")
        return redirect("/")

    ann = fn.get_annotations_for_review(t["id"])
    return render_template("review.html", t=t, annotations=ann)

# =========================
# 📊 ADMIN: EVOLUTION
# =========================
@app.route("/admin/evolution")
def evolution():

    if not session.get("admin"):
        return "403"

    maps = fn.get_evolution_stats()

    return render_template(
        "evolution.html",
        maps=maps
    )
# =========================
# 📥 EXPORT CSV
# =========================
@app.route("/export_csv/<int:map_id>")
def export_csv(map_id):
    if not session.get("admin"):
        return "403"

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