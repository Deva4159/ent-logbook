"""Alerts (v7.4).

Two kinds share one table:

* MANUAL alerts are written by the Developer and aimed at an audience.
* SYSTEM alerts are raised and cleared automatically from facts already in
  the database: a posting about to end, an appointment about to lapse, a post
  nobody holds, a backup that is overdue.

There is no scheduler. Render has no cron and the free tier sleeps, so the
system alerts are produced by sweep(), which runs on request (at most once
every few minutes per process) -- the same pattern as run_due_deletions. The
honest consequence: if nobody opens the app, nothing is raised until
somebody does. For this department that is fine, because an alert nobody is
online to read has no reader anyway; it would matter for the e-mail/SMS
reminders described in the README, which need an outside trigger.

AUDIENCE (stored as JSON on the alert)
--------------------------------------
    {"all": true}                                   everyone
    {"users": ["a","b"]}                            these accounts
    {"perm": "postings.assign_others"}              everyone who holds this permission
    {"roles": [...], "units": [...]}                roles AND units together
Clauses are OR'd except roles/units, which narrow each other: roles=[fellow],
units=[ent2] means "fellows in ENT 2", not "all fellows and everyone in ENT
2". Roles are the account kinds (resident, senior_resident, fellow,
consultant, developer) plus the appointments hod, coordinator, head_of_unit.
A person's unit is their home unit and, for a trainee, the unit they are
posted to today.
"""
import datetime
import json
import time

import courses as courses_mod
import perms

SEVERITIES = ("info", "warning", "urgent")
ACCOUNT_ROLES = ("resident", "senior_resident", "fellow", "consultant", "developer")
APPOINTMENT_ROLES = ("hod", "coordinator", "head_of_unit")

DEFAULT_RULES = {
    "posting_ending": {"enabled": True, "leadDays": 7,
                       "label": "A posting is about to end"},
    "unposted": {"enabled": True,
                 "label": "A trainee has no current posting"},
    "appointment_ending": {"enabled": True, "leadDays": 30,
                           "label": "An appointment (HOD, Coordinator, Head of Unit) is about to end"},
    "vacancies": {"enabled": True,
                  "label": "A post has nobody in it (HOD, Coordinator, a unit's Head)"},
    "course_ending": {"enabled": True, "leadDays": 60,
                      "label": "A trainee's course is about to finish"},
    "backup_due": {"enabled": True, "everyDays": 7,
                   "label": "A backup has not been downloaded recently"},
}

SWEEP_EVERY_SECONDS = 300
_last_sweep = 0.0


def _now():
    return datetime.datetime.utcnow().isoformat() + "Z"


# ----------------------------------------------------------------- settings
def system_settings(db):
    row = db.execute("SELECT data FROM config WHERE id = 'system'").fetchone()
    try:
        return json.loads(row["data"]) if row else {}
    except (TypeError, ValueError):
        return {}


def save_system_settings(db, data):
    db.execute("INSERT INTO config (id, data) VALUES ('system', ?)"
               " ON CONFLICT(id) DO UPDATE SET data = excluded.data", (json.dumps(data),))


def get_rules(db):
    saved = system_settings(db).get("alertRules") or {}
    out = {}
    for k, d in DEFAULT_RULES.items():
        r = dict(d)
        s = saved.get(k)
        if isinstance(s, dict):
            if isinstance(s.get("enabled"), bool):
                r["enabled"] = s["enabled"]
            for num in ("leadDays", "everyDays"):
                if num in d and isinstance(s.get(num), int) and not isinstance(s.get(num), bool) \
                        and 0 <= s[num] <= 365:
                    r[num] = s[num]
        out[k] = r
    return out


def save_rules(db, body):
    if not isinstance(body, dict):
        return None, "Malformed rules."
    current = get_rules(db)
    for k, v in body.items():
        if k not in current or not isinstance(v, dict):
            continue
        if "enabled" in v:
            if not isinstance(v["enabled"], bool):
                return None, "enabled must be true or false."
            current[k]["enabled"] = v["enabled"]
        for num, lo in (("leadDays", 1), ("everyDays", 0)):
            if num in v and num in DEFAULT_RULES[k]:
                x = v[num]
                if isinstance(x, bool) or not isinstance(x, int) or not (lo <= x <= 365):
                    return None, "%s must be a whole number from %d to 365." % (num, lo)
                current[k][num] = x
    s = system_settings(db)
    s["alertRules"] = {k: {kk: vv for kk, vv in v.items() if kk != "label"} for k, v in current.items()}
    save_system_settings(db, s)
    return current, None


