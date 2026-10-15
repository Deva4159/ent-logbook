"""v8.0: Post-Operative / Post-Procedure complications, for Surgical and
Other Procedure entries only.

A complication is a CHILD record of the entry it happened after, never a
column on `entries` itself (see schema_sqlite.sql's comment above
entry_complications) -- the base case stays completely untouched by
anything logged, edited, approved, disputed or later deleted here. Its own
append-only log (complication_edits / complication_approvals) mirrors
entry_edits / entry_approvals in api.py on purpose, for the same reason:
"was this signed off, by whom, of which version" has to stay answerable
after it's been edited since -- this module leans on that precedent rather
than reinventing it.

Who may add or edit a complication (spec section 3): the base entry's
author, an Involved Fellow or Involved Consultant (someone named in the
entry's `involved` list who currently holds that role), the Head of Unit of
the entry's unit, or the Developer. The HOD and Course Coordinator hold
only approving rights here -- via the existing signoff.delegate scope, the
same mechanism entries use for an absent approver -- never add/edit rights.
"""
import datetime

from flask import Blueprint, g, jsonify, request

import perms
from api import (
    _display_name, _may_read_entry_row, _text, _valid_approver,
    entry_row_to_dict, pod_day,
)
from auth import login_required
from db import get_db

cx = Blueprint("complications", __name__, url_prefix="/api")

# Same two entry types the rest of this feature is scoped to -- Interesting
# Case, Academic and Seminar entries never get a complication.
COMPLICATION_ENTRY_TYPES = {"surgical", "other"}

APPROVAL_STATES = {"not_submitted", "pending", "changes_requested", "approved"}
ARRIVES_IN_QUEUE = ("submitted", "reassigned", "released", "changes_requested")

MAX_OPEN_DELETE_REQUESTS = 1  # per complication


def _json():
    b = request.get_json(force=True, silent=True)
    return b if isinstance(b, dict) else {}


def _now():
    return datetime.datetime.utcnow().isoformat() + "Z"


def _iso_date(v):
    if not isinstance(v, str) or len(v) != 10:
        return None
    try:
        datetime.date.fromisoformat(v)
        return v
    except ValueError:
        return None


def _hhmm(v):
    """HH:MM, 24-hour, or None. A typed free-hand time is kept only if it
    actually parses -- otherwise it is silently not what the field is for."""
    if not isinstance(v, str) or not v.strip():
        return None
    s = v.strip()
    try:
        datetime.datetime.strptime(s, "%H:%M")
        return s
    except ValueError:
        return None


# -------------------------------------------------------------- lookups
def _entry_for_complication(db, entry_id):
    return db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()


def _complication(db, cid):
    return db.execute("SELECT * FROM entry_complications WHERE id = ?", (cid,)).fetchone()


def _comp_and_entry(db, cid):
    """(complication_row, entry_row) or (None, None) if either is missing."""
    c = _complication(db, cid)
    if not c:
        return None, None
    e = _entry_for_complication(db, c["entry_id"])
    if not e:
        return c, None
    return c, e


def _entry_linked_usernames(entry_row):
    """Accounts the base entry names as clinically involved: the supervising
    consultant plus everyone in `involved` who resolved to an account. Free
    text with no account cannot be "involved" for this purpose -- there is
    nobody to log in as them."""
    out = set()
    if entry_row["consultant_username"]:
        out.add(entry_row["consultant_username"])
    raw = entry_row["involved"] if "involved" in entry_row.keys() else None
    if raw:
        import json
        try:
            items = json.loads(raw)
        except (TypeError, ValueError):
            items = []
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict) and it.get("username"):
                    out.add(it["username"])
    return out


def _is_head_of_unit_of(username, unit):
    if not unit:
        return False
    return any(a["assignment_role"] == "head_of_unit" and a["unit"] == unit
               for a in perms.active_role_assignments(username))


