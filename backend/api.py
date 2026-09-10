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
# Every role that logs entries and gets the resident-style dashboard/logbook
# experience -- "PG resident" is just one of the three now.
TRAINEE_ROLES = {"resident", "senior_resident", "fellow"}
CONSULTANT_ROLE_ASSIGNMENTS = {"head_of_unit", "coordinator", "hod"}


# ---------------------------------------------------------------- helpers
def row_to_user(row):
    if row is None:
        return None
    d = dict(row)
    return {
        "username": d["username"],
        "role": d["role"],
        "displayName": d["display_name"],
        "pgYear": d["pg_year"],
        "designation": d["designation"],
        "unit": d["unit"],
        "active": bool(d.get("active", 1)),
        "approvalStatus": d.get("approval_status", "approved"),
        "createdAt": d["created_at"],
    }


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


def _active_role_assignments(username):
    db = get_db()
    rows = db.execute("SELECT * FROM role_assignments WHERE consultant_username = ?", (username,)).fetchall()
    return [dict(r) for r in rows if is_assignment_active(dict(r))]


# Who can see a trainee's (PG / Senior Resident / Fellow) progress:
#  - HOD or Course Coordinator: everyone, every unit ("full").
#  - Head of Unit: everyone in the unit(s) they're Head of -- this is what
#    "same rights as HOD/Coordinator" means for them: they don't need to be
#    a Professor to see their own unit, they just aren't org-wide like HOD/
#    Coordinator are.
#  - A Professor-designation consultant: their own home unit only.
#  - Any other consultant (Assistant/Associate Professor, no role
#    assignment): nothing. This is a deliberate tightening -- every
#    consultant with a home unit used to get that unit's roster for free.
def consultant_scope(username):
    db = get_db()
    mine = _active_role_assignments(username)
    full = any(a["assignment_role"] in ("hod", "coordinator") for a in mine)
    hou_units = set(a["unit"] for a in mine if a["assignment_role"] == "head_of_unit" and a["unit"])
    user = db.execute("SELECT unit, designation FROM users WHERE username = ?", (username,)).fetchone()
    prof_units = set()
    if user and user["unit"] and (user["designation"] or "").strip().lower() == "professor":
        prof_units.add(user["unit"])
    return {"full": full, "units": list(hou_units | prof_units)}


def user_capabilities(username):
    if not username:
        return {"isDeveloper": False, "isHod": False, "isCoordinator": False, "isHeadOfUnit": False, "canApprove": False, "canManageProfiles": False}
    db = get_db()
    row = db.execute("SELECT role FROM users WHERE username = ?", (username,)).fetchone()
    is_developer = bool(row and row["role"] == "developer")
    mine = _active_role_assignments(username)
    is_hod = any(a["assignment_role"] == "hod" for a in mine)
    is_coordinator = any(a["assignment_role"] == "coordinator" for a in mine)
    is_head_of_unit = any(a["assignment_role"] == "head_of_unit" for a in mine)
    return {
        "isDeveloper": is_developer,
        "isHod": is_hod,
        "isCoordinator": is_coordinator,
        "isHeadOfUnit": is_head_of_unit,
        # Developer/HOD/Coordinator approve every new account; Head of Unit
        # only ever sees fellow signups in the actual list/approve endpoints.
        "canApprove": is_developer or is_hod or is_coordinator or is_head_of_unit,
        # Batch/designation edits and account deletion: Developer + HOD only.
        "canManageProfiles": is_developer or is_hod,
    }


