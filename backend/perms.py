"""Permission engine (v7.4).

Until v7.3 every gate in api.py asked a question like "is this person an HOD
or a Coordinator?". That worked while there were three kinds of oversight and
each was all-or-nothing. It cannot express "this Associate Professor may see
ENT 2's roster but not sign anything off", which is what the department asked
for, so the questions are now about PERMISSIONS and the old titles are just
named bundles of them.

The model, in one paragraph
---------------------------
There is a fixed CATALOGUE of permissions (below). Each holds a *scope*:
"all" (the whole department) or "unit" (only the person's units), and a few
are plain on/off. A person's effective permissions are the union of

  1. the template of every appointment they currently hold
     (HOD / Coordinator / Head of Unit),
  2. the template for their designation ("professor") and for their account
     kind ("consultant", "fellow"),
  3. plus anything granted to them individually,
  4. minus anything individually denied.

A template is a default set shipped in code (DEFAULT_TEMPLATES) which the
Developer may edit; only the *difference* from the shipped default is stored
(permission_templates.changes), so a permission added in a later release
reaches every template that has not explicitly removed it.

Hard rules that are NOT editable
--------------------------------
* The Developer holds everything, always. A permission system the Developer
  controls cannot constrain the Developer; pretending otherwise would be
  decoration. (Said in the UI too.)
* RESERVED permissions (changing roles, resetting passwords, renaming
  accounts, restoring closed accounts, appointments, alerts, courses,
  backups, and this panel itself) can only ever be the Developer's. Delegating
  them would let a delegate promote themselves.
* Residents and Senior Residents hold no delegable permissions. Fellows can
  hold the view / export / sign-off ones (FELLOW_OK) and nothing else.
* Nobody can ever approve their own record, whatever they hold.
"""
import datetime
import json

from db import get_db

SCOPE_ALL = "all"
SCOPE_UNIT = "unit"

TRAINEE_ROLES = {"resident", "senior_resident", "fellow"}

# (key, group, label, help, scoped)
# `scoped` permissions can be held department-wide or for particular units;
# the rest are simply on or off.
_DELEGABLE = [
    # ---- viewing -------------------------------------------------------
    ("view.roster", "view", "See the trainee roster",
     "List trainees posted to the units in scope, with their counts and current unit.", True),
    ("view.records", "view", "Open a trainee's records",
     "Open a trainee's page: their case records and postings for the units in scope.", True),
    ("view.teaching", "view", "See Academic and Seminar entries",
     "Without this, a trainee's teaching entries are withheld by the server, not just hidden on screen.", False),
    ("view.history", "view", "Read an entry's edit history",
     "Who changed what, and when, on entries in scope.", True),
    ("view.escalations", "view", "See overdue sign-offs",
     "Records waiting longer than the escalation threshold, in scope.", True),
    ("export.scoped", "view", "Export records in scope to CSV",
     "Download the records this person is allowed to see.", True),
    ("entries.edit_others", "view", "Correct other people's entries",
     "Edit or delete a trainee's entry. Every change is logged against the editor; a signed-off record stays locked.", True),
    # ---- sign-off ------------------------------------------------------
    ("signoff.approve", "signoff", "Be a sign-off approver",
     "Be named as approver on a record, and approve or request changes on it. Never on their own record.", False),
    ("signoff.delegate", "signoff", "Sign off for an absent approver",
     "Act on records that name someone else, in scope. Recorded as a delegate action, not the approver's own.", True),
    # ---- accounts ------------------------------------------------------
    ("accounts.approve_trainees", "accounts", "Approve Resident / Senior Resident sign-ups", "", False),
    ("accounts.approve_fellows", "accounts", "Approve Fellow sign-ups", "", False),
    ("accounts.approve_consultants", "accounts", "Approve Consultant sign-ups", "", False),
    ("accounts.view_directory", "accounts", "See the full user list", "The Manage Users list.", False),
    ("accounts.edit_profile", "accounts", "Edit a trainee's course, batch and unit", "", False),
    ("accounts.deactivate", "accounts", "Deactivate or reactivate accounts", "", False),
    ("accounts.delete", "accounts", "Delete accounts, or open a closure request for someone", "", False),
    ("accounts.requests_view", "accounts", "See account requests", "Deactivations and closures waiting or in their buffer.", False),
    ("accounts.decide_trainee_closure", "accounts", "Decide a trainee's closure",
     "A trainee's logbook is certification evidence, so this is its own permission.", False),
    ("accounts.decide_other_closure", "accounts", "Decide a closure for anyone else", "", False),
    ("accounts.view_events", "accounts", "Read an account's event log", "", False),
    # ---- department ----------------------------------------------------
    ("postings.assign_others", "department", "Set other people's postings", "Single and bulk.", False),
    ("feedback.manage", "department", "Read and manage feedback", "Inbox, status and internal notes.", False),
    ("config.edit_lists", "department", "Edit the dropdown lists",
     "Diagnoses, procedures, designations, sign-off escalation days and the rest of Manage Lists, except units.", False),
    ("config.edit_units", "department", "Edit the units", "Create, rename and remove units; the orphan report.", False),
    # ---- data ----------------------------------------------------------
    ("data.export_all", "data", "Export the whole logbook", "Every entry in the department.", False),
    ("data.export_users", "data", "Export the user list", "", False),
]

