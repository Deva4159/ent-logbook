"""v7.7 routes: stages (complete a course, move on, reopen) and the signed-in
person's own stage history. See stages.py for the rules."""
from flask import Blueprint, g, jsonify, request

import courses as courses_mod
import doctors as doctors_mod
import perms
import stages
from api import (
    _account_event, _display_name, _text, _trainee_profile, bad_unit_response, get_config,
    known_unit_keys, require_perm, row_to_user,
)
from auth import login_required
from db import get_db

st = Blueprint("stages", __name__, url_prefix="/api")


def _json():
    b = request.get_json(force=True, silent=True)
    return b if isinstance(b, dict) else {}


def _target(db, username):
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        return None, (jsonify({"error": "not_found"}), 404)
    if row["role"] == "developer":
        return None, (jsonify({"error": "A Developer account has no stage."}), 400)
    if row["approval_status"] != "approved":
        return None, (jsonify({"error": "This account is still waiting for approval."}), 409)
    return row, None


def _names(db, stage_list):
    for s in stage_list:
        s["completedByName"] = _display_name(db, s["completedBy"]) if s.get("completedBy") else None
    return stage_list


def _reply(db, username):
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    ov = stages.overview(db, row)
    _names(db, ov["stages"])
    return {"stage": ov, "user": row_to_user(row)}


@st.get("/users/<username>/stage")
@require_perm("accounts.change_stage")
def stage_overview(username):
    db = get_db()
    row, err = _target(db, username)
    if err:
        return err
    return jsonify(_reply(db, username))


@st.post("/users/<username>/stage/complete")
@require_perm("accounts.change_stage")
def stage_complete(username):
    body = _json()
    db = get_db()
    row, err = _target(db, username)
    if err:
        return err
    sid, why, cur = stages.complete(db, row, g.user["username"], body.get("note"), bool(body.get("acknowledge")))
    if why == "unfinished":
        # Nothing is written until the person approving has seen what is
        # unfinished and said so.
        return jsonify({"error": "unfinished", "current": cur,
                        "detail": "Some entries are not finished. They will stay as they are, "
                                  "read-only. Confirm to complete the stage anyway."}), 409
    if why:
        return jsonify({"error": why}), 409
    _account_event(db, username, "stage_completed", g.user["username"],
                   "%s completed; %d entries saved" % (row["role"].replace("_", " "), cur["total"]))
    db.commit()
    perms.invalidate(username)
    return jsonify(_reply(db, username))


@st.post("/users/<username>/stage/reopen")
@require_perm("accounts.change_stage")
def stage_reopen(username):
    db = get_db()
    row, err = _target(db, username)
    if err:
        return err
    why = stages.reopen(db, row, g.user["username"])
    if why:
        return jsonify({"error": why}), 409
    _account_event(db, username, "stage_reopened", g.user["username"], "Completed stage reopened")
    db.commit()
    return jsonify(_reply(db, username))


@st.post("/users/<username>/stage/move")
@require_perm("accounts.change_stage")
def stage_move(username):
    body = _json()
    db = get_db()
    me = g.user["username"]
    is_dev = g.user["role"] == "developer"
    row, err = _target(db, username)
    if err:
        return err
    old_role = row["role"]
    if old_role not in stages.TRAINEE_ROLES:
        return jsonify({"error": "Only a trainee can be moved to a next stage."}), 400
    new_role = _text(body.get("role"), 40)
    if new_role not in stages.NEXT_ROLES.get(old_role, []):
        return jsonify({"error": "A %s can move to: %s." % (
            old_role.replace("_", " "), ", ".join(r.replace("_", " ") for r in stages.NEXT_ROLES[old_role]))}), 400

    new_unit = row["unit"]
    if "unit" in body:
        new_unit = _text(body.get("unit"), 60) or None
        if new_unit is not None and new_unit not in known_unit_keys():
            return bad_unit_response(new_unit)
    designation = row["designation"]
    course_id, joined_ym = None, None
    if new_role == "consultant":
        if not new_unit:
            return jsonify({"error": "Choose the consultant's home unit."}), 400
        designation = _text(body.get("designation"), 80)
        allowed = [d for d in (get_config().get("consultantDesignations") or [])]
        if not designation or designation not in allowed:
            return jsonify({"error": "Choose a designation."}), 400
        # "Professor" opens a whole unit's roster, so it stays a Developer decision.
        if designation.strip().lower() == "professor" and not is_dev:
            return jsonify({"error": "Only a Developer can set the Professor designation."}), 403
    else:
        if new_role == "fellow" and not new_unit:
            return jsonify({"error": "A fellow needs a parent unit."}), 400
        if not body.get("joinedYm"):
            return jsonify({"error": "Enter the month they start this stage."}), 400
        probe = {"courseId": body.get("courseId") or None, "joinedYm": body.get("joinedYm")}
        course_id, joined_ym, cerr = _trainee_profile(db, new_role, new_unit, probe, {})
        if cerr:
            return jsonify({"error": cerr}), 400
        designation = None

    # Completing and moving in one step: the same unfinished-entry check
    # applies, and nothing is written if it fails.
    if stages.status_of(row) != stages.COMPLETED:
        if not body.get("complete"):
            return jsonify({"error": "Complete the current stage first."}), 409
        sid, why, cur = stages.complete(db, row, me, body.get("note"), bool(body.get("acknowledge")))
        if why == "unfinished":
            db.rollback()
            return jsonify({"error": "unfinished", "current": cur,
                            "detail": "Some entries are not finished. They will stay as they are, "
                                      "read-only. Confirm to continue."}), 409
        if why:
            db.rollback()
            return jsonify({"error": why}), 409
        row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

    db.execute("UPDATE users SET role = ?, unit = ?, designation = ?, course_id = ?, joined_ym = ? WHERE username = ?",
               (new_role, new_unit, designation, course_id, joined_ym, username))
    stages.mark_moved(db, row, me, new_role)
    _account_event(db, username, "stage_moved", me,
                   "%s → %s%s" % (old_role.replace("_", " "), new_role.replace("_", " "),
                                       (" (course %s, from %s)" % (course_id, joined_ym)) if course_id else ""))
    # Senior residents, fellows and consultants are on the doctors list.
    doctors_mod.ensure_for_user(db, username, me)
    doctors_mod.sync_user(db, username)
    db.commit()
    perms.invalidate()
    return jsonify(_reply(db, username))


@st.get("/me/stages")
@login_required()
def my_stages():
    """The signed-in person's own stages, for the stage filter and the Archive."""
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username = ?", (g.user["username"],)).fetchone()
    return jsonify({
        "status": stages.status_of(row),
        "stages": _names(db, stages.history(db, row["username"])),
        "current": stages.current_summary(db, row["username"]),
    })
