"""Backups (v7.4).

What this is, and is not
------------------------
The department chose "alert only": the app tells the Developer when a backup
is due, and the Developer downloads one. Nothing here copies data anywhere by
itself. The file you download is the whole database as one SQLite file -- every
entry, every sign-off, every account including password hashes -- so it must
be kept as carefully as the logbook itself. Live sessions and login-attempt
records are stripped from the copy.

Restoring
---------
A previously downloaded file can be uploaded to put the data back (the Render
disk was wiped, or something was deleted that should not have been). That
REPLACES everything in the live database, so the path is deliberately slow:

  1. upload -> validate (is it really SQLite, does it pass an integrity check,
     does it contain the tables and a Developer account, was it made by this
     or an older version) -> show a before/after comparison. Nothing changes.
  2. confirm -> the Developer re-enters their password, types RESTORE, and
     the live database is first copied to a "safety" file on the disk.
  3. the copy is written into the live database through SQLite's own backup
     API (a locked, atomic page copy -- not a file swap under other workers),
     the schema is brought up to date, every session is ended, and the
     restore is logged.

The safety copy is the undo: restoring it goes through the same two steps.

Honest limits: a restore returns the data to *the moment of the file*, so
anything entered since is gone; the safety copy is on the same disk as the
database, so it protects against a mistaken restore, not against losing the
disk -- only a file you keep elsewhere does that.
"""
import datetime
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time

import db as dbmod
from db import get_db

STAGING_MINUTES = 30
KEEP_SAFETY = 5
# Tables whose absence means "this is not our database".
CORE_TABLES = {"users", "entries", "postings", "config", "role_assignments"}


class BackupError(Exception):
    pass


def _root():
    d = os.path.join(os.path.dirname(os.path.abspath(dbmod.DB_PATH)), "backups")
    os.makedirs(os.path.join(d, "staging"), exist_ok=True)
    os.makedirs(os.path.join(d, "safety"), exist_ok=True)
    return d


def _now():
    return datetime.datetime.utcnow().isoformat() + "Z"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(dest_path, strip_secrets=True):
    """Consistent copy of the live database via SQLite's online backup API."""
    live = get_db()
    if live.in_transaction:
        live.commit()
    dest = sqlite3.connect(dest_path)
    try:
        live.backup(dest)
        if strip_secrets:
            dest.execute("DELETE FROM sessions")
            dest.execute("DELETE FROM login_attempts")
            dest.commit()
        # A downloaded file is one self-contained file: rollback-journal
        # mode, so opening it later (even read-only) leaves no -wal/-shm
        # beside it.
        dest.execute("PRAGMA journal_mode = DELETE")
    finally:
        dest.close()
    for ext in ("-wal", "-shm"):
        try:
            os.remove(dest_path + ext)
        except OSError:
            pass


def make_download():
    """-> (bytes, filename, sha256)."""
    tmp = os.path.join(_root(), "staging", "dl-%s.db" % secrets.token_hex(6))
    try:
        snapshot(tmp)
        with open(tmp, "rb") as f:
            data = f.read()
    finally:
        for ext in ("", "-wal", "-shm"):
            try:
                os.remove(tmp + ext)
            except OSError:
                pass
    name = "ent-logbook-backup-%s.db" % datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return data, name, hashlib.sha256(data).hexdigest()


def log(db, kind, actor, filename, size, sha, detail=None):
    db.execute("INSERT INTO backup_log (at, kind, actor_username, filename, size_bytes, sha256, detail)"
               " VALUES (?,?,?,?,?,?,?)", (_now(), kind, actor, filename, size, sha, detail))


# ------------------------------------------------------------ inspection
def _tables(conn):
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def _count(conn, table, where=""):
    try:
        return conn.execute("SELECT COUNT(*) FROM %s %s" % (table, where)).fetchone()[0]
    except sqlite3.Error:
        return None


def _newest(conn, sql):
    try:
        r = conn.execute(sql).fetchone()
        return r[0] if r else None
    except sqlite3.Error:
        return None


def _summary(conn):
    return {
        "users": _count(conn, "users"),
        "developers": _count(conn, "users", "WHERE role = 'developer' AND active = 1"),
        "entries": _count(conn, "entries"),
        "postings": _count(conn, "postings"),
        "approvals": _count(conn, "entry_approvals"),
        "newestEntryAt": _newest(conn, "SELECT MAX(created_at) FROM entries"),
        "newestEventAt": _newest(conn, "SELECT MAX(created_at) FROM account_events"),
    }


