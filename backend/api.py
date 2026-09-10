"""All /api/* routes: auth, entries, postings, config, role assignments,
password-reset queue, CSV export. Every write uses parameterized queries
(no string-built SQL) and every state-changing route requires a valid
session via auth.login_required.
"""
import csv
import datetime
import io
import json

from flask import Blueprint, g, jsonify, request, Response

from auth import (
    clean_username, client_ip, create_session, current_user,
    destroy_all_sessions_for, destroy_session, hash_password,
    login_required, rate_limit, record_attempt, set_session_cookie,
    clear_session_cookie, verify_password,
)
from db import get_db

api = Blueprint("api", __name__, url_prefix="/api")

ENTRY_TYPES = {"surgical", "other", "case", "academic", "seminar"}


# ---------------------------------------------------------------- helpers
def row_to_user(row):
    if row is None:
        return None
    d = dict(row)
    d.pop("password_hash", None)
    d["active"] = bool(d.get("active", 1))
    return d


def get_config():
    row = get_db().execute("SELECT data FROM config WHERE id = 'lists'").fetchone()
    return json.loads(row["data"]) if row else {}


def get_postings(username):
    rows = get_db().execute(
        "SELECT id, unit, start_date, end_date FROM postings WHERE username = ? ORDER BY start_date",
        (username,),
    ).fetchall()
    return [{"id": r["id"], "unit": r["unit"], "startDate": r["start_date"], "endDate": r["end_date"]} for r in rows]


def unit_for_date(postings, date_str):
    if not postings or not date_str:
        return ""
    covering = [p for p in postings if p["startDate"] and p["startDate"] <= date_str and (not p["endDate"] or p["endDate"] >= date_str)]
    if not covering:
        return ""
    covering.sort(key=lambda p: p["startDate"], reverse=True)
    return covering[0]["unit"]


def entry_row_to_dict(row):
    d = dict(row)
    for k in ("procedures", "diagnoses", "diagnoses_secondary", "comorbidities"):
        try:
            d[k] = json.loads(d[k]) if d[k] else []
        except (TypeError, ValueError):
            d[k] = []
    return {
        "id": d["id"],
        "authorUsername": d["author_username"],
        "entryType": d["entry_type"],
        "unit": d["unit"],
        "date": d["entry_date"],
        "createdAt": d["created_at"],
        "site": d["site"],
        "procedures": d["procedures"],
        "setting": d["setting"],
        "otherSettingType": d["other_setting_type"],
        "hospitalNumber": d["hospital_number"],
        "age": d["age"],
        "sex": d["sex"],
        "diagnoses": d["diagnoses"],
        "diagnosesSecondary": d["diagnoses_secondary"],
        "comorbidities": d["comorbidities"],
        "laterality": d["laterality"],
        "role": d["role_level"],
        "consultant": d["consultant"],
        "consultantUsername": d["consultant_username"],
        "assistants": d["assistants"],
        "comments": d["comments"],
        "caseReport": d["case_report"],
        "linkedFromId": d["linked_from_id"],
        "history": d["history"],
        "examination": d["examination"],
        "academicType": d["academic_type"],
        "academicTypeOther": d["academic_type_other"],
        "seminarType": d["seminar_type"],
        "seminarTypeOther": d["seminar_type_other"],
        "topic": d["topic"],
        "venue": d["venue"],
        "details": d["details"],
    }


def is_assignment_active(a):
    now = datetime.datetime.utcnow().isoformat() + "Z"
    start = a["start_at"] or ""
    end = a["end_at"] or "9999"
    return (not start or start <= now) and (not end or now <= end)


def consultant_scope(username):
    db = get_db()
    rows = db.execute("SELECT * FROM role_assignments WHERE consultant_username = ?", (username,)).fetchall()
    mine = [dict(r) for r in rows if is_assignment_active(dict(r))]
    full = any(a["assignment_role"] in ("hod", "coordinator") for a in mine)
    units = set(a["unit"] for a in mine if a["assignment_role"] == "head_of_unit" and a["unit"])
    user = db.execute("SELECT unit FROM users WHERE username = ?", (username,)).fetchone()
    if user and user["unit"]:
        units.add(user["unit"])
    return {"full": full, "units": list(units)}


