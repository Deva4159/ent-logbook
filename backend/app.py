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
    if origin:
        host = request.host
        if host not in origin:
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


@app.get("/health")
def health():
    return jsonify({"ok": True})


app.register_blueprint(api)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