def _may_log_complication(user, entry_row):
    """Add/edit/submit/withdraw group (spec section 3): author, Involved
    Fellow, Involved Consultant, Head of Unit of the entry's unit, or the
    Developer. The HOD / Coordinator are deliberately NOT in this group --
    they only ever get approving rights, via _can_decide_complication."""
    if user["role"] == "developer":
        return True
    if entry_row["author_username"] == user["username"]:
        return True
    if user["role"] in ("fellow", "consultant") and user["username"] in _entry_linked_usernames(entry_row):
        return True
    return _is_head_of_unit_of(user["username"], entry_row["unit"])


def _delegate_for_complication(user, entry_row):
    """Same rule entries use for an absent approver (perms.in_scope on
    signoff.delegate), scoped to the BASE ENTRY's unit -- a complication has
    no unit of its own."""
    if user["role"] == "developer":
        return False
    return perms.in_scope(user["username"], "signoff.delegate", entry_row["unit"])


def _can_decide_complication(user, comp_row, entry_row):
    """(allowed, on_behalf_of). Nobody decides their own complication. The
    Developer DOES decide complications (unlike base-entry sign-off) --
    spec section 3 names the Developer explicitly in this column, a
    deliberate asymmetry: self-decision is still refused regardless of role,
    which is the one invariant perms.py treats as non-negotiable everywhere
    else in this app."""
    if comp_row["author_username"] == user["username"]:
        return False, None
    if user["role"] == "developer":
        return True, None
    if comp_row["approver_username"] == user["username"] and perms.can(user["username"], "signoff.approve"):
        if user["role"] == "fellow":
            a = get_db().execute("SELECT role FROM users WHERE username = ?",
                                 (entry_row["author_username"],)).fetchone()
            if not a or a["role"] not in ("resident", "senior_resident"):
                return False, None
        return True, None
    if _delegate_for_complication(user, entry_row):
        return True, comp_row["approver_username"]
    return False, None


def _max_edit_id(db, complication_id):
    r = db.execute("SELECT COALESCE(MAX(id), 0) m FROM complication_edits WHERE complication_id = ?",
                   (complication_id,)).fetchone()
    return r["m"] if r else 0


def _log_complication_approval(db, complication_id, action, actor, comment=None,
                               approver_username=None, on_behalf_of=None):
    db.execute(
        "INSERT INTO complication_approvals (complication_id, action, actor_username, actor_role,"
        " approver_username, on_behalf_of, comment, edits_at_action, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (complication_id, action, actor["username"], actor.get("role"), approver_username,
         on_behalf_of, _text(comment, 4000), _max_edit_id(db, complication_id), _now()),
    )


# ------------------------------------------------------------- serialising
def complication_row_to_dict(db, c, entry_row=None):
    d = dict(c)
    out = {
        "id": d["id"],
        "entryId": d["entry_id"],
        "authorUsername": d["author_username"],
        "authorDisplayName": _display_name(db, d["author_username"]),
        "complicationName": d["complication_name"],
        "dateOfComplication": d["date_of_complication"],
        "timeOfComplication": d["time_of_complication"],
        "presentedAt": d["presented_at"],
        "presentedAtOther": d["presented_at_other"],
        "management": d["management"],
        "managementOther": d["management_other"],
        "notes": d["notes"],
        "linkedEntryId": d["linked_entry_id"],
        "createdAt": d["created_at"],
        "approvalState": d["approval_state"],
        "approverUsername": d["approver_username"],
        "approverDisplayName": _display_name(db, d["approver_username"]) if d["approver_username"] else None,
    }
    if entry_row is not None:
        out["podDay"] = pod_day(entry_row["entry_date"], entry_row["unit"], d["date_of_complication"])
    return out


