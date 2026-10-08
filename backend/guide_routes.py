"""v7.6: the in-app Guide.

The prose of the guide (who / what / why / when / how, per activity) is
written by hand in the front end, because it explains a process. What each
kind of person is ALLOWED to do is not prose: it is whatever the permission
panel says today, so it is built here from the live templates. If the
Developer changes what Head of Unit may do, the Guide changes with it and
nobody is told something that is no longer true.
"""
import datetime

from flask import Blueprint, g, jsonify, request

import perms
from api import _account_event, approval_escalation_days
from auth import login_required
from db import get_db

gd = Blueprint("guide", __name__, url_prefix="/api")

# Who a persona is made of: which permission templates apply. A Professor who
# is also a Head of Unit holds both, which the matrix shows as the wider scope.
PERSONAS = [
    ("resident", "PG Resident", []),
    ("senior_resident", "Senior Resident", []),
    ("fellow", "Fellow", ["fellow"]),
    ("consultant", "Consultant", ["consultant"]),
    ("professor", "Professor", ["consultant", "professor"]),
    ("head_of_unit", "Head of Unit", ["consultant", "head_of_unit"]),
    ("coordinator", "Course Coordinator", ["consultant", "coordinator"]),
    ("hod", "Head of Department", ["consultant", "hod"]),
    ("developer", "Developer", None),            # None = holds everything
]


def _union(templates):
    """Department-wide beats unit-only when two templates grant the same thing."""
    out = {}
    for t in templates:
        for perm, scope in t.items():
            if scope == perms.SCOPE_ALL or perm not in out:
                out[perm] = scope
    return out


@gd.get("/guide")
@login_required()
def guide():
    db = get_db()
    tpls = perms.all_templates(db)
    personas = []
    for key, label, parts in PERSONAS:
        if parts is None:
            held = {p["key"]: perms.SCOPE_ALL for p in perms.CATALOGUE if p["key"] not in perms.SEPARATED}
        else:
            held = _union([tpls[k] for k in parts])
        personas.append({"key": key, "label": label, "perms": held})
    cat = [{"key": p["key"], "group": p["group"], "label": p["label"], "help": p["help"],
            "scoped": p["scoped"], "reserved": p["reserved"]} for p in perms.CATALOGUE]
    me = g.user["username"]
    return jsonify({
        "catalogue": cat,
        "groups": [{"key": k, "label": l} for k, l in perms.GROUPS],
        "personas": personas,
        "escalationDays": approval_escalation_days(),
        "appointments": [{"role": a["assignment_role"], "unit": a["unit"],
                          "startAt": a["start_at"], "endAt": a["end_at"]}
                         for a in perms.active_role_assignments(me)],
    })


@gd.post("/me/tour")
@login_required()
def tour_seen():
    """Record that this person has seen (or skipped) the welcome tour, so it
    is offered once per account per tour version, on any device."""
    b = request.get_json(force=True, silent=True)
    if not isinstance(b, dict) or "version" not in b:
        return jsonify({"error": "bad_request"}), 400
    v = b["version"]
    if v is not None and (not isinstance(v, str) or not (1 <= len(v) <= 20)):
        return jsonify({"error": "bad_version"}), 400
    db = get_db()
    db.execute("UPDATE users SET tour_seen = ? WHERE username = ?", (v, g.user["username"]))
    db.commit()
    return jsonify({"ok": True, "tourSeen": v})


@gd.post("/users/<username>/tour-reset")
@login_required("developer")
def tour_reset(username):
    """Developer only: forget that this account has seen the welcome tour, so
    it is offered again the next time they sign in. Nothing else about the
    account changes. Recorded in the account's history."""
    db = get_db()
    row = db.execute("SELECT username FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    db.execute("UPDATE users SET tour_seen = NULL WHERE username = ?", (username,))
    _account_event(db, username, "tour_reset", g.user["username"], "Welcome tour reset")
    db.commit()
    return jsonify({"ok": True, "tourSeen": None})
