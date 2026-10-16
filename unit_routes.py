"""v7.7: consultants rotate through units, and ask before they move.

A consultant has a home unit on their account. A POSTING (consultant_postings)
puts them in another unit for dates. While a posting covers today they hold the
"Consultant posted to a unit" permissions for that unit (the roster and the
records logged there), computed by perms.compute, so it follows the same
rules and shows up in the same Permissions screens as everything else.

Moving is asked for first: a consultant raises a request (unit, dates, reason),
like a piece of feedback, and the Head of Department, the Head of the unit they
would move to, or a Developer approves or declines it. Approving creates the
posting. The same people can set a posting directly.
"""
import datetime

from flask import Blueprint, g, jsonify, request

import perms
from api import _account_event, _display_name, _text, bad_unit_response, known_unit_keys
from auth import login_required
from db import get_db

ur = Blueprint("unit_requests", __name__, url_prefix="/api")

DECIDE = "postings.decide_consultant"
MAX_OPEN = 3


def _json():
    b = request.get_json(force=True, silent=True)
    return b if isinstance(b, dict) else {}


def _now():
    return datetime.datetime.utcnow().isoformat() + "Z"


def _date(v):
    if not isinstance(v, str) or len(v) != 10:
        return None
    try:
        datetime.date.fromisoformat(v)
        return v
    except ValueError:
        return None


def _day_before(iso):
    return (datetime.date.fromisoformat(iso) - datetime.timedelta(days=1)).isoformat()


def _home_or_posted(db, username, on=None):
    """The unit a consultant is in on a date: a posting if one covers it, else home."""
    cur = perms.active_consultant_postings(username, on)
    if cur:
        return sorted(cur, key=lambda p: p["start_date"])[-1]["unit"]
    r = db.execute("SELECT unit FROM users WHERE username = ?", (username,)).fetchone()
    return r["unit"] if r else None


def _posting_dict(p):
    return {"id": p["id"], "username": p["username"], "unit": p["unit"], "startDate": p["start_date"],
            "endDate": p["end_date"], "createdBy": p["created_by"], "createdAt": p["created_at"],
            "requestId": p["request_id"], "note": p["note"]}


def _request_dict(db, r):
    u = db.execute("SELECT display_name, designation, unit FROM users WHERE username = ?",
                   (r["requester"],)).fetchone()
    return {
        "id": r["id"], "requester": r["requester"],
        "requesterName": u["display_name"] if u else r["requester"],
        "designation": u["designation"] if u else None,
        "fromUnit": r["from_unit"], "toUnit": r["to_unit"],
        "startDate": r["start_date"], "endDate": r["end_date"], "reason": r["reason"],
        "status": r["status"], "decidedBy": r["decided_by"],
        "decidedByName": _display_name(db, r["decided_by"]) if r["decided_by"] else None,
        "decidedAt": r["decided_at"], "decisionNote": r["decision_note"],
        "postingId": r["posting_id"], "createdAt": r["created_at"],
    }


def _may_see(me, r):
    if perms.in_scope(me, DECIDE, r["to_unit"]):
        return True
    return bool(r["from_unit"]) and perms.in_scope(me, DECIDE, r["from_unit"])


def _clash(db, username, start, end, ignore=None):
    """Postings that overlap [start, end]. The ones that merely run on past
    `start` are trimmed by the caller; anything that begins inside the new
    period is a real conflict."""
    rows = db.execute("SELECT * FROM consultant_postings WHERE username = ? ORDER BY start_date",
                      (username,)).fetchall()
    out = []
    for p in rows:
        if ignore and p["id"] == ignore:
            continue
        p_end = p["end_date"] or "9999-12-31"
        n_end = end or "9999-12-31"
        if p["start_date"] <= n_end and start <= p_end:
            out.append(p)
    return out


def _place(db, username, unit, start, end, actor, request_id=None, note=None):
    """Create a posting, trimming an earlier one that runs into it.
    -> (posting_id, error_text)."""
    clashes = _clash(db, username, start, end)
    trim = []
    for p in clashes:
        if p["start_date"] < start:
            trim.append(p)
        else:
            return None, ("This overlaps an existing posting (%s, from %s). Remove it first."
                          % (p["unit"], p["start_date"]))
    for p in trim:
        db.execute("UPDATE consultant_postings SET end_date = ? WHERE id = ?", (_day_before(start), p["id"]))
    cur = db.execute(
        "INSERT INTO consultant_postings (username, unit, start_date, end_date, created_by, created_at,"
        " request_id, note) VALUES (?,?,?,?,?,?,?,?)",
        (username, unit, start, end, actor, _now(), request_id, note))
    return cur.lastrowid, None