def _complication_history(db, complication_id):
    rows = db.execute(
        "SELECT action, actor_username, actor_role, approver_username, on_behalf_of, comment, created_at"
        " FROM complication_approvals WHERE complication_id = ? ORDER BY id ASC", (complication_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ CRUD
@cx.get("/entries/<int:entry_id>/complications")
@login_required()
def list_complications(entry_id):
    db = get_db()
    entry = _entry_for_complication(db, entry_id)
    if not entry:
        return jsonify({"error": "not_found"}), 404
    # Anyone who can see the base entry under the ordinary view.records
    # scope, PLUS the complications add/edit group itself (an Involved
    # Fellow/Consultant or the Head of Unit needs to see what they are
    # submitting or editing even on a unit they don't otherwise have
    # standing view access to -- being named on the case is what grants it
    # here, narrowly, for this feature's own records).
    allowed = (entry["author_username"] == g.user["username"] or g.user["role"] == "developer"
               or _may_read_entry_row(g.user, dict(entry)) or _may_log_complication(g.user, entry))
    if not allowed:
        return jsonify({"error": "forbidden"}), 403
    rows = db.execute("SELECT * FROM entry_complications WHERE entry_id = ? ORDER BY date_of_complication, id",
                      (entry_id,)).fetchall()
    out = [complication_row_to_dict(db, r, entry) for r in rows]
    for item, r in zip(out, rows):
        item["canEdit"] = (r["approval_state"] in ("not_submitted", "changes_requested")
                          and _may_log_complication(g.user, entry))
    return jsonify({"complications": out})


@cx.post("/entries/<int:entry_id>/complications")
@login_required()
def create_complication(entry_id):
    db = get_db()
    entry = _entry_for_complication(db, entry_id)
    if not entry:
        return jsonify({"error": "not_found"}), 404
    if entry["entry_type"] not in COMPLICATION_ENTRY_TYPES:
        return jsonify({"error": "Complications can only be logged on Surgical or Other Procedure entries."}), 400
    if entry["status"] != "final":
        return jsonify({"error": "Finish this entry before logging a complication against it."}), 400
    if not _may_log_complication(g.user, entry):
        return jsonify({"error": "forbidden"}), 403
    b = _json()
    name = _text(b.get("complicationName"), 200)
    if not name or not name.strip():
        return jsonify({"error": "Name the complication."}), 400
    date_c = _iso_date(b.get("dateOfComplication"))
    if not date_c:
        return jsonify({"error": "Give a real date for the complication (YYYY-MM-DD)."}), 400
    if date_c < entry["entry_date"]:
        return jsonify({"error": "A complication can't be dated before the procedure."}), 400
    time_c = _hhmm(b.get("timeOfComplication")) if b.get("timeOfComplication") else None
    presented_at = _text(b.get("presentedAt"), 120)
    if not presented_at or not presented_at.strip():
        return jsonify({"error": "Say where the patient presented."}), 400
    presented_other = _text(b.get("presentedAtOther"), 200) if presented_at == "Other" else None
    management = _text(b.get("management"), 120)
    if not management or not management.strip():
        return jsonify({"error": "Say how it was managed."}), 400
    management_other = _text(b.get("managementOther"), 200) if management == "Other" else None
    notes = _text(b.get("notes"), 4000)
    cur = db.execute(
        "INSERT INTO entry_complications (entry_id, author_username, complication_name, date_of_complication,"
        " time_of_complication, presented_at, presented_at_other, management, management_other, notes,"
        " created_at, approval_state) VALUES (?,?,?,?,?,?,?,?,?,?,?,'not_submitted')",
        (entry_id, g.user["username"], name.strip(), date_c, time_c, presented_at.strip(), presented_other,
         management.strip(), management_other, notes, _now()),
    )
    db.commit()
    row = _complication(db, cur.lastrowid)
    return jsonify({"complication": complication_row_to_dict(db, row, entry)}), 201


@cx.patch("/complications/<int:cid>")
@login_required()
def update_complication(cid):
    db = get_db()
    c, entry = _comp_and_entry(db, cid)
    if not c or not entry:
        return jsonify({"error": "not_found"}), 404
    if not _may_log_complication(g.user, entry):
        return jsonify({"error": "forbidden"}), 403
    if c["approval_state"] not in ("not_submitted", "changes_requested"):
        return jsonify({"error": "This complication is with the approving consultant and can't be edited. "
                                  "Ask them to release it first."}), 409
    b = _json()
    before = complication_row_to_dict(db, c, entry)

    name = _text(b.get("complicationName"), 200) if "complicationName" in b else c["complication_name"]
    if not name or not name.strip():
        return jsonify({"error": "Name the complication."}), 400
    date_c = c["date_of_complication"]
    if "dateOfComplication" in b:
        date_c = _iso_date(b.get("dateOfComplication"))
        if not date_c:
            return jsonify({"error": "Give a real date for the complication (YYYY-MM-DD)."}), 400
        if date_c < entry["entry_date"]:
            return jsonify({"error": "A complication can't be dated before the procedure."}), 400
    time_c = (_hhmm(b.get("timeOfComplication")) if b.get("timeOfComplication") else None) \
        if "timeOfComplication" in b else c["time_of_complication"]
    presented_at = _text(b.get("presentedAt"), 120) if "presentedAt" in b else c["presented_at"]
    if not presented_at or not presented_at.strip():
        return jsonify({"error": "Say where the patient presented."}), 400
    presented_other = (_text(b.get("presentedAtOther"), 200) if presented_at == "Other" else None) \
        if "presentedAtOther" in b or "presentedAt" in b else c["presented_at_other"]
    management = _text(b.get("management"), 120) if "management" in b else c["management"]
    if not management or not management.strip():
        return jsonify({"error": "Say how it was managed."}), 400
    management_other = (_text(b.get("managementOther"), 200) if management == "Other" else None) \
        if "managementOther" in b or "management" in b else c["management_other"]
    notes = _text(b.get("notes"), 4000) if "notes" in b else c["notes"]

    db.execute(
        "UPDATE entry_complications SET complication_name=?, date_of_complication=?, time_of_complication=?,"
        " presented_at=?, presented_at_other=?, management=?, management_other=?, notes=? WHERE id=?",
        (name.strip(), date_c, time_c, presented_at.strip(), presented_other,
         management.strip(), management_other, notes, cid),
    )
    row = _complication(db, cid)
    after = complication_row_to_dict(db, row, entry)
    changes = {k: {"old": before[k], "new": after[k]} for k in after
              if k in ("complicationName", "dateOfComplication", "timeOfComplication", "presentedAt",
                       "presentedAtOther", "management", "managementOther", "notes")
              and before.get(k) != after.get(k)}
    if changes:
        import json as _json_mod
        db.execute("INSERT INTO complication_edits (complication_id, edited_by, edited_at, changes) VALUES (?,?,?,?)",
                  (cid, g.user["username"], _now(), _json_mod.dumps(changes)))
    db.commit()
    return jsonify({"complication": after})


# --------------------------------------------------------------- approvals
@cx.post("/complications/<int:cid>/submit")
@login_required()
def submit_complication(cid):
    db = get_db()
    c, entry = _comp_and_entry(db, cid)
    if not c or not entry:
        return jsonify({"error": "not_found"}), 404
    if not _may_log_complication(g.user, entry):
        return jsonify({"error": "forbidden"}), 403
    if c["approval_state"] not in ("not_submitted", "changes_requested"):
        return jsonify({"error": "This complication has already been submitted."}), 409
    b = _json()
    approver = _text(b.get("approverUsername"), 100) if b.get("approverUsername") else entry["approver_username"]
    if not approver:
        return jsonify({"error": "Choose who should sign this off -- the base case has no approver to default to."}), 400
    if approver == g.user["username"]:
        return jsonify({"error": "You cannot send this to yourself for approval."}), 400
    if not _valid_approver(db, approver):
        return jsonify({"error": "That person cannot be sent records for sign-off."}), 400
    comment = b.get("comment")
    action = "reassigned" if (c["approval_state"] == "changes_requested" and c["approver_username"]
                              and c["approver_username"] != approver) else \
        ("resubmitted" if c["approval_state"] == "changes_requested" else "submitted")
    _log_complication_approval(db, cid, action, g.user, comment=comment, approver_username=approver)
    db.execute("UPDATE entry_complications SET approval_state='pending', approver_username=? WHERE id=?",
              (approver, cid))
    db.commit()
    row = _complication(db, cid)
    return jsonify({"complication": complication_row_to_dict(db, row, entry)})


@cx.post("/complications/<int:cid>/withdraw")
@login_required()
def withdraw_complication(cid):
    db = get_db()
    c, entry = _comp_and_entry(db, cid)
    if not c or not entry:
        return jsonify({"error": "not_found"}), 404
    if not _may_log_complication(g.user, entry):
        return jsonify({"error": "forbidden"}), 403
    if c["approval_state"] not in ("pending", "changes_requested"):
        return jsonify({"error": "Nothing to withdraw."}), 409
    _log_complication_approval(db, cid, "withdrawn", g.user)
    db.execute("UPDATE entry_complications SET approval_state='not_submitted', approver_username=NULL WHERE id=?",
              (cid,))
    db.commit()
    return jsonify({"ok": True})


def _decide_complication(cid, action, require_comment):
    db = get_db()
    c, entry = _comp_and_entry(db, cid)
    if not c or not entry:
        return jsonify({"error": "not_found"}), 404
    allowed, on_behalf = _can_decide_complication(g.user, c, entry)
    if not allowed:
        return jsonify({"error": "forbidden"}), 403
    if c["approval_state"] != "pending":
        return jsonify({"error": "This complication is not awaiting a decision."}), 409
    b = _json()
    comment = b.get("comment")
    if require_comment and not str(comment or "").strip():
        return jsonify({"error": "Say what needs changing."}), 400
    _log_complication_approval(db, cid, action, g.user, comment=comment, on_behalf_of=on_behalf)
    db.execute("UPDATE entry_complications SET approval_state=? WHERE id=?",
              ("approved" if action == "approved" else "changes_requested", cid))
    db.commit()
    row = _complication(db, cid)
    return jsonify({"complication": complication_row_to_dict(db, row, entry)})


@cx.post("/complications/<int:cid>/approve")
@login_required()
def approve_complication(cid):
    return _decide_complication(cid, "approved", require_comment=False)


@cx.post("/complications/<int:cid>/request-changes")
@login_required()
def request_changes_complication(cid):
    return _decide_complication(cid, "changes_requested", require_comment=True)


@cx.post("/complications/<int:cid>/release")
@login_required()
def release_complication(cid):
    db = get_db()
    c, entry = _comp_and_entry(db, cid)
    if not c or not entry:
        return jsonify({"error": "not_found"}), 404
    allowed, on_behalf = _can_decide_complication(g.user, c, entry)
    if not allowed:
        return jsonify({"error": "forbidden"}), 403
    if c["approval_state"] != "approved":
        return jsonify({"error": "This complication is not locked."}), 409
    b = _json()
    _log_complication_approval(db, cid, "released", g.user, comment=b.get("comment"), on_behalf_of=on_behalf)
    db.execute("UPDATE entry_complications SET approval_state='changes_requested' WHERE id=?", (cid,))
    db.commit()
    return jsonify({"ok": True})


@cx.post("/entries/<int:entry_id>/complications/release-bulk")
@login_required()
def release_complications_bulk(entry_id):
    db = get_db()
    entry = _entry_for_complication(db, entry_id)
    if not entry:
        return jsonify({"error": "not_found"}), 404
    b = _json()
    ids = b.get("ids")
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "Pick at least one complication."}), 400
    done, skipped = [], []
    for raw in ids[:200]:
        try:
            comp_id = int(raw)
        except (TypeError, ValueError):
            continue
        c = db.execute("SELECT * FROM entry_complications WHERE id = ? AND entry_id = ?",
                      (comp_id, entry_id)).fetchone()
        if not c:
            skipped.append({"id": comp_id, "reason": "not_found"}); continue
        allowed, on_behalf = _can_decide_complication(g.user, c, entry)
        if not allowed:
            skipped.append({"id": comp_id, "reason": "forbidden"}); continue
        if c["approval_state"] != "approved":
            skipped.append({"id": comp_id, "reason": "not_locked"}); continue
        _log_complication_approval(db, comp_id, "released", g.user, on_behalf_of=on_behalf)
        db.execute("UPDATE entry_complications SET approval_state='changes_requested' WHERE id=?", (comp_id,))
        done.append(comp_id)
    db.commit()
    return jsonify({"released": done, "skipped": skipped})