# ------------------------------------------------------------------ auth
@api.post("/auth/signup")
def signup():
    body = request.get_json(force=True, silent=True) or {}
    username = clean_username(body.get("username"))
    password = body.get("password") or ""
    confirm = body.get("confirm") or ""
    display_name = (body.get("displayName") or username).strip()
    role = body.get("role") if body.get("role") in (TRAINEE_ROLES | {"consultant"}) else "resident"

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
    # Every self-signup waits for a human to approve it, except the very
    # first account ever created (bootstrapping the developer account --
    # nobody exists yet who could approve it).
    approval_status = "approved" if is_first_user else "pending"

    now = datetime.datetime.utcnow().isoformat() + "Z"
    pg_year = body.get("pgYear") if final_role in TRAINEE_ROLES else None
    designation = body.get("designation") if final_role == "consultant" else None
    unit = body.get("unit") if final_role == "consultant" else None

    db.execute(
        "INSERT INTO users (username, password_hash, role, display_name, pg_year, designation, unit, active, approval_status, created_at) VALUES (?,?,?,?,?,?,?,1,?,?)",
        (username, hash_password(password), final_role, display_name, pg_year, designation, unit, approval_status, now),
    )
    db.commit()

    if approval_status == "pending":
        approvers = "a Head of Unit, Head of Department, Course Coordinator, or Developer" if final_role == "fellow" \
            else "a Head of Department, Course Coordinator, or Developer"
        return jsonify({
            "pending": True,
            "message": f"Your account has been created and is waiting for approval from {approvers} before you can sign in.",
        })

    token = create_session(username)
    user = row_to_user(db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone())
    resp = jsonify({"user": user, "firstUser": is_first_user, "capabilities": user_capabilities(username)})
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
    if row["approval_status"] == "pending":
        return jsonify({"error": "Your account is still awaiting approval from a Head of Department, Course Coordinator, Head of Unit, or Developer."}), 403
    if require_role and row["role"] != require_role:
        return jsonify({"error": f"This account is not a {require_role} account."}), 403
    if not verify_password(row["password_hash"], password):
        record_attempt(rl_key_ip)
        record_attempt(rl_key_account)
        return jsonify({"error": "Incorrect password."}), 401

    token = create_session(username)
    resp = jsonify({"user": row_to_user(row), "capabilities": user_capabilities(username)})
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
    return jsonify({
        "user": row_to_user(user) if user else None,
        "capabilities": user_capabilities(user["username"]) if user else None,
    })


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


