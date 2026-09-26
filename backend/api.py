"""All /api/* routes: auth, entries, postings, config, role assignments,
password-reset queue, CSV export. Every write uses parameterized queries
(no string-built SQL) and every state-changing route requires a valid
session via auth.login_required.
"""
import csv
import datetime
import io
import json
import re

from flask import Blueprint, g, jsonify, request, Response

from auth import (
    clean_username, client_ip, create_session, current_user,
    destroy_all_sessions_for, destroy_session, hash_password,
    login_required, rate_limit, record_attempt, set_session_cookie,
    clear_session_cookie, verify_password,
)
from db import get_db

api = Blueprint("api", __name__, url_prefix="/api")

def known_unit_keys():
    """The unit keys the department actually has, from the config list."""
    cfg = get_config()
    out = set()
    units = cfg.get("units")
    # A malformed config row must not take out signup, postings, account
    # creation and role assignments -- every one of which calls this, and
    # all of which 500'd together when `units` was not a list.
    if not isinstance(units, list):
        return out
    for u in units:
        if isinstance(u, dict) and isinstance(u.get("key"), str) and u["key"]:
            out.add(u["key"])
    return out


def bad_unit_response(unit):
    """400 for a unit key that isn't in the department's list.

    This is the check that stops a trainee choosing which unit their work is
    filed under. The unit on a posting is stamped onto every entry logged
    during it (_resolve_unit_for_entry), and that stamp is what every
    unit-scoped consultant query filters on -- so an unrecognised key put a
    resident's entire logbook outside their Head of Unit's roster and CSV
    export while it still counted on their own dashboard. The UI only ever
    offered real units; the hole was the API accepting anything.
    """
    return jsonify({
        "error": "Unknown unit.",
        "detail": "'%s' is not a unit in this department's list." % (unit,),
    }), 400


def _iso_date_or_none(v):
    """Accept only a real YYYY-MM-DD. Anything else is dropped.

    Without this a stored junk date is unrecoverable through the UI: the
    reminders endpoint takes MAX(entry_date) -- a string max, so "zzz" beats
    every real date -- and then calls date.fromisoformat() on it, so the
    author's dashboard 500s forever and they cannot reach the entry to
    delete it.
    """
    if not isinstance(v, str):
        return None
    try:
        datetime.date.fromisoformat(v.strip())
    except (ValueError, TypeError):
        return None
    return v.strip()


def _text(v, limit=20000):
    """Coerce a JSON value to a bindable string. sqlite3 raises
    ProgrammingError on a dict or list, which surfaced as a 500."""
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int) and abs(v) > 2 ** 62:
        # sqlite3 raises OverflowError binding an int this large.
        return None
    return str(v)[:limit]


def _str_list(v, limit=500, max_items=200):
    """A list of plain strings, or an empty list. Anything else -- a bare
    string, a dict, nested lists, 10,000 items -- is not what these fields
    are, and json.dumps would happily store the nonsense for every later
    reader to trip over."""
    if not isinstance(v, list):
        return []
    out = []
    for item in v[:max_items]:
        s = _text(item, limit)
        if s is not None and s.strip():
            out.append(s.strip())
    return out


# Every free-text column on `entries`. All of these were bound straight from
# the request body, so a JSON object or array in any one of them raised
# sqlite3.ProgrammingError mid-INSERT -- a 500 to the caller and, before the
# teardown rollback in app.py, a poisoned connection that blocked every
# write in the application.
ENTRY_TEXT_FIELDS = (
    "site", "setting", "otherSettingType", "hospitalNumber", "age", "sex",
    "laterality", "role", "consultant", "consultantUsername", "assistants",
    "comments", "caseReport", "history", "examination", "academicType",
    "academicTypeOther", "seminarType", "seminarTypeOther", "topic", "venue",
    "details",
)
# Short identifiers get a short cap; the narrative fields get a generous one.
# Nothing here should ever hold a pasted PDF, and a 2MB "topic" is a row the
# entries table then has to carry into every list, export and drill-down.
ENTRY_FIELD_LIMITS = {
    "site": 60, "setting": 60, "otherSettingType": 120, "hospitalNumber": 60,
    "age": 20, "sex": 30, "laterality": 30, "role": 120, "consultant": 120,
    "consultantUsername": 100, "assistants": 500, "academicType": 120,
    "academicTypeOther": 120, "seminarType": 120, "seminarTypeOther": 120,
    "topic": 300, "venue": 200,
    "comments": 8000, "caseReport": 20000, "history": 8000,
    "examination": 8000, "details": 8000,
}
ENTRY_LIST_FIELDS = ("procedures", "diagnoses", "diagnosesSecondary", "comorbidities")


def _sanitise_entry_body(body):
    """Normalise an entry payload in place, so every later use of it binds
    cleanly. Coerces rather than rejects: a trainee mid-list should not lose
    a case because one field arrived in an odd shape."""
    if not isinstance(body, dict):
        return {}
    for k in ENTRY_TEXT_FIELDS:
        if k in body:
            body[k] = _text(body[k], ENTRY_FIELD_LIMITS.get(k, 20000))
    for k in ENTRY_LIST_FIELDS:
        if k in body:
            body[k] = _str_list(body[k])
    return body


def _linked_entry_id(db, raw, author):
    """A case may be linked to one of the author's OWN operative records.

    Previously bound straight through, so a non-existent id raised a
    FOREIGN KEY violation (a 500), and any existing id was accepted --
    including another trainee's, which would have attached one person's
    case write-up to another person's operation.
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        eid = int(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    row = db.execute("SELECT author_username FROM entries WHERE id = ?", (eid,)).fetchone()
    if not row or row["author_username"] != author:
        return None
    return eid


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
# A combined case is two or three sites. Anything near this is a mistake or
# a script, and each block is rendered as its own card in the wizard.
MAX_PROCEDURE_BLOCKS = 12


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
        # The version the client must send back when it saves.
        "rowVersion": d.get("row_version") or 1,
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
        "approvalState": d.get("approval_state") or "not_submitted",
        "approverUsername": d.get("approver_username"),
        "status": d.get("status") or "final",
    }


# Fields excluded from the edit-history diff: identity/authorship never
# changes, and createdAt is set once at insert and never touched by an edit.
# rowVersion and the lock columns are transport, not content -- without
# this every save would log "rowVersion changed 3 -> 4" as an edit.
ENTRY_HISTORY_IGNORE = {"id", "authorUsername", "createdAt", "rowVersion", "lock"}

# ---------------------------------------------------------- approvals
# Only operative records and case write-ups are signed off. Academic and
# Seminar entries are the trainee's own attendance record; nobody attests
# to them.
APPROVABLE_TYPES = {"surgical", "other", "case"}
APPROVAL_STATES = {"not_submitted", "pending", "changes_requested", "approved"}

# Changing one of these invalidates an approval, because it changes what the
# consultant attested to. Everything else does not.
#
# This list is load-bearing, not cosmetic. paperStatus is PATCHed straight
# from a dropdown in the entries list -- if *any* edit reopened approval, a
# case would bounce back to the consultant every time a PG ticked off their
# write-up, and the queue would become noise within a week.
# Never content: these are transport, not part of the record.
NON_CONTENT_FIELDS = {"rowVersion"}

MATERIAL_FIELDS = {
    "procedureBlocks",          # site, procedures, laterality, entrustment level
    "date", "unit",
    "consultant", "consultantUsername",
    "diagnoses", "diagnosesSecondary", "comorbidities",
    "hospitalNumber", "age", "sex",
    "setting", "otherSettingType",
    "history", "examination", "caseReport",   # the substance of a case write-up
}
# Deliberately NOT material: comments, paperStatus, assistants, linkedFromId.
# assistants is the closest call -- it is a factual record of who was in the
# room -- but changing it does not alter what was attested to.


def approval_escalation_days():
    try:
        v = int(get_config().get("approvalEscalationDays", 7))
        return v if v > 0 else 7
    except (TypeError, ValueError):
        return 7


def _max_edit_id(db, entry_id):
    """MAX(entry_edits.id) right now. Stored on each approval row so an
    approval is pinned to a *version* of the entry rather than to the entry."""
    r = db.execute("SELECT COALESCE(MAX(id), 0) m FROM entry_edits WHERE entry_id = ?", (entry_id,)).fetchone()
    return r["m"] if r else 0


def _log_approval(db, entry_id, action, actor, comment=None,
                  approver_username=None, on_behalf_of=None):
    db.execute(
        "INSERT INTO entry_approvals (entry_id, action, actor_username, actor_role,"
        " approver_username, on_behalf_of, comment, edits_at_action, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (entry_id, action, actor["username"], actor.get("role"),
         approver_username, on_behalf_of, _text(comment, 4000),
         _max_edit_id(db, entry_id), datetime.datetime.utcnow().isoformat() + "Z"),
    )


def _delegate_for(user, entry_row):
    """A Head of Unit for this entry's unit, a Coordinator or the HOD may act
    when the nominated consultant cannot. Without this, one consultant
    leaving the department strands every pending record naming them, for
    good. Recorded as a delegate action, never as the consultant's own.
    """
    if user["role"] != "consultant":
        return False
    caps = user_capabilities(user["username"])
    if caps["isHod"] or caps["isCoordinator"]:
        return True
    if caps["isHeadOfUnit"]:
        return entry_row["unit"] in consultant_scope(user["username"])["units"]
    return False


def _can_decide(user, entry_row):
    """(allowed, on_behalf_of). A trainee can never approve -- not their own
    record, not anyone's, regardless of who is set as approver."""
    if user["role"] != "consultant":
        return False, None
    if entry_row["approver_username"] == user["username"]:
        return True, None
    if _delegate_for(user, entry_row):
        return True, entry_row["approver_username"]
    return False, None


def _valid_approver(db, username):
    if not isinstance(username, str) or not username:
        return None
    return db.execute(
        "SELECT username FROM users WHERE username = ? AND role = 'consultant'"
        " AND active = 1 AND approval_status = 'approved'", (username,)
    ).fetchone()


# Sentinel for "clear the approver", distinct from approver=None meaning
# "leave it as it is". Without it, withdraw asked for the column to be
# cleared and silently changed nothing, so a withdrawn record went on naming
# a consultant in the entries list and in every export -- "with Dr X" for a
# record that is with nobody.
CLEAR_APPROVER = "__clear__"


def _set_approval(db, entry_id, state, approver=None):
    if approver is CLEAR_APPROVER:
        db.execute("UPDATE entries SET approval_state = ?, approver_username = NULL WHERE id = ?",
                   (state, entry_id))
    elif approver is None:
        db.execute("UPDATE entries SET approval_state = ? WHERE id = ?", (state, entry_id))
    else:
        db.execute("UPDATE entries SET approval_state = ?, approver_username = ? WHERE id = ?",
                   (state, approver, entry_id))

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


def _consultant_may_see_user(db, consultant, target):
    """The same rule the roster uses: full scope sees everyone; a
    unit-scoped consultant sees a trainee posted to (or logging in) one of
    their units, and a consultant whose home unit is one of theirs."""
    scope = consultant_scope(consultant)
    if scope["full"]:
        return True
    units = set(scope["units"])
    if not units:
        return False
    row = db.execute("SELECT role, unit FROM users WHERE username = ?", (target,)).fetchone()
    if not row:
        return False
    if row["role"] in ("consultant", "developer"):
        return bool(row["unit"] and row["unit"] in units)
    seen = {r["unit"] for r in db.execute(
        "SELECT DISTINCT unit FROM postings WHERE username = ?", (target,))}
    seen |= {r["unit"] for r in db.execute(
        "SELECT DISTINCT unit FROM entries WHERE author_username = ?", (target,))}
    return bool(seen & units)