@cx.get("/complications/<int:cid>/history")
@login_required()
def complication_history(cid):
    db = get_db()
    c, entry = _comp_and_entry(db, cid)
    if not c or not entry:
        return jsonify({"error": "not_found"}), 404
    allowed = (g.user["role"] == "developer" or c["author_username"] == g.user["username"]
               or _may_log_complication(g.user, entry))
    if not allowed:
        allowed, _ = _can_decide_complication(g.user, c, entry)
    if not allowed:
        return jsonify({"error": "forbidden"}), 403
    return jsonify({"history": _complication_history(db, cid)})


# ----------------------------------------------------------------- queue
@cx.get("/complications/approvals/queue")
@login_required()
def complications_queue():
    # v8.0.1: the Developer deliberately DOES decide complications --
    # _can_decide_complication above names this explicitly as the one
    # asymmetry with base-entry sign-off, where the Developer is excluded
    # outright. This listing had copied the base-entry queue's blanket
    # "role == developer -> forbidden" verbatim, which left the Developer's
    # own "Complications" nav tab 403ing on every visit -- nothing wrong
    # with their account, the list just refused to compute for them at all.
    me = g.user["username"]
    is_dev = g.user["role"] == "developer"
    if not is_dev and not (
            g.user["role"] == "consultant" or perms.can(me, "signoff.approve")
            or perms.can(me, "signoff.delegate")):
        return jsonify({"error": "forbidden"}), 403
    db = get_db()
    rows = db.execute("SELECT * FROM entry_complications WHERE approval_state = 'pending' ORDER BY id ASC").fetchall()
    can_approve = perms.can(me, "signoff.approve")
    mine, delegated = [], []
    for c in rows:
        if c["author_username"] == me:
            continue  # nobody decides their own, Developer included
        entry = _entry_for_complication(db, c["entry_id"])
        if not entry:
            continue
        own = c["approver_username"] == me and can_approve and not is_dev
        # A Developer isn't the nominated approver on anything, but can
        # still decide every one of these -- same bucket a delegate's items
        # land in, so the UI's existing "for <nominee>" chip applies here
        # without any frontend change.
        can_delegate = (not own) and (is_dev or perms.in_scope(me, "signoff.delegate", entry["unit"]))
        if not own and not can_delegate:
            continue
        item = complication_row_to_dict(db, c, entry)
        item["entry"] = entry_row_to_dict(entry)
        item["onBehalfOf"] = None if own else c["approver_username"]
        (mine if own else delegated).append(item)
    return jsonify({"queue": mine, "delegated": delegated})