# ------------------------------------------------------------------ auth
@api.post("/auth/signup")
def signup():
    body = request.get_json(force=True, silent=True) or {}
    username = clean_username(body.get("username"))
    password = body.get("password") or ""
    confirm = body.get("confirm") or ""
    display_name = (body.get("displayName") or username).strip()
    role = body.get("role") if body.get("role") in ("resident", "consultant") else "resident"

    if len(username) < 3:
        return jsonify({"error": "Username must be at least 3 characters (letters, numbers, . _ -)."}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400
    if password != confirm:
        return jsonify({"error": "Passwords do not match."}), 400

    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        return jsonify({"error": "That username is already taken."}), 409

    is_first_user = db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 0
    final_role = "developer" if is_first_user else role

    now = datetime.datetime.utcnow().isoformat() + "Z"
    pg_year = body.get("pgYear") if final_role == "resident" else None
    designation = body.get("designation") if final_role == "consultant" else None
    unit = body.get("unit") if final_role == "consultant" else None

    db.execute(
        "INSERT INTO users (username, password_hash, role, display_name, pg_year, designation, unit, active, created_at) VALUES (?,?,?,?,?,?,?,1,?)",
        (username, hash_password(password), final_role, display_name, pg_year, designation, unit, now),
    )
    db.commit()

    token = create_session(username)
    user = row_to_user(db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone())
    resp = jsonify({"user": user, "firstUser": is_first_user})
    return set_session_cookie(resp, token)


@api.post("/auth/login")
def login():
    body = request.get_json(force=True, silent=True) or {}
    username = clean_username(body.get("username"))
    password = body.get("password") or ""
    require_role = body.get("requireRole")

    # Two separate limits: one keyed to this IP (stops one attacker hammering
    # from one place), and one keyed to the account alone regardless of IP
    # (stops an attacker spreading guesses across many IPs/proxies to dodge
    # the first one -- a real gap in a pure per-IP limit).
    rl_key_ip = f"login:{username}:{client_ip()}"
    rl_key_account = f"login:{username}"
    if rate_limit(rl_key_ip) or rate_limit(rl_key_account):
        return jsonify({"error": "Too many attempts. Wait 15 minutes and try again."}), 429

    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        record_attempt(rl_key_ip)
        record_attempt(rl_key_account)
        return jsonify({"error": "No account with that username."}), 401
    if not row["active"]:
        return jsonify({"error": "This account has been deactivated. Ask your Developer admin to reactivate it."}), 403
    if require_role and row["role"] != require_role:
        return jsonify({"error": f"This account is not a {require_role} account."}), 403
    if not verify_password(row["password_hash"], password):
        record_attempt(rl_key_ip)
        record_attempt(rl_key_account)
        return jsonify({"error": "Incorrect password."}), 401

    token = create_session(username)
    resp = jsonify({"user": row_to_user(row)})
    return set_session_cookie(resp, token)


@api.post("/auth/logout")
def logout():
    from flask import request as req
    token = req.cookies.get("entlog_session")
    if token:
        destroy_session(token)
    resp = jsonify({"ok": True})
    return clear_session_cookie(resp)


@api.get("/auth/me")
def me():
    user = current_user()
    return jsonify({"user": row_to_user(user) if user else None})


@api.post("/auth/change-password")
@login_required()
def change_password():
    body = request.get_json(force=True, silent=True) or {}
    old = body.get("oldPassword") or ""
    new = body.get("newPassword") or ""
    confirm = body.get("confirm") or ""
    if len(new) < 8:
        return jsonify({"error": "New password must be at least 8 characters."}), 400
    if new != confirm:
        return jsonify({"error": "New passwords do not match."}), 400
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username = ?", (g.user["username"],)).fetchone()
    if not verify_password(row["password_hash"], old):
        return jsonify({"error": "Current password is incorrect."}), 400
    db.execute("UPDATE users SET password_hash = ? WHERE username = ?", (hash_password(new), g.user["username"]))
    db.commit()
    destroy_all_sessions_for(g.user["username"])
    token = create_session(g.user["username"])
    resp = jsonify({"ok": True})
    return set_session_cookie(resp, token)


@api.post("/auth/forgot-password")
def forgot_password():
    body = request.get_json(force=True, silent=True) or {}
    username = clean_username(body.get("username"))
    note = (body.get("note") or "").strip()
    db = get_db()
    if not db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        return jsonify({"error": "No account with that username."}), 404
    db.execute(
        "INSERT INTO password_resets (username, note, status, requested_at) VALUES (?,?,'pending',?)",
        (username, note, datetime.datetime.utcnow().isoformat() + "Z"),
    )
    db.commit()
    return jsonify({"ok": True})


# --------------------------------------------------------------- postings
@api.get("/postings")
@login_required()
def list_postings():
    return jsonify({"postings": get_postings(g.user["username"])})


@api.post("/postings")
@login_required()
def add_posting():
    body = request.get_json(force=True, silent=True) or {}
    unit = body.get("unit")
    start_date = body.get("startDate")
    end_date = body.get("endDate") or None
    if not unit or not start_date:
        return jsonify({"error": "Unit and start date are required."}), 400
    if end_date and end_date < start_date:
        return jsonify({"error": "End date can't be before the start date."}), 400
    db = get_db()
    db.execute(
        "INSERT INTO postings (username, unit, start_date, end_date) VALUES (?,?,?,?)",
        (g.user["username"], unit, start_date, end_date),
    )
    db.commit()
    return jsonify({"postings": get_postings(g.user["username"])})


@api.delete("/postings/<int:posting_id>")
@login_required()
def remove_posting(posting_id):
    db = get_db()
    row = db.execute("SELECT username FROM postings WHERE id = ?", (posting_id,)).fetchone()
    if not row or row["username"] != g.user["username"]:
        return jsonify({"error": "not_found"}), 404
    db.execute("DELETE FROM postings WHERE id = ?", (posting_id,))
    db.commit()
    return jsonify({"postings": get_postings(g.user["username"])})


# ---------------------------------------------------------------- entries
def _resolve_unit_for_entry(username, entry_date):
    postings = get_postings(username)
    return unit_for_date(postings, entry_date)


@api.post("/entries")
@login_required()
def create_entry():
    body = request.get_json(force=True, silent=True) or {}
    entry_type = body.get("entryType")
    if entry_type not in ENTRY_TYPES:
        return jsonify({"error": "Unknown entry type."}), 400
    entry_date = body.get("date") or datetime.date.today().isoformat()
    unit = _resolve_unit_for_entry(g.user["username"], entry_date)
    now = datetime.datetime.utcnow().isoformat() + "Z"

    db = get_db()
    cur = db.execute(
        """INSERT INTO entries (
            author_username, entry_type, unit, entry_date, created_at, site, procedures,
            setting, other_setting_type, hospital_number, age, sex, diagnoses,
            diagnoses_secondary, comorbidities, laterality, role_level, consultant,
            consultant_username, assistants, comments, case_report, linked_from_id,
            history, examination, academic_type, academic_type_other, seminar_type,
            seminar_type_other, topic, venue, details
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            g.user["username"], entry_type, unit, entry_date, now,
            body.get("site"), json.dumps(body.get("procedures") or []),
            body.get("setting"), body.get("otherSettingType"), body.get("hospitalNumber"),
            body.get("age"), body.get("sex"), json.dumps(body.get("diagnoses") or []),
            json.dumps(body.get("diagnosesSecondary") or []), json.dumps(body.get("comorbidities") or []),
            body.get("laterality"), body.get("role"), body.get("consultant"),
            body.get("consultantUsername"), body.get("assistants"), body.get("comments"),
            body.get("caseReport"), body.get("linkedFromId"),
            body.get("history"), body.get("examination"), body.get("academicType"),
            body.get("academicTypeOther"), body.get("seminarType"), body.get("seminarTypeOther"),
            body.get("topic"), body.get("venue"), body.get("details"),
        ),
    )
    db.commit()
    row = db.execute("SELECT * FROM entries WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify({"entry": entry_row_to_dict(row)})


@api.get("/entries/mine")
@login_required()
def list_my_entries():
    rows = get_db().execute(
        "SELECT * FROM entries WHERE author_username = ? ORDER BY entry_date DESC, id DESC",
        (g.user["username"],),
    ).fetchall()
    return jsonify({"entries": [entry_row_to_dict(r) for r in rows]})


@api.get("/entries/<int:entry_id>")
@login_required()
def get_entry(entry_id):
    db = get_db()
    row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    d = dict(row)
    # visibility: own entries, developer, or a consultant whose scope covers the entry's unit
    if g.user["role"] == "developer" or d["author_username"] == g.user["username"]:
        return jsonify({"entry": entry_row_to_dict(row)})
    if g.user["role"] == "consultant":
        scope = consultant_scope(g.user["username"])
        if scope["full"] or d["unit"] in scope["units"]:
            return jsonify({"entry": entry_row_to_dict(row)})
    return jsonify({"error": "forbidden"}), 403


@api.delete("/entries/<int:entry_id>")
@login_required()
def delete_entry(entry_id):
    db = get_db()
    row = db.execute("SELECT author_username FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    if row["author_username"] != g.user["username"] and g.user["role"] != "developer":
        return jsonify({"error": "forbidden"}), 403
    db.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
    db.commit()
    return jsonify({"ok": True})


@api.get("/entries/roster")
@login_required(role="consultant")
def roster_entries():
    scope = consultant_scope(g.user["username"])
    db = get_db()
    users = [dict(r) for r in db.execute("SELECT * FROM users WHERE role = 'resident'").fetchall()]
    all_entries = [entry_row_to_dict(r) for r in db.execute("SELECT * FROM entries").fetchall()]
    if not scope["full"]:
        allowed = set(scope["units"])
        all_entries = [e for e in all_entries if e["unit"] in allowed]
    roster = []
    for u in users:
        mine = [e for e in all_entries if e["authorUsername"] == u["username"]]
        if scope["full"] or mine:
            roster.append({"user": row_to_user(u), "entries": mine})
    return jsonify({"roster": roster, "scope": scope})


@api.get("/entries/all")
@login_required(role="developer")
def all_entries():
    rows = get_db().execute("SELECT * FROM entries ORDER BY entry_date DESC, id DESC").fetchall()
    return jsonify({"entries": [entry_row_to_dict(r) for r in rows]})


@api.get("/entries/by-author/<username>")
@login_required()
def entries_by_author(username):
    if not (g.user["username"] == username or g.user["role"] in ("developer", "consultant")):
        return jsonify({"error": "forbidden"}), 403
    rows = get_db().execute(
        "SELECT * FROM entries WHERE author_username = ? ORDER BY entry_date DESC, id DESC", (username,)
    ).fetchall()
    return jsonify({"entries": [entry_row_to_dict(r) for r in rows]})


def _export_csv(rows, columns):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([label for _, label in columns])
    for r in rows:
        writer.writerow([r.get(key, "") if not callable(key) else key(r) for key, _ in columns])
    return buf.getvalue()


@api.get("/entries/export.csv")
@login_required(role="developer")
def export_entries_csv():
    rows = [entry_row_to_dict(r) for r in get_db().execute("SELECT * FROM entries").fetchall()]

    def joined(field):
        return lambda r: "; ".join(r.get(field) or [])

    columns = [
        ("date", "Date"), ("authorUsername", "Resident"), ("entryType", "Type"), ("unit", "Unit"),
        ("site", "Site"), (joined("procedures"), "Procedures"), ("hospitalNumber", "Hospital Number"),
        ("age", "Age"), ("sex", "Sex"), (joined("diagnoses"), "Primary Diagnoses"),
        (joined("diagnosesSecondary"), "Secondary Diagnoses"), (joined("comorbidities"), "Comorbidities"),
        ("laterality", "Side"), ("setting", "Emergency/Elective"), ("role", "Role/Entrustment"),
        ("consultant", "Consultant"), ("assistants", "Assistants"), ("otherSettingType", "Other-procedure setting"),
        ("history", "Brief History"), ("examination", "Examination Findings"), ("academicType", "Academic Type"),
        ("academicTypeOther", "Academic Type (other)"), ("seminarType", "Seminar Type"),
        ("seminarTypeOther", "Seminar Type (other)"), ("topic", "Topic"), ("venue", "Venue"),
        ("details", "Details"), ("comments", "Comments/Complications"),
    ]
    csv_text = _export_csv(rows, columns)
    return Response(csv_text, mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=ent-logbook-entries.csv"})


@api.get("/users/export.csv")
@login_required(role="developer")
def export_users_csv():
    rows = [row_to_user(r) for r in get_db().execute("SELECT * FROM users").fetchall()]
    columns = [
        ("username", "Username"), ("display_name", "Display Name"), ("role", "Role"),
        ("unit", "Unit"), ("pg_year", "PG Year"), ("designation", "Designation"),
        ("active", "Active"), ("created_at", "Created At"),
    ]
    csv_text = _export_csv(rows, columns)
    return Response(csv_text, mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=ent-logbook-users.csv"})


# ------------------------------------------------------------------ users
@api.get("/users")
@login_required(role="developer")
def list_users():
    rows = get_db().execute("SELECT * FROM users ORDER BY created_at").fetchall()
    return jsonify({"users": [row_to_user(r) for r in rows]})


@api.get("/users/consultants")
@login_required()
def list_consultants():
    rows = get_db().execute("SELECT * FROM users WHERE role = 'consultant' AND active = 1").fetchall()
    return jsonify({"users": [row_to_user(r) for r in rows]})


@api.get("/users/<username>")
@login_required()
def get_user(username):
    if not (g.user["username"] == username or g.user["role"] in ("developer", "consultant")):
        return jsonify({"error": "forbidden"}), 403
    row = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"user": row_to_user(row)})


@api.post("/users")
@login_required(role="developer")
def admin_create_user():
    body = request.get_json(force=True, silent=True) or {}
    username = clean_username(body.get("username"))
    password = body.get("password") or ""
    role = body.get("role")
    if len(username) < 3:
        return jsonify({"error": "Username must be at least 3 characters."}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400
    if role not in ("resident", "consultant", "developer"):
        return jsonify({"error": "Invalid role."}), 400
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        return jsonify({"error": "That username is already taken."}), 409
    now = datetime.datetime.utcnow().isoformat() + "Z"
    pg_year = body.get("pgYear") if role == "resident" else None
    designation = body.get("designation") if role == "consultant" else None
    unit = body.get("unit") if role == "consultant" else None
    db.execute(
        "INSERT INTO users (username, password_hash, role, display_name, pg_year, designation, unit, active, created_at) VALUES (?,?,?,?,?,?,?,1,?)",
        (username, hash_password(password), role, body.get("displayName") or username, pg_year, designation, unit, now),
    )
    db.commit()
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return jsonify({"user": row_to_user(row)})


@api.patch("/users/<username>")
@login_required(role="developer")
def update_user(username):
    body = request.get_json(force=True, silent=True) or {}
    db = get_db()
    if not db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        return jsonify({"error": "not_found"}), 404
    if "active" in body:
        db.execute("UPDATE users SET active = ? WHERE username = ?", (1 if body["active"] else 0, username))
        if not body["active"]:
            destroy_all_sessions_for(username)
    if "role" in body and body["role"] in ("resident", "consultant", "developer"):
        db.execute("UPDATE users SET role = ? WHERE username = ?", (body["role"], username))
    if "password" in body and body["password"]:
        if len(body["password"]) < 8:
            return jsonify({"error": "New password must be at least 8 characters."}), 400
        db.execute("UPDATE users SET password_hash = ? WHERE username = ?", (hash_password(body["password"]), username))
        destroy_all_sessions_for(username)
    db.commit()
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return jsonify({"user": row_to_user(row)})


# --------------------------------------------------------- password admin
@api.get("/password-requests")
@login_required(role="developer")
def list_password_requests():
    rows = get_db().execute("SELECT * FROM password_resets ORDER BY requested_at DESC").fetchall()
    return jsonify({"requests": [dict(r) for r in rows]})


@api.post("/password-requests/<int:req_id>/resolve")
@login_required(role="developer")
def resolve_password_request(req_id):
    # Marks the queue item resolved. Setting the user's actual new password
    # is a separate call (PATCH /api/users/<username> {password}) made
    # right before this by the same admin action -- keeping them separate
    # means a developer can also just resolve/dismiss a request without
    # necessarily having reset the password through this exact flow.
    db = get_db()
    row = db.execute("SELECT * FROM password_resets WHERE id = ?", (req_id,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    db.execute(
        "UPDATE password_resets SET status = 'resolved', resolved_at = ?, resolved_by = ? WHERE id = ?",
        (datetime.datetime.utcnow().isoformat() + "Z", g.user["username"], req_id),
    )
    db.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------------ config
@api.get("/config")
def read_config():
    # Deliberately public (no login_required): the sign-up screen needs the
    # PG-year and unit lists before anyone has a session, and none of this
    # is sensitive -- it's dropdown metadata, not patient or user data.
    return jsonify({"config": get_config()})


@api.patch("/config")
@login_required(role="developer")
def update_config():
    body = request.get_json(force=True, silent=True) or {}
    db = get_db()
    cfg = get_config()
    cfg.update(body)
    db.execute("UPDATE config SET data = ? WHERE id = 'lists'", (json.dumps(cfg),))
    db.commit()
    return jsonify({"config": cfg})


# ---------------------------------------------------------- role assigns
@api.get("/role-assignments")
@login_required()
def list_role_assignments():
    db = get_db()
    if g.user["role"] == "developer":
        rows = db.execute("SELECT * FROM role_assignments ORDER BY assigned_at DESC").fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM role_assignments WHERE consultant_username = ? ORDER BY assigned_at DESC",
            (g.user["username"],),
        ).fetchall()
    return jsonify({"roleAssignments": [dict(r) for r in rows]})


@api.post("/role-assignments")
@login_required(role="developer")
def add_role_assignment():
    body = request.get_json(force=True, silent=True) or {}
    db = get_db()
    consultant = db.execute("SELECT display_name FROM users WHERE username = ?", (body.get("consultantUsername"),)).fetchone()
    if not consultant:
        return jsonify({"error": "No such consultant."}), 404
    now = datetime.datetime.utcnow().isoformat() + "Z"
    cur = db.execute(
        "INSERT INTO role_assignments (consultant_username, consultant_display_name, assignment_role, unit, start_at, end_at, assigned_by, assigned_at) VALUES (?,?,?,?,?,?,?,?)",
        (body.get("consultantUsername"), consultant["display_name"], body.get("role"), body.get("unit"), body.get("startAt"), body.get("endAt"), g.user["username"], now),
    )
    db.commit()
    row = db.execute("SELECT * FROM role_assignments WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify({"roleAssignment": dict(row)})


@api.delete("/role-assignments/<int:assignment_id>")
@login_required(role="developer")
def remove_role_assignment(assignment_id):
    db = get_db()
    db.execute("DELETE FROM role_assignments WHERE id = ?", (assignment_id,))
    db.commit()
    return jsonify({"ok": True})
