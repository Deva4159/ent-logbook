"""Server-side auth: password hashing (scrypt via Werkzeug), opaque
server-side sessions (the cookie never carries anything but a random
token), and simple per-key rate limiting for login/signup/forgot-password.
No client-side hashing anywhere -- passwords travel once, over HTTPS, and
are hashed the instant they arrive here.
"""
import datetime
import functools
import re
import secrets

from flask import g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_db

SESSION_COOKIE = "entlog_session"
SESSION_LIFETIME_DAYS = 14
RATE_LIMIT_WINDOW_SECONDS = 15 * 60
RATE_LIMIT_MAX_ATTEMPTS = 10


def now_iso():
    return datetime.datetime.utcnow().isoformat() + "Z"


def hash_password(plain):
    return generate_password_hash(plain)


def verify_password(hash_, plain):
    try:
        return check_password_hash(hash_, plain)
    except Exception:
        return False


def clean_username(u):
    u = (u or "").strip().lower()
    return re.sub(r"[^a-z0-9._-]", "", u)


def create_session(username):
    token = secrets.token_urlsafe(32)
    created = datetime.datetime.utcnow()
    expires = created + datetime.timedelta(days=SESSION_LIFETIME_DAYS)
    db = get_db()
    db.execute(
        "INSERT INTO sessions (token, username, created_at, expires_at) VALUES (?,?,?,?)",
        (token, username, created.isoformat() + "Z", expires.isoformat() + "Z"),
    )
    db.commit()
    return token


def destroy_session(token):
    db = get_db()
    db.execute("DELETE FROM sessions WHERE token = ?", (token,))
    db.commit()


def destroy_all_sessions_for(username):
    """Called on password change / account deactivation so a stolen or
    stale session cookie stops working immediately, everywhere."""
    db = get_db()
    db.execute("DELETE FROM sessions WHERE username = ?", (username,))
    db.commit()


def current_user():
    """Resolves the logged-in user's DB row from the session cookie, or
    None. Expired sessions are lazily deleted."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    db = get_db()
    row = db.execute(
        "SELECT s.username, s.expires_at, u.* FROM sessions s JOIN users u ON u.username = s.username WHERE s.token = ?",
        (token,),
    ).fetchone()
    if not row:
        return None
    if row["expires_at"] < now_iso():
        destroy_session(token)
        return None
    if not row["active"]:
        return None
    return dict(row)


def set_session_cookie(resp, token):
    resp.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=request.is_secure or request.headers.get("X-Forwarded-Proto") == "https",
        samesite="Lax",
        max_age=SESSION_LIFETIME_DAYS * 24 * 3600,
        path="/",
    )
    return resp


def clear_session_cookie(resp):
    resp.set_cookie(SESSION_COOKIE, "", expires=0, path="/")
    return resp


def login_required(role=None):
    def deco(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                return jsonify({"error": "not_authenticated"}), 401
            if role and user["role"] != role:
                return jsonify({"error": "forbidden"}), 403
            g.user = user
            return fn(*args, **kwargs)
        return wrapped
    return deco


def rate_limit(key):
    """True if `key` (e.g. "login:demo.resident:1.2.3.4") has exceeded
    RATE_LIMIT_MAX_ATTEMPTS within the trailing window. Call
    record_attempt() only on a *failed* attempt, so legitimate users
    typing their password correctly are never slowed down."""
    db = get_db()
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS)).isoformat() + "Z"
    row = db.execute(
        "SELECT COUNT(*) AS n FROM login_attempts WHERE key = ? AND attempted_at > ?",
        (key, cutoff),
    ).fetchone()
    return row["n"] >= RATE_LIMIT_MAX_ATTEMPTS


def record_attempt(key):
    db = get_db()
    db.execute("INSERT INTO login_attempts (key, attempted_at) VALUES (?, ?)", (key, now_iso()))
    db.commit()


def client_ip():
    # Trust X-Forwarded-For only if you configure your proxy to set it
    # (Render/Railway/Fly all do this correctly by default).
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"
