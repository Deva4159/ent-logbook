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


PROCEDURE_BLOCK_TYPES = {"surgical", "other"}


def _valid_procedure_block(b):
    return (
        isinstance(b, dict)
        and isinstance(b.get("site"), str) and b.get("site")
        and isinstance(b.get("procedures"), list) and len(b["procedures"]) > 0
        and all(isinstance(p, str) for p in b["procedures"])
        and (b.get("laterality") is None or isinstance(b.get("laterality"), str))
        and isinstance(b.get("role"), str) and b.get("role")
    )


def _clean_procedure_block(b):
    return {
        "site": b["site"],
        "procedures": list(b["procedures"]),
        "laterality": b.get("laterality") or "",
        "role": b["role"],
    }


def _clean_procedure_block_draft(b):
    """Same shape as _clean_procedure_block, but for a 'draft' Surgical/Other
    Procedure entry -- a resident is deliberately mid-fill, so nothing here
    is required yet. Missing/malformed pieces default to empty rather than
    rejecting the save; _valid_procedure_block (the full-strictness check)
    is what finally gates a draft on its way to 'final'."""
    if not isinstance(b, dict):
        b = {}
    procedures = b.get("procedures")
    site = b.get("site")
    role = b.get("role")
    laterality = b.get("laterality")
    return {
        "site": site if isinstance(site, str) else "",
        "procedures": [p for p in procedures if isinstance(p, str)] if isinstance(procedures, list) else [],
        "laterality": laterality if isinstance(laterality, str) else "",
        "role": role if isinstance(role, str) else "",
    }


def _blocks_derived(blocks):
    """Flat site/procedures/laterality/role, derived (never stored) from a
    surgical/other entry's procedure_blocks, purely so simple read-side
    consumers (the admin CSV export, any legacy caller) still get something
    sensible without having to understand the block structure. Computed
    fresh from procedure_blocks on every read -- never written back to the
    flat columns -- so there is exactly one source of truth for these
    fields and no way for the two to drift apart the way the old
    partial-PATCH bug let scalar fields drift.
    """
    sites, procs, laterals, roles = [], [], [], []
    for b in blocks:
        if b.get("site") and b["site"] not in sites:
            sites.append(b["site"])
        for p in b.get("procedures") or []:
            procs.append(p)
        lat = b.get("laterality") or ""
        if lat and lat not in laterals:
            laterals.append(lat)
        role = b.get("role") or ""
        if role and role not in roles:
            roles.append(role)
    return {
        "site": ", ".join(sites),
        "procedures": procs,
        "laterality": "; ".join(laterals),
        "role": "; ".join(roles),
    }


def entry_row_to_dict(row):
    d = dict(row)
    for k in ("procedures", "diagnoses", "diagnoses_secondary", "comorbidities"):
        try:
            d[k] = json.loads(d[k]) if d[k] else []
        except (TypeError, ValueError):
            d[k] = []
    try:
        procedure_blocks = json.loads(d["procedure_blocks"]) if d.get("procedure_blocks") else []
    except (TypeError, ValueError):
        procedure_blocks = []
    derived = _blocks_derived(procedure_blocks) if (d["entry_type"] in PROCEDURE_BLOCK_TYPES and procedure_blocks) else None
    return {
        "id": d["id"],
        "authorUsername": d["author_username"],
        "entryType": d["entry_type"],
        "unit": d["unit"],
        "date": d["entry_date"],
        "createdAt": d["created_at"],
        "procedureBlocks": procedure_blocks,
        "site": derived["site"] if derived else d["site"],
        "procedures": derived["procedures"] if derived else d["procedures"],
        "setting": d["setting"],
        "otherSettingType": d["other_setting_type"],
        "hospitalNumber": d["hospital_number"],
        "age": d["age"],
        "sex": d["sex"],
        "diagnoses": d["diagnoses"],
        "diagnosesSecondary": d["diagnoses_secondary"],
        "comorbidities": d["comorbidities"],
        "laterality": derived["laterality"] if derived else d["laterality"],
        "role": derived["role"] if derived else d["role_level"],
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
        "paperStatus": d.get("paper_status"),
        "status": d.get("status") or "final",
    }