def clean_staging():
    cutoff = time.time() - STAGING_MINUTES * 60
    d = os.path.join(_root(), "staging")
    for n in os.listdir(d):
        p = os.path.join(d, n)
        try:
            if os.path.getmtime(p) < cutoff:
                os.remove(p)
        except OSError:
            pass


def stage_upload(file_storage, actor, db):
    """Validate an uploaded file and stage a normalised copy. Returns a report
    dict; raises BackupError with a plain message on any refusal."""
    clean_staging()
    token = secrets.token_urlsafe(18)
    raw = os.path.join(_root(), "staging", token + ".raw")
    file_storage.save(raw)
    try:
        return _stage_path(raw, token, actor, db, file_storage.filename or "upload.db")
    finally:
        for ext in ("", "-wal", "-shm"):
            try:
                os.remove(raw + ext)
            except OSError:
                pass


def stage_safety(name, actor, db):
    clean_staging()
    if not re.fullmatch(r"pre-restore-\d{8}-\d{6}\.db", name or ""):
        raise BackupError("Unknown safety copy.")
    path = os.path.join(_root(), "safety", name)
    if not os.path.exists(path):
        raise BackupError("That safety copy no longer exists.")
    token = secrets.token_urlsafe(18)
    return _stage_path(path, token, actor, db, name, copy=True)


def _stage_path(src_path, token, actor, db, display_name, copy=True):
    with open(src_path, "rb") as f:
        head = f.read(16)
    if head != b"SQLite format 3\x00":
        raise BackupError("That file is not a SQLite database, so it is not one of this app's backups.")
    staged = os.path.join(_root(), "staging", token + ".db")
    try:
        src = sqlite3.connect("file:%s?mode=ro" % src_path, uri=True)
    except sqlite3.Error as e:
        raise BackupError("The file could not be opened: %s" % e)
    try:
        try:
            res = src.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.DatabaseError as e:
            raise BackupError("The file is damaged and cannot be read: %s" % e)
        if [r[0] for r in res] != ["ok"]:
            raise BackupError("The file failed SQLite's integrity check, so restoring it could "
                              "bring corruption into the live database.")
        tables = _tables(src)
        missing = CORE_TABLES - tables
        if missing:
            raise BackupError("This does not look like an ENT Logbook backup (missing: %s)."
                              % ", ".join(sorted(missing)))
        live = get_db()
        newer = tables - _tables(live)
        if newer:
            raise BackupError("This backup was made by a newer version of the app (it has tables this "
                              "version does not: %s). Update the app first, then restore."
                              % ", ".join(sorted(newer)))
        cols = {r[1] for r in src.execute("PRAGMA table_info(users)")}
        if "role" not in cols or "password_hash" not in cols:
            raise BackupError("The users table in this file is not in the shape this app expects.")
        summ = _summary(src)
        if not summ["developers"]:
            raise BackupError("This backup has no active Developer account. Restoring it would leave "
                              "nobody able to sign in and fix things.")
        page = src.execute("PRAGMA page_size").fetchone()[0]
        live_page = live.execute("PRAGMA page_size").fetchone()[0]
        if page != live_page:
            raise BackupError("This file uses a different database page size (%d vs %d) and cannot be "
                              "copied into the live database." % (page, live_page))
        out = sqlite3.connect(staged)
        try:
            src.backup(out)
            out.execute("PRAGMA journal_mode = WAL")
            out.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            out.close()
    finally:
        src.close()
    for ext in ("-wal", "-shm"):
        try:
            os.remove(staged + ext)
        except OSError:
            pass
    sha = _sha256(src_path)
    live_sum = _summary(get_db())
    known = db.execute("SELECT at, actor_username, kind FROM backup_log WHERE sha256 = ?"
                       " AND kind = 'download' ORDER BY id DESC LIMIT 1", (sha,)).fetchone()
    meta = {"token": token, "sha256": sha, "name": display_name, "actor": actor,
            "expires": time.time() + STAGING_MINUTES * 60}
    with open(os.path.join(_root(), "staging", token + ".json"), "w") as f:
        json.dump(meta, f)
    older = bool(summ["newestEntryAt"] and live_sum["newestEntryAt"]
                 and summ["newestEntryAt"] < live_sum["newestEntryAt"])
    return {
        "token": token, "fileName": display_name, "sha256": sha,
        "sizeBytes": os.path.getsize(staged),
        "backup": summ, "live": live_sum,
        "olderThanLive": older,
        "fewerEntriesThanLive": (summ["entries"] or 0) < (live_sum["entries"] or 0),
        "matchesDownload": ({"at": known["at"], "by": known["actor_username"]} if known else None),
        "olderSchema": sorted(_tables(get_db()) - tables),
        "expiresInMinutes": STAGING_MINUTES,
    }