# Permissions the Developer deliberately does NOT hold, so that one person
# cannot both start and settle the same decision. A trainee's logbook is
# certification evidence; closing the account is the Head of Department's
# call, not an administrator's (decided when account closure was built).
# The Developer can still give it to a consultant, which is how a department
# without a sitting HOD would handle it.
SEPARATED = {"accounts.decide_trainee_closure"}

# Developer-only, forever. Listed so the panel can show them honestly as
# locked rather than leaving the impression the catalogue is complete.
_RESERVED = [
    ("perms.manage", "reserved", "Change anyone's permissions", "This panel."),
    ("accounts.change_role", "reserved", "Change an account's kind (Resident, Consultant, Developer…)", ""),
    ("accounts.edit_designation", "reserved", "Change a consultant's designation", "Designation can act as an access grant (Professor)."),
    ("accounts.reset_password", "reserved", "Reset anyone's password", ""),
    ("accounts.rename", "reserved", "Change a username or display name", "Renaming rewrites every record that mentions the person."),
    ("accounts.restore", "reserved", "Restore a closed account, read the archive", ""),
    ("appointments.manage", "reserved", "Appoint HOD / Coordinator / Head of Unit", "An appointment is a bundle of permissions."),
    ("alerts.compose", "reserved", "Create alerts and set the alert rules", ""),
    ("courses.manage", "reserved", "Create and edit courses", ""),
    ("backup.manage", "reserved", "Download and restore backups", "A backup contains every password hash and every record."),
]

CATALOGUE = (
    [{"key": k, "group": g, "label": l, "help": h, "scoped": s, "reserved": False,
      "separated": k in SEPARATED}
     for (k, g, l, h, s) in _DELEGABLE]
    + [{"key": k, "group": g, "label": l, "help": h, "scoped": False, "reserved": True,
        "separated": False}
       for (k, g, l, h) in _RESERVED]
)
CATALOGUE_BY_KEY = {p["key"]: p for p in CATALOGUE}
DELEGABLE_KEYS = [p["key"] for p in CATALOGUE if not p["reserved"]]
ALL_KEYS = [p["key"] for p in CATALOGUE]

GROUPS = [
    ("view", "Viewing and records"),
    ("signoff", "Sign-off"),
    ("accounts", "Accounts"),
    ("department", "Department"),
    ("data", "Data"),
    ("reserved", "Developer only (cannot be delegated)"),
]

# What a Fellow may ever hold. Everything else needs consultant standing.
FELLOW_OK = {
    "view.roster", "view.records", "view.teaching", "view.history",
    "export.scoped", "signoff.approve",
}


def eligible(role, perm):
    """Can an account of this kind hold this permission at all?"""
    p = CATALOGUE_BY_KEY.get(perm)
    if not p or p["reserved"]:
        return False
    if role == "consultant":
        return True
    if role == "fellow":
        return perm in FELLOW_OK
    return False


# ---------------------------------------------------------------- templates
TEMPLATE_META = {
    "hod": ("Head of Department", "Held through an HOD appointment."),
    "coordinator": ("Course Coordinator", "Held through a Coordinator appointment."),
    "head_of_unit": ("Head of Unit", "Held through a Head of Unit appointment; “unit” means the unit appointed to."),
    "professor": ("Professor (designation)", "Every consultant whose designation is exactly “Professor”; “unit” means their home unit."),
    "consultant": ("Every consultant", "Baseline for every consultant account."),
    "fellow": ("Every fellow", "Baseline for every fellow account. Only view, export and sign-off permissions can be given."),
}
TEMPLATE_KEYS = list(TEMPLATE_META)

_ALL_VIEW = {"view.roster": "all", "view.records": "all", "view.teaching": "all",
             "view.history": "all", "view.escalations": "all", "export.scoped": "all"}