def is_assignment_active(a):
    """Is this appointment in force today?

    Compared by DATE, in the server's local timezone, with the end date
    inclusive. Two bugs sat in the old string comparison of the full
    timestamp against datetime.utcnow():

    1. The frontend sends a <input type="datetime-local"> value, which is
       the admin's own wall clock with no timezone on it. Comparing that to
       UTC put every appointment out by the local offset -- in IST, a Head
       of Unit appointed "from now" had no scope at all for five and a half
       hours, and kept it for five and a half hours after it lapsed.
    2. A date-only end of "2026-09-25" lost to "2026-09-25T04:11:07Z" from
       one minute past midnight, so an appointment ending today expired a
       day early.

    Taking the first 10 characters handles both the date-only and the
    datetime-local shapes, and an appointment measured in whole days is
    what these actually are -- nobody appoints a Head of Unit until 4pm.
    """
    today = datetime.date.today().isoformat()
    start = (a.get("start_at") or "")[:10]
    end = (a.get("end_at") or "")[:10]
    if start and start > today:
        return False
    if end and end < today:
        return False
    return True


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
    # Every one of these was taken on trust, so a number where a string
    # belonged raised TypeError/AttributeError -- a 500 on an endpoint
    # anyone who can load the sign-in page can reach.
    username = clean_username(_text(body.get("username"), 100))
    password = _text(body.get("password"), 200) or ""
    confirm = _text(body.get("confirm"), 200) or ""
    display_name = (_text(body.get("displayName"), 120) or username).strip()
    raw_role = _text(body.get("role"), 40)
    role = raw_role if raw_role in (TRAINEE_ROLES | {"consultant"}) else "resident"

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
    unit = _text(body.get("unit"), 60) if final_role in ("consultant", "fellow") else None
    if final_role == "fellow" and not unit:
        return jsonify({"error": "Fellows must select a parent unit at sign-up."}), 400
    if unit and (not isinstance(unit, str) or unit not in known_unit_keys()):
        return bad_unit_response(unit)

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
    # A tombstoned account is checked FIRST, before the password. Its hash
    # was destroyed, so no password can ever match it, and without this the
    # person is told "Incorrect password" and left trying variations of a
    # password that was correct -- when what they need to know is that the
    # account was closed and that their records can be brought back. There
    # is no secret being protected here: the login no longer exists.
    if _lifecycle_of(row) == LIFECYCLE_DELETED:
        return jsonify({
            "error": "This account has been closed. If that was a mistake, ask your "
                     "Developer admin -- their copy of your records can be restored.",
        }), 403

    # Every other state is decided only AFTER the password is verified, so
    # the different messages below cannot tell someone which state an
    # account is in without knowing its password.
    if not verify_password(row["password_hash"], password):
        record_attempt(rl_key_ip)
        record_attempt(rl_key_account)
        return jsonify({"error": "Incorrect password."}), 401

    lifecycle = _lifecycle_of(row)
    if lifecycle == LIFECYCLE_PENDING_DELETION:
        req = _open_request(db, username, "delete")
        when = (req["scheduled_for"] or "")[:10] if req else ""
        return jsonify({
            "error": "This account is scheduled to close%s. Ask the Head of Department or "
                     "your Developer admin to cancel it if that is not what you want."
                     % ((" on " + when) if when else ""),
        }), 403
    if not row["active"]:
        if lifecycle == LIFECYCLE_SELF:
            # Switched off by the person themselves -- signing in is how they
            # switch it back on, which is the whole point of that option.
            db.execute(
                "UPDATE users SET active = 1, lifecycle = ?, lifecycle_reason = NULL,"
                " lifecycle_at = ?, lifecycle_by = ? WHERE username = ?",
                (LIFECYCLE_ACTIVE, _now_iso(), username, username))
            _account_event(db, username, "self_reactivated", username, None)
            db.commit()
            row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        else:
            return jsonify({"error": "This account has been deactivated. Ask your Developer admin to reactivate it."}), 403
    if row["approval_status"] == "pending":
        return jsonify({"error": "Your account is still awaiting approval from a Head of Department, Course Coordinator, Head of Unit, or Developer."}), 403
    if require_role and row["role"] != require_role:
        return jsonify({"error": f"This account is not a {require_role} account."}), 403

    token = create_session(username)
    db.execute("UPDATE users SET last_seen_at = ? WHERE username = ?", (_now_iso(), username))
    db.commit()
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
    old = _text(body.get("oldPassword"), 200) or ""
    new = _text(body.get("newPassword"), 200) or ""
    confirm = _text(body.get("confirm"), 200) or ""
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
    username = clean_username(_text(body.get("username"), 100))
    note = (_text(body.get("note"), 2000) or "").strip()
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
    if not isinstance(unit, str) or unit not in known_unit_keys():
        return bad_unit_response(unit)
    if not _iso_date_or_none(start_date):
        return jsonify({"error": "Start date must be a real date (YYYY-MM-DD)."}), 400
    if end_date and not _iso_date_or_none(end_date):
        return jsonify({"error": "End date must be a real date (YYYY-MM-DD)."}), 400
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
    body = _sanitise_entry_body(request.get_json(force=True, silent=True) or {})
    entry_type = body.get("entryType")
    if not isinstance(entry_type, str) or entry_type not in ENTRY_TYPES:
        return jsonify({"error": "Unknown entry type."}), 400
    entry_date = _iso_date_or_none(body.get("date")) or datetime.date.today().isoformat()
    unit = _resolve_unit_for_entry(g.user["username"], entry_date)
    now = datetime.datetime.utcnow().isoformat() + "Z"

    db = get_db()
    linked_from_id = _linked_entry_id(db, body.get("linkedFromId"), g.user["username"])
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
            if len(blocks) > MAX_PROCEDURE_BLOCKS:
                return jsonify({"error": "At most %d sites on one record." % MAX_PROCEDURE_BLOCKS}), 400
            procedure_blocks_json = json.dumps([_clean_procedure_block(b) for b in blocks])

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
            "[]" if entry_type in PROCEDURE_BLOCK_TYPES else json.dumps(_str_list(body.get("procedures"))),
            body.get("setting"), body.get("otherSettingType"), body.get("hospitalNumber"),
            body.get("age"), body.get("sex"), json.dumps(_str_list(body.get("diagnoses"))),
            json.dumps(_str_list(body.get("diagnosesSecondary"))), json.dumps(_str_list(body.get("comorbidities"))),
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
    if d["author_username"] == g.user["username"]:
        return jsonify({"entry": entry_row_to_dict(row)})
    # A draft belongs to nobody but its author -- not to a developer and not
    # to an HOD. Ids are sequential, so without this the whole department's
    # unfinished entries are enumerable one GET at a time.
    if d.get("status") == "draft":
        return jsonify({"error": "forbidden"}), 403
    if g.user["role"] == "developer":
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
    row = db.execute("SELECT author_username, approval_state FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    if row["author_username"] != g.user["username"] and g.user["role"] != "developer":
        return jsonify({"error": "forbidden"}), 403
    # Nobody hard-deletes an attested record -- not the author, not a
    # developer. entry_approvals is ON DELETE CASCADE, so a delete here does
    # not just remove the case: it removes the consultant's signature and the
    # whole audit trail proving the case was ever signed. That is the one
    # thing this feature exists to make impossible to lose. A developer who
    # genuinely needs the record gone releases it first (which is itself
    # logged, on the approving consultant's authority) and then deletes.
    if row["approval_state"] == "approved":
        return jsonify({
            "error": "approved_record_locked",
            "detail": "This record has been signed off and cannot be deleted. The "
                      "approving consultant (or a Head of Unit / Coordinator / HOD) "
                      "must release it first.",
        }), 409
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

    body = _sanitise_entry_body(request.get_json(force=True, silent=True) or {})
    # A developer may fix a trainee's finalised entry, but a draft is the
    # trainee's own unfinished workspace -- GET and the history endpoint
    # both refuse it to everyone but the author, and PATCH has to agree.
    # An empty-body PATCH returns the whole entry, so without this it was a
    # read of someone's draft dressed up as a write.
    if existing["status"] == "draft" and existing["author_username"] != g.user["username"]:
        return jsonify({"error": "forbidden"}), 403

    # Somebody else is in this record right now.
    held = _lock_info(db, existing)
    if held and held["username"] != g.user["username"]:
        return jsonify({
            "error": "entry_locked",
            "lock": held,
            "detail": "%s has had this record open since %s. Your changes were not saved."
                      % (held["displayName"], held["since"][11:16]),
        }), 423

    # Optimistic concurrency. The client sends the version it loaded; if the
    # row has moved since, the edit was composed against a copy that no
    # longer exists and saving it would silently discard whatever happened in
    # between -- and, worse, entry_edits would then record a change that the
    # stored row does not have. Refuse and let the caller reload.
    #
    # Omitting rowVersion is still accepted, so an older client (or a
    # scripted call) keeps working; it simply forfeits the protection.
    if "rowVersion" in body:
        try:
            sent = int(body.get("rowVersion"))
        except (TypeError, ValueError):
            sent = None
        current = existing["row_version"] if "row_version" in existing.keys() else 1
        if sent is None or sent != current:
            return jsonify({
                "error": "stale_edit",
                "rowVersion": current,
                "detail": "This record changed while you were editing it. Reopen it to see "
                          "the current version before saving again.",
            }), 409
        body.pop("rowVersion", None)
    # An approved record is locked. The consultant attested to a specific
    # version of it; letting the author rewrite it underneath that signature
    # is the whole reason the lock exists. Only the approver or a delegate
    # can release it, and releasing returns it to changes_requested so the
    # author knows it needs resubmitting.
    #
    # paperStatus is exempt: it is the PG's own write-up tracker, set from a
    # dropdown in the entries list, and has nothing to do with what was
    # signed off. Locking it would make the tracker unusable on exactly the
    # cases most likely to become papers.
    if (existing["approval_state"] == "approved"
            and existing["author_username"] == g.user["username"]
            and set(body) - {"paperStatus"}):
        return jsonify({
            "error": "approved_record_locked",
            "detail": "This record has been approved and is locked. Ask the approving "
                      "consultant to release it before editing.",
        }), 409
    entry_type = body.get("entryType") or existing["entry_type"]
    if not isinstance(entry_type, str) or entry_type not in ENTRY_TYPES:
        return jsonify({"error": "Unknown entry type."}), 400
    # create_entry has always validated this; PATCH never did. A junk date
    # stored here is not a cosmetic problem: /reminders takes
    # MAX(entry_date), which is a STRING max, so "not-a-date" outranks every
    # real date and date.fromisoformat() then raises on it -- the author's
    # dashboard 500s on every load from that moment on, and they cannot get
    # back to the entry to fix it. Reject rather than silently drop, so the
    # caller knows the edit did not take.
    if "date" in body and body.get("date") is not None:
        cleaned_date = _iso_date_or_none(body.get("date"))
        if not cleaned_date:
            return jsonify({"error": "That date is not a real calendar date (use YYYY-MM-DD)."}), 400
        body["date"] = cleaned_date
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
            if len(blocks_raw) > MAX_PROCEDURE_BLOCKS:
                return jsonify({"error": "At most %d sites on one record." % MAX_PROCEDURE_BLOCKS}), 400
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
            "[]" if is_block_type else json.dumps(_str_list(body.get("procedures", before["procedures"]))),
            body.get("setting", before["setting"]), body.get("otherSettingType", before["otherSettingType"]),
            body.get("hospitalNumber", before["hospitalNumber"]),
            body.get("age", before["age"]), body.get("sex", before["sex"]),
            json.dumps(_str_list(body.get("diagnoses", before["diagnoses"]))),
            json.dumps(_str_list(body.get("diagnosesSecondary", before["diagnosesSecondary"]))),
            json.dumps(_str_list(body.get("comorbidities", before["comorbidities"]))),
            None if is_block_type else body.get("laterality", existing["laterality"]),
            None if is_block_type else body.get("role", existing["role_level"]),
            body.get("consultant", before["consultant"]),
            body.get("consultantUsername", before["consultantUsername"]),
            body.get("assistants", before["assistants"]), body.get("comments", before["comments"]),
            body.get("caseReport", before["caseReport"]),
            (_linked_entry_id(db, body["linkedFromId"], existing["author_username"])
             if "linkedFromId" in body else before["linkedFromId"]),
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
    # Bump the version on every successful write, so the next save composed
    # against the copy this one just replaced is refused rather than
    # silently overwriting it.
    db.execute("UPDATE entries SET row_version = COALESCE(row_version, 1) + 1 WHERE id = ?", (entry_id,))

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
        # A material edit to a record that was already out for review, or
        # already approved, sends it back automatically. Not via a dialog:
        # a record must never sit there claiming an approval it no longer
        # has while the author decides whether to resubmit.
        material = sorted(set(changes) & MATERIAL_FIELDS)
        if material and existing["approval_state"] in ("pending", "approved"):
            _log_approval(db, entry_id, "reopened_by_edit", g.user,
                          comment="Material change to: " + ", ".join(material))
            _set_approval(db, entry_id, "pending")
            after["approvalState"] = "pending"
    db.commit()
    return jsonify({"entry": after})


def _can_view_entry_history(user, entry_row):
    if user["username"] == entry_row["author_username"]:
        return True
    # entry_edits.changes holds the full old/new value of every field, so a
    # draft's history is the draft. Same rule as get_entry.
    if (entry_row["status"] if "status" in entry_row.keys() else "final") == "draft":
        return False
    if user["role"] == "developer":
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
    # status is needed by _can_view_entry_history -- without it the draft
    # guard there silently falls through to "final".
    entry_row = db.execute("SELECT author_username, unit, status FROM entries WHERE id = ?", (entry_id,)).fetchone()
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
    # Postings travel with the user. The roster's "Current unit" column has
    # always read them off user.postings, and row_to_user has never carried
    # them, so that column has shown a dash for every trainee since it was
    # written.
    #
    # One grouped query rather than get_postings() per row: this endpoint
    # already loads every entry in the department, and a per-trainee query
    # on top of that is the kind of N+1 that only shows up once the
    # department is a few years old.
    postings_by_user = {}
    for r in db.execute(
        "SELECT username, id, unit, start_date, end_date FROM postings ORDER BY username, start_date"
    ):
        postings_by_user.setdefault(r["username"], []).append(
            {"id": r["id"], "unit": r["unit"], "startDate": r["start_date"], "endDate": r["end_date"]}
        )

    today = datetime.date.today().isoformat()
    allowed_units = set(scope["units"])

    roster = []
    for u in users:
        all_postings = postings_by_user.get(u["username"], [])
        mine = [e for e in all_entries if e["authorUsername"] == u["username"]]

        if scope["full"]:
            visible_postings = all_postings
            include = True
        else:
            # Membership follows POSTINGS, not entries. A trainee rotating
            # through this unit belongs on its Head of Unit's roster from the
            # day the posting exists, whether or not they have logged
            # anything yet -- "nobody has logged a case this month" is
            # exactly what a roster is for showing. Past postings keep them
            # listed; a future one lists them as upcoming.
            #
            # Entries in scope still count as well, so a record that somehow
            # carries this unit without a matching posting is never orphaned
            # out of the only view that would surface it.
            visible_postings = [p for p in all_postings if p["unit"] in allowed_units]
            include = bool(visible_postings or mine)

        if not include:
            continue

        # Where they are TODAY, computed from every posting regardless of
        # scope and sent as a bare unit key. Deliberate: a Head of Unit is
        # told where a trainee currently is (so the department knows who is
        # where) without being handed their whole rotation history, which
        # `visible_postings` withholds.
        current = unit_for_date(all_postings, today)

        roster.append({
            "user": row_to_user(u),
            "postings": visible_postings,
            "currentUnit": current,
            "entries": mine,
        })
    return jsonify({"roster": roster, "scope": scope, "today": today})


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
                posting_units = {
                    r["unit"] for r in db.execute(
                        "SELECT DISTINCT unit FROM postings WHERE username = ?", (username,)
                    ).fetchall()
                }
                # A posting into this unit is enough on its own: the roster
                # now lists trainees by posting, so every row it shows has to
                # be openable, including one who has logged nothing yet.
                in_scope = bool((entry_units | posting_units) & set(scope["units"]))
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

    # Scope the ENTRIES, not just the door. This previously checked whether
    # the caller could open the trainee at all and then returned every entry
    # that trainee had ever logged -- so a Head of Unit who could see one
    # case of theirs could read their rotations through every other unit
    # too. A unit-scoped consultant sees only what was logged under a unit
    # they oversee, which (because an entry's unit is stamped from the
    # posting covering its date) is exactly the trainee's postings in their
    # unit and nothing else.
    postings = get_postings(username)
    if (g.user["username"] != username and g.user["role"] == "consultant"):
        scope = consultant_scope(g.user["username"])
        if not scope["full"]:
            allowed = set(scope["units"])
            entries = [e for e in entries if e["unit"] in allowed]
            postings = [p for p in postings if p["unit"] in allowed]
    return jsonify({"entries": entries, "postings": postings})


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
    ("approvalState", "Approval"),
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


# Stable machine keys for the column picker. The key is what the client
# sends; the pair is the same (getter, label) shape _export_csv already
# takes. Kept separate from ENTRY_EXPORT_COLUMNS so the fixed "everything"
# export keeps working byte-for-byte if this list is ever reordered.
EXPORT_COLUMN_CATALOGUE = [
    ("date",        ("date", "Date")),
    ("author",      ("authorUsername", "Resident")),
    ("type",        ("entryType", "Type")),
    ("unit",        ("unit", "Unit")),
    ("approval",    ("approvalState", "Approval")),
    ("site",        ("site", "Site")),
    ("procedures",  (_joined("procedures"), "Procedures")),
    ("hospitalNumber", ("hospitalNumber", "Hospital Number")),
    ("age",         ("age", "Age")),
    ("sex",         ("sex", "Sex")),
    ("diagnoses",   (_joined("diagnoses"), "Primary Diagnoses")),
    ("diagnosesSecondary", (_joined("diagnosesSecondary"), "Secondary Diagnoses")),
    ("comorbidities", (_joined("comorbidities"), "Comorbidities")),
    ("laterality",  ("laterality", "Side")),
    ("setting",     ("setting", "Emergency/Elective")),
    ("role",        ("role", "Role/Entrustment")),
    ("consultant",  ("consultant", "Consultant")),
    ("assistants",  ("assistants", "Assistants")),
    ("otherSettingType", ("otherSettingType", "Other-procedure setting")),
    ("history",     ("history", "Brief History")),
    ("examination", ("examination", "Examination Findings")),
    ("caseReport",  ("caseReport", "Case Report")),
    ("academicType", ("academicType", "Academic Type")),
    ("seminarType", ("seminarType", "Seminar Type")),
    ("topic",       ("topic", "Topic")),
    ("venue",       ("venue", "Venue")),
    ("details",     ("details", "Details")),
    ("comments",    ("comments", "Comments/Complications")),
    ("paperStatus", ("paperStatus", "Paper Status")),
]
EXPORT_COLUMN_MAP = dict(EXPORT_COLUMN_CATALOGUE)
EXPORT_COLUMN_ORDER = [k for k, _ in EXPORT_COLUMN_CATALOGUE]


def _visible_entry_rows(db, user):
    """Every entry this user is already allowed to see, drafts excluded.

    Shared by the fixed export and the custom one so a filter can never be
    the thing that decides what someone may read -- the scope is applied
    first, and filters only ever narrow what is already permitted.
    """
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
            "SELECT * FROM entries WHERE author_username = ? ORDER BY entry_date DESC, id DESC",
            (user["username"],),
        ).fetchall()
    return [e for e in (entry_row_to_dict(r) for r in rows) if e["status"] != "draft"]