# ----------------------------------------------------------------- restore
def apply_restore(token, actor):
    """Replace the live database with a staged file. Caller has already
    verified the Developer's password and the typed confirmation."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,40}", token or ""):
        raise BackupError("Unknown or expired upload. Upload the file again.")
    staged = os.path.join(_root(), "staging", token + ".db")
    metap = os.path.join(_root(), "staging", token + ".json")
    if not os.path.exists(staged) or not os.path.exists(metap):
        raise BackupError("Unknown or expired upload. Upload the file again.")
    meta = json.load(open(metap))
    if meta.get("expires", 0) < time.time():
        raise BackupError("That upload has expired. Upload the file again.")
    if meta.get("actor") != actor:
        raise BackupError("That upload was staged by someone else.")

    live = get_db()
    if live.in_transaction:
        live.commit()
    stamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    safety_name = "pre-restore-%s.db" % stamp
    safety_path = os.path.join(_root(), "safety", safety_name)
    snapshot(safety_path, strip_secrets=False)
    safety_sha = _sha256(safety_path)
    safety_size = os.path.getsize(safety_path)
    _trim_safety()

    src = sqlite3.connect(staged)
    try:
        src.backup(live)
    finally:
        src.close()
    # Bring an older backup up to the current schema, exactly as a boot does.
    dbmod.init_db()
    live = get_db()
    live.execute("DELETE FROM sessions")
    live.execute("DELETE FROM login_attempts")
    log(live, "safety", actor, safety_name, safety_size, safety_sha,
        "Copy of the live database taken immediately before restoring %s" % meta.get("name"))
    log(live, "restore", actor, meta.get("name"), os.path.getsize(staged), meta.get("sha256"),
        "Restored over the live database")
    live.execute(
        "INSERT INTO account_events (username, action, actor_username, detail, created_at)"
        " VALUES (?,?,?,?,?)",
        (actor if live.execute("SELECT 1 FROM users WHERE username = ?", (actor,)).fetchone()
         else "system", "database_restored", actor,
         "From %s (sha256 %s…). Previous state kept as %s." % (meta.get("name"),
                                                                    (meta.get("sha256") or "")[:12], safety_name),
         _now()))
    live.commit()
    for ext in (".db", ".json"):
        try:
            os.remove(os.path.join(_root(), "staging", token + ext))
        except OSError:
            pass
    return {"safetyCopy": safety_name}


def _trim_safety():
    d = os.path.join(_root(), "safety")
    files = sorted(n for n in os.listdir(d) if re.fullmatch(r"pre-restore-\d{8}-\d{6}\.db", n))
    for n in files[:-KEEP_SAFETY]:
        try:
            os.remove(os.path.join(d, n))
        except OSError:
            pass


def list_safety():
    d = os.path.join(_root(), "safety")
    out = []
    for n in sorted(os.listdir(d), reverse=True):
        if re.fullmatch(r"pre-restore-\d{8}-\d{6}\.db", n):
            p = os.path.join(d, n)
            out.append({"name": n, "sizeBytes": os.path.getsize(p),
                        "at": datetime.datetime.utcfromtimestamp(os.path.getmtime(p)).isoformat() + "Z"})
    return out


def safety_path(name):
    if not re.fullmatch(r"pre-restore-\d{8}-\d{6}\.db", name or ""):
        return None
    p = os.path.join(_root(), "safety", name)
    return p if os.path.exists(p) else None


def status(db):
    last_dl = db.execute("SELECT * FROM backup_log WHERE kind = 'download' ORDER BY id DESC LIMIT 1").fetchone()
    last_rs = db.execute("SELECT * FROM backup_log WHERE kind = 'restore' ORDER BY id DESC LIMIT 1").fetchone()
    history = db.execute("SELECT * FROM backup_log ORDER BY id DESC LIMIT 15").fetchall()
    try:
        size = os.path.getsize(dbmod.DB_PATH)
    except OSError:
        size = None

    def row(r):
        return None if not r else {"at": r["at"], "by": r["actor_username"], "filename": r["filename"],
                                   "sizeBytes": r["size_bytes"], "sha256": r["sha256"], "kind": r["kind"],
                                   "detail": r["detail"]}
    return {
        "lastDownload": row(last_dl), "lastRestore": row(last_rs),
        "history": [row(r) for r in history],
        "databaseBytes": size, "counts": _summary(get_db()),
        "safetyCopies": list_safety(),
        "dbPath": os.path.basename(dbmod.DB_PATH),
    }