# -------------------------------------------------------------- deletion
def _delete_request_dict(db, r):
    return {
        "id": r["id"], "complicationId": r["complication_id"], "entryId": r["entry_id"],
        "complicationName": r["complication_name_snapshot"],
        "requestedBy": r["requested_by"], "requestedByName": _display_name(db, r["requested_by"]),
        "requestedAt": r["requested_at"], "reason": r["reason"],
        "alsoDeleteLinkedEntry": bool(r["also_delete_linked_entry"]),
        "status": r["status"], "decidedBy": r["decided_by"],
        "decidedByName": _display_name(db, r["decided_by"]) if r["decided_by"] else None,
        "decidedAt": r["decided_at"], "decisionNote": r["decision_note"],
    }


def _execute_deletion(db, comp_id, also_delete_linked):
    """Actually remove a complication (and, if asked and safe, its linked
    follow-up entry). Returns an error string, or None on success. Never
    partially applies: if the linked entry is locked, nothing is deleted."""
    c = _complication(db, comp_id)
    if not c:
        return "That complication no longer exists."
    if also_delete_linked and c["linked_entry_id"]:
        linked = db.execute("SELECT * FROM entries WHERE id = ?", (c["linked_entry_id"],)).fetchone()
        if linked and linked["approval_state"] == "approved":
            return ("The linked record has been signed off and is locked. Release it first, "
                    "or delete the complication without it.")
        if linked:
            db.execute("DELETE FROM entries WHERE id = ?", (linked["id"],))
    db.execute("DELETE FROM entry_complications WHERE id = ?", (comp_id,))
    return None


