"""Times Blitz - a minimalist times-tables blitz app (Flask + SQLite)."""

from __future__ import annotations

import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

import click
from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = Path(os.environ.get("BLITZ_INSTANCE", BASE_DIR / "instance"))
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.environ.get("BLITZ_DB", INSTANCE_DIR / "blitz.db"))

TABLES = list(range(2, 13))          # Year 4 target: times tables up to 12 x 12
MODES = ("count", "time")
COUNT_PRESETS = (10, 20, 30, 50)     # number of questions
TIME_PRESETS = (30, 60, 90, 120)     # seconds
COUNT_RANGE = (5, 100)
TIME_RANGE = (15, 600)
MIN_SECONDS_PER_ANSWER = 0.25        # anything faster is not humanly possible
ADMIN_SESSION_SECONDS = 4 * 3600


def load_secret_key() -> str:
    """Use SECRET_KEY if set, otherwise create and persist one."""
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    key_file = INSTANCE_DIR / "secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    key = secrets.token_hex(32)
    key_file.write_text(key)
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return key


app = Flask(__name__)
app.config.update(
    SECRET_KEY=load_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("BLITZ_HTTPS") == "1",
    MAX_CONTENT_LENGTH=64 * 1024,
)

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    password   TEXT NOT NULL UNIQUE,
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scores (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mode       TEXT NOT NULL CHECK (mode IN ('count', 'time')),
    target     INTEGER NOT NULL,
    tables     TEXT NOT NULL,
    correct    INTEGER NOT NULL,
    total      INTEGER NOT NULL,
    duration   REAL NOT NULL,
    mistakes   TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scores_user ON scores(user_id, id);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def ensure_admin_password(db: sqlite3.Connection) -> None:
    """Create the admin password on first run (env var, or random + printed)."""
    if db.execute("SELECT 1 FROM settings WHERE key = 'admin_hash'").fetchone():
        return
    password = os.environ.get("ADMIN_PASSWORD")
    generated = not password
    if generated:
        password = secrets.token_urlsafe(9)
    cur = db.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('admin_hash', ?)",
        (generate_password_hash(password),),
    )
    db.commit()
    if cur.rowcount and generated:
        print("\n" + "=" * 60)
        print("  Times Blitz - first run")
        print(f"  Admin password: {password}")
        print("  Sign in at /admin/login and change it in the admin panel.")
        print("=" * 60 + "\n", flush=True)


def init_db() -> None:
    db = sqlite3.connect(DB_PATH, timeout=10)
    try:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript(SCHEMA)
        ensure_admin_password(db)
    finally:
        db.close()


init_db()

# ---------------------------------------------------------------------------
# Security helpers: CSRF, headers, login throttling
# ---------------------------------------------------------------------------