@api.patch("/entries/<int:entry_id>")
@login_required()
def update_entry(entry_id):
    # Same-author-only edit (developer can also fix a resident's entry), so
    # mistakes and incomplete entries can be corrected after the fact instead
    # of only ever being deletable. Recomputes unit from the (possibly
    # changed) date, exactly like create_entry does.
    db = get_db()
    existing = db.execute("SELECT author_username, entry_type FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not existing:
        return jsonify({"error": "not_found"}), 404
    if existing["author_username"] != g.user["username"] and g.user["role"] != "developer":
        return jsonify({"error": "forbidden"}), 403

    body = request.get_json(force=True, silent=True) or {}
    entry_type = body.get("entryType") or existing["entry_type"]
    if entry_type not in ENTRY_TYPES:
        return jsonify({"error": "Unknown entry type."}), 400
    entry_date = body.get("date") or datetime.date.today().isoformat()
    unit = _resolve_unit_for_entry(existing["author_username"], entry_date)

    db.execute(
        """UPDATE entries SET
            entry_type=?, unit=?, entry_date=?, site=?, procedures=?,
            setting=?, other_setting_type=?, hospital_number=?, age=?, sex=?, diagnoses=?,
            diagnoses_secondary=?, comorbidities=?, laterality=?, role_level=?, consultant=?,
            consultant_username=?, assistants=?, comments=?, case_report=?, linked_from_id=?,
            history=?, examination=?, academic_type=?, academic_type_other=?, seminar_type=?,
            seminar_type_other=?, topic=?, venue=?, details=?
        WHERE id = ?""",
        (
            entry_type, unit, entry_date,
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
            entry_id,
        ),
    )
    db.commit()
    row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    return jsonify({"entry": entry_row_to_dict(row)})


@api.get("/entries/roster")
@login_required(role="consultant")
def roster_entries():
    scope = consultant_scope(g.user["username"])
    db = get_db()
    placeholders = ",".join("?" * len(TRAINEE_ROLES))
    users = [dict(r) for r in db.execute(f"SELECT * FROM users WHERE role IN ({placeholders})", tuple(TRAINEE_ROLES)).fetchall()]
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
    db = get_db()
    if g.user["username"] == username or g.user["role"] == "developer":
        pass
    elif g.user["role"] == "consultant":
        # Was previously wide open to any logged-in consultant, regardless of
        # scope -- the roster UI just never linked to it for someone outside
        # their scope. Enforce the same unit-scope rule the roster itself
        # uses, now that scope is deliberately restrictive (Professor
        # designation, or a Head of Unit/HOD/Coordinator assignment).
        target = db.execute("SELECT role, unit FROM users WHERE username = ?", (username,)).fetchone()
        if not target:
            return jsonify({"error": "not_found"}), 404
        scope = consultant_scope(g.user["username"])
        if not scope["full"]:
            if target["role"] == "consultant":
                # A consultant profile's own "unit" is their home unit -- the
                # only case where that column is meaningful.
                in_scope = target["unit"] in scope["units"]
            else:
                # A trainee has no static home unit (that column is only ever
                # set for consultants) -- their unit lives on each logged
                # entry via the posting active on that date, exactly as
                # roster_entries() computes it. Mirror that here: in scope if
                # they've logged anything under a unit this caller can see.
                entry_units = {
                    r["unit"] for r in db.execute(
                        "SELECT DISTINCT unit FROM entries WHERE author_username = ?", (username,)
                    ).fetchall()
                }
                in_scope = bool(entry_units & set(scope["units"]))
            if not in_scope:
                return jsonify({"error": "forbidden"}), 403
    else:
        return jsonify({"error": "forbidden"}), 403
    rows = db.execute(
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
        ("username", "Username"), ("displayName", "Display Name"), ("role", "Role"),
        ("unit", "Unit"), ("pgYear", "PG Year"), ("designation", "Designation"),
        ("active", "Active"), ("createdAt", "Created At"),
    ]
    csv_text = _export_csv(rows, columns)
    return Response(csv_text, mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=ent-logbook-users.csv"})


# ------------------------------------------------------------------ users
@api.get("/users")
@login_required()
def list_users():
    # Developer sees this via the Users screen, HOD via Manage Users -- same
    # canManageProfiles gate as editing/deleting a profile, so a Head of
    # Department who can act on an account can also see the full list it's
    # drawn from.
    if not user_capabilities(g.user["username"])["canManageProfiles"]:
        return jsonify({"error": "forbidden"}), 403
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
    if role not in (TRAINEE_ROLES | {"consultant", "developer"}):
        return jsonify({"error": "Invalid role."}), 400
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        return jsonify({"error": "That username is already taken."}), 409
    now = datetime.datetime.utcnow().isoformat() + "Z"
    pg_year = body.get("pgYear") if role in TRAINEE_ROLES else None
    designation = body.get("designation") if role == "consultant" else None
    unit = body.get("unit") if role == "consultant" else None
    # Admin-created accounts are pre-approved -- an admin creating the
    # account directly IS the approval.
    db.execute(
        "INSERT INTO users (username, password_hash, role, display_name, pg_year, designation, unit, active, approval_status, created_at) VALUES (?,?,?,?,?,?,?,1,'approved',?)",
        (username, hash_password(password), role, body.get("displayName") or username, pg_year, designation, unit, now),
    )
    db.commit()
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return jsonify({"user": row_to_user(row)})


@api.patch("/users/<username>")
@login_required()
def update_user(username):
    caps = user_capabilities(g.user["username"])
    if not caps["canManageProfiles"]:
        return jsonify({"error": "forbidden"}), 403
    body = request.get_json(force=True, silent=True) or {}
    db = get_db()
    if not db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        return jsonify({"error": "not_found"}), 404
    if "active" in body:
        db.execute("UPDATE users SET active = ? WHERE username = ?", (1 if body["active"] else 0, username))
        if not body["active"]:
            destroy_all_sessions_for(username)
    # Batch (PG Year) and designation -- the "dynamic profile changes" both
    # Developer and HOD were given (a resident moving up a batch, a
    # consultant getting promoted from Assistant to Associate Professor).
    if "pgYear" in body:
        db.execute("UPDATE users SET pg_year = ? WHERE username = ?", (body.get("pgYear"), username))
    if "designation" in body:
        db.execute("UPDATE users SET designation = ? WHERE username = ?", (body.get("designation"), username))
    # Role changes and password resets stay Developer-only -- broader than
    # the specific batch/designation/delete powers HOD was given.
    if caps["isDeveloper"]:
        if "role" in body and body["role"] in (TRAINEE_ROLES | {"consultant", "developer"}):
            db.execute("UPDATE users SET role = ? WHERE username = ?", (body["role"], username))
        if "password" in body and body["password"]:
            if len(body["password"]) < 8:
                return jsonify({"error": "New password must be at least 8 characters."}), 400
            db.execute("UPDATE users SET password_hash = ? WHERE username = ?", (hash_password(body["password"]), username))
            destroy_all_sessions_for(username)
    db.commit()
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return jsonify({"user": row_to_user(row)})


@api.delete("/users/<username>")
@login_required()
def delete_user(username):
    caps = user_capabilities(g.user["username"])
    if not caps["canManageProfiles"]:
        return jsonify({"error": "forbidden"}), 403
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    if username == g.user["username"]:
        return jsonify({"error": "You can't delete your own account."}), 400
    # Deleting a user cascades to their postings, sessions and role
    # assignments -- fine, those are throwaway. It would ALSO cascade to
    # every entry they've ever logged, which is the one training record this
    # whole app exists to keep. Refuse that and point at deactivation
    # instead, which blocks sign-in without touching their logged history.
    entry_count = db.execute("SELECT COUNT(*) AS n FROM entries WHERE author_username = ?", (username,)).fetchone()["n"]
    if entry_count > 0:
        return jsonify({
            "error": f"{row['display_name']} has {entry_count} logged entr{'y' if entry_count == 1 else 'ies'}. "
                     "Deleting the account would permanently delete that training record too. "
                     "Deactivate the account instead to block sign-in while keeping their history.",
        }), 409
    db.execute("DELETE FROM users WHERE username = ?", (username,))
    db.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------- signup approvals
def _can_approve_role(caps, role):
    if caps["isDeveloper"] or caps["isHod"] or caps["isCoordinator"]:
        return True
    return caps["isHeadOfUnit"] and role == "fellow"


@api.get("/signup-requests")
@login_required()
def list_signup_requests():
    caps = user_capabilities(g.user["username"])
    if not caps["canApprove"]:
        return jsonify({"error": "forbidden"}), 403
    rows = get_db().execute("SELECT * FROM users WHERE approval_status = 'pending' ORDER BY created_at").fetchall()
    if not (caps["isDeveloper"] or caps["isHod"] or caps["isCoordinator"]):
        # Head-of-Unit-only: fellow signups are the only ones they can act on.
        rows = [r for r in rows if r["role"] == "fellow"]
    return jsonify({"requests": [row_to_user(r) for r in rows]})


@api.post("/signup-requests/<username>/approve")
@login_required()
def approve_signup_request(username):
    caps = user_capabilities(g.user["username"])
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row or row["approval_status"] != "pending":
        return jsonify({"error": "not_found"}), 404
    if not _can_approve_role(caps, row["role"]):
        return jsonify({"error": "forbidden"}), 403
    db.execute("UPDATE users SET approval_status = 'approved' WHERE username = ?", (username,))
    db.commit()
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return jsonify({"user": row_to_user(row)})


@api.post("/signup-requests/<username>/reject")
@login_required()
def reject_signup_request(username):
    caps = user_capabilities(g.user["username"])
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row or row["approval_status"] != "pending":
        return jsonify({"error": "not_found"}), 404
    if not _can_approve_role(caps, row["role"]):
        return jsonify({"error": "forbidden"}), 403
    # Safe to hard-delete outright: a never-approved account can't have
    # logged any entries yet.
    db.execute("DELETE FROM users WHERE username = ?", (username,))
    db.commit()
    return jsonify({"ok": True})


# --------------------------------------------------------- password admin
def password_reset_row_to_dict(row):
    d = dict(row)
    return {
        "id": d["id"],
        "username": d["username"],
        "note": d["note"],
        "status": d["status"],
        "requestedAt": d["requested_at"],
        "resolvedAt": d["resolved_at"],
        "resolvedBy": d["resolved_by"],
    }


@api.get("/password-requests")
@login_required(role="developer")
def list_password_requests():
    rows = get_db().execute("SELECT * FROM password_resets ORDER BY requested_at DESC").fetchall()
    return jsonify({"requests": [password_reset_row_to_dict(r) for r in rows]})


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
def role_assignment_row_to_dict(row):
    d = dict(row)
    return {
        "id": d["id"],
        "consultantUsername": d["consultant_username"],
        "consultantDisplayName": d["consultant_display_name"],
        "role": d["assignment_role"],
        "unit": d["unit"],
        "startAt": d["start_at"],
        "endAt": d["end_at"],
        "assignedBy": d["assigned_by"],
        "assignedAt": d["assigned_at"],
    }


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
    return jsonify({"roleAssignments": [role_assignment_row_to_dict(r) for r in rows]})


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
    return jsonify({"roleAssignment": role_assignment_row_to_dict(row)})


@api.delete("/role-assignments/<int:assignment_id>")
@login_required(role="developer")
def remove_role_assignment(assignment_id):
    db = get_db()
    db.execute("DELETE FROM role_assignments WHERE id = ?", (assignment_id,))
    db.commit()
    return jsonify({"ok": True})