@cx.post("/complications/delete-requests")
@login_required()
def request_complication_deletion():
    db = get_db()
    b = _json()
    try:
        comp_id = int(b.get("complicationId"))
    except (TypeError, ValueError):
        return jsonify({"error": "Choose a complication."}), 400
    c, entry = _comp_and_entry(db, comp_id)
    if not c or not entry:
        return jsonify({"error": "not_found"}), 404
    if not _may_log_complication(g.user, entry):
        return jsonify({"error": "forbidden"}), 403
    open_existing = db.execute(
        "SELECT id FROM complication_deletion_requests WHERE complication_id = ? AND status = 'pending'",
        (comp_id,)).fetchone()
    if open_existing:
        return jsonify({"error": "There is already an open deletion request for this complication."}), 409
    also_delete = bool(b.get("alsoDeleteLinkedEntry")) and bool(c["linked_entry_id"])
    reason = _text(b.get("reason"), 1000)
    now = _now()
    cur = db.execute(
        "INSERT INTO complication_deletion_requests (complication_id, entry_id, complication_name_snapshot,"
        " requested_by, requested_at, reason, also_delete_linked_entry, status)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (comp_id, entry["id"], c["complication_name"], g.user["username"], now, reason, int(also_delete),
         "pending"))
    rid = cur.lastrowid
    # Open item (spec section 6/10): a never-submitted complication has no
    # approver to route this to -- the author (or anyone in the add/edit
    # group) may delete it directly. Still goes through this same table, as
    # an already-decided request, so the "who deleted this and why" trail
    # looks the same either way.
    if c["approval_state"] == "not_submitted":
        err = _execute_deletion(db, comp_id, also_delete)
        if err:
            db.rollback()
            return jsonify({"error": err}), 409
        db.execute(
            "UPDATE complication_deletion_requests SET status='approved', decided_by=?, decided_at=?,"
            " decision_note=? WHERE id=?",
            (g.user["username"], now, "Never submitted -- deleted directly.", rid))
        db.commit()
        return jsonify({"ok": True, "autoDeleted": True,
                        "request": _delete_request_dict(db, db.execute(
                            "SELECT * FROM complication_deletion_requests WHERE id = ?", (rid,)).fetchone())}), 201
    db.commit()
    return jsonify({"request": _delete_request_dict(
        db, db.execute("SELECT * FROM complication_deletion_requests WHERE id = ?", (rid,)).fetchone())}), 201