def _csv_list_arg(name):
    raw = request.args.get(name) or ""
    return [v for v in (p.strip() for p in raw.split(",")) if v]


@api.get("/entries/export/custom.csv")
@login_required()
def export_custom_csv():
    """The export builder: the caller picks which entries (rows) and which
    fields (columns). Everything is a narrowing of _visible_entry_rows, so
    no combination of parameters can widen what the caller may read.

    Unknown column keys are ignored rather than rejected: a saved selection
    in someone's browser should keep working after a column is renamed,
    minus that column, instead of failing the whole download.
    """
    db = get_db()
    rows = _visible_entry_rows(db, g.user)

    types = set(_csv_list_arg("types"))
    units = set(_csv_list_arg("units"))
    approvals = set(_csv_list_arg("approval"))
    authors = set(_csv_list_arg("authors"))
    date_from = (request.args.get("from") or "").strip()
    date_to = (request.args.get("to") or "").strip()

    def keep(e):
        if types and e.get("entryType") not in types:
            return False
        # "__none__" is how the picker asks for entries with no unit: an
        # empty string in a query parameter is indistinguishable from an
        # unset filter, so it cannot be sent literally.
        if units and (e.get("unit") or "__none__") not in units:
            return False
        # Only operative records and case write-ups carry an approval state;
        # filtering by it would otherwise silently drop every academic and
        # seminar entry the moment someone ticks "Approved".
        if approvals and e.get("entryType") in APPROVABLE_TYPES and (e.get("approvalState") or "not_submitted") not in approvals:
            return False
        if authors and e.get("authorUsername") not in authors:
            return False
        d = e.get("date") or ""
        if date_from and d < date_from:
            return False
        if date_to and d > date_to:
            return False
        return True

    rows = [e for e in rows if keep(e)]

    picked = [k for k in _csv_list_arg("columns") if k in EXPORT_COLUMN_MAP]
    if not picked:
        picked = EXPORT_COLUMN_ORDER
    # Column ORDER follows the catalogue, not the order the checkboxes were
    # ticked in -- two people exporting the same fields get the same file,
    # which is what makes the outputs comparable.
    picked = [k for k in EXPORT_COLUMN_ORDER if k in set(picked)]
    columns = [EXPORT_COLUMN_MAP[k] for k in picked]

    csv_text = _export_csv(rows, columns)
    filename = f"ent-logbook-{g.user['username']}-{datetime.datetime.utcnow().strftime('%Y%m%d')}.csv"
    return Response(csv_text, mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


@api.get("/entries/export/options")
@login_required()
def export_options():
    """What the picker can offer THIS caller: the column catalogue, plus the
    units and authors actually present in what they can see (a trainee gets
    only themselves, so the author filter is hidden for them)."""
    db = get_db()
    rows = _visible_entry_rows(db, g.user)
    units = sorted({e.get("unit") or "" for e in rows})
    authors = sorted({e.get("authorUsername") for e in rows if e.get("authorUsername")})
    return jsonify({
        "columns": [{"key": k, "label": EXPORT_COLUMN_MAP[k][1]} for k in EXPORT_COLUMN_ORDER],
        "units": [u for u in units if u],
        "hasUnattributed": "" in units,   # rendered as the "__none__" sentinel
        "authors": [{"username": a, "displayName": _display_name(db, a)} for a in authors],
        "total": len(rows),
    })


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
    # approval_status as well as active: an unapproved sign-up is not a
    # consultant yet, and this list is what every trainee's "send for
    # sign-off" picker is built from. Without it, anyone who can reach the
    # public sign-up page could put a display name of their choosing in
    # front of the whole department. _valid_approver refused the actual
    # submit, so this was disclosure rather than a way in -- but it is the
    # sort of thing that gets noticed in a demo.
    rows = get_db().execute(
        "SELECT * FROM users WHERE role = 'consultant' AND active = 1"
        " AND approval_status = 'approved' ORDER BY display_name"
    ).fetchall()
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
    # The one consultant-facing read with no scope check: a consultant with
    # no assignment and no Professor designation -- who gets an empty
    # roster, 403 on every drill-down and a zero-row export -- could still
    # read any account in the department by name, the developer's included.
    # Scoped to match the roster it feeds.
    db = get_db()
    if g.user["username"] != username:
        if g.user["role"] == "developer":
            pass
        elif g.user["role"] == "consultant" and _consultant_may_see_user(db, g.user["username"], username):
            pass
        else:
            return jsonify({"error": "forbidden"}), 403
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
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
    if unit and (not isinstance(unit, str) or unit not in known_unit_keys()):
        return bad_unit_response(unit)
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
    target = db.execute("SELECT role FROM users WHERE username = ?", (username,)).fetchone()
    if not target:
        return jsonify({"error": "not_found"}), 404
    # Only a developer may touch a developer account. Without this an HOD
    # -- who has canManageProfiles -- could set active=false on the
    # developer and lock out the one role that can manage config, accounts
    # and role assignments. The role-change and password branches below
    # were already fenced this way; the profile branches above them were
    # not, and `active` is the one that locks someone out.
    if target["role"] == "developer" and not caps["isDeveloper"]:
        return jsonify({
            "error": "forbidden",
            "detail": "Only a Developer admin can change a Developer account.",
        }), 403
    if "active" in body:
        if not body["active"]:
            blocked = _last_developer_block(db, username, "Deactivating")
            if blocked:
                db.rollback()
                return blocked
        db.execute("UPDATE users SET active = ?, lifecycle = ?, lifecycle_at = ?, lifecycle_by = ?"
                   " WHERE username = ?",
                   (1 if body["active"] else 0,
                    LIFECYCLE_ACTIVE if body["active"] else LIFECYCLE_ADMIN,
                    _now_iso(), g.user["username"], username))
        _account_event(db, username, "activated" if body["active"] else "admin_deactivated",
                       g.user["username"], _text(body.get("reason"), 500))
        if not body["active"]:
            destroy_all_sessions_for(username)
    # Batch (PG Year) and designation -- the "dynamic profile changes" both
    # Developer and HOD were given (a resident moving up a batch, a
    # consultant getting promoted from Assistant to Associate Professor).
    if "pgYear" in body:
        db.execute("UPDATE users SET pg_year = ? WHERE username = ?", (_text(body.get("pgYear"), 80), username))
    # Designation is not merely descriptive: consultant_scope() grants a
    # Professor their home unit's entire roster and case records. That makes
    # writing it an access grant, and access grants in this app are
    # developer-only and recorded (POST /role-assignments carries assigned_by,
    # assigned_at and an end date). Leaving it open to an HOD gave the same
    # power through an unaudited, permanent side channel.
    if "designation" in body:
        if not caps["isDeveloper"]:
            db.rollback()
            return jsonify({
                "error": "forbidden",
                "detail": "Designation decides which units a consultant can see, so only "
                          "a Developer admin can change it.",
            }), 403
        db.execute("UPDATE users SET designation = ? WHERE username = ?", (_text(body.get("designation"), 80), username))
    # A Fellow's parent unit, or a consultant's home unit, can change too
    # (a Fellow reassigned, a consultant transferred) -- same gate as batch/
    # designation.
    if "unit" in body:
        new_unit = _text(body.get("unit"), 60) or None
        if new_unit is not None and (not isinstance(new_unit, str) or new_unit not in known_unit_keys()):
            db.rollback()
            return bad_unit_response(new_unit)
        db.execute("UPDATE users SET unit = ? WHERE username = ?", (new_unit, username))
    # Role changes and password resets stay Developer-only -- broader than
    # the specific batch/designation/delete powers HOD was given.
    if caps["isDeveloper"]:
        if "role" in body and _text(body["role"], 40) in (TRAINEE_ROLES | {"consultant", "developer"}):
            # Demoting the last developer empties the role just as surely as
            # deleting the account does.
            if _text(body["role"], 40) != "developer":
                blocked = _last_developer_block(db, username, "Changing the role of")
                if blocked:
                    db.rollback()
                    return blocked
            db.execute("UPDATE users SET role = ? WHERE username = ?", (_text(body["role"], 40), username))
        if "password" in body and body["password"]:
            if len(_text(body["password"], 200) or "") < 8:
                # Roll back first: the role/active/profile UPDATEs above have
                # already run on this thread-local connection, and without
                # this they are committed by whatever request lands next.
                db.rollback()
                return jsonify({"error": "New password must be at least 8 characters."}), 400
            db.execute("UPDATE users SET password_hash = ? WHERE username = ?", (hash_password(_text(body["password"], 200)), username))
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
    # Same reasoning as update_user: an HOD has canManageProfiles, and
    # without this could delete the Developer account outright.
    if row["role"] == "developer" and not caps["isDeveloper"]:
        return jsonify({
            "error": "Only a Developer admin can remove a Developer account.",
        }), 403
    blocked = _last_developer_block(db, username, "Deleting")
    if blocked:
        return blocked
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


# `procedures` is a map of site-key -> list. A plain cfg.update() replaces
# the WHOLE map, so a caller that sends only the site it changed silently
# deletes every other site's list. That is not hypothetical: it is how this
# department's catalogue was reduced to two ear procedures in production.
# The current frontend works around it by re-sending the entire map on every
# save, but "every call site must remember to send everything" is exactly
# the kind of contract that breaks the next time someone adds a call site.
# Merged per sub-key here instead, so the server is safe whatever arrives.
#
# A site's list is still removable -- send it explicitly as null (or remove
# its category, which drops the list with it) -- so this buys safety without
# making deletion impossible.
NESTED_CONFIG_KEYS = {"procedures"}


def _merge_config(cfg, body):
    for key, value in body.items():
        if key in NESTED_CONFIG_KEYS and isinstance(value, dict) and isinstance(cfg.get(key), dict):
            merged = dict(cfg[key])
            for sub, sub_value in value.items():
                if sub_value is None:
                    merged.pop(sub, None)
                else:
                    merged[sub] = sub_value
            cfg[key] = merged
        else:
            cfg[key] = value
    return cfg


def _prune_orphan_procedures(cfg):
    """A removed category leaves its procedure list behind forever, because
    removeCategory only ever patched `categories`. Dead weight on every
    read, and it reappears the moment someone re-creates a site with the
    same key."""
    cats = {c.get("key") for c in (cfg.get("categories") or []) if isinstance(c, dict)}
    procs = cfg.get("procedures")
    if isinstance(procs, dict) and cats:
        cfg["procedures"] = {k: v for k, v in procs.items() if k in cats}
    return cfg


CONFIG_LIST_KEYS = {
    "categories", "units", "diagnoses", "comorbidities", "roleLevels", "settings",
    "laterality", "pgYears", "academicTypes", "seminarTypes", "sexOptions",
    "otherProcedureSettings", "consultantDesignations", "deactivationReasons",
}


def _config_shape_error(body):
    """The config row is read by signup, postings, account creation, role
    assignments and the orphan report. A value of the wrong shape saved here
    took all of them down together, survived a restart, and could only be
    undone by another PATCH or a direct database edit -- so it is checked on
    the way in rather than defended against at every reader."""
    for key in CONFIG_LIST_KEYS:
        if key in body and not isinstance(body[key], list):
            return "%s must be a list." % key
    for key in ("units", "categories"):
        if key in body:
            for item in body[key]:
                if not isinstance(item, dict) or not isinstance(item.get("key"), str) or not item["key"]:
                    return "Every %s needs a key." % key[:-1]
    if "procedures" in body and not isinstance(body["procedures"], dict):
        return "procedures must be a map of site to list."
    if "approvalEscalationDays" in body:
        v = body["approvalEscalationDays"]
        if isinstance(v, bool) or not isinstance(v, int) or not (1 <= v <= 365):
            return "Escalation days must be a whole number between 1 and 365."
    return None


@api.patch("/config")
@login_required(role="developer")
def update_config():
    body = request.get_json(force=True, silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"error": "Malformed configuration."}), 400
    shape_error = _config_shape_error(body)
    if shape_error:
        return jsonify({"error": shape_error}), 400
    db = get_db()
    cfg = _prune_orphan_procedures(_merge_config(get_config(), body))
    db.execute("UPDATE config SET data = ? WHERE id = 'lists'", (json.dumps(cfg),))
    db.commit()
    return jsonify({"config": cfg})