# Fields excluded from the edit-history diff: identity/authorship never
# changes, and createdAt is set once at insert and never touched by an edit.
ENTRY_HISTORY_IGNORE = {"id", "authorUsername", "createdAt"}

PAPER_STATUSES = {"not_done", "in_progress", "done"}


def _entry_can_set_paper_status(user, entry_row):
    """Only the PG who wrote an Interesting Case linked to a surgical entry
    can move its paper-status to-do -- Senior Residents/Fellows don't get
    this tracker, and it's a private to-do, not something anyone else sets."""
    return (
        entry_row["entry_type"] == "case"
        and entry_row["linked_from_id"] is not None
        and user["username"] == entry_row["author_username"]
        and user["role"] == "resident"
    )


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
    # The frontend's scope banner names which role(s) actually granted full
    # ("as Head of Department & Course Coordinator") -- it was already
    # written to read this (renderScopeBanner in app.js), but this endpoint
    # never actually sent it, so that banner has been throwing (undefined
    # .filter) and stuck the whole consultant dashboard on "Loading..." for
    # any HOD/Coordinator ever since. `role` here (not the raw column name
    # assignment_role) is what that existing frontend code reads.
    return {
        "full": full,
        "units": list(hou_units | prof_units),
        "activeAssignments": [{"role": a["assignment_role"], "unit": a["unit"]} for a in mine],
    }


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

    # A Fellow belongs to one parent/home unit, same idea as a consultant's
    # home unit, chosen at sign-up -- their day-to-day postings (including to
    # other units) are still tracked separately via Postings, unaffected by
    # this. Required, unlike a consultant's unit, because it's how a Fellow
    # shows up in that unit's consultant/assistant picker from day one.
    unit = body.get("unit") if final_role in ("consultant", "fellow") else None
    if final_role == "fellow" and not unit:
        return jsonify({"error": "Fellows must select a parent unit at sign-up."}), 400

    now = datetime.datetime.utcnow().isoformat() + "Z"
    pg_year = body.get("pgYear") if final_role in TRAINEE_ROLES else None
    designation = body.get("designation") if final_role == "consultant" else None

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

    linked_from_id = body.get("linkedFromId")
    # A case entry linked to a surgical entry starts its PG paper-writeup
    # to-do at 'not_done'; every other entry (including an unlinked case,
    # or a case logged by a Senior Resident/Fellow) gets no tracker at all.
    paper_status = "not_done" if (entry_type == "case" and linked_from_id and g.user["role"] == "resident") else None

    # A draft is a deliberate mid-fill save -- only meaningful for the two
    # entry types with enough required fields to make "save now, finish
    # later" worthwhile. Anything else that asks for status=draft is simply
    # saved final, same as if the field had been omitted.
    status = body.get("status") if body.get("status") in ("draft", "final") else "final"
    if status == "draft" and entry_type not in PROCEDURE_BLOCK_TYPES:
        status = "final"

    procedure_blocks_json = "[]"
    if entry_type in PROCEDURE_BLOCK_TYPES:
        blocks = body.get("procedureBlocks")
        if status == "draft":
            # Draft: keep whatever partial blocks were given, defaulting
            # anything missing rather than rejecting the save outright.
            if not isinstance(blocks, list):
                blocks = []
            procedure_blocks_json = json.dumps([_clean_procedure_block_draft(b) for b in blocks])
        else:
            if not isinstance(blocks, list) or not blocks or not all(_valid_procedure_block(b) for b in blocks):
                return jsonify({"error": "Each site logged needs at least one procedure and a role/entrustment level."}), 400
            procedure_blocks_json = json.dumps([_clean_procedure_block(b) for b in blocks])

    db = get_db()
    cur = db.execute(
        """INSERT INTO entries (
            author_username, entry_type, unit, entry_date, created_at, site, procedures,
            setting, other_setting_type, hospital_number, age, sex, diagnoses,
            diagnoses_secondary, comorbidities, laterality, role_level, consultant,
            consultant_username, assistants, comments, case_report, linked_from_id,
            history, examination, academic_type, academic_type_other, seminar_type,
            seminar_type_other, topic, venue, details, paper_status, procedure_blocks, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            g.user["username"], entry_type, unit, entry_date, now,
            # site/procedures/laterality/role_level stay unset for a
            # surgical/other entry -- procedure_blocks is authoritative for
            # those two types from here on (see entry_row_to_dict, which
            # derives these same flat fields back out for any reader that
            # still wants them, e.g. the CSV export).
            None if entry_type in PROCEDURE_BLOCK_TYPES else body.get("site"),
            "[]" if entry_type in PROCEDURE_BLOCK_TYPES else json.dumps(body.get("procedures") or []),
            body.get("setting"), body.get("otherSettingType"), body.get("hospitalNumber"),
            body.get("age"), body.get("sex"), json.dumps(body.get("diagnoses") or []),
            json.dumps(body.get("diagnosesSecondary") or []), json.dumps(body.get("comorbidities") or []),
            None if entry_type in PROCEDURE_BLOCK_TYPES else body.get("laterality"),
            None if entry_type in PROCEDURE_BLOCK_TYPES else body.get("role"),
            body.get("consultant"),
            body.get("consultantUsername"), body.get("assistants"), body.get("comments"),
            body.get("caseReport"), linked_from_id,
            body.get("history"), body.get("examination"), body.get("academicType"),
            body.get("academicTypeOther"), body.get("seminarType"), body.get("seminarTypeOther"),
            body.get("topic"), body.get("venue"), body.get("details"), paper_status, procedure_blocks_json, status,
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


@api.get("/reminders")
@login_required()
def reminders():
    # Trainee-only, on purpose: postings (and the paper to-do) are theirs,
    # not a consultant's. Returns structured facts, not pre-written copy --
    # the frontend composes the message using its own unit labels and shows
    # only the single highest-priority one, so the dashboard never stacks
    # more than one reminder line at a time.
    if g.user["role"] not in TRAINEE_ROLES:
        return jsonify({"reminders": []})
    db = get_db()
    username = g.user["username"]
    today = datetime.date.today()
    today_str = today.isoformat()
    out = []

    postings = get_postings(username)
    current = [p for p in postings if p["startDate"] and p["startDate"] <= today_str and (not p["endDate"] or p["endDate"] >= today_str)]
    for p in current:
        if not p["endDate"]:
            continue
        days_left = (datetime.date.fromisoformat(p["endDate"]) - today).days
        if 0 <= days_left <= 7:
            has_next = any(q["startDate"] and q["startDate"] > p["endDate"] for q in postings)
            out.append({
                "type": "end_of_posting", "priority": 1, "unit": p["unit"],
                "endDate": p["endDate"], "daysLeft": days_left, "hasNextPosting": has_next,
            })

    last7 = (today - datetime.timedelta(days=7)).isoformat()
    week_count = db.execute(
        "SELECT COUNT(*) AS n FROM entries WHERE author_username=? AND entry_date >= ?", (username, last7)
    ).fetchone()["n"]
    pending_papers = None
    if g.user["role"] == "resident":
        pending_papers = db.execute(
            "SELECT COUNT(*) AS n FROM entries WHERE author_username=? AND entry_type='case' "
            "AND linked_from_id IS NOT NULL AND (paper_status IS NULL OR paper_status != 'done')",
            (username,),
        ).fetchone()["n"]
    out.append({"type": "weekly", "priority": 2, "weekCount": week_count, "pendingPapers": pending_papers})

    last_entry = db.execute(
        "SELECT MAX(entry_date) AS d FROM entries WHERE author_username=?", (username,)
    ).fetchone()["d"]
    if not last_entry or (today - datetime.date.fromisoformat(last_entry)).days >= 2:
        out.append({"type": "daily", "priority": 3, "lastEntryDate": last_entry})

    out.sort(key=lambda r: r["priority"])
    return jsonify({"reminders": out})


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
    # changed) date, exactly like create_entry does. Every actual change is
    # captured in entry_edits so the author and the relevant oversight roles
    # can see what changed, when, and by whom.
    db = get_db()
    existing = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not existing:
        return jsonify({"error": "not_found"}), 404
    if existing["author_username"] != g.user["username"] and g.user["role"] != "developer":
        return jsonify({"error": "forbidden"}), 403

    body = request.get_json(force=True, silent=True) or {}
    entry_type = body.get("entryType") or existing["entry_type"]
    if entry_type not in ENTRY_TYPES:
        return jsonify({"error": "Unknown entry type."}), 400
    entry_date = body.get("date") or existing["entry_date"]
    # Only re-resolve unit from postings when the caller is actually changing
    # the date -- recomputing it unconditionally on every PATCH (including a
    # lightweight one that only sets e.g. paperStatus or comments) silently
    # blanks an entry's unit to "" whenever the author has no posting
    # covering that date at PATCH time (a gap between postings, or a historic
    # entry from before posting-based resolution existed). Otherwise, the
    # entry keeps whatever unit it already had, exactly like every other
    # field this function doesn't touch.
    unit = _resolve_unit_for_entry(existing["author_username"], entry_date) if "date" in body else existing["unit"]

    # paper_status is a separate, narrowly-gated to-do the PG sets on their
    # own linked case -- never silently wiped by a regular edit that doesn't
    # mention it, and never settable by anyone the entry doesn't belong to.
    if "paperStatus" in body:
        new_paper_status = body.get("paperStatus")
        if new_paper_status not in PAPER_STATUSES:
            return jsonify({"error": "Invalid paper status."}), 400
        if not _entry_can_set_paper_status(g.user, existing):
            return jsonify({"error": "forbidden"}), 403
    else:
        new_paper_status = existing["paper_status"]

    before = entry_row_to_dict(existing)

    # status: draft only ever applies to Surgical/Other Procedure, and only
    # while explicitly requested (finalizing, or a plain re-save of a draft
    # that doesn't mention status, keeps it as-is). A finalized entry never
    # reverts to draft -- the frontend never offers that once an entry is
    # final, and this is the actual guarantee: without it, an entry could be
    # un-finalized on request to pull it back out of the roster/stats/export
    # a consultant has already reviewed it in.
    existing_status = existing["status"] if existing["status"] in ("draft", "final") else "final"
    if "status" in body:
        new_status = body.get("status")
        if new_status not in ("draft", "final"):
            return jsonify({"error": "Invalid status."}), 400
        if new_status == "draft" and entry_type not in PROCEDURE_BLOCK_TYPES:
            return jsonify({"error": "Only Surgical/Other Procedure entries can be saved as drafts."}), 400
        if new_status == "draft" and existing_status == "final":
            return jsonify({"error": "A finalized entry can't be moved back to draft."}), 400
    else:
        new_status = existing_status

    # procedure_blocks is the source of truth for a surgical/other entry;
    # site/procedures/laterality/role in `before`/`after` are DERIVED from it
    # (see entry_row_to_dict) and are never valid values to write back into
    # the flat site/procedures/laterality/role_level columns -- a joined
    # "ear, nose" string is not a category key. So those four columns are
    # simply unset for these two entry types (exactly like create_entry),
    # and any fallback for them reads the RAW existing row, never `before`.
    is_block_type = entry_type in PROCEDURE_BLOCK_TYPES
    if is_block_type:
        if "procedureBlocks" in body:
            blocks_raw = body.get("procedureBlocks")
        else:
            try:
                blocks_raw = json.loads(existing["procedure_blocks"]) if existing["procedure_blocks"] else []
            except (TypeError, ValueError):
                blocks_raw = []
        if new_status == "draft":
            # Draft: partial blocks are fine, default what's missing rather
            # than rejecting the save.
            if not isinstance(blocks_raw, list):
                blocks_raw = []
            procedure_blocks_json = json.dumps([_clean_procedure_block_draft(b) for b in blocks_raw])
        else:
            # Finalizing (or a plain edit to an already-final entry): full
            # strictness applies, whether or not this PATCH itself resent
            # procedureBlocks -- so a draft can't slip to 'final' with
            # incomplete blocks just by omitting the field.
            if not isinstance(blocks_raw, list) or not blocks_raw or not all(_valid_procedure_block(b) for b in blocks_raw):
                return jsonify({"error": "Each site logged needs at least one procedure and a role/entrustment level."}), 400
            procedure_blocks_json = json.dumps([_clean_procedure_block(b) for b in blocks_raw])
    else:
        procedure_blocks_json = "[]"

    db.execute(
        """UPDATE entries SET
            entry_type=?, unit=?, entry_date=?, site=?, procedures=?,
            setting=?, other_setting_type=?, hospital_number=?, age=?, sex=?, diagnoses=?,
            diagnoses_secondary=?, comorbidities=?, laterality=?, role_level=?, consultant=?,
            consultant_username=?, assistants=?, comments=?, case_report=?, linked_from_id=?,
            history=?, examination=?, academic_type=?, academic_type_other=?, seminar_type=?,
            seminar_type_other=?, topic=?, venue=?, details=?, paper_status=?, procedure_blocks=?, status=?
        WHERE id = ?""",
        (
            entry_type, unit, entry_date,
            None if is_block_type else body.get("site", existing["site"]),
            "[]" if is_block_type else json.dumps(body.get("procedures", before["procedures"]) or []),
            body.get("setting", before["setting"]), body.get("otherSettingType", before["otherSettingType"]),
            body.get("hospitalNumber", before["hospitalNumber"]),
            body.get("age", before["age"]), body.get("sex", before["sex"]),
            json.dumps(body.get("diagnoses", before["diagnoses"]) or []),
            json.dumps(body.get("diagnosesSecondary", before["diagnosesSecondary"]) or []),
            json.dumps(body.get("comorbidities", before["comorbidities"]) or []),
            None if is_block_type else body.get("laterality", existing["laterality"]),
            None if is_block_type else body.get("role", existing["role_level"]),
            body.get("consultant", before["consultant"]),
            body.get("consultantUsername", before["consultantUsername"]),
            body.get("assistants", before["assistants"]), body.get("comments", before["comments"]),
            body.get("caseReport", before["caseReport"]), body.get("linkedFromId", before["linkedFromId"]),
            body.get("history", before["history"]), body.get("examination", before["examination"]),
            body.get("academicType", before["academicType"]),
            body.get("academicTypeOther", before["academicTypeOther"]),
            body.get("seminarType", before["seminarType"]),
            body.get("seminarTypeOther", before["seminarTypeOther"]),
            body.get("topic", before["topic"]), body.get("venue", before["venue"]),
            body.get("details", before["details"]), new_paper_status, procedure_blocks_json, new_status,
            entry_id,
        ),
    )

    row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    after = entry_row_to_dict(row)
    # site/procedures/laterality/role are derived read-side from
    # procedureBlocks for a surgical/other entry (see entry_row_to_dict), so
    # diffing them here too would just repeat whatever procedureBlocks
    # already shows, as four extra noisy lines every time it changes.
    ignore = ENTRY_HISTORY_IGNORE | ({"site", "procedures", "laterality", "role"} if is_block_type else set())
    changes = {
        k: {"old": before[k], "new": after[k]}
        for k in after
        if k not in ignore and before.get(k) != after[k]
    }
    if changes:
        db.execute(
            "INSERT INTO entry_edits (entry_id, edited_by, edited_at, changes) VALUES (?,?,?,?)",
            (entry_id, g.user["username"], datetime.datetime.utcnow().isoformat() + "Z", json.dumps(changes)),
        )
    db.commit()
    return jsonify({"entry": after})


def _can_view_entry_history(user, entry_row):
    if user["role"] == "developer" or user["username"] == entry_row["author_username"]:
        return True
    if user["role"] != "consultant":
        return False
    caps = user_capabilities(user["username"])
    if caps["isHod"] or caps["isCoordinator"]:
        return True
    if caps["isHeadOfUnit"]:
        scope = consultant_scope(user["username"])
        return entry_row["unit"] in scope["units"]
    return False


@api.get("/entries/<int:entry_id>/history")
@login_required()
def entry_history(entry_id):
    db = get_db()
    entry_row = db.execute("SELECT author_username, unit FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not entry_row:
        return jsonify({"error": "not_found"}), 404
    if not _can_view_entry_history(g.user, entry_row):
        return jsonify({"error": "forbidden"}), 403
    rows = db.execute(
        "SELECT edited_by, edited_at, changes FROM entry_edits WHERE entry_id = ? ORDER BY id ASC", (entry_id,)
    ).fetchall()
    edits = [{"editedBy": r["edited_by"], "editedAt": r["edited_at"], "changes": json.loads(r["changes"])} for r in rows]
    return jsonify({"edits": edits})


@api.get("/entries/roster")
@login_required(role="consultant")
def roster_entries():
    scope = consultant_scope(g.user["username"])
    db = get_db()
    placeholders = ",".join("?" * len(TRAINEE_ROLES))
    users = [dict(r) for r in db.execute(f"SELECT * FROM users WHERE role IN ({placeholders})", tuple(TRAINEE_ROLES)).fetchall()]
    # Drafts are a resident's private scratch space -- hidden from the
    # roster (and everywhere else consultant/HOD-facing) until finalized.
    all_entries = [e for e in (entry_row_to_dict(r) for r in db.execute("SELECT * FROM entries").fetchall()) if e["status"] != "draft"]
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
    # Same "hidden until finalized" rule as the roster: a draft is the
    # resident's own scratch space, not yet an entry to review, even for the
    # developer's admin view. list_my_entries() (their own drafts) and
    # reminders() (their own counts) are the only endpoints that still show
    # a user their own drafts.
    return jsonify({"entries": [e for e in (entry_row_to_dict(r) for r in rows) if e["status"] != "draft"]})


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
    entries = [entry_row_to_dict(r) for r in rows]
    if g.user["username"] != username:
        # Looking at someone else's entries (consultant/developer drill-down)
        # -- their drafts are private to them, same rule as the roster.
        entries = [e for e in entries if e["status"] != "draft"]
    return jsonify({"entries": entries})


def _export_csv(rows, columns):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([label for _, label in columns])
    for r in rows:
        writer.writerow([r.get(key, "") if not callable(key) else key(r) for key, _ in columns])
    return buf.getvalue()


def _joined(field):
    return lambda r: "; ".join(r.get(field) or [])


ENTRY_EXPORT_COLUMNS = [
    ("date", "Date"), ("authorUsername", "Resident"), ("entryType", "Type"), ("unit", "Unit"),
    ("site", "Site"), (_joined("procedures"), "Procedures"), ("hospitalNumber", "Hospital Number"),
    ("age", "Age"), ("sex", "Sex"), (_joined("diagnoses"), "Primary Diagnoses"),
    (_joined("diagnosesSecondary"), "Secondary Diagnoses"), (_joined("comorbidities"), "Comorbidities"),
    ("laterality", "Side"), ("setting", "Emergency/Elective"), ("role", "Role/Entrustment"),
    ("consultant", "Consultant"), ("assistants", "Assistants"), ("otherSettingType", "Other-procedure setting"),
    ("history", "Brief History"), ("examination", "Examination Findings"), ("academicType", "Academic Type"),
    ("academicTypeOther", "Academic Type (other)"), ("seminarType", "Seminar Type"),
    ("seminarTypeOther", "Seminar Type (other)"), ("topic", "Topic"), ("venue", "Venue"),
    ("details", "Details"), ("comments", "Comments/Complications"), ("paperStatus", "Paper Status"),
]


@api.get("/entries/export.csv")
@login_required(role="developer")
def export_entries_csv():
    # A CSV export is an official record, not a private workspace -- a draft
    # (even the exporting user's own, from export_my_entries_csv below)
    # never appears in one, same "hidden until finalized" rule as the roster.
    rows = [e for e in (entry_row_to_dict(r) for r in get_db().execute("SELECT * FROM entries").fetchall()) if e["status"] != "draft"]
    csv_text = _export_csv(rows, ENTRY_EXPORT_COLUMNS)
    return Response(csv_text, mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=ent-logbook-entries.csv"})


@api.get("/entries/export/mine.csv")
@login_required()
def export_my_entries_csv():
    # Self-service export for everyone, not just the Developer: a trainee
    # gets their own authored entries; a consultant gets whatever their
    # consultant_scope() already lets them see (their unit, or everything for
    # HOD/Coordinator/full-scope Head of Unit); the Developer gets the same
    # everything the admin export gives them.
    db = get_db()
    user = g.user
    if user["role"] == "developer":
        rows = db.execute("SELECT * FROM entries ORDER BY entry_date DESC, id DESC").fetchall()
    elif user["role"] == "consultant":
        scope = consultant_scope(user["username"])
        if scope["full"]:
            rows = db.execute("SELECT * FROM entries ORDER BY entry_date DESC, id DESC").fetchall()
        elif scope["units"]:
            placeholders = ",".join("?" * len(scope["units"]))
            rows = db.execute(
                f"SELECT * FROM entries WHERE unit IN ({placeholders}) ORDER BY entry_date DESC, id DESC",
                tuple(scope["units"]),
            ).fetchall()
        else:
            rows = []
    else:
        rows = db.execute(
            "SELECT * FROM entries WHERE author_username = ? ORDER BY entry_date DESC, id DESC", (user["username"],)
        ).fetchall()
    # Export is an official record -- exclude drafts even from a resident's
    # own export of their own entries (see export_entries_csv above).
    exportable = [e for e in (entry_row_to_dict(r) for r in rows) if e["status"] != "draft"]
    csv_text = _export_csv(exportable, ENTRY_EXPORT_COLUMNS)
    filename = f"ent-logbook-my-entries-{user['username']}.csv"
    return Response(csv_text, mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})


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


@api.get("/units/<unit>/people")
@login_required()
def unit_people(unit):
    # Feeds the Consultant / Assistants pickers when logging a Surgical or
    # Other Procedure entry: whoever is actually attached to this unit around
    # this date. Consultants are matched on their static home unit; Senior
    # Residents and Fellows (who rotate) are matched on an actual posting
    # covering that date -- exactly the same date-window logic
    # _resolve_unit_for_entry already uses to pick the entry's own unit, just
    # run in reverse (who was posted here, not where was I posted).
    date_str = (request.args.get("date") or "").strip() or datetime.date.today().isoformat()
    db = get_db()
    consultants = db.execute(
        "SELECT username, display_name, role FROM users WHERE role='consultant' AND active=1 AND unit=? ORDER BY display_name",
        (unit,),
    ).fetchall()
    trainees = db.execute(
        """SELECT DISTINCT u.username, u.display_name, u.role FROM users u
           JOIN postings p ON p.username = u.username
           WHERE u.role IN ('senior_resident','fellow') AND u.active = 1 AND p.unit = ?
             AND p.start_date <= ? AND (p.end_date IS NULL OR p.end_date >= ?)
           ORDER BY u.display_name""",
        (unit, date_str, date_str),
    ).fetchall()
    people = [{"username": r["username"], "displayName": r["display_name"], "role": r["role"]} for r in list(consultants) + list(trainees)]
    return jsonify({"people": people})


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
    unit = body.get("unit") if role in ("consultant", "fellow") else None
    if role == "fellow" and not unit:
        return jsonify({"error": "Fellows must have a parent unit."}), 400
    now = datetime.datetime.utcnow().isoformat() + "Z"
    pg_year = body.get("pgYear") if role in TRAINEE_ROLES else None
    designation = body.get("designation") if role == "consultant" else None
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
    # A Fellow's parent unit, or a consultant's home unit, can change too
    # (a Fellow reassigned, a consultant transferred) -- same gate as batch/
    # designation.
    if "unit" in body:
        db.execute("UPDATE users SET unit = ? WHERE username = ?", (body.get("unit"), username))
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