@cx.post("/complications/delete-requests/<int:rid>/withdraw")
@login_required()
def withdraw_deletion_request(rid):
    db = get_db()
    r = db.execute("SELECT * FROM complication_deletion_requests WHERE id = ?", (rid,)).fetchone()
    if not r:
        return jsonify({"error": "not_found"}), 404
    if r["requested_by"] != g.user["username"]:
        return jsonify({"error": "forbidden"}), 403
    if r["status"] != "pending":
        return jsonify({"error": "This request has already been decided."}), 409
    db.execute("UPDATE complication_deletion_requests SET status='withdrawn' WHERE id=?", (rid,))
    db.commit()
    return jsonify({"ok": True})


@cx.post("/complications/delete-requests/<int:rid>/decide")
@login_required()
def decide_deletion_request(rid):
    db = get_db()
    r = db.execute("SELECT * FROM complication_deletion_requests WHERE id = ?", (rid,)).fetchone()
    if not r:
        return jsonify({"error": "not_found"}), 404
    if r["status"] != "pending":
        return jsonify({"error": "This request has already been decided."}), 409
    if not r["complication_id"]:
        return jsonify({"error": "That complication no longer exists."}), 409
    c, entry = _comp_and_entry(db, r["complication_id"])
    if not c or not entry:
        return jsonify({"error": "not_found"}), 404
    allowed, _on_behalf = _can_decide_complication(g.user, c, entry)
    if not allowed:
        return jsonify({"error": "forbidden"}), 403
    b = _json()
    decision = b.get("decision")
    note = _text(b.get("note"), 500)
    if decision not in ("approve", "reject"):
        return jsonify({"error": "Choose approve or reject."}), 400
    now = _now()
    if decision == "reject":
        if not (note or "").strip():
            return jsonify({"error": "Say why, so the request makes sense later."}), 400
        db.execute(
            "UPDATE complication_deletion_requests SET status='rejected', decided_by=?, decided_at=?,"
            " decision_note=? WHERE id=?", (g.user["username"], now, note, rid))
        db.commit()
        return jsonify({"request": _delete_request_dict(
            db, db.execute("SELECT * FROM complication_deletion_requests WHERE id = ?", (rid,)).fetchone())})
    err = _execute_deletion(db, r["complication_id"], bool(r["also_delete_linked_entry"]))
    if err:
        db.rollback()
        return jsonify({"error": err}), 409
    db.execute(
        "UPDATE complication_deletion_requests SET status='approved', decided_by=?, decided_at=?,"
        " decision_note=? WHERE id=?", (g.user["username"], now, note, rid))
    db.commit()
    return jsonify({"ok": True, "request": _delete_request_dict(
        db, db.execute("SELECT * FROM complication_deletion_requests WHERE id = ?", (rid,)).fetchone())})