@api.post("/config/restore-procedure-defaults")
@login_required(role="developer")
def restore_procedure_defaults():
    """Puts the shipped procedure lists back for any site that has lost them,
    without touching anything the department has added itself.

    Needed because the merge bug above already destroyed live data, and the
    only other way to repair it is typing sixty-odd procedures back in by
    hand through Manage Lists.
    """
    from db import DEFAULT_PROCEDURES

    db = get_db()
    cfg = get_config()
    procs = dict(cfg.get("procedures") or {})
    restored = {}
    for site, defaults in DEFAULT_PROCEDURES.items():
        existing = procs.get(site) or []
        # Union, not replace: a site the department has curated keeps its own
        # entries and gains back only the defaults that went missing.
        added = [p for p in defaults if p not in existing]
        if added:
            procs[site] = sorted(existing + added, key=lambda s: s.lower())
            restored[site] = len(added)
    cfg["procedures"] = procs
    db.execute("UPDATE config SET data = ? WHERE id = 'lists'", (json.dumps(cfg),))
    db.commit()
    return jsonify({"config": cfg, "restored": restored})


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


@api.get("/units/orphans")
@login_required(role="developer")
def unit_orphans():
    """Rows pointing at a unit key the department no longer has.

    Two ways to get here: a unit was deleted from Manage Lists while records
    still referenced it, or -- before the validation above existed -- someone
    posted a key that never existed. Entries with NO unit at all are counted
    separately: that is the ordinary "logged before adding a posting" case,
    not evasion, but it has the same effect on a Head of Unit's roster, so
    it is worth seeing.
    """
    db = get_db()
    known = known_unit_keys()
    unknown = {}

    def note(key, field, count):
        if key is None or key == "" or key in known:
            return
        unknown.setdefault(key, {"unit": key, "postings": 0, "entries": 0, "users": 0, "assignments": 0})
        unknown[key][field] += count

    for r in db.execute("SELECT unit, COUNT(*) c FROM postings GROUP BY unit"):
        note(r["unit"], "postings", r["c"])
    for r in db.execute("SELECT unit, COUNT(*) c FROM entries GROUP BY unit"):
        note(r["unit"], "entries", r["c"])
    for r in db.execute("SELECT unit, COUNT(*) c FROM users GROUP BY unit"):
        note(r["unit"], "users", r["c"])
    for r in db.execute("SELECT unit, COUNT(*) c FROM role_assignments GROUP BY unit"):
        note(r["unit"], "assignments", r["c"])

    unattributed = db.execute(
        "SELECT COUNT(*) c FROM entries WHERE (unit IS NULL OR unit = '') AND status = 'final'"
    ).fetchone()["c"]
    return jsonify({
        "orphans": sorted(unknown.values(), key=lambda o: -(o["entries"] + o["postings"])),
        "unattributedEntries": unattributed,
        "knownUnits": sorted(known),
    })


# =====================================================================
#  APPROVALS
#  Surgical Procedure, Other Procedure and Interesting Case only. A linked
#  case and its parent operation are two independent approvals of two
#  different documents -- approving one never approves the other.
# =====================================================================

def _display_name(db, username):
    if not username:
        return None
    r = db.execute("SELECT display_name FROM users WHERE username = ?", (username,)).fetchone()
    return (r["display_name"] if r else None) or username


def _account_state(db, username):
    """Shown next to a name wherever it appears -- on an operation record,
    in a sign-off history, on a roster. A closed or deactivated account's
    name has to keep appearing on the records it is part of (they are
    somebody else's evidence), so it is flagged instead of removed, and a
    name that is no longer in the users table at all is 'unknown' rather
    than silently ordinary."""
    if not username:
        return None
    r = db.execute("SELECT active, lifecycle FROM users WHERE username = ?", (username,)).fetchone()
    if not r:
        return "unknown"
    state = _lifecycle_of(r)
    if state == LIFECYCLE_DELETED:
        return "deleted"
    if state == LIFECYCLE_PENDING_DELETION:
        return "closing"
    if not r["active"]:
        return "deactivated"
    return "active"


# Every action that puts a record (back) in front of a consultant. The
# clock on "waiting N days" restarts at the latest of these, not at the
# original submission: a record submitted a month ago, approved, then
# reopened by an edit today has been with the consultant for a day, not
# thirty, and flagging it overdue on arrival is the one number a Head of
# Unit will look at first.
ARRIVES_IN_QUEUE = ("submitted", "reassigned", "reopened_by_edit", "released", "changes_requested")


def _waiting_since(history, fallback):
    for h in reversed(history):
        if h["action"] in ARRIVES_IN_QUEUE:
            return h["created_at"]
    return fallback