# ----------------------------------------------------------------- audience
def clean_audience(raw, known_units):
    """(audience, error). Normalises whatever the form sent."""
    if not isinstance(raw, dict):
        return None, "Choose who this is for."
    out = {}
    if raw.get("all"):
        out["all"] = True
    for key in ("roles", "units", "users"):
        v = raw.get(key)
        if v in (None, []):
            continue
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v) or len(v) > 500:
            return None, "%s must be a list." % key
        out[key] = sorted(set(x.strip() for x in v if x.strip()))
    p = raw.get("perm")
    if p:
        if p not in perms.CATALOGUE_BY_KEY:
            return None, "Unknown permission."
        out["perm"] = p
    for r in out.get("roles", []):
        if r not in ACCOUNT_ROLES + APPOINTMENT_ROLES:
            return None, "Unknown role '%s'." % r
    for u in out.get("units", []):
        if u not in known_units:
            return None, "Unknown unit '%s'." % u
    if not out:
        return None, "Choose who this is for."
    return out, None


def _attrs(db, row, today):
    """What an audience can match on, for one account."""
    username = row["username"]
    units = set()
    if row["unit"]:
        units.add(row["unit"])
    if row["role"] in perms.TRAINEE_ROLES:
        for p in db.execute(
                "SELECT unit FROM postings WHERE username = ? AND start_date <= ?"
                " AND (end_date IS NULL OR end_date >= ?)", (username, today, today)):
            units.add(p["unit"])
    appts = set()
    for a in perms.active_role_assignments(username):
        appts.add(a["assignment_role"])
    return {"username": username, "role": row["role"], "units": units, "appts": appts}


def matches(aud, at):
    if aud.get("all"):
        return True
    if at["username"] in (aud.get("users") or []):
        return True
    if aud.get("perm") and perms.can(at["username"], aud["perm"]):
        return True
    roles, units = aud.get("roles") or [], aud.get("units") or []
    if roles or units:
        role_ok = (not roles) or at["role"] in roles or bool(at["appts"] & set(roles))
        unit_ok = (not units) or bool(at["units"] & set(units))
        return role_ok and unit_ok
    return False


def _live_users(db):
    return db.execute(
        "SELECT username, role, unit FROM users WHERE approval_status = 'approved'"
        " AND active = 1 AND lifecycle = 'active'").fetchall()


def recipients(db, aud):
    today = datetime.date.today().isoformat()
    out = []
    for r in _live_users(db):
        if matches(aud, _attrs(db, r, today)):
            out.append(r["username"])
    return out


# --------------------------------------------------------------- reading
def _alert_dict(r, read_row):
    return {
        "id": r["id"], "kind": r["kind"], "rule": r["rule"], "title": r["title"],
        "body": r["body"] or "", "severity": r["severity"], "linkView": r["link_view"],
        "createdAt": r["created_at"], "expiresAt": r["expires_at"],
        "read": bool(read_row and read_row["read_at"]),
        "dismissed": bool(read_row and read_row["dismissed_at"]),
    }


def _live_rows(db):
    now = _now()
    return db.execute(
        "SELECT * FROM alerts WHERE active = 1 AND resolved_at IS NULL"
        " AND (starts_at IS NULL OR starts_at <= ?) AND (expires_at IS NULL OR expires_at > ?)"
        " ORDER BY id DESC", (now, now)).fetchall()


def visible_for(db, username):
    me = db.execute("SELECT username, role, unit FROM users WHERE username = ?", (username,)).fetchone()
    if not me:
        return []
    at = _attrs(db, me, datetime.date.today().isoformat())
    reads = {r["alert_id"]: r for r in db.execute(
        "SELECT * FROM alert_reads WHERE username = ?", (username,))}
    sev = {"urgent": 0, "warning": 1, "info": 2}
    out = []
    for r in _live_rows(db):
        try:
            aud = json.loads(r["audience"])
        except (TypeError, ValueError):
            continue
        if not matches(aud, at):
            continue
        d = _alert_dict(r, reads.get(r["id"]))
        if d["dismissed"]:
            continue
        out.append(d)
    out.sort(key=lambda d: (d["read"], sev.get(d["severity"], 3), -d["id"]))
    return out


