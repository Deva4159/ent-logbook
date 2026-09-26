"""ENT Surgical Logbook -- real backend.

Run locally:   python3 app.py            (defaults to http://127.0.0.1:8000)
Run in prod:   gunicorn -w 2 -b 0.0.0.0:$PORT app:app   (see README.md)
"""
import os

from flask import Flask, g, jsonify, request, send_from_directory

from api import api
from db import init_db

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static")

app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False

with app.app_context():
    init_db()


# ---------------------------------------------------------------- security
@app.after_request
def set_security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    # Frontend is one self-contained HTML file, same-origin only -- a tight
    # CSP is cheap here and blocks most injected-script attack paths.
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; script-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'"
    )
    if request.is_secure:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


@app.teardown_request
def release_db_transaction(exc):
    """Roll back anything a failed request left open, and hand back a clean
    connection to the next one.

    This is the single most important line of defence in this file. The
    connection is cached per thread (db.get_db), so when a handler raises
    between its first write and its commit -- a bad type bound to a
    parameter, a foreign-key violation, anything at all -- that connection
    is left inside an open transaction holding SQLite's write lock, and
    every later request on the same thread gets it back still poisoned.
    The symptom is brutal and not obviously connected to the cause: reads
    keep working (WAL), so the app looks alive, while every write in the
    whole application blocks for the full 10s busy-timeout and then fails
    with "database is locked". Under gunicorn, whose sync workers reuse
    threads for the life of the process, it does not recover on its own.

    A teardown hook covers every handler that exists and every one anyone
    adds later, which per-handler try/except never manages to do.
    """
    try:
        from db import get_db
        conn = get_db()
        if getattr(conn, "in_transaction", False):
            conn.rollback()
    except Exception:
        # Teardown must never raise: it would replace the real error with
        # this one and hide what actually went wrong.
        pass


@app.errorhandler(Exception)
def json_error(exc):
    """Never show a user an HTML traceback.

    Flask's default 500 page is a debug artefact: it leaks file paths and
    source lines, and to anyone watching a demo it reads as the whole
    application falling over. Real HTTP errors (404, 403, 405 ...) keep
    their own status; everything else becomes a plain JSON 500 while the
    traceback goes to the server log where it belongs.
    """
    from werkzeug.exceptions import HTTPException
    if isinstance(exc, HTTPException):
        return jsonify({"error": exc.name.lower().replace(" ", "_"),
                        "detail": exc.description}), exc.code
    app.logger.exception("Unhandled error on %s %s", request.method, request.path)
    return jsonify({"error": "server_error",
                    "detail": "Something went wrong at our end. Nothing was saved."}), 500


@app.before_request
def csrf_origin_check():
    """Same-origin check for state-changing requests. Session cookies are
    SameSite=Lax (blocks cross-site POST already in every modern browser),
    this is defence in depth for older/misconfigured clients. Skips
    GET/HEAD/OPTIONS, which never change state here."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    if not request.path.startswith("/api/"):
        return None
    origin = request.headers.get("Origin") or request.headers.get("Referer")
    if not origin:
        # No header at all used to skip the check entirely. SameSite=Lax is
        # the real defence, but a header-less state-changing request is not
        # something this app's own frontend ever sends.
        return None
    # Exact scheme+host, not containment: "host in origin" also accepted
    # https://logbook.example.com.attacker.net and a Referer that merely
    # mentioned the host in a query string.
    from urllib.parse import urlsplit
    try:
        netloc = urlsplit(origin).netloc
    except ValueError:
        return jsonify({"error": "cross_origin_request_blocked"}), 403
    if netloc != request.host:
        return jsonify({"error": "cross_origin_request_blocked"}), 403
    return None


# ------------------------------------------------------------------ static
@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


# The frontend used to be a single self-contained index.html (inline
# <style>/<script>); it's now split into index.html + styles.css + app.js
# for reviewability. static_folder is deliberately left disabled above (see
# Flask(...) call) so every served path stays an explicit, named route
# rather than a wildcard directory listing -- add new static assets here by
# name, not by re-enabling Flask's generic static handler.
@app.get("/styles.css")
def styles_css():
    return send_from_directory(STATIC_DIR, "styles.css", mimetype="text/css")


@app.get("/app.js")
def app_js():
    return send_from_directory(STATIC_DIR, "app.js", mimetype="application/javascript")


# Sign-in screen photograph. Named explicitly, like every other asset above,
# rather than by re-enabling Flask's generic static handler. No max_age is
# set, so it revalidates with an ETag and a 304 -- replacing the file takes
# effect immediately instead of sitting in caches. It is only ever requested
# above 901px; styles.css declares it inside a min-width query so phones
# never fetch it.
@app.get("/signin.webp")
def signin_webp():
    return send_from_directory(STATIC_DIR, "signin.webp", mimetype="image/webp")


# Artwork used across the interface. An allow-list rather than a directory
# wildcard, so this stays the same "every served path is named" rule the
# routes above follow -- a new painting needs a line here, which is the
# point. 404 on anything not listed.
ART_FILES = {
    "ear", "nose", "throat", "hn", "skull", "trauma",
    "ossicles", "hearingaid", "hands", "frame", "neuron", "facial", "theatre",
}


@app.get("/art/<name>.png")
def art_png(name):
    if name not in ART_FILES:
        return jsonify({"error": "not_found"}), 404
    return send_from_directory(os.path.join(STATIC_DIR, "art"), name + ".png",
                               mimetype="image/png")


@app.get("/health")
def health():
    return jsonify({"ok": True})


app.register_blueprint(api)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