def _approval_history(db, entry_id):
    rows = db.execute(
        "SELECT action, actor_username, actor_role, approver_username, on_behalf_of,"
        " comment, created_at FROM entry_approvals WHERE entry_id = ? ORDER BY id ASC",
        (entry_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _days_since(iso):
    if not iso:
        return 0
    try:
        then = datetime.datetime.fromisoformat(str(iso).replace("Z", ""))
    except (ValueError, TypeError):
        return 0
    return max(0, (datetime.datetime.utcnow() - then).days)


def _submit_one(db, entry_id, approver, comment=None):
    """Returns (ok, error_dict, http_status)."""
    row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return False, {"error": "not_found"}, 404
    if row["author_username"] != g.user["username"]:
        return False, {"error": "forbidden"}, 403
    if row["entry_type"] not in APPROVABLE_TYPES:
        return False, {"error": "Only operative records and case write-ups are approved."}, 400
    if row["status"] != "final":
        return False, {"error": "Finish the entry before sending it for approval."}, 400
    if row["approval_state"] == "approved":
        return False, {"error": "Already approved."}, 409
    # Re-sending a record that is already waiting on someone. Silently
    # re-pointing it at a second consultant is how a trainee shops for a
    # signature: the first consultant's queue loses the record with no
    # notice and the trail reads as two ordinary submissions. Re-sending to
    # the SAME consultant is a no-op worth refusing outright; re-sending to a
    # different one is allowed (the nominated consultant may have left) but
    # is recorded as a reassignment naming both.
    if row["approval_state"] == "pending":
        if row["approver_username"] == approver:
            return False, {"error": "This record is already waiting with that consultant."}, 409
        _log_approval(db, entry_id, "reassigned", g.user,
                      comment="Moved from %s to %s%s" % (
                          row["approver_username"], approver,
                          (" — " + comment) if comment else ""),
                      approver_username=approver,
                      on_behalf_of=row["approver_username"])
        _set_approval(db, entry_id, "pending", approver)
        return True, None, 200
    _log_approval(db, entry_id, "submitted", g.user, comment=comment,
                  approver_username=approver)
    _set_approval(db, entry_id, "pending", approver)
    return True, None, 200


@api.post("/entries/<int:entry_id>/submit")
@login_required()
def submit_for_approval(entry_id):
    body = request.get_json(force=True, silent=True) or {}
    db = get_db()
    # The approver is nominated here rather than read off consultant_username:
    # that field is free text plus an OPTIONAL account, is frequently NULL,
    # and an Interesting Case has no consultant field at all. The free-text
    # consultant stays as the record of who supervised, which is not always
    # the same person who signs it off.
    approver = _valid_approver(db, body.get("approverUsername"))
    if not approver:
        return jsonify({"error": "Pick an active consultant to send this to."}), 400
    ok, err, code = _submit_one(db, entry_id, approver["username"], body.get("comment"))
    if not ok:
        db.rollback()
        return jsonify(err), code
    db.commit()
    return jsonify({"entry": entry_row_to_dict(
        db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone())})


def _entry_ids(raw_ids):
    """Only real, in-range integer ids. int(float('inf')) raises
    OverflowError and int(True) is 1, so a batch containing Infinity took
    the request down mid-loop and a batch containing `true` silently acted
    on entry 1."""
    out = []
    for raw in raw_ids:
        if isinstance(raw, bool) or isinstance(raw, float):
            continue
        try:
            eid = int(raw)
        except (TypeError, ValueError, OverflowError):
            continue
        if 0 < eid < 2 ** 62:
            out.append(eid)
    return out


@api.post("/entries/bulk-submit")
@login_required()
def bulk_submit_for_approval():
    """The back-catalogue path. Everything predating this feature is
    'not_submitted' by design -- dropping a department's history into its
    consultants' queues on day one is how the feature gets ignored -- so a
    PG opts their own history in, in batches."""
    body = request.get_json(force=True, silent=True) or {}
    ids = body.get("ids")
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "Pick at least one record."}), 400
    if len(ids) > 200:
        return jsonify({"error": "Send at most 200 records at a time."}), 400
    db = get_db()
    approver = _valid_approver(db, body.get("approverUsername"))
    if not approver:
        return jsonify({"error": "Pick an active consultant to send these to."}), 400
    done, skipped = [], []
    for eid in _entry_ids(ids):
        ok, err, _ = _submit_one(db, eid, approver["username"], body.get("comment"))
        (done if ok else skipped).append(
            eid if ok else {"id": eid, "reason": (err or {}).get("error")})
    db.commit()
    return jsonify({"submitted": done, "skipped": skipped})


@api.post("/entries/<int:entry_id>/withdraw")
@login_required()
def withdraw_from_approval(entry_id):
    db = get_db()
    row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    if row["author_username"] != g.user["username"]:
        return jsonify({"error": "forbidden"}), 403
    if row["approval_state"] not in ("pending", "changes_requested"):
        return jsonify({"error": "Nothing to withdraw."}), 409
    _log_approval(db, entry_id, "withdrawn", g.user)
    _set_approval(db, entry_id, "not_submitted", CLEAR_APPROVER)
    db.commit()
    return jsonify({"ok": True})


def _decide(entry_id, action, require_comment):
    body = request.get_json(force=True, silent=True) or {}
    comment = body.get("comment")
    if require_comment and not str(comment or "").strip():
        return jsonify({"error": "Say what needs changing."}), 400
    db = get_db()
    row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    allowed, on_behalf = _can_decide(g.user, row)
    if not allowed:
        return jsonify({"error": "forbidden"}), 403
    if row["approval_state"] == "approved" and action == "approved":
        # A second 'approved' row is a duplicate signature in the audit log
        # for a version nothing has changed about.
        return jsonify({"error": "This record is already signed off."}), 409
    if row["approval_state"] not in ("pending", "approved"):
        return jsonify({"error": "This record is not awaiting a decision."}), 409
    if action == "approved":
        _log_approval(db, entry_id, "approved", g.user, comment=comment, on_behalf_of=on_behalf)
        _set_approval(db, entry_id, "approved")
    else:
        _log_approval(db, entry_id, "changes_requested", g.user, comment=comment, on_behalf_of=on_behalf)
        _set_approval(db, entry_id, "changes_requested")
    db.commit()
    return jsonify({"entry": entry_row_to_dict(
        db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone())})


@api.post("/entries/<int:entry_id>/approve")
@login_required()
def approve_entry(entry_id):
    return _decide(entry_id, "approved", require_comment=False)


@api.post("/entries/<int:entry_id>/request-changes")
@login_required()
def request_changes_entry(entry_id):
    # A comment is required. "Changes requested" with no reason is worse than
    # no feedback: the trainee has to guess, and usually resubmits unchanged.
    return _decide(entry_id, "changes_requested", require_comment=True)


@api.post("/entries/bulk-approve")
@login_required()
def bulk_approve():
    """A consultant coming back to a rotation's worth of cases will not do
    thirty records at four taps each. Approve only -- requesting changes is
    per-record by definition, since it needs a reason."""
    body = request.get_json(force=True, silent=True) or {}
    ids = body.get("ids")
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "Pick at least one record."}), 400
    if len(ids) > 200:
        return jsonify({"error": "Approve at most 200 records at a time."}), 400
    db = get_db()
    done, skipped = [], []
    for eid in _entry_ids(ids):
        row = db.execute("SELECT * FROM entries WHERE id = ?", (eid,)).fetchone()
        if not row:
            skipped.append({"id": eid, "reason": "not_found"}); continue
        allowed, on_behalf = _can_decide(g.user, row)
        if not allowed:
            skipped.append({"id": eid, "reason": "forbidden"}); continue
        if row["approval_state"] != "pending":
            skipped.append({"id": eid, "reason": "not_pending"}); continue
        _log_approval(db, eid, "approved", g.user, comment=body.get("comment"), on_behalf_of=on_behalf)
        _set_approval(db, eid, "approved")
        done.append(eid)
    db.commit()
    return jsonify({"approved": done, "skipped": skipped})