# --------------------------------------------------------- log as new case
@cx.post("/complications/<int:cid>/log-as-entry")
@login_required()
def log_complication_as_entry(cid):
    """Stamp a NEW entry (already created by the caller via the ordinary
    POST /api/entries, pre-filled with the original case's demographics) as
    the management of this complication. Deliberately split from entry
    creation rather than one combined endpoint: the new record is completely
    ordinary from here on (own draft/final, own sign-off), so it goes
    through the one path that already validates an entry fully, and this
    endpoint only ever adds the two pointer columns plus the link on the
    complication side.

    Gate: the base entry's add/edit group (author, Involved Fellow/
    Consultant) -- "he/she must be involved in the case" -- and the caller
    must be the new entry's own author, since this is them logging their
    own management of it, not nominating someone else's entry.
    """
    db = get_db()
    c, entry = _comp_and_entry(db, cid)
    if not c or not entry:
        return jsonify({"error": "not_found"}), 404
    if not (g.user["role"] == "developer" or entry["author_username"] == g.user["username"]
            or (g.user["role"] in ("fellow", "consultant")
                and g.user["username"] in _entry_linked_usernames(entry))):
        return jsonify({"error": "forbidden",
                        "detail": "You must be involved in the original case to log its management "
                                  "as a new record."}), 403
    b = _json()
    try:
        new_entry_id = int(b.get("entryId"))
    except (TypeError, ValueError):
        return jsonify({"error": "Choose the record you logged."}), 400
    new_entry = db.execute("SELECT * FROM entries WHERE id = ?", (new_entry_id,)).fetchone()
    if not new_entry:
        return jsonify({"error": "not_found"}), 404
    if new_entry["author_username"] != g.user["username"]:
        return jsonify({"error": "forbidden", "detail": "You can only link a record you yourself created."}), 403
    if new_entry["entry_type"] not in COMPLICATION_ENTRY_TYPES:
        return jsonify({"error": "Only a Surgical or Other Procedure record can be linked as management."}), 400
    if new_entry["id"] == entry["id"]:
        return jsonify({"error": "A record can't manage itself."}), 400
    if new_entry["came_from_complication"]:
        return jsonify({"error": "That record is already linked to a complication."}), 409
    if c["linked_entry_id"]:
        return jsonify({"error": "This complication is already linked to a record."}), 409
    db.execute("UPDATE entries SET came_from_complication = 1, complication_origin_entry_id = ? WHERE id = ?",
              (entry["id"], new_entry["id"]))
    db.execute("UPDATE entry_complications SET linked_entry_id = ? WHERE id = ?", (new_entry["id"], cid))
    db.commit()
    row = _complication(db, cid)
    return jsonify({"complication": complication_row_to_dict(db, row, entry),
                    "entry": entry_row_to_dict(db.execute("SELECT * FROM entries WHERE id = ?",
                                                          (new_entry["id"],)).fetchone())})