# ================================================================ consultant
@ur.get("/consultant-postings/mine")
@login_required()
def my_postings():
    me = g.user["username"]
    if g.user["role"] != "consultant":
        return jsonify({"error": "forbidden"}), 403
    db = get_db()
    posts = [_posting_dict(p) for p in db.execute(
        "SELECT * FROM consultant_postings WHERE username = ? ORDER BY start_date DESC", (me,))]
    reqs = [_request_dict(db, r) for r in db.execute(
        "SELECT * FROM unit_requests WHERE requester = ? ORDER BY id DESC LIMIT 50", (me,))]
    row = db.execute("SELECT unit FROM users WHERE username = ?", (me,)).fetchone()
    return jsonify({"homeUnit": row["unit"] if row else None, "currentUnit": _home_or_posted(db, me),
                    "postings": posts, "requests": reqs})


@ur.post("/unit-requests")
@login_required()
def create_request():
    me = g.user["username"]
    if g.user["role"] != "consultant":
        return jsonify({"error": "Only consultants ask to change unit."}), 403
    b = _json()
    to_unit = _text(b.get("toUnit"), 60)
    if not to_unit or to_unit not in known_unit_keys():
        return bad_unit_response(to_unit)
    start = _date(b.get("startDate"))
    end = _date(b.get("endDate")) if b.get("endDate") else None
    if not start:
        return jsonify({"error": "Choose the date you would start."}), 400
    if b.get("endDate") and not end:
        return jsonify({"error": "The end date is not a valid date."}), 400
    if end and end < start:
        return jsonify({"error": "The end date cannot be before the start date."}), 400
    if start < datetime.date.today().isoformat():
        return jsonify({"error": "Ask before the move: the start date cannot be in the past."}), 400
    db = get_db()
    here = _home_or_posted(db, me, start)
    if here == to_unit:
        return jsonify({"error": "You are already in that unit on that date."}), 400
    n_open = db.execute("SELECT COUNT(*) c FROM unit_requests WHERE requester = ? AND status = 'open'",
                        (me,)).fetchone()["c"]
    if n_open >= MAX_OPEN:
        return jsonify({"error": "You already have %d open requests. Withdraw one or wait for a decision." % MAX_OPEN}), 409
    reason = (_text(b.get("reason"), 1000) or "").strip() or None
    now = _now()
    cur = db.execute(
        "INSERT INTO unit_requests (requester, from_unit, to_unit, start_date, end_date, reason, status,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?,'open',?,?)",
        (me, here, to_unit, start, end, reason, now, now))
    db.commit()
    r = db.execute("SELECT * FROM unit_requests WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify({"request": _request_dict(db, r)}), 201


@ur.post("/unit-requests/<int:rid>/withdraw")
@login_required()
def withdraw_request(rid):
    db = get_db()
    r = db.execute("SELECT * FROM unit_requests WHERE id = ?", (rid,)).fetchone()
    if not r or r["requester"] != g.user["username"]:
        return jsonify({"error": "not_found"}), 404
    if r["status"] != "open":
        return jsonify({"error": "This request has already been decided."}), 409
    db.execute("UPDATE unit_requests SET status = 'withdrawn', updated_at = ? WHERE id = ?", (_now(), rid))
    db.commit()
    return jsonify({"request": _request_dict(db, db.execute("SELECT * FROM unit_requests WHERE id = ?", (rid,)).fetchone())})


# ================================================================= deciders
def _need_decide():
    if not perms.can(g.user["username"], DECIDE):
        return jsonify({"error": "forbidden"}), 403
    return None


@ur.get("/unit-requests")
@login_required()
def list_requests():
    me = g.user["username"]
    bad = _need_decide()
    if bad:
        return bad
    db = get_db()
    status = request.args.get("status")
    sql = "SELECT * FROM unit_requests"
    args = []
    if status in ("open", "approved", "declined", "withdrawn"):
        sql += " WHERE status = ?"
        args.append(status)
    sql += " ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, id DESC LIMIT 300"
    out = []
    for r in db.execute(sql, args).fetchall():
        if not _may_see(me, r):
            continue
        d = _request_dict(db, r)
        d["canDecide"] = r["status"] == "open" and perms.in_scope(me, DECIDE, r["to_unit"])
        out.append(d)
    return jsonify({"requests": out})


@ur.get("/unit-requests/summary")
@login_required()
def requests_summary():
    me = g.user["username"]
    if not perms.compute(me).get(DECIDE):
        return jsonify({"open": 0})
    db = get_db()
    n = sum(1 for r in db.execute("SELECT * FROM unit_requests WHERE status = 'open'")
            if perms.in_scope(me, DECIDE, r["to_unit"]))
    return jsonify({"open": n})


@ur.post("/unit-requests/<int:rid>/decide")
@login_required()
def decide_request(rid):
    me = g.user["username"]
    bad = _need_decide()
    if bad:
        return bad
    b = _json()
    db = get_db()
    r = db.execute("SELECT * FROM unit_requests WHERE id = ?", (rid,)).fetchone()
    if not r:
        return jsonify({"error": "not_found"}), 404
    if not perms.in_scope(me, DECIDE, r["to_unit"]):
        return jsonify({"error": "forbidden",
                        "detail": "Only the Head of Department, the Head of the unit they would move to, "
                                  "or a Developer can decide this."}), 403
    if r["status"] != "open":
        return jsonify({"error": "This request has already been decided."}), 409
    decision = b.get("decision")
    note = (_text(b.get("note"), 500) or "").strip() or None
    if decision not in ("approve", "decline"):
        return jsonify({"error": "Choose approve or decline."}), 400
    if decision == "decline":
        if not note:
            return jsonify({"error": "Say why, so the consultant knows what to do next."}), 400
        db.execute("UPDATE unit_requests SET status='declined', decided_by=?, decided_at=?, decision_note=?,"
                   " updated_at=? WHERE id=?", (me, _now(), note, _now(), rid))
        _account_event(db, r["requester"], "unit_request_declined", me, "%s: %s" % (r["to_unit"], note))
        db.commit()
        return jsonify({"request": _request_dict(db, db.execute("SELECT * FROM unit_requests WHERE id = ?", (rid,)).fetchone())})
    start = _date(b.get("startDate")) or r["start_date"]
    end = _date(b.get("endDate")) if b.get("endDate") else (r["end_date"] if "endDate" not in b else None)
    if end and end < start:
        return jsonify({"error": "The end date cannot be before the start date."}), 400
    pid, err = _place(db, r["requester"], r["to_unit"], start, end, me, request_id=rid)
    if err:
        db.rollback()
        return jsonify({"error": err}), 409
    db.execute("UPDATE unit_requests SET status='approved', decided_by=?, decided_at=?, decision_note=?,"
               " posting_id=?, updated_at=? WHERE id=?", (me, _now(), note, pid, _now(), rid))
    _account_event(db, r["requester"], "unit_request_approved", me,
                   "%s from %s%s" % (r["to_unit"], start, (" to " + end) if end else ""))
    db.commit()
    perms.invalidate()
    return jsonify({"request": _request_dict(db, db.execute("SELECT * FROM unit_requests WHERE id = ?", (rid,)).fetchone()),
                    "posting": _posting_dict(db.execute("SELECT * FROM consultant_postings WHERE id = ?", (pid,)).fetchone())})


@ur.get("/consultant-postings")
@login_required()
def list_postings_for():
    """One consultant's postings, for the person looking after them."""
    bad = _need_decide()
    if bad:
        return bad
    who = request.args.get("username") or ""
    db = get_db()
    u = db.execute("SELECT role, unit FROM users WHERE username = ?", (who,)).fetchone()
    if not u or u["role"] != "consultant":
        return jsonify({"error": "not_found"}), 404
    posts = [_posting_dict(p) for p in db.execute(
        "SELECT * FROM consultant_postings WHERE username = ? ORDER BY start_date DESC", (who,))]
    me = g.user["username"]
    for p in posts:
        p["canRemove"] = perms.in_scope(me, DECIDE, p["unit"])
    return jsonify({"homeUnit": u["unit"], "postings": posts,
                    "canSet": bool(perms.compute(me).get(DECIDE))})


@ur.post("/consultant-postings")
@login_required()
def set_posting():
    me = g.user["username"]
    bad = _need_decide()
    if bad:
        return bad
    b = _json()
    db = get_db()
    who = _text(b.get("username"), 60)
    u = db.execute("SELECT role FROM users WHERE username = ?", (who,)).fetchone()
    if not u or u["role"] != "consultant":
        return jsonify({"error": "Choose a consultant."}), 400
    unit = _text(b.get("unit"), 60)
    if not unit or unit not in known_unit_keys():
        return bad_unit_response(unit)
    if not perms.in_scope(me, DECIDE, unit):
        return jsonify({"error": "forbidden", "detail": "You can set postings only into units you head."}), 403
    start = _date(b.get("startDate"))
    end = _date(b.get("endDate")) if b.get("endDate") else None
    if not start:
        return jsonify({"error": "Choose the start date."}), 400
    if end and end < start:
        return jsonify({"error": "The end date cannot be before the start date."}), 400
    note = (_text(b.get("note"), 300) or "").strip() or None
    pid, err = _place(db, who, unit, start, end, me, note=note)
    if err:
        db.rollback()
        return jsonify({"error": err}), 409
    _account_event(db, who, "unit_posting_set", me, "%s from %s%s" % (unit, start, (" to " + end) if end else ""))
    db.commit()
    perms.invalidate()
    return jsonify({"posting": _posting_dict(db.execute("SELECT * FROM consultant_postings WHERE id = ?", (pid,)).fetchone())}), 201


@ur.delete("/consultant-postings/<int:pid>")
@login_required()
def remove_posting(pid):
    me = g.user["username"]
    bad = _need_decide()
    if bad:
        return bad
    db = get_db()
    p = db.execute("SELECT * FROM consultant_postings WHERE id = ?", (pid,)).fetchone()
    if not p:
        return jsonify({"error": "not_found"}), 404
    if not perms.in_scope(me, DECIDE, p["unit"]):
        return jsonify({"error": "forbidden"}), 403
    db.execute("DELETE FROM consultant_postings WHERE id = ?", (pid,))
    _account_event(db, p["username"], "unit_posting_removed", me, "%s from %s" % (p["unit"], p["start_date"]))
    db.commit()
    perms.invalidate()
    return jsonify({"ok": True})