@api.post("/entries/<int:entry_id>/release")
@login_required()
def release_entry(entry_id):
    """Unlock an approved record so its author can edit it again. Only the
    approver or a delegate -- the lock exists precisely so the author cannot
    do this themselves. Lands in changes_requested, not not_submitted, so the
    author sees it needs attention and resubmitting."""
    body = request.get_json(force=True, silent=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    allowed, on_behalf = _can_decide(g.user, row)
    if not allowed:
        return jsonify({"error": "forbidden"}), 403
    if row["approval_state"] != "approved":
        return jsonify({"error": "This record is not locked."}), 409
    _log_approval(db, entry_id, "released", g.user, comment=body.get("comment"), on_behalf_of=on_behalf)
    _set_approval(db, entry_id, "changes_requested")
    db.commit()
    return jsonify({"ok": True})


@api.post("/entries/<int:entry_id>/request-unlock")
@login_required()
def request_unlock(entry_id):
    """The author spotted an error in an approved, locked record. This only
    records the ask and surfaces it in the approver's queue -- it does not
    unlock anything."""
    body = request.get_json(force=True, silent=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    if row["author_username"] != g.user["username"]:
        return jsonify({"error": "forbidden"}), 403
    if row["approval_state"] != "approved":
        return jsonify({"error": "This record is not locked."}), 409
    # Same reasoning as request-changes: an unlock request with no reason
    # lands in a consultant's queue as a bare flag they have to chase.
    comment = str(body.get("comment") or "").strip()
    if not comment:
        return jsonify({"error": "Say what needs correcting."}), 400
    _log_approval(db, entry_id, "unlock_requested", g.user, comment=comment)
    db.commit()
    return jsonify({"ok": True})


@api.get("/entries/<int:entry_id>/approvals")
@login_required()
def entry_approval_history(entry_id):
    db = get_db()
    row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    allowed = (row["author_username"] == g.user["username"]
               or g.user["role"] == "developer")
    if not allowed:
        allowed, _ = _can_decide(g.user, row)
    if not allowed:
        return jsonify({"error": "forbidden"}), 403
    return jsonify({"approvals": _approval_history(db, entry_id)})


@api.get("/approvals/queue")
@login_required()
def approval_queue():
    """Records naming me as approver, plus anything I can act on as a
    delegate.

    Deliberately NOT filtered by consultant_scope(): a PG on a peripheral
    posting may legitimately nominate a consultant from another unit, and
    that consultant must still see it. This is a second, narrow visibility
    path -- entries naming this consultant as approver, and nothing else. It
    widens no other endpoint.
    """
    if g.user["role"] != "consultant":
        return jsonify({"error": "forbidden"}), 403
    db = get_db()
    caps = user_capabilities(g.user["username"])
    scope = consultant_scope(g.user["username"])
    rows = db.execute(
        "SELECT * FROM entries WHERE approval_state = 'pending' AND status = 'final'"
        " ORDER BY id ASC"
    ).fetchall()
    limit = approval_escalation_days()
    mine, delegated = [], []
    for r in rows:
        own = r["approver_username"] == g.user["username"]
        can_delegate = (not own) and (
            caps["isHod"] or caps["isCoordinator"]
            or (caps["isHeadOfUnit"] and r["unit"] in scope["units"]))
        if not own and not can_delegate:
            continue
        hist = _approval_history(db, r["id"])
        submitted_at = next((h["created_at"] for h in reversed(hist)
                             if h["action"] == "submitted"), r["created_at"])
        item = entry_row_to_dict(r)
        item["authorDisplayName"] = _display_name(db, r["author_username"])
        item["approverDisplayName"] = _display_name(db, r["approver_username"])
        item["submittedAt"] = submitted_at
        item["waitingDays"] = _days_since(submitted_at)
        item["overdue"] = item["waitingDays"] >= limit
        item["unlockRequested"] = any(h["action"] == "unlock_requested" for h in hist)
        item["onBehalfOf"] = None if own else r["approver_username"]
        (mine if own else delegated).append(item)
    return jsonify({"queue": mine, "delegated": delegated, "escalationDays": limit})


@api.get("/approvals/summary")
@login_required()
def approval_summary():
    """Counters. Shape depends on who is asking."""
    db = get_db()
    limit = approval_escalation_days()
    out = {"escalationDays": limit}
    types = "('surgical','other','case')"

    if g.user["role"] in TRAINEE_ROLES:
        counts = {s: 0 for s in APPROVAL_STATES}
        for r in db.execute(
            "SELECT approval_state st, COUNT(*) c FROM entries WHERE author_username = ?"
            " AND status = 'final' AND entry_type IN " + types + " GROUP BY approval_state",
            (g.user["username"],),
        ):
            counts[r["st"]] = r["c"]
        out["mine"] = counts

    if g.user["role"] == "consultant":
        caps = user_capabilities(g.user["username"])
        scope = consultant_scope(g.user["username"])
        pending = db.execute(
            "SELECT * FROM entries WHERE approval_state = 'pending' AND status = 'final'"
        ).fetchall()
        mine = [r for r in pending if r["approver_username"] == g.user["username"]]
        ages = []
        for r in mine:
            hist = _approval_history(db, r["id"])
            sub = _waiting_since(hist, r["created_at"])
            ages.append(_days_since(sub))
        out["queue"] = {
            "pending": len(mine),
            "oldestDays": max(ages) if ages else 0,
            "overdue": sum(1 for a in ages if a >= limit),
        }
        # Anything sitting past the threshold anywhere this consultant has
        # oversight of. In-app notification only reaches the nominated
        # consultant when they log in -- this is what stops a record waiting
        # indefinitely because one person is on leave.
        if caps["isHod"] or caps["isCoordinator"] or caps["isHeadOfUnit"]:
            overdue = []
            for r in pending:
                # An entry logged on a date no posting covers is stored with
                # an empty unit (see unit_for_date). It is nobody's unit, so
                # a Head of Unit would never see it here -- which is exactly
                # backwards: those are the records most likely to be
                # forgotten, and the HoU delegate route cannot act on them
                # either, so they must at least be visible to somebody with
                # oversight.
                unattributed = not (r["unit"] or "").strip()
                in_reach = (caps["isHod"] or caps["isCoordinator"]
                            or r["unit"] in scope["units"]
                            or unattributed)
                if not in_reach:
                    continue
                hist = _approval_history(db, r["id"])
                sub = _waiting_since(hist, r["created_at"])
                days = _days_since(sub)
                if days >= limit:
                    overdue.append({
                        "id": r["id"], "author": _display_name(db, r["author_username"]),
                        "unit": r["unit"],
                        "approver": _display_name(db, r["approver_username"]), "waitingDays": days,
                        "entryType": r["entry_type"], "date": r["entry_date"],
                    })
            overdue.sort(key=lambda o: -o["waitingDays"])
            out["unitOverdue"] = overdue[:50]
            out["unitOverdueTotal"] = len(overdue)
    return jsonify(out)


@api.post("/role-assignments")
@login_required(role="developer")
def add_role_assignment():
    body = request.get_json(force=True, silent=True) or {}
    db = get_db()
    target_username = clean_username(_text(body.get("consultantUsername"), 100))
    consultant = db.execute(
        "SELECT display_name, role FROM users WHERE username = ?", (target_username,)
    ).fetchone()
    if not consultant:
        return jsonify({"error": "No such consultant."}), 404
    # These appointments confer consultant-level oversight; giving one to a
    # trainee account would hand them their own cohort's records.
    if consultant["role"] != "consultant":
        return jsonify({"error": "Head of Unit, Coordinator and HOD appointments are for consultant accounts."}), 400
    assignment_role = _text(body.get("role"), 40)
    if assignment_role not in ("head_of_unit", "coordinator", "hod"):
        return jsonify({"error": "Role must be head_of_unit, coordinator or hod."}), 400
    # A Head of Unit assignment IS a unit scope, so an unrecognised key here
    # silently grants sight of nothing.
    assign_unit = _text(body.get("unit"), 60) or None
    if assign_unit is not None and assign_unit not in known_unit_keys():
        return bad_unit_response(assign_unit)
    if assignment_role == "head_of_unit" and not assign_unit:
        return jsonify({"error": "A Head of Unit assignment needs a unit."}), 400
    now = datetime.datetime.utcnow().isoformat() + "Z"
    cur = db.execute(
        "INSERT INTO role_assignments (consultant_username, consultant_display_name, assignment_role, unit, start_at, end_at, assigned_by, assigned_at) VALUES (?,?,?,?,?,?,?,?)",
        (target_username, consultant["display_name"], assignment_role, assign_unit,
         _text(body.get("startAt"), 40), _text(body.get("endAt"), 40), g.user["username"], now),
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


# =====================================================================
#  FEEDBACK / COMPLAINTS / SUGGESTIONS
#
#  Anyone with an account can raise one. Only Head of Department, Course
#  Coordinator and Developer can read them.
#
#  Anonymity is structural, not a flag that hides a stored name: an
#  anonymous submission writes NULL into author_username, so there is
#  nothing in the database to look up afterwards. The cost is that an
#  anonymous submission cannot be followed up or tracked by its own author,
#  and the submit screen says so before the choice is made.
# =====================================================================

FEEDBACK_KINDS = {"feedback", "complaint", "suggestion", "bug"}
FEEDBACK_STATUSES = {"open", "in_progress", "closed"}
FEEDBACK_MAX_SUBJECT = 200
FEEDBACK_MAX_BODY = 8000


def _can_read_feedback(username):
    caps = user_capabilities(username)
    return bool(caps["isHod"] or caps["isCoordinator"] or caps["isDeveloper"])


def _feedback_row_to_dict(db, row, include_author):
    d = dict(row)
    out = {
        "id": d["id"],
        "kind": d["kind"],
        "subject": d["subject"],
        "body": d["body"],
        "status": d["status"],
        "createdAt": d["created_at"],
        "updatedAt": d["updated_at"],
        "anonymous": d["author_username"] is None,
    }
    if include_author and d["author_username"]:
        out["authorUsername"] = d["author_username"]
        out["authorDisplayName"] = _display_name(db, d["author_username"])
    return out


def _feedback_notes(db, feedback_id):
    rows = db.execute(
        "SELECT actor_username, action, note, status, created_at FROM feedback_notes"
        " WHERE feedback_id = ? ORDER BY id ASC", (feedback_id,)
    ).fetchall()
    return [{
        "actorUsername": r["actor_username"],
        "actorDisplayName": _display_name(db, r["actor_username"]),
        "action": r["action"], "note": r["note"], "status": r["status"],
        "createdAt": r["created_at"],
    } for r in rows]


@api.post("/feedback")
@login_required()
def create_feedback():
    body = request.get_json(force=True, silent=True) or {}
    kind = (_text(body.get("kind"), 40) or "feedback").strip()
    if kind not in FEEDBACK_KINDS:
        return jsonify({"error": "Pick what kind of message this is."}), 400
    subject = (_text(body.get("subject"), FEEDBACK_MAX_SUBJECT + 1) or "").strip()
    text = (_text(body.get("body"), FEEDBACK_MAX_BODY + 1) or "").strip()
    if not subject:
        return jsonify({"error": "Give it a one-line subject."}), 400
    if not text:
        return jsonify({"error": "Say what you would like to raise."}), 400
    if len(subject) > FEEDBACK_MAX_SUBJECT:
        return jsonify({"error": f"Keep the subject under {FEEDBACK_MAX_SUBJECT} characters."}), 400
    if len(text) > FEEDBACK_MAX_BODY:
        return jsonify({"error": f"Keep the message under {FEEDBACK_MAX_BODY} characters."}), 400

    anonymous = bool(body.get("anonymous"))
    db = get_db()
    now = datetime.datetime.utcnow().isoformat() + "Z"
    cur = db.execute(
        "INSERT INTO feedback (kind, subject, body, author_username, status, created_at)"
        " VALUES (?,?,?,?,'open',?)",
        (kind, subject, text, None if anonymous else g.user["username"], now),
    )
    db.commit()
    # An anonymous submission gets no id back either: an id the submitter
    # holds is a handle a later conversation could be matched against.
    return jsonify({"ok": True, "anonymous": anonymous,
                    "id": None if anonymous else cur.lastrowid})


@api.get("/feedback/mine")
@login_required()
def my_feedback():
    """Named submissions only -- an anonymous one has no author to match on,
    which is the point of it."""
    db = get_db()
    rows = db.execute(
        "SELECT * FROM feedback WHERE author_username = ? ORDER BY id DESC",
        (g.user["username"],),
    ).fetchall()
    return jsonify({"feedback": [_feedback_row_to_dict(db, r, include_author=False) for r in rows]})


@api.get("/feedback")
@login_required()
def list_feedback():
    if not _can_read_feedback(g.user["username"]):
        return jsonify({"error": "forbidden"}), 403
    db = get_db()
    status = (request.args.get("status") or "").strip()
    if status and status in FEEDBACK_STATUSES:
        rows = db.execute("SELECT * FROM feedback WHERE status = ? ORDER BY id DESC", (status,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM feedback ORDER BY id DESC").fetchall()
    counts = {s: 0 for s in FEEDBACK_STATUSES}
    for r in db.execute("SELECT status, COUNT(*) c FROM feedback GROUP BY status"):
        if r["status"] in counts:
            counts[r["status"]] = r["c"]
    return jsonify({
        "feedback": [_feedback_row_to_dict(db, r, include_author=True) for r in rows],
        "counts": counts,
    })


@api.get("/feedback/<int:feedback_id>")
@login_required()
def get_feedback(feedback_id):
    if not _can_read_feedback(g.user["username"]):
        return jsonify({"error": "forbidden"}), 403
    db = get_db()
    row = db.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    out = _feedback_row_to_dict(db, row, include_author=True)
    out["notes"] = _feedback_notes(db, feedback_id)
    return jsonify({"feedback": out})


@api.patch("/feedback/<int:feedback_id>")
@login_required()
def update_feedback(feedback_id):
    """Status only. The submission itself is never edited by the people
    handling it -- a complaint that can be rewritten by its recipient is
    not a record of anything."""
    if not _can_read_feedback(g.user["username"]):
        return jsonify({"error": "forbidden"}), 403
    body = request.get_json(force=True, silent=True) or {}
    status = (_text(body.get("status"), 40) or "").strip()
    if status not in FEEDBACK_STATUSES:
        return jsonify({"error": "Unknown status."}), 400
    db = get_db()
    row = db.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    if row["status"] == status:
        return jsonify({"feedback": _feedback_row_to_dict(db, row, include_author=True)})
    now = datetime.datetime.utcnow().isoformat() + "Z"
    db.execute("UPDATE feedback SET status = ?, updated_at = ? WHERE id = ?", (status, now, feedback_id))
    db.execute(
        "INSERT INTO feedback_notes (feedback_id, actor_username, action, note, status, created_at)"
        " VALUES (?,?,'status',?,?,?)",
        (feedback_id, g.user["username"], (body.get("note") or None), status, now),
    )
    db.commit()
    row = db.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
    return jsonify({"feedback": _feedback_row_to_dict(db, row, include_author=True)})


@api.post("/feedback/<int:feedback_id>/notes")
@login_required()
def add_feedback_note(feedback_id):
    if not _can_read_feedback(g.user["username"]):
        return jsonify({"error": "forbidden"}), 403
    body = request.get_json(force=True, silent=True) or {}
    note = (_text(body.get("note"), FEEDBACK_MAX_BODY + 1) or "").strip()
    if not note:
        return jsonify({"error": "Write the note first."}), 400
    if len(note) > FEEDBACK_MAX_BODY:
        return jsonify({"error": "That note is too long."}), 400
    db = get_db()
    if not db.execute("SELECT 1 FROM feedback WHERE id = ?", (feedback_id,)).fetchone():
        return jsonify({"error": "not_found"}), 404
    now = datetime.datetime.utcnow().isoformat() + "Z"
    db.execute(
        "INSERT INTO feedback_notes (feedback_id, actor_username, action, note, status, created_at)"
        " VALUES (?,?,'note',?,NULL,?)",
        (feedback_id, g.user["username"], note, now),
    )
    db.execute("UPDATE feedback SET updated_at = ? WHERE id = ?", (now, feedback_id))
    db.commit()
    return jsonify({"notes": _feedback_notes(db, feedback_id)})


@api.get("/feedback/summary")
@login_required()
def feedback_summary():
    """Open count for the sidebar badge. Silent 0 for anyone who cannot read
    them, so the dashboard does not have to know the rule."""
    if not _can_read_feedback(g.user["username"]):
        return jsonify({"open": 0, "canRead": False})
    r = get_db().execute("SELECT COUNT(*) c FROM feedback WHERE status = 'open'").fetchone()
    return jsonify({"open": r["c"], "canRead": True})


# =====================================================================
#  EDIT LOCKS  +  OPTIMISTIC CONCURRENCY
#
#  Two separate mechanisms, deliberately:
#
#  * The LOCK is a courtesy. It stops two people opening the same record
#    at once and tells the second who has it. It is a lease with a short
#    life, because a browser gives no reliable signal when someone closes
#    a tab or shuts a laptop -- a lock that waits for an explicit release
#    would strand records permanently.
#
#  * The VERSION CHECK is the guarantee. Every save carries the version it
#    was based on and is refused if the row moved underneath it. This is
#    what actually stops the lost update, and it holds even for a caller
#    that never took a lock or whose lease lapsed mid-edit.
# =====================================================================

LOCK_MINUTES = 10


def _now_iso():
    return datetime.datetime.utcnow().isoformat() + "Z"


def _lock_is_live(row):
    at = row["locked_at"] if "locked_at" in row.keys() else None
    if not row["locked_by"] or not at:
        return False
    try:
        held = datetime.datetime.fromisoformat(str(at).replace("Z", ""))
    except (ValueError, TypeError):
        return False
    age = (datetime.datetime.utcnow() - held).total_seconds()
    return age < LOCK_MINUTES * 60


def _lock_info(db, row):
    if not _lock_is_live(row):
        return None
    return {
        "username": row["locked_by"],
        "displayName": _display_name(db, row["locked_by"]),
        "since": row["locked_at"],
        "expiresInSeconds": max(
            0,
            int(LOCK_MINUTES * 60 - (datetime.datetime.utcnow()
                - datetime.datetime.fromisoformat(str(row["locked_at"]).replace("Z", ""))).total_seconds()),
        ),
    }


def _may_edit_entry(user, row):
    return row["author_username"] == user["username"] or user["role"] == "developer"


@api.post("/entries/<int:entry_id>/lock")
@login_required()
def take_entry_lock(entry_id):
    """Claim, or refresh, the edit lease. Called when the form opens and
    again every few minutes while it stays open."""
    db = get_db()
    row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    if not _may_edit_entry(g.user, row):
        return jsonify({"error": "forbidden"}), 403
    held = _lock_info(db, row)
    if held and held["username"] != g.user["username"]:
        return jsonify({"error": "locked", "lock": held}), 423
    db.execute("UPDATE entries SET locked_by = ?, locked_at = ? WHERE id = ?",
               (g.user["username"], _now_iso(), entry_id))
    db.commit()
    return jsonify({"ok": True, "rowVersion": row["row_version"], "lockMinutes": LOCK_MINUTES})


@api.post("/entries/<int:entry_id>/unlock")
@login_required()
def release_entry_lock(entry_id):
    """Released on save or cancel. A developer may also break someone
    else's lease -- a lease that has to be waited out is a lease that
    stops work in a department where people share machines."""
    db = get_db()
    row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    if row["locked_by"] and row["locked_by"] != g.user["username"] and g.user["role"] != "developer":
        return jsonify({"error": "forbidden"}), 403
    if row["locked_by"] and row["locked_by"] != g.user["username"]:
        _account_event(db, row["locked_by"], "edit_lock_broken", g.user["username"],
                       "Entry %d" % entry_id)
    db.execute("UPDATE entries SET locked_by = NULL, locked_at = NULL WHERE id = ?", (entry_id,))
    db.commit()
    return jsonify({"ok": True})


# =====================================================================
#  ACCOUNT LIFECYCLE
# =====================================================================

DELETION_BUFFER_DAYS = 14
LIFECYCLE_ACTIVE = "active"
LIFECYCLE_SELF = "self_deactivated"
LIFECYCLE_ADMIN = "admin_deactivated"
LIFECYCLE_PENDING_DELETION = "pending_deletion"
LIFECYCLE_DELETED = "deleted"

DEFAULT_DEACTIVATION_REASONS = [
    "Long leave", "Sabbatical", "Maternity / paternity leave",
    "Secondment to another department", "Completed the programme", "Other",
]


def _account_event(db, username, action, actor, detail=None):
    db.execute(
        "INSERT INTO account_events (username, action, actor_username, detail, created_at)"
        " VALUES (?,?,?,?,?)",
        (username, action, actor, _text(detail, 2000), _now_iso()),
    )


def _lifecycle_of(row):
    keys = row.keys()
    return (row["lifecycle"] if "lifecycle" in keys and row["lifecycle"] else LIFECYCLE_ACTIVE)


def _developer_count(db, exclude=None):
    """Live developers, not counting a named one. Used to refuse the last."""
    sql = ("SELECT COUNT(*) c FROM users WHERE role = 'developer' AND active = 1"
           " AND lifecycle NOT IN (?, ?)")
    args = [LIFECYCLE_DELETED, LIFECYCLE_PENDING_DELETION]
    if exclude:
        sql += " AND username != ?"
        args.append(exclude)
    return db.execute(sql, tuple(args)).fetchone()["c"]


def _last_developer_block(db, username, what):
    """The department must never end up with no developer: it is the only
    role that can manage accounts, units, lists and appointments, so losing
    the last one is unrecoverable from inside the app.

    Checked on deactivation, deletion AND role change -- guarding only
    deletion leaves the other two doors open to exactly the same outcome.
    """
    row = db.execute("SELECT role FROM users WHERE username = ?", (username,)).fetchone()
    if not row or row["role"] != "developer":
        return None
    if _developer_count(db, exclude=username) > 0:
        return None
    return jsonify({
        "error": "last_developer",
        "detail": "This is the only Developer account. %s it would leave the department "
                  "with nobody able to manage accounts, units or lists. Appoint another "
                  "Developer first." % what,
    }), 409


def _may_decide_account(db, target_username, actor_username):
    """Who may approve a deactivation or deletion.

    A trainee's logbook is the evidence for their certification, so deleting
    one is a training decision rather than an administrative one: the Head of
    Department signs those off, not the Developer. For everyone else either
    will do.
    """
    caps = user_capabilities(actor_username)
    target = db.execute("SELECT role FROM users WHERE username = ?", (target_username,)).fetchone()
    if not target:
        return False, "No such account."
    if target["role"] in TRAINEE_ROLES:
        if not caps["isHod"]:
            return False, ("Deleting a trainee account removes access to their training "
                           "record, so only the Head of Department can approve it.")
        return True, None
    if not (caps["isHod"] or caps["isDeveloper"]):
        return False, "Only the Head of Department or a Developer admin can decide this."
    return True, None


def _open_request(db, username, kind=None):
    sql = "SELECT * FROM account_requests WHERE username = ? AND status IN ('pending','approved')"
    args = [username]
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    return db.execute(sql + " ORDER BY id DESC", tuple(args)).fetchone()


def _request_to_dict(db, row):
    d = dict(row)
    return {
        "id": d["id"], "username": d["username"],
        "displayName": _display_name(db, d["username"]),
        "kind": d["kind"], "reason": d["reason"], "status": d["status"],
        "requestedBy": d["requested_by"],
        "requestedByName": _display_name(db, d["requested_by"]),
        "requestedAt": d["requested_at"],
        "decidedBy": d["decided_by"], "decidedAt": d["decided_at"],
        "decisionNote": d["decision_note"],
        "scheduledFor": d["scheduled_for"], "executedAt": d["executed_at"],
        "daysRemaining": _days_until(d["scheduled_for"]) if d["scheduled_for"] else None,
    }


def _days_until(iso):
    try:
        when = datetime.datetime.fromisoformat(str(iso).replace("Z", ""))
    except (ValueError, TypeError):
        return None
    return max(0, (when - datetime.datetime.utcnow()).days + (1 if (when - datetime.datetime.utcnow()).seconds else 0))


def _build_archive(db, username):
    """Everything the account authored, in one self-describing JSON blob.

    A blob rather than a pointer at live rows, because the whole point is
    that it still reads correctly after the profile is gone.
    """
    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    entries = [entry_row_to_dict(r) for r in db.execute(
        "SELECT * FROM entries WHERE author_username = ? ORDER BY id", (username,))]
    return {
        "schema": 1,
        "archivedAt": _now_iso(),
        "user": {k: user[k] for k in user.keys() if k != "password_hash"} if user else None,
        "entries": entries,
        "postings": get_postings(username),
        "approvalsGiven": [dict(r) for r in db.execute(
            "SELECT * FROM entry_approvals WHERE actor_username = ? ORDER BY id", (username,))],
        "roleAssignments": [dict(r) for r in db.execute(
            "SELECT * FROM role_assignments WHERE consultant_username = ? ORDER BY id", (username,))],
        "accountEvents": [dict(r) for r in db.execute(
            "SELECT * FROM account_events WHERE username = ? ORDER BY id", (username,))],
    }


def _tombstone(db, username, actor):
    """Execute the deletion.

    NOT `DELETE FROM users`. Every entry, sign-off signature and consultant
    attribution the account touched is evidence somebody else may still need
    -- a trainee's logbook for their certification, a consultant's name on an
    operation record for the trainee who logged it. The row stays, so the
    foreign keys stay satisfied and nothing cascades; the login is destroyed
    and the identifying profile is cleared.
    """
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        return False
    db.execute(
        """UPDATE users SET
             password_hash = '!deleted',
             active = 0,
             pg_year = NULL, designation = NULL,
             lifecycle = ?, lifecycle_at = ?, lifecycle_by = ?
           WHERE username = ?""",
        (LIFECYCLE_DELETED, _now_iso(), actor, username),
    )
    destroy_all_sessions_for(username)
    _account_event(db, username, "deleted", actor,
                   "Tombstoned; %d entries retained" % db.execute(
                       "SELECT COUNT(*) c FROM entries WHERE author_username = ?",
                       (username,)).fetchone()["c"])
    return True


def run_due_deletions(db):
    """Apply any approved deletion whose buffer has run out.

    There is no scheduler here: Render has no cron and the free tier sleeps,
    so this is swept on request instead. It is cheap -- one indexed query --
    and in practice fires within moments of anyone using the app. If nobody
    opens the app for a week, nothing happens for a week, and the Developer's
    screen shows anything overdue. Said plainly rather than pretended
    otherwise.
    """
    now = _now_iso()
    due = db.execute(
        "SELECT * FROM account_requests WHERE kind = 'delete' AND status = 'approved'"
        " AND scheduled_for IS NOT NULL AND scheduled_for <= ?", (now,)
    ).fetchall()
    done = 0
    for r in due:
        if _tombstone(db, r["username"], r["decided_by"] or "system"):
            db.execute("UPDATE account_requests SET status = 'executed', executed_at = ? WHERE id = ?",
                       (now, r["id"]))
            done += 1
    if done:
        db.commit()
    return done


@api.get("/account/overview")
@login_required()
def account_overview():
    """Everything My Account shows, in one call."""
    db = get_db()
    run_due_deletions(db)
    me = db.execute("SELECT * FROM users WHERE username = ?", (g.user["username"],)).fetchone()
    scope = consultant_scope(g.user["username"]) if me["role"] == "consultant" else {"full": False, "units": [], "activeAssignments": []}

    assignments = []
    for a in db.execute(
        "SELECT * FROM role_assignments WHERE consultant_username = ? ORDER BY start_at DESC",
        (g.user["username"],)
    ):
        d = dict(a)
        started = (d["start_at"] or "")[:10]
        ended = (d["end_at"] or "")[:10]
        assignments.append({
            "role": d["assignment_role"], "unit": d["unit"],
            "startAt": started, "endAt": ended or None,
            "active": is_assignment_active(d),
            "assignedBy": d["assigned_by"], "assignedAt": d["assigned_at"],
        })

    postings = get_postings(g.user["username"])
    # "Which unit am I in" differs by role: a trainee rotates and their unit
    # comes from today's posting; a consultant has a home unit on the account.
    today = datetime.date.today().isoformat()
    current_unit = (unit_for_date(postings, today) if me["role"] in TRAINEE_ROLES else me["unit"]) or ""

    members = {"consultants": [], "trainees": []}
    if current_unit:
        for r in db.execute(
            "SELECT username, display_name, role, designation, pg_year, active, lifecycle"
            " FROM users WHERE unit = ? AND approval_status = 'approved' ORDER BY display_name",
            (current_unit,)
        ):
            bucket = "consultants" if r["role"] == "consultant" else "trainees"
            if r["role"] == "developer":
                continue
            members[bucket].append({
                "username": r["username"], "displayName": r["display_name"],
                "role": r["role"], "designation": r["designation"], "pgYear": r["pg_year"],
                "status": _lifecycle_of(r),
            })
        # Trainees posted here now, who may have a different home unit.
        posted = db.execute(
            "SELECT DISTINCT u.username, u.display_name, u.role, u.pg_year, u.active, u.lifecycle"
            " FROM postings p JOIN users u ON u.username = p.username"
            " WHERE p.unit = ? AND p.start_date <= ? AND (p.end_date IS NULL OR p.end_date >= ?)"
            " AND u.role IN ('resident','senior_resident','fellow')", (current_unit, today, today)
        ).fetchall()
        have = {m["username"] for m in members["trainees"]}
        for r in posted:
            if r["username"] in have:
                continue
            members["trainees"].append({
                "username": r["username"], "displayName": r["display_name"],
                "role": r["role"], "designation": None, "pgYear": r["pg_year"],
                "status": _lifecycle_of(r),
            })
        members["trainees"].sort(key=lambda m: (m["displayName"] or "").lower())

    pending = _open_request(db, g.user["username"])
    cfg = get_config()
    return jsonify({
        "profile": {
            "username": me["username"], "displayName": me["display_name"],
            "role": me["role"], "designation": me["designation"], "pgYear": me["pg_year"],
            "unit": current_unit, "homeUnit": me["unit"],
            "createdAt": me["created_at"], "lastSeenAt": me["last_seen_at"],
            "lifecycle": _lifecycle_of(me),
        },
        "scope": scope,
        "assignments": assignments,
        "postings": postings,
        "members": members,
        "request": _request_to_dict(db, pending) if pending else None,
        "deactivationReasons": cfg.get("deactivationReasons") or DEFAULT_DEACTIVATION_REASONS,
        "deletionBufferDays": DELETION_BUFFER_DAYS,
        "isLastDeveloper": me["role"] == "developer" and _developer_count(db, exclude=me["username"]) == 0,
    })


@api.post("/account/deactivate")
@login_required()
def self_deactivate():
    """Immediate, and reversed by simply signing in again.

    Distinct from an admin switching an account off: that one must NOT come
    back on sign-in, or deactivating someone would be unenforceable. The
    difference is carried in `lifecycle`, not in `active`.
    """
    body = request.get_json(force=True, silent=True) or {}
    reason = (_text(body.get("reason"), 200) or "").strip()
    note = (_text(body.get("note"), 2000) or "").strip()
    if not reason:
        return jsonify({"error": "Pick a reason so your unit knows why you are away."}), 400
    db = get_db()
    blocked = _last_developer_block(db, g.user["username"], "Deactivating")
    if blocked:
        return blocked
    detail = reason + ((" — " + note) if note else "")
    db.execute(
        "UPDATE users SET active = 0, lifecycle = ?, lifecycle_reason = ?, lifecycle_at = ?,"
        " lifecycle_by = ? WHERE username = ?",
        (LIFECYCLE_SELF, detail, _now_iso(), g.user["username"], g.user["username"]),
    )
    _account_event(db, g.user["username"], "self_deactivated", g.user["username"], detail)
    db.commit()
    destroy_all_sessions_for(g.user["username"])
    return jsonify({"ok": True, "reactivateBySigningIn": True})


@api.post("/account/request-deletion")
@login_required()
def request_account_deletion():
    body = request.get_json(force=True, silent=True) or {}
    target = clean_username(_text(body.get("username"), 100)) or g.user["username"]
    reason = (_text(body.get("reason"), 2000) or "").strip()
    if not reason:
        return jsonify({"error": "Say why this account should be closed."}), 400

    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username = ?", (target,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404

    if target != g.user["username"]:
        caps = user_capabilities(g.user["username"])
        # Someone leaves without closing their own account -- the common
        # case -- so an HOD or Developer can start it for them. It still
        # goes through the same approval and the same buffer.
        if not (caps["isHod"] or caps["isDeveloper"]):
            return jsonify({"error": "forbidden"}), 403
    if _lifecycle_of(row) == LIFECYCLE_DELETED:
        return jsonify({"error": "This account has already been closed."}), 409
    if _open_request(db, target, "delete"):
        return jsonify({"error": "There is already a deletion request open for this account."}), 409
    blocked = _last_developer_block(db, target, "Deleting")
    if blocked:
        return blocked

    db.execute(
        "INSERT INTO account_requests (username, kind, reason, status, requested_by, requested_at)"
        " VALUES (?,'delete',?,'pending',?,?)",
        (target, reason, g.user["username"], _now_iso()),
    )
    _account_event(db, target, "deletion_requested", g.user["username"], reason)
    db.commit()
    entry_count = db.execute("SELECT COUNT(*) c FROM entries WHERE author_username = ?",
                             (target,)).fetchone()["c"]
    return jsonify({
        "ok": True,
        "entriesRetained": entry_count,
        "needsApprovalFrom": "the Head of Department" if row["role"] in TRAINEE_ROLES
                             else "the Head of Department or a Developer admin",
    })


@api.post("/account/cancel-deletion")
@login_required()
def cancel_account_deletion():
    """Withdrawable by the person themselves at any point in the buffer, and
    by anyone who could have decided it."""
    body = request.get_json(force=True, silent=True) or {}
    target = clean_username(_text(body.get("username"), 100)) or g.user["username"]
    db = get_db()
    req = _open_request(db, target, "delete")
    if not req:
        return jsonify({"error": "Nothing to cancel."}), 404
    if target != g.user["username"]:
        allowed, why = _may_decide_account(db, target, g.user["username"])
        if not allowed:
            return jsonify({"error": "forbidden", "detail": why}), 403
    db.execute("UPDATE account_requests SET status = 'cancelled', decided_by = ?, decided_at = ?"
               " WHERE id = ?", (g.user["username"], _now_iso(), req["id"]))
    # Restore the login only if the deletion had actually suspended it.
    row = db.execute("SELECT * FROM users WHERE username = ?", (target,)).fetchone()
    if row and _lifecycle_of(row) == LIFECYCLE_PENDING_DELETION:
        db.execute("UPDATE users SET active = 1, lifecycle = ?, lifecycle_reason = NULL,"
                   " lifecycle_at = ?, lifecycle_by = ? WHERE username = ?",
                   (LIFECYCLE_ACTIVE, _now_iso(), g.user["username"], target))
    _account_event(db, target, "deletion_cancelled", g.user["username"], None)
    db.commit()
    return jsonify({"ok": True})


@api.get("/account/requests")
@login_required()
def list_account_requests():
    db = get_db()
    caps = user_capabilities(g.user["username"])
    if not (caps["isHod"] or caps["isDeveloper"] or caps["isCoordinator"]):
        return jsonify({"error": "forbidden"}), 403
    run_due_deletions(db)
    rows = db.execute(
        "SELECT * FROM account_requests WHERE status IN ('pending','approved') ORDER BY id DESC"
    ).fetchall()
    out = [_request_to_dict(db, r) for r in rows]
    deactivated = [{
        "username": r["username"], "displayName": r["display_name"], "role": r["role"],
        "lifecycle": _lifecycle_of(r), "reason": r["lifecycle_reason"], "since": r["lifecycle_at"],
    } for r in db.execute(
        "SELECT * FROM users WHERE active = 0 AND lifecycle IN (?,?) ORDER BY display_name",
        (LIFECYCLE_SELF, LIFECYCLE_ADMIN))]
    return jsonify({
        "requests": out,
        "pending": [r for r in out if r["status"] == "pending"],
        "inBuffer": [r for r in out if r["status"] == "approved"],
        "deactivated": deactivated,
        "bufferDays": DELETION_BUFFER_DAYS,
        "canDecideTrainees": bool(caps["isHod"]),
    })


@api.post("/account/requests/<int:request_id>/decide")
@login_required()
def decide_account_request(request_id):
    body = request.get_json(force=True, silent=True) or {}
    decision = _text(body.get("decision"), 20)
    if decision not in ("approve", "reject"):
        return jsonify({"error": "Decision must be approve or reject."}), 400
    db = get_db()
    req = db.execute("SELECT * FROM account_requests WHERE id = ?", (request_id,)).fetchone()
    if not req:
        return jsonify({"error": "not_found"}), 404
    if req["status"] != "pending":
        return jsonify({"error": "This request has already been decided."}), 409
    allowed, why = _may_decide_account(db, req["username"], g.user["username"])
    if not allowed:
        return jsonify({"error": "forbidden", "detail": why}), 403
    now = _now_iso()
    note = _text(body.get("note"), 2000)

    if decision == "reject":
        db.execute("UPDATE account_requests SET status='rejected', decided_by=?, decided_at=?,"
                   " decision_note=? WHERE id = ?", (g.user["username"], now, note, request_id))
        _account_event(db, req["username"], "deletion_rejected", g.user["username"], note)
        db.commit()
        return jsonify({"ok": True, "status": "rejected"})

    blocked = _last_developer_block(db, req["username"], "Deleting")
    if blocked:
        return blocked

    # The archive is taken NOW, at the decision, not at execution: it is the
    # copy the Developer can restore from, and it should exist for the whole
    # buffer rather than appearing at the moment the data goes.
    payload = json.dumps(_build_archive(db, req["username"]))
    target = db.execute("SELECT display_name FROM users WHERE username = ?", (req["username"],)).fetchone()
    db.execute("INSERT INTO account_archives (username, display_name, archived_at, archived_by, payload)"
               " VALUES (?,?,?,?,?)",
               (req["username"], target["display_name"] if target else None, now, g.user["username"], payload))
    scheduled = (datetime.datetime.utcnow()
                 + datetime.timedelta(days=DELETION_BUFFER_DAYS)).isoformat() + "Z"
    db.execute("UPDATE account_requests SET status='approved', decided_by=?, decided_at=?,"
               " decision_note=?, scheduled_for=? WHERE id = ?",
               (g.user["username"], now, note, scheduled, request_id))
    # Suspended, not yet tombstoned: the buffer is there to be reversible.
    db.execute("UPDATE users SET active = 0, lifecycle = ?, lifecycle_reason = ?, lifecycle_at = ?,"
               " lifecycle_by = ? WHERE username = ?",
               (LIFECYCLE_PENDING_DELETION, req["reason"], now, g.user["username"], req["username"]))
    destroy_all_sessions_for(req["username"])
    _account_event(db, req["username"], "deletion_approved", g.user["username"],
                   "Scheduled for %s" % scheduled[:10])
    db.commit()
    return jsonify({"ok": True, "status": "approved", "scheduledFor": scheduled})


@api.post("/account/restore/<username>")
@login_required(role="developer")
def restore_account(username):
    """Developer-only, as asked. Works during the buffer and afterwards: a
    tombstone still has its row and its archive, so bringing someone back is
    a password reset rather than a rebuild."""
    body = request.get_json(force=True, silent=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    new_password = _text(body.get("password"), 200)
    state = _lifecycle_of(row)
    if state == LIFECYCLE_DELETED and not new_password:
        return jsonify({
            "error": "password_required",
            "detail": "This account was closed, so its password no longer exists. "
                      "Set a new one to bring it back.",
        }), 400
    if new_password is not None and len(new_password) < 8:
        return jsonify({"error": "New password must be at least 8 characters."}), 400
    if new_password:
        db.execute("UPDATE users SET password_hash = ? WHERE username = ?",
                   (hash_password(new_password), username))
    db.execute("UPDATE users SET active = 1, lifecycle = ?, lifecycle_reason = NULL,"
               " lifecycle_at = ?, lifecycle_by = ? WHERE username = ?",
               (LIFECYCLE_ACTIVE, _now_iso(), g.user["username"], username))
    db.execute("UPDATE account_requests SET status = 'cancelled', decided_by = ?, decided_at = ?"
               " WHERE username = ? AND status IN ('pending','approved')",
               (g.user["username"], _now_iso(), username))
    _account_event(db, username, "restored", g.user["username"], None)
    db.commit()
    return jsonify({"ok": True})


@api.get("/account/archives")
@login_required(role="developer")
def list_account_archives():
    db = get_db()
    rows = db.execute(
        "SELECT id, username, display_name, archived_at, archived_by, LENGTH(payload) bytes"
        " FROM account_archives ORDER BY id DESC").fetchall()
    return jsonify({"archives": [dict(r) for r in rows]})


@api.get("/account/archives/<int:archive_id>.json")
@login_required(role="developer")
def download_account_archive(archive_id):
    db = get_db()
    row = db.execute("SELECT * FROM account_archives WHERE id = ?", (archive_id,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    return Response(
        row["payload"], mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=account-%s-%s.json"
                 % (row["username"], (row["archived_at"] or "")[:10])})


@api.get("/account/events/<username>")
@login_required()
def account_events(username):
    caps = user_capabilities(g.user["username"])
    if not (caps["isHod"] or caps["isDeveloper"] or g.user["username"] == username):
        return jsonify({"error": "forbidden"}), 403
    db = get_db()
    rows = db.execute(
        "SELECT * FROM account_events WHERE username = ? ORDER BY id DESC LIMIT 100", (username,)
    ).fetchall()
    return jsonify({"events": [{
        "action": r["action"], "actor": r["actor_username"],
        "actorName": _display_name(db, r["actor_username"]) if r["actor_username"] else None,
        "detail": r["detail"], "createdAt": r["created_at"],
    } for r in rows]})


@api.post("/config/bulk-add")
@login_required(role="developer")
def config_bulk_add():
    """Paste a block of options into one list.

    Adding a department's diagnosis list one box-and-button at a time is
    forty round trips. Splits on newlines, commas and semicolons, trims,
    drops blanks, de-duplicates against itself AND against what is already
    there (case-insensitively), and reports exactly what it did rather than
    silently merging.

    `preview: true` runs the whole thing and changes nothing, so the count
    can be shown before anyone commits to it.
    """
    body = request.get_json(force=True, silent=True) or {}
    key = _text(body.get("list"), 60)
    raw = _text(body.get("text"), 200000) or ""
    preview = bool(body.get("preview"))

    if key not in CONFIG_LIST_KEYS or key in ("units", "categories"):
        # units and categories are objects with keys, not plain strings --
        # they have their own editors and pasting names into them would
        # produce entries nothing can reference.
        return jsonify({"error": "That list cannot be bulk-filled here."}), 400

    cfg = get_config()
    existing = [x for x in (cfg.get(key) or []) if isinstance(x, str)]
    lower = {x.strip().lower() for x in existing}

    added, duplicates, already = [], [], []
    seen = set()
    for piece in re.split(r"[\n,;]+", raw):
        item = piece.strip()
        if not item:
            continue
        if len(item) > 300:
            item = item[:300]
        low = item.lower()
        if low in lower:
            already.append(item); continue
        if low in seen:
            duplicates.append(item); continue
        seen.add(low)
        added.append(item)

    if len(existing) + len(added) > 2000:
        return jsonify({"error": "That would take the list past 2000 options."}), 400

    result = {
        "list": key, "added": added, "alreadyPresent": already,
        "repeatedInPaste": duplicates, "total": len(existing) + len(added),
        "preview": preview,
    }
    if preview or not added:
        return jsonify(result)

    cfg[key] = existing + added
    db = get_db()
    db.execute("UPDATE config SET data = ? WHERE id = 'lists'", (json.dumps(cfg),))
    db.commit()
    result["config"] = cfg
    return jsonify(result)