def mark(db, username, alert_id, what):
    """what: 'read' | 'dismiss' | 'unread'. Only for an alert the user can see."""
    ids = {a["id"] for a in visible_for(db, username)}
    if alert_id not in ids:
        return False
    now = _now()
    if what == "unread":
        db.execute("UPDATE alert_reads SET read_at = NULL WHERE alert_id = ? AND username = ?",
                   (alert_id, username))
        return True
    db.execute("INSERT OR IGNORE INTO alert_reads (alert_id, username) VALUES (?,?)", (alert_id, username))
    if what == "dismiss":
        db.execute("UPDATE alert_reads SET dismissed_at = ?, read_at = COALESCE(read_at, ?)"
                   " WHERE alert_id = ? AND username = ?", (now, now, alert_id, username))
    else:
        db.execute("UPDATE alert_reads SET read_at = COALESCE(read_at, ?) WHERE alert_id = ? AND username = ?",
                   (now, alert_id, username))
    return True


# ----------------------------------------------------------------- sweep
def _fmt(d):
    try:
        return datetime.date.fromisoformat(d[:10]).strftime("%d %b %Y").lstrip("0")
    except (TypeError, ValueError):
        return d or ""


def _unit_name(units_cfg, key):
    for u in units_cfg:
        if isinstance(u, dict) and u.get("key") == key:
            return u.get("shortForm") or u.get("fullName") or key
    return key or "no unit"


def _names(db, usernames, limit=12):
    out = []
    for u in usernames[:limit]:
        r = db.execute("SELECT display_name FROM users WHERE username = ?", (u,)).fetchone()
        out.append(r["display_name"] if r else u)
    extra = len(usernames) - limit
    return ", ".join(out) + (" and %d more" % extra if extra > 0 else "")