DEFAULT_TEMPLATES = {
    "hod": dict(
        _ALL_VIEW,
        **{"signoff.delegate": "all",
           "accounts.approve_trainees": "all", "accounts.approve_fellows": "all",
           "accounts.approve_consultants": "all",
           "accounts.view_directory": "all", "accounts.edit_profile": "all",
           "accounts.deactivate": "all", "accounts.delete": "all",
           "accounts.requests_view": "all", "accounts.decide_trainee_closure": "all",
           "accounts.decide_other_closure": "all", "accounts.view_events": "all",
           "postings.assign_others": "all", "feedback.manage": "all"}),
    "coordinator": dict(
        _ALL_VIEW,
        **{"signoff.delegate": "all",
           "accounts.approve_trainees": "all", "accounts.approve_fellows": "all",
           "accounts.approve_consultants": "all",
           "accounts.requests_view": "all",
           "postings.assign_others": "all", "feedback.manage": "all"}),
    "head_of_unit": {
        "view.roster": "unit", "view.records": "unit", "view.history": "unit",
        "view.escalations": "unit", "export.scoped": "unit",
        "signoff.delegate": "unit", "accounts.approve_fellows": "all",
    },
    "professor": {"view.roster": "unit", "view.records": "unit", "export.scoped": "unit"},
    "consultant": {"signoff.approve": "all"},
    "fellow": {},
}

APPOINTMENT_TEMPLATE = {"hod": "hod", "coordinator": "coordinator", "head_of_unit": "head_of_unit"}


def default_template(key):
    return dict(DEFAULT_TEMPLATES.get(key, {}))


def _norm_scope(perm, scope):
    p = CATALOGUE_BY_KEY.get(perm)
    if not p or p["reserved"]:
        return None
    if scope == SCOPE_UNIT and p["scoped"]:
        return SCOPE_UNIT
    if scope in (SCOPE_ALL, SCOPE_UNIT):
        return SCOPE_ALL
    return None


def stored_template_changes(db, key):
    row = db.execute("SELECT changes FROM permission_templates WHERE role_key = ?", (key,)).fetchone()
    if not row:
        return {}
    try:
        v = json.loads(row["changes"])
        return v if isinstance(v, dict) else {}
    except (TypeError, ValueError):
        return {}


def template(db, key):
    """Shipped default with the Developer's stored differences laid over it."""
    out = default_template(key)
    for perm, scope in stored_template_changes(db, key).items():
        if scope == "off":
            out.pop(perm, None)
            continue
        n = _norm_scope(perm, scope)
        if n:
            out[perm] = n
    if key == "fellow":
        out = {k: v for k, v in out.items() if k in FELLOW_OK}
    return out


def all_templates(db):
    return {k: template(db, k) for k in TEMPLATE_KEYS}


def save_template(db, key, wanted, actor):
    """`wanted` is the complete desired {perm: scope}. Stores only how it
    differs from the shipped default. Returns (changed, error)."""
    if key not in TEMPLATE_META:
        return None, "Unknown template."
    if not isinstance(wanted, dict):
        return None, "Template must be a map of permission to scope."
    clean = {}
    for perm, scope in wanted.items():
        if perm not in CATALOGUE_BY_KEY or CATALOGUE_BY_KEY[perm]["reserved"]:
            return None, "'%s' cannot be part of a template." % perm
        if key == "fellow" and perm not in FELLOW_OK:
            return None, "A fellow cannot be given '%s'." % perm
        n = _norm_scope(perm, scope)
        if not n:
            return None, "Bad scope for '%s'." % perm
        clean[perm] = n
    default = default_template(key)
    changes = {}
    for perm in set(default) | set(clean):
        if perm in clean and default.get(perm) != clean[perm]:
            changes[perm] = clean[perm]
        elif perm not in clean and perm in default:
            changes[perm] = "off"
    before = template(db, key)
    now = datetime.datetime.utcnow().isoformat() + "Z"
    if changes:
        db.execute(
            "INSERT INTO permission_templates (role_key, changes, updated_at, updated_by) VALUES (?,?,?,?)"
            " ON CONFLICT(role_key) DO UPDATE SET changes = excluded.changes,"
            " updated_at = excluded.updated_at, updated_by = excluded.updated_by",
            (key, json.dumps(changes), now, actor))
    else:
        db.execute("DELETE FROM permission_templates WHERE role_key = ?", (key,))
    after = template(db, key)
    diff = {p: {"from": before.get(p), "to": after.get(p)}
            for p in set(before) | set(after) if before.get(p) != after.get(p)}
    if diff:
        audit(db, actor, "template", key, "template_changed", diff)
    invalidate()
    return diff, None