def csrf_token() -> str:
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def csrf_protect():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token") or ""
        expected = session.get("_csrf") or ""
        if not expected or not hmac.compare_digest(sent.encode(), expected.encode()):
            abort(400, description="Your session expired. Please go back, refresh the page and try again.")


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    )
    if request.path.startswith("/admin"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


_failures: dict[tuple[str, str], list[float]] = {}
FAIL_WINDOW = 600  # seconds
FAIL_LIMITS = {"user": 40, "admin": 8}  # generous for user: a whole class may share one IP


def _recent_failures(bucket: str):
    key = (bucket, request.remote_addr or "?")
    now = time.time()
    recent = [t for t in _failures.get(key, []) if now - t < FAIL_WINDOW]
    _failures[key] = recent
    return key, recent


def is_throttled(bucket: str) -> bool:
    return len(_recent_failures(bucket)[1]) >= FAIL_LIMITS[bucket]


def record_failure(bucket: str) -> None:
    _recent_failures(bucket)[1].append(time.time())


def clear_failures(bucket: str) -> None:
    _failures.pop((bucket, request.remote_addr or "?"), None)


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(405)
@app.errorhandler(413)
def http_error(err):
    messages = {
        404: "We couldn't find that page.",
        405: "That action isn't allowed here.",
        413: "That request was too large.",
    }
    message = messages.get(err.code) or getattr(err, "description", "Something went wrong.")
    return render_template("error.html", code=err.code, message=message), err.code


# ---------------------------------------------------------------------------
# Users, passwords, formatting helpers
# ---------------------------------------------------------------------------
ADJECTIVES = [
    "happy", "brave", "swift", "clever", "sunny", "jolly", "lucky", "mighty", "quick", "bright",
    "calm", "cosmic", "daring", "eager", "fuzzy", "gentle", "golden", "kind", "lively", "magic",
    "merry", "noble", "proud", "silly", "speedy", "super", "tiny", "wild", "witty", "zippy",
]
ANIMALS = [
    "otter", "tiger", "panda", "koala", "falcon", "dolphin", "fox", "owl", "rabbit", "turtle",
    "lion", "eagle", "penguin", "badger", "gecko", "hedgehog", "llama", "moose", "newt", "puffin",
    "raven", "seal", "sloth", "squirrel", "whale", "wolf", "yak", "zebra", "bison", "lynx",
]


def generate_password(db: sqlite3.Connection) -> str:
    existing = {row["password"] for row in db.execute("SELECT password FROM users")}
    for _ in range(200):
        pw = f"{secrets.choice(ADJECTIVES)}{secrets.choice(ANIMALS)}{secrets.randbelow(90) + 10}"
        if pw not in existing:
            return pw
    return secrets.token_hex(5)


def norm_password(value: str | None) -> str:
    """Player passwords are not case sensitive (easier on tablets)."""
    return (value or "").strip().lower()


def password_problem(pw: str) -> str | None:
    if not re.fullmatch(r"\S{4,40}", pw):
        return "Passwords need 4-40 characters with no spaces."
    return None


def clean_name(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()[:40]


def find_user_by_password(pw: str):
    """Return (row, matched) - compares against every user in constant time."""
    if not pw:
        return None
    match = None
    for row in get_db().execute("SELECT * FROM users"):
        if hmac.compare_digest(row["password"].encode(), pw.encode()):
            match = row
    return match


def current_user():
    if "user_row" not in g:
        g.user_row = None
        uid = session.get("uid")
        if uid:
            g.user_row = get_db().execute(
                "SELECT * FROM users WHERE id = ? AND active = 1", (uid,)
            ).fetchone()
    return g.user_row


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            session.pop("uid", None)
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def tables_label(tables) -> str:
    nums = sorted(set(tables))
    if not nums:
        return ""
    parts, start, prev = [], nums[0], nums[0]
    for n in nums[1:] + [None]:
        if n is not None and n == prev + 1:
            prev = n
            continue
        parts.append(str(start) if start == prev else f"{start}–{prev}")
        if n is not None:
            start = prev = n
    return ", ".join(parts)


def seconds_label(secs: int) -> str:
    if secs < 60:
        return f"{secs} seconds"
    mins, rest = divmod(secs, 60)
    if rest == 0:
        return f"{mins} minute" + ("" if mins == 1 else "s")
    return f"{mins} min {rest} s"


def describe_run(row) -> dict:
    tables = [int(t) for t in row["tables"].split(",") if t]
    total = row["total"]
    if row["mode"] == "count":
        score, setting = f'{row["correct"]}/{total}', f'{row["target"]} questions'
    else:
        score, setting = f'{row["correct"]} correct', seconds_label(row["target"])
    return {
        "id": row["id"],
        "score": score,
        "setting": setting,
        "tables": tables_label(tables),
        "accuracy": round(100 * row["correct"] / total) if total else 0,
        "duration": row["duration"],
        "created_at": row["created_at"],
        "mistakes": json.loads(row["mistakes"] or "[]"),
    }


def parse_settings(args):
    mode = args.get("mode", "count")
    if mode not in MODES:
        mode = "count"
    lo, hi = COUNT_RANGE if mode == "count" else TIME_RANGE
    default = 20 if mode == "count" else 60
    try:
        n = int(args.get("n", default))
    except (TypeError, ValueError):
        n = default
    n = max(lo, min(hi, n))
    tables = sorted({int(p) for p in args.get("tables", "").split(",")
                     if p.strip().isdigit() and int(p) in TABLES})
    return mode, n, tables or TABLES


# ---------------------------------------------------------------------------
# Player routes
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("index"))
    if request.method == "POST":
        if is_throttled("user"):
            flash("Too many tries. Please wait a few minutes and try again.", "error")
            return render_template("login.html"), 429
        user = find_user_by_password(norm_password(request.form.get("password")))
        if user and user["active"]:
            clear_failures("user")
            session["uid"] = user["id"]
            return redirect(url_for("index"))
        if user:
            flash("Your account is paused. Please ask your teacher.", "error")
        else:
            record_failure("user")
            flash("That password isn't right. Try again!", "error")
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.pop("uid", None)
    return redirect(url_for("login"))


@app.get("/")
@login_required
def index():
    user = current_user()
    rows = get_db().execute(
        "SELECT * FROM scores WHERE user_id = ? ORDER BY id DESC LIMIT 6", (user["id"],)
    ).fetchall()
    return render_template(
        "index.html",
        user=user,
        runs=[describe_run(r) for r in rows],
        tables=TABLES,
        count_presets=COUNT_PRESETS,
        time_presets=TIME_PRESETS,
        count_range=COUNT_RANGE,
        time_range=TIME_RANGE,
    )


@app.get("/quiz")
@login_required
def quiz():
    mode, n, tables = parse_settings(request.args)
    return render_template("quiz.html", mode=mode, n=n, tables=tables)


def clean_mistakes(raw) -> list[list[int]]:
    out: list[list[int]] = []
    if isinstance(raw, list):
        for item in raw[:100]:
            try:
                a, b, given = (int(x) for x in item)
            except (TypeError, ValueError):
                continue
            if 2 <= a <= 12 and 2 <= b <= 12 and 0 <= given <= 9999:
                out.append([a, b, given])
    return out


@app.post("/api/score")
def api_score():
    user = current_user()
    if user is None:
        return jsonify(error="signed_out"), 401
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="bad_request"), 400
    try:
        mode = data["mode"]
        target = int(data["target"])
        correct = int(data["correct"])
        total = int(data["total"])
        duration = float(data["duration"])
        tables = sorted({int(t) for t in data["tables"]})
    except (KeyError, TypeError, ValueError):
        return jsonify(error="bad_request"), 400

    if mode not in MODES:
        return jsonify(error="bad_request"), 400
    lo, hi = COUNT_RANGE if mode == "count" else TIME_RANGE
    valid = (
        lo <= target <= hi
        and tables and all(t in TABLES for t in tables)
        and 0 <= correct <= total <= 1000
        and math.isfinite(duration) and 0 < duration <= 3600
        and (mode != "count" or total == target)
        and (mode != "time" or duration <= target + 5)
        and duration >= total * MIN_SECONDS_PER_ANSWER
    )
    if not valid:
        return jsonify(error="invalid_score"), 400
    if total == 0:
        return jsonify(saved=False)

    db = get_db()
    tables_key = ",".join(map(str, tables))
    prev = db.execute(
        """SELECT correct, total, duration FROM scores
           WHERE user_id = ? AND mode = ? AND target = ? AND tables = ?
           ORDER BY correct DESC, duration ASC LIMIT 1""",
        (user["id"], mode, target, tables_key),
    ).fetchone()
    db.execute(
        """INSERT INTO scores (user_id, mode, target, tables, correct, total, duration, mistakes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user["id"], mode, target, tables_key, correct, total, round(duration, 1),
         json.dumps(clean_mistakes(data.get("mistakes"))), now_iso()),
    )
    db.commit()

    new_best = bool(prev) and (
        correct > prev["correct"]
        or (correct == prev["correct"] and mode == "count" and duration < prev["duration"])
    )
    return jsonify(
        saved=True,
        new_best=new_best,
        previous_best=dict(prev) if prev else None,
    )


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------
def admin_ok() -> bool:
    stamp = session.get("admin_at")
    return bool(stamp) and time.time() - stamp < ADMIN_SESSION_SECONDS


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not admin_ok():
            session.pop("admin_at", None)
            return redirect(url_for("admin_login"))
        session["admin_at"] = time.time()  # sliding expiry
        return view(*args, **kwargs)
    return wrapped


def admin_hash() -> str:
    row = get_db().execute("SELECT value FROM settings WHERE key = 'admin_hash'").fetchone()
    return row["value"] if row else ""


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if admin_ok():
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        if is_throttled("admin"):
            flash("Too many tries. Please wait a few minutes.", "error")
            return render_template("admin_login.html"), 429
        if check_password_hash(admin_hash(), request.form.get("password", "")):
            clear_failures("admin")
            session["admin_at"] = time.time()
            return redirect(url_for("admin_dashboard"))
        record_failure("admin")
        flash("Wrong admin password.", "error")
    return render_template("admin_login.html")


@app.post("/admin/logout")
def admin_logout():
    session.pop("admin_at", None)
    return redirect(url_for("admin_login"))


@app.get("/admin")
@admin_required
def admin_dashboard():
    rows = get_db().execute(
        """SELECT u.id, u.name, u.password, u.active, u.created_at,
                  COUNT(s.id) AS runs,
                  COALESCE(SUM(s.correct), 0) AS sum_correct,
                  COALESCE(SUM(s.total), 0) AS sum_total,
                  MAX(s.created_at) AS last_played
           FROM users u LEFT JOIN scores s ON s.user_id = u.id
           GROUP BY u.id ORDER BY u.name COLLATE NOCASE, u.id"""
    ).fetchall()
    users = []
    for r in rows:
        d = dict(r)
        d["accuracy"] = round(100 * d["sum_correct"] / d["sum_total"]) if d["sum_total"] else None
        users.append(d)
    return render_template("admin.html", users=users)


def _get_user_or_404(user_id: int):
    row = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        abort(404)
    return row


@app.post("/admin/users/add")
@admin_required
def admin_add_user():
    db = get_db()
    name = clean_name(request.form.get("name"))
    pw = norm_password(request.form.get("password")) or generate_password(db)
    if not name:
        flash("Please enter a name.", "error")
    elif password_problem(pw):
        flash(password_problem(pw), "error")
    else:
        try:
            db.execute(
                "INSERT INTO users (name, password, created_at) VALUES (?, ?, ?)",
                (name, pw, now_iso()),
            )
            db.commit()
            flash(f"Added {name}. Password: {pw}", "ok")
        except sqlite3.IntegrityError:
            flash("Someone else already uses that password. Pick another one.", "error")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/users/bulk")
@admin_required
def admin_bulk_add():
    db = get_db()
    names = [clean_name(line) for line in request.form.get("names", "").splitlines()]
    names = [n for n in names if n][:200]
    for name in names:
        db.execute(
            "INSERT INTO users (name, password, created_at) VALUES (?, ?, ?)",
            (name, generate_password(db), now_iso()),
        )
    db.commit()
    if names:
        flash(f"Added {len(names)} user{'s' if len(names) != 1 else ''} with generated passwords.", "ok")
    else:
        flash("Type one name per line.", "error")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/users/<int:user_id>/update")
@admin_required
def admin_update_user(user_id: int):
    user = _get_user_or_404(user_id)
    name = clean_name(request.form.get("name")) or user["name"]
    pw = norm_password(request.form.get("password")) or user["password"]
    if password_problem(pw):
        flash(password_problem(pw), "error")
    else:
        db = get_db()
        try:
            db.execute("UPDATE users SET name = ?, password = ? WHERE id = ?", (name, pw, user_id))
            db.commit()
            flash(f"Saved {name}.", "ok")
        except sqlite3.IntegrityError:
            flash("Someone else already uses that password. Pick another one.", "error")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/users/<int:user_id>/toggle")
@admin_required
def admin_toggle_user(user_id: int):
    user = _get_user_or_404(user_id)
    db = get_db()
    db.execute("UPDATE users SET active = 1 - active WHERE id = ?", (user_id,))
    db.commit()
    flash(f"{user['name']} is now {'paused' if user['active'] else 'active'}.", "ok")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/users/<int:user_id>/delete")
@admin_required
def admin_delete_user(user_id: int):
    user = _get_user_or_404(user_id)
    db = get_db()
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    flash(f"Deleted {user['name']}.", "ok")
    return redirect(url_for("admin_dashboard"))


@app.get("/admin/users/<int:user_id>")
@admin_required
def admin_user(user_id: int):
    user = _get_user_or_404(user_id)
    rows = get_db().execute(
        "SELECT * FROM scores WHERE user_id = ? ORDER BY id DESC LIMIT 200", (user_id,)
    ).fetchall()
    runs = [describe_run(r) for r in rows]
    missed = Counter()
    for run in runs:
        for a, b, _given in run["mistakes"]:
            missed[tuple(sorted((a, b)))] += 1
    total = sum(r["total"] for r in rows)
    correct = sum(r["correct"] for r in rows)
    return render_template(
        "admin_user.html",
        u=user,
        runs=runs[:50],
        run_count=len(runs),
        accuracy=round(100 * correct / total) if total else None,
        answered=total,
        missed=missed.most_common(10),
    )


@app.post("/admin/users/<int:user_id>/clear-scores")
@admin_required
def admin_clear_scores(user_id: int):
    user = _get_user_or_404(user_id)
    db = get_db()
    db.execute("DELETE FROM scores WHERE user_id = ?", (user_id,))
    db.commit()
    flash(f"Cleared all scores for {user['name']}.", "ok")
    return redirect(url_for("admin_user", user_id=user_id))


@app.get("/admin/generate-password")
@admin_required
def admin_generate_password():
    return jsonify(password=generate_password(get_db()))


@app.get("/admin/slips")
@admin_required
def admin_slips():
    users = get_db().execute(
        "SELECT name, password FROM users WHERE active = 1 ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return render_template("slips.html", users=users)


@app.post("/admin/password")
@admin_required
def admin_password():
    current = request.form.get("current", "")
    new = request.form.get("new", "")
    confirm = request.form.get("confirm", "")
    if not check_password_hash(admin_hash(), current):
        flash("Your current admin password isn't right.", "error")
    elif len(new) < 6:
        flash("Use at least 6 characters for the admin password.", "error")
    elif new != confirm:
        flash("The new passwords don't match.", "error")
    else:
        db = get_db()
        db.execute("UPDATE settings SET value = ? WHERE key = 'admin_hash'", (generate_password_hash(new),))
        db.commit()
        flash("Admin password changed.", "ok")
    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
@app.cli.command("set-admin-password")
@click.password_option()
def set_admin_password(password: str):
    """Reset the admin password (use if you have forgotten it)."""
    if len(password) < 6:
        raise click.ClickException("Use at least 6 characters.")
    db = get_db()
    db.execute(
        "INSERT INTO settings (key, value) VALUES ('admin_hash', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (generate_password_hash(password),),
    )
    db.commit()
    click.echo("Admin password updated.")


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