def _wanted(db, rules):
    """{dedupe_key: alert dict} -- everything that is true right now."""
    from api import get_config  # lazy: api imports this module
    today = datetime.date.today()
    iso = today.isoformat()
    cfg = get_config()
    units_cfg = cfg.get("units") if isinstance(cfg.get("units"), list) else []
    want = {}

    def add(key, rule, title, body, severity, audience, link=None):
        want[key] = {"rule": rule, "title": title, "body": body, "severity": severity,
                     "audience": audience, "link": link}

    trainees = db.execute(
        "SELECT username, display_name, role, course_id, joined_ym, unit FROM users"
        " WHERE role IN ('resident','senior_resident','fellow') AND approval_status = 'approved'"
        " AND active = 1 AND lifecycle = 'active'").fetchall()
    tnames = {t["username"]: t["display_name"] for t in trainees}

    # -- postings ending ------------------------------------------------
    r = rules["posting_ending"]
    if r["enabled"]:
        horizon = (today + datetime.timedelta(days=r["leadDays"])).isoformat()
        rows = db.execute(
            "SELECT id, username, unit, end_date FROM postings WHERE end_date IS NOT NULL"
            " AND end_date >= ? AND end_date <= ? ORDER BY end_date", (iso, horizon)).fetchall()
        rows = [x for x in rows if x["username"] in tnames]
        for x in rows:
            add("posting_ending:%d:%s" % (x["id"], x["end_date"]), "posting_ending",
                "Your posting in %s ends on %s" % (_unit_name(units_cfg, x["unit"]), _fmt(x["end_date"])),
                "Add your next posting so entries logged after that date are filed under the right unit.",
                "warning", {"users": [x["username"]]}, "postings")
        if rows:
            who = ["%s – %s, %s" % (tnames[x["username"]], _unit_name(units_cfg, x["unit"]),
                                        _fmt(x["end_date"])) for x in rows[:12]]
            add("posting_ending:summary", "posting_ending",
                "%d posting%s ending within %d days" % (len(rows), "" if len(rows) == 1 else "s", r["leadDays"]),
                "; ".join(who) + ("; and %d more" % (len(rows) - 12) if len(rows) > 12 else ""),
                "info", {"perm": "postings.assign_others"}, "bulkPostings")

    # -- trainees with no current posting --------------------------------
    r = rules["unposted"]
    if r["enabled"]:
        posted = {x["username"] for x in db.execute(
            "SELECT DISTINCT username FROM postings WHERE start_date <= ?"
            " AND (end_date IS NULL OR end_date >= ?)", (iso, iso))}
        un = [t["username"] for t in trainees if t["username"] not in posted]
        for u in un:
            add("unposted:%s" % u, "unposted", "You have no current posting",
                "Entries you log are filed without a unit, so your Head of Unit cannot see them. "
                "Add where you are posted now.", "warning", {"users": [u]}, "postings")
        if un:
            add("unposted:summary", "unposted",
                "%d trainee%s with no current posting" % (len(un), "" if len(un) == 1 else "s"),
                _names(db, un), "warning", {"perm": "postings.assign_others"}, "bulkPostings")

    # -- appointments ending ---------------------------------------------
    r = rules["appointment_ending"]
    if r["enabled"]:
        horizon = (today + datetime.timedelta(days=r["leadDays"])).isoformat()
        for a in db.execute("SELECT * FROM role_assignments WHERE end_at IS NOT NULL AND end_at != ''"):
            a = dict(a)
            end = (a["end_at"] or "")[:10]
            if not perms.is_assignment_active(a) or not (iso <= end <= horizon):
                continue
            title = {"hod": "Head of Department", "coordinator": "Course Coordinator",
                     "head_of_unit": "Head of Unit"}.get(a["assignment_role"], a["assignment_role"])
            where = (" – " + _unit_name(units_cfg, a["unit"])) if a["unit"] else ""
            nm = a["consultant_display_name"] or a["consultant_username"]
            add("appointment_ending:%d:%s" % (a["id"], end), "appointment_ending",
                "%s appointment%s ends on %s" % (title, where, _fmt(end)),
                "%s holds it now. Once it ends the permissions that come with it go too; "
                "appoint a successor or extend the end date." % nm,
                "warning", {"users": [a["consultant_username"]], "roles": ["developer"]}, "appointments")

    # -- vacancies -------------------------------------------------------
    r = rules["vacancies"]
    if r["enabled"]:
        have = {}
        for a in db.execute("SELECT * FROM role_assignments"):
            a = dict(a)
            if perms.is_assignment_active(a):
                have.setdefault(a["assignment_role"], set()).add(a["unit"] or "")
        aud = {"roles": ["developer", "hod", "coordinator"]}
        if "hod" not in have:
            add("vacancy:hod", "vacancies", "No Head of Department is appointed",
                "Nobody holds an active HOD appointment, so the HOD-only decisions "
                "(a trainee's closure, profile edits) have no one to make them.",
                "urgent", {"roles": ["developer"]}, "appointments")
        if "coordinator" not in have:
            add("vacancy:coordinator", "vacancies", "No Course Coordinator is appointed",
                "Nobody holds an active Coordinator appointment.", "warning", aud, "appointments")
        busy_units = set()
        for u in db.execute("SELECT DISTINCT unit FROM users WHERE role = 'consultant' AND unit IS NOT NULL"
                            " AND active = 1 AND lifecycle = 'active'"):
            busy_units.add(u["unit"])
        for u in db.execute("SELECT DISTINCT unit FROM postings WHERE start_date <= ?"
                            " AND (end_date IS NULL OR end_date >= ?)", (iso, iso)):
            busy_units.add(u["unit"])
        known = {u.get("key") for u in units_cfg if isinstance(u, dict)}
        heads = have.get("head_of_unit", set())
        for unit in sorted(busy_units & known):
            if unit not in heads:
                add("vacancy:hou:%s" % unit, "vacancies",
                    "%s has no Head of Unit" % _unit_name(units_cfg, unit),
                    "People work in this unit but nobody holds an active Head of Unit appointment for it, "
                    "so no one can see its roster or sign off for an absent consultant.",
                    "warning", aud, "appointments")

    # -- course ending ---------------------------------------------------
    r = rules["course_ending"]
    if r["enabled"]:
        by_id = {c["id"]: c for c in courses_mod.list_courses(db)}
        ending = []
        for t in trainees:
            c = by_id.get(t["course_id"])
            pr = courses_mod.progress(c, t["joined_ym"], today) if c else None
            if not pr or pr["status"] != "in_progress":
                continue
            y, m = int(pr["expectedEndYm"][:4]), int(pr["expectedEndYm"][5:])
            end_day = datetime.date(y, m, 1) - datetime.timedelta(days=1)   # last day of the final month
            days = (end_day - today).days
            if 0 <= days <= r["leadDays"]:
                ending.append((t, c, pr, end_day))
        for t, c, pr, end_day in ending:
            add("course_ending:%s:%s" % (t["username"], pr["expectedEndYm"]), "course_ending",
                "%s finishes around %s" % (c["name"], end_day.strftime("%b %Y")),
                "Check your logbook is complete and signed off before then.",
                "info", {"users": [t["username"]]}, None)
        if ending:
            add("course_ending:summary", "course_ending",
                "%d trainee%s finishing within %d days" % (len(ending), "" if len(ending) == 1 else "s", r["leadDays"]),
                "; ".join("%s – %s" % (t["display_name"], e.strftime("%b %Y")) for t, c, p, e in ending[:12]),
                "info", {"roles": ["hod", "coordinator"]}, None)

    # -- backup due ------------------------------------------------------
    r = rules["backup_due"]
    if r["enabled"] and r["everyDays"] > 0:
        last = db.execute("SELECT at, actor_username FROM backup_log WHERE kind = 'download'"
                          " ORDER BY id DESC LIMIT 1").fetchone()
        if not last:
            add("backup_due", "backup_due", "No backup has ever been downloaded",
                "The database lives on one disk. If that disk is lost, so is every record. "
                "Download a backup from Developer → Backups.", "urgent",
                {"roles": ["developer"]}, "backup")
        else:
            try:
                age = (datetime.datetime.utcnow()
                       - datetime.datetime.fromisoformat(last["at"].replace("Z", ""))).days
            except ValueError:
                age = 9999
            if age >= r["everyDays"]:
                add("backup_due", "backup_due", "Backup due – last one was %d days ago" % age,
                    "The last backup was downloaded on %s. Download a new one from "
                    "Developer → Backups." % _fmt(last["at"]),
                    "urgent" if age >= 3 * r["everyDays"] else "warning",
                    {"roles": ["developer"]}, "backup")
    return want