def reset_template(db, key, actor):
    before = template(db, key)
    db.execute("DELETE FROM permission_templates WHERE role_key = ?", (key,))
    after = template(db, key)
    diff = {p: {"from": before.get(p), "to": after.get(p)}
            for p in set(before) | set(after) if before.get(p) != after.get(p)}
    audit(db, actor, "template", key, "template_reset", diff)
    invalidate()
    return diff


# ---------------------------------------------------------------- overrides
def overrides_for(db, username):
    rows = db.execute(
        "SELECT * FROM permission_overrides WHERE username = ? ORDER BY perm", (username,)).fetchall()
    out = []
    for r in rows:
        try:
            units = json.loads(r["units"]) if r["units"] else None
        except (TypeError, ValueError):
            units = None
        out.append({"perm": r["perm"], "effect": r["effect"], "scope": r["scope"],
                    "units": units, "note": r["note"], "setBy": r["set_by"], "setAt": r["set_at"]})
    return out


def set_override(db, username, perm, effect, scope, units, note, actor, known_units):
    """effect: 'grant' | 'deny' | 'clear'. Returns error string or None."""
    row = db.execute("SELECT role FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        return "No such account."
    if row["role"] == "developer":
        return "A Developer already holds every permission."
    if perm not in CATALOGUE_BY_KEY:
        return "Unknown permission."
    if CATALOGUE_BY_KEY[perm]["reserved"]:
        return "That permission is reserved for the Developer."
    if effect == "clear":
        had = db.execute("SELECT effect FROM permission_overrides WHERE username = ? AND perm = ?",
                         (username, perm)).fetchone()
        db.execute("DELETE FROM permission_overrides WHERE username = ? AND perm = ?", (username, perm))
        if had:
            audit(db, actor, "user", username, "override_cleared", {"perm": perm, "was": had["effect"]})
        invalidate(username)
        return None
    if effect not in ("grant", "deny"):
        return "Effect must be grant, deny or clear."
    if effect == "grant" and not eligible(row["role"], perm):
        if row["role"] in ("resident", "senior_resident"):
            return "Residents and Senior Residents cannot hold delegated permissions."
        return "A %s cannot hold '%s'." % (row["role"], CATALOGUE_BY_KEY[perm]["label"])
    sc = _norm_scope(perm, scope) or SCOPE_ALL
    ulist = None
    if effect == "grant" and sc == SCOPE_UNIT and units:
        if not isinstance(units, list) or not all(isinstance(u, str) for u in units):
            return "Units must be a list of unit keys."
        bad = [u for u in units if u not in known_units]
        if bad:
            return "Unknown unit: %s." % bad[0]
        ulist = sorted(set(units))
    now = datetime.datetime.utcnow().isoformat() + "Z"
    db.execute(
        "INSERT INTO permission_overrides (username, perm, effect, scope, units, note, set_by, set_at)"
        " VALUES (?,?,?,?,?,?,?,?)"
        " ON CONFLICT(username, perm) DO UPDATE SET effect = excluded.effect, scope = excluded.scope,"
        " units = excluded.units, note = excluded.note, set_by = excluded.set_by, set_at = excluded.set_at",
        (username, perm, effect, sc, json.dumps(ulist) if ulist else None,
         (note or None), actor, now))
    audit(db, actor, "user", username, "override_" + effect,
          {"perm": perm, "scope": sc, "units": ulist, "note": note or None})
    invalidate(username)
    return None


def audit(db, actor, target_kind, target, action, detail):
    db.execute(
        "INSERT INTO permission_audit (actor_username, target_kind, target, action, detail, at)"
        " VALUES (?,?,?,?,?,?)",
        (actor, target_kind, target, action, json.dumps(detail),
         datetime.datetime.utcnow().isoformat() + "Z"))


# --------------------------------------------------------------- appointments
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


def active_role_assignments(username):
    db = get_db()
    rows = db.execute("SELECT * FROM role_assignments WHERE consultant_username = ?", (username,)).fetchall()
    return [dict(r) for r in rows if is_assignment_active(dict(r))]


# -------------------------------------------------------------------- engine
# Computed per request and memoised on flask.g so a handler that asks ten
# questions pays for one computation. Anything that changes permissions or
# appointments calls invalidate().
try:
    from flask import g, has_app_context
except Exception:  # pragma: no cover
    g = None

    def has_app_context():
        return False


def _memo():
    if not has_app_context():
        return {}
    if not hasattr(g, "_perm_memo"):
        g._perm_memo = {}
    return g._perm_memo


def invalidate(username=None):
    if has_app_context() and hasattr(g, "_perm_memo"):
        if username is None:
            g._perm_memo = {}
        else:
            g._perm_memo.pop(username, None)


def _grant(acc, perm, scope, units, source):
    cur = acc.setdefault(perm, {"scope": None, "units": set(), "sources": []})
    if scope == SCOPE_ALL:
        cur["scope"] = SCOPE_ALL
    elif cur["scope"] != SCOPE_ALL:
        cur["scope"] = SCOPE_UNIT
        cur["units"] |= set(units)
    if source not in cur["sources"]:
        cur["sources"].append(source)


def compute(username):
    """{perm: {"scope", "units", "sources"}} for one account, with every
    layer applied. A unit-scoped permission with no units resolves to nothing."""
    memo = _memo()
    if username in memo:
        return memo[username]
    db = get_db()
    row = db.execute("SELECT role, unit, designation FROM users WHERE username = ?", (username,)).fetchone()
    acc = {}
    if not row:
        memo[username] = acc
        return acc
    role = row["role"]
    if role == "developer":
        for k in ALL_KEYS:
            if k in SEPARATED:
                continue
            acc[k] = {"scope": SCOPE_ALL, "units": set(), "sources": ["Developer"]}
        memo[username] = acc
        return acc
    home = [row["unit"]] if row["unit"] else []
    tpls = all_templates(db)

    def apply(tpl_key, units_for_unit_scope, source):
        for perm, scope in tpls[tpl_key].items():
            if not eligible(role, perm):
                continue
            _grant(acc, perm, scope, units_for_unit_scope, source)

    if role == "consultant":
        for a in active_role_assignments(username):
            key = APPOINTMENT_TEMPLATE.get(a["assignment_role"])
            if not key:
                continue
            units = [a["unit"]] if a.get("unit") else home
            label = TEMPLATE_META[key][0] + ((" · " + a["unit"]) if a.get("unit") else "")
            apply(key, units, label)
        if (row["designation"] or "").strip().lower() == "professor":
            apply("professor", home, "Professor designation")
        apply("consultant", home, "Every consultant")
    elif role == "fellow":
        apply("fellow", home, "Every fellow")

    denied = set()
    for o in overrides_for(db, username):
        if o["effect"] == "deny":
            denied.add(o["perm"])
        elif eligible(role, o["perm"]):
            units = o["units"] if o["units"] else home
            _grant(acc, o["perm"], o["scope"], units, "Granted individually")
    for perm in denied:
        acc.pop(perm, None)
    # A unit-scoped permission with nowhere to apply is no permission.
    for perm in list(acc):
        if acc[perm]["scope"] == SCOPE_UNIT and not acc[perm]["units"]:
            del acc[perm]
    memo[username] = acc
    return acc


def can(username, perm):
    return perm in compute(username)


def scope_for(username, perm):
    """{"full": bool, "units": [...]} -- 'full' means department-wide."""
    p = compute(username).get(perm)
    if not p:
        return {"full": False, "units": []}
    if p["scope"] == SCOPE_ALL:
        return {"full": True, "units": []}
    return {"full": False, "units": sorted(p["units"])}


def in_scope(username, perm, unit):
    """May this person use `perm` on something that belongs to `unit`?"""
    p = compute(username).get(perm)
    if not p:
        return False
    if p["scope"] == SCOPE_ALL:
        return True
    return bool(unit) and unit in p["units"]


def explain(db, username):
    """Everything the Developer panel shows for one person."""
    row = db.execute("SELECT role FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        return None
    eff = compute(username)
    ov = {o["perm"]: o for o in overrides_for(db, username)}
    out = []
    for p in CATALOGUE:
        e = eff.get(p["key"])
        out.append({
            "key": p["key"], "group": p["group"], "label": p["label"],
            "reserved": p["reserved"], "scoped": p["scoped"],
            "eligible": eligible(row["role"], p["key"]) or row["role"] == "developer",
            "effective": (e["scope"] if e else None),
            "units": (sorted(e["units"]) if e else []),
            "sources": (e["sources"] if e else []),
            "override": ov.get(p["key"]),
        })
    return {"role": row["role"], "permissions": out,
            "appointments": [{"role": a["assignment_role"], "unit": a["unit"],
                              "startAt": a["start_at"], "endAt": a["end_at"]}
                             for a in active_role_assignments(username)]}


def public_map(username):
    """What the browser is sent: {perm: {"scope": "all"|"unit", "units": [...]}}.
    Used only to decide which buttons to draw -- the server re-checks every
    request."""
    return {k: {"scope": v["scope"], "units": sorted(v["units"])}
            for k, v in compute(username).items()}