def sweep(db, force=False):
    """Bring the system alerts in line with the facts. Safe to call from two
    workers at once (dedupe_key is UNIQUE). Returns counts."""
    global _last_sweep
    if not force and time.monotonic() - _last_sweep < SWEEP_EVERY_SECONDS:
        return None
    _last_sweep = time.monotonic()
    rules = get_rules(db)
    want = _wanted(db, rules)
    now = _now()
    raised = updated = resolved = 0
    for key, a in want.items():
        row = db.execute("SELECT id, resolved_at, title, body, severity FROM alerts WHERE dedupe_key = ?",
                         (key,)).fetchone()
        aud = json.dumps(a["audience"], sort_keys=True)
        if row is None:
            db.execute(
                "INSERT OR IGNORE INTO alerts (kind, rule, dedupe_key, title, body, severity, audience,"
                " link_view, active, created_by, created_at) VALUES ('system',?,?,?,?,?,?,?,1,'system',?)",
                (a["rule"], key, a["title"], a["body"], a["severity"], aud, a["link"], now))
            raised += 1
        elif row["resolved_at"]:
            # The condition came back: raise it again from scratch, so anyone
            # who dismissed the earlier occurrence is told again.
            db.execute("DELETE FROM alert_reads WHERE alert_id = ?", (row["id"],))
            db.execute("UPDATE alerts SET resolved_at = NULL, title = ?, body = ?, severity = ?,"
                       " audience = ?, link_view = ?, created_at = ?, updated_at = ? WHERE id = ?",
                       (a["title"], a["body"], a["severity"], aud, a["link"], now, now, row["id"]))
            raised += 1
        elif (row["title"], row["body"], row["severity"]) != (a["title"], a["body"], a["severity"]):
            db.execute("UPDATE alerts SET title = ?, body = ?, severity = ?, audience = ?, updated_at = ?"
                       " WHERE id = ?", (a["title"], a["body"], a["severity"], aud, now, row["id"]))
            updated += 1
    for row in db.execute("SELECT id, dedupe_key FROM alerts WHERE kind = 'system'"
                          " AND resolved_at IS NULL").fetchall():
        if row["dedupe_key"] not in want:
            db.execute("UPDATE alerts SET resolved_at = ?, updated_at = ? WHERE id = ?", (now, now, row["id"]))
            resolved += 1
    # Old, resolved system alerts are noise; keep two months for the record.
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=60)).isoformat() + "Z"
    db.execute("DELETE FROM alerts WHERE kind = 'system' AND resolved_at IS NOT NULL AND resolved_at < ?",
               (cutoff,))
    db.commit()
    return {"raised": raised, "updated": updated, "resolved": resolved, "live": len(want)}
