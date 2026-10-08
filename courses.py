"""Courses (v7.4).

A course is what a trainee is enrolled in: how long it runs, which units it
rotates through, whether it has peripheral postings, and what each year of it
is called. Until now the app knew only three account kinds and a free-text
"PG year" label, so "the PG rotates through every unit and has peripheries,
the Fellow belongs to one unit and also has a peripheral posting" was a fact
in people's heads rather than something the app could check.

What a course drives
--------------------
* YEAR OF STUDY. Trainees give the month and year they joined; the year of
  study is computed from that and the course length, never typed. The same
  arithmetic is in app.js (studyProgress) and the two must agree -- the test
  suite pins a table of cases against both.
* WHERE POSTINGS MAY GO. department scope = any unit, except peripheral ones
  unless the course allows them. units scope = the course's own units (or,
  if it names none, the person's own home unit) plus peripherals if allowed.
  A posting outside that is not refused, it is flagged and needs a
  confirmation -- the same shape as an overlapping posting, because the aim is
  to catch a slip, not to stop a real arrangement.
* WHICH ENTRIES. Every entry is stamped with the course its author was on
  when it was logged, and existing entries are backfilled from their author's
  course, so exports and rosters can be cut by course.
"""
import datetime
import json
import math
import re

DEFAULT_COURSES = [
    # These are placeholders for the department to confirm, not facts about
    # the department. Durations in particular vary by programme and year.
    {"id": "pg", "name": "PG Residency", "short_name": "PG", "role": "resident",
     "duration_months": 36, "scope": "department", "units": [], "allow_peripheral": 1,
     "year_labels": ["JR-1", "JR-2", "JR-3"], "start_month": 1, "sort": 1,
     "notes": "Rotates through every unit, with peripheral postings."},
    {"id": "sr", "name": "Senior Residency", "short_name": "SR", "role": "senior_resident",
     "duration_months": 36, "scope": "department", "units": [], "allow_peripheral": 1,
     "year_labels": ["SR-1", "SR-2", "SR-3"], "start_month": 1, "sort": 2, "notes": ""},
    {"id": "fellowship", "name": "Fellowship", "short_name": "Fellow", "role": "fellow",
     "duration_months": 12, "scope": "units", "units": [], "allow_peripheral": 1,
     "year_labels": ["Fellow"], "start_month": 1, "sort": 3,
     "notes": "Belongs to the fellow's own unit, with a peripheral posting."},
]
ROLE_DEFAULT_COURSE = {"resident": "pg", "senior_resident": "sr", "fellow": "fellowship"}


def _j(v, default):
    try:
        out = json.loads(v) if isinstance(v, str) else v
        return out if isinstance(out, type(default)) else default
    except (TypeError, ValueError):
        return default


def row_to_course(r):
    return {
        "id": r["id"], "name": r["name"], "shortName": r["short_name"] or r["name"],
        "role": r["role"], "durationMonths": r["duration_months"], "scope": r["scope"],
        "units": _j(r["units"], []), "allowPeripheral": bool(r["allow_peripheral"]),
        "peripheralUnits": _j(r["peripheral_units"], []),
        "maxPeripheralMonths": r["max_peripheral_months"],
        "yearLabels": _j(r["year_labels"], []), "startMonth": r["start_month"],
        "notes": r["notes"] or "", "active": bool(r["active"]), "sort": r["sort"],
        "updatedAt": r["updated_at"], "updatedBy": r["updated_by"],
    }


def list_courses(db, active_only=False):
    sql = "SELECT * FROM courses" + (" WHERE active = 1" if active_only else "") + " ORDER BY sort, name"
    return [row_to_course(r) for r in db.execute(sql).fetchall()]


def get_course(db, course_id):
    if not course_id:
        return None
    r = db.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    return row_to_course(r) if r else None


def seed_and_backfill(conn):
    """Idempotent. Seeds the three default courses once, then attaches every
    trainee and every entry that has no course yet."""
    now = datetime.datetime.utcnow().isoformat() + "Z"
    flag = conn.execute("SELECT data FROM config WHERE id = 'system'").fetchone()
    system = _j(flag["data"], {}) if flag else {}
    if not system.get("coursesSeeded"):
        if conn.execute("SELECT COUNT(*) c FROM courses").fetchone()["c"] == 0:
            cfg_row = conn.execute("SELECT data FROM config WHERE id = 'lists'").fetchone()
            cfg = _j(cfg_row["data"], {}) if cfg_row else {}
            peripheral = [u["key"] for u in (cfg.get("units") or [])
                          if isinstance(u, dict) and u.get("group") == "Peripheral Postings"]
            pg_years = cfg.get("pgYears")
            for c in DEFAULT_COURSES:
                labels = c["year_labels"]
                if c["id"] == "pg" and isinstance(pg_years, list) and pg_years \
                        and all(isinstance(x, str) for x in pg_years):
                    labels = pg_years[:10]
                conn.execute(
                    "INSERT INTO courses (id, name, short_name, role, duration_months, scope, units,"
                    " allow_peripheral, peripheral_units, year_labels, start_month, notes, active, sort,"
                    " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
                    (c["id"], c["name"], c["short_name"], c["role"], c["duration_months"], c["scope"],
                     json.dumps(c["units"]), c["allow_peripheral"],
                     json.dumps(peripheral if c["allow_peripheral"] else []),
                     json.dumps(labels), c["start_month"], c["notes"], c["sort"], now))
        system["coursesSeeded"] = True
        conn.execute("INSERT INTO config (id, data) VALUES ('system', ?)"
                     " ON CONFLICT(id) DO UPDATE SET data = excluded.data", (json.dumps(system),))
    for role, cid in ROLE_DEFAULT_COURSE.items():
        if conn.execute("SELECT 1 FROM courses WHERE id = ?", (cid,)).fetchone():
            conn.execute("UPDATE users SET course_id = ? WHERE role = ? AND course_id IS NULL", (cid, role))
    if conn.execute("SELECT 1 FROM entries WHERE course_id IS NULL LIMIT 1").fetchone():
        conn.execute(
            "UPDATE entries SET course_id = (SELECT u.course_id FROM users u"
            " WHERE u.username = entries.author_username) WHERE course_id IS NULL")
    conn.commit()


# ------------------------------------------------------------ year of study
def _ym(v):
    m = re.fullmatch(r"(\d{4})-(\d{2})", v or "")
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2))
    return (y, mo) if 1 <= mo <= 12 and 1900 <= y <= 2200 else None


def normalise_join(value, start_month=1):
    """'2025' -> '2025-<start_month>'; '2025-08' stays. Returns (ym, error)."""
    if value is None or value == "":
        return None, None
    if not isinstance(value, str):
        return None, "Joining date must be a year or a year and month."
    v = value.strip()
    if re.fullmatch(r"\d{4}", v):
        v = "%s-%02d" % (v, start_month if 1 <= (start_month or 1) <= 12 else 1)
    p = _ym(v)
    if not p:
        return None, "Joining date must look like 2025 or 2025-08."
    today = datetime.date.today()
    if p[0] > today.year + 1:
        return None, "That joining year is in the future."
    return "%04d-%02d" % p, None


def progress(course, joined_ym, today=None):
    """Where a trainee is in their course. None when it cannot be known.

    Whole months from the START of the joining month: someone who joined in
    August is in Year 1 from August until the following July.
    """
    p = _ym(joined_ym)
    if not course or not p:
        return None
    today = today or datetime.date.today()
    months = (today.year - p[0]) * 12 + (today.month - p[1])
    total = course["durationMonths"]
    years = max(1, math.ceil(total / 12))
    end_total = p[0] * 12 + (p[1] - 1) + total
    end_ym = "%04d-%02d" % (end_total // 12, end_total % 12 + 1)
    labels = course.get("yearLabels") or []
    if months < 0:
        status, year = "not_started", 0
    elif months >= total:
        status, year = "completed", years
    else:
        status, year = "in_progress", months // 12 + 1
    label = None
    if year >= 1:
        label = labels[year - 1] if year - 1 < len(labels) and labels[year - 1] else "Year %d" % year
    return {
        "year": year, "years": years, "label": label, "status": status,
        "joinedYm": joined_ym, "expectedEndYm": end_ym,
        "monthsIn": max(0, months), "monthsLeft": max(0, total - max(0, months)),
    }


# ---------------------------------------------------------- where it may go
def allowed_units(course, home_unit, known_units):
    """Units a posting for someone on this course may go to without a flag.
    None means unrestricted (no course)."""
    if not course:
        return None
    known = set(known_units)
    peripheral = set(course["peripheralUnits"]) & known
    if course["scope"] == "department":
        base = known - peripheral
    else:
        base = (set(course["units"]) & known) or ({home_unit} if home_unit in known else set())
    if course["allowPeripheral"]:
        base = base | peripheral
    return base


def peripheral_days(postings, course, today=None):
    """Days already spent in this course's peripheral units (open-ended
    postings counted to today). Overlaps are not de-duplicated."""
    if not course:
        return 0
    today = today or datetime.date.today()
    per = set(course["peripheralUnits"])
    days = 0
    for p in postings:
        if p["unit"] not in per:
            continue
        try:
            a = datetime.date.fromisoformat(p["startDate"])
            b = datetime.date.fromisoformat(p["endDate"]) if p["endDate"] else today
        except (TypeError, ValueError):
            continue
        days += max(0, (b - a).days + 1)
    return days


def posting_flags(course, home_unit, known_units, existing_postings, unit, start_date, end_date, labels=None):
    """Reasons a new posting needs confirming. [] when it is fine.
    `labels` maps unit key -> display name for the messages."""
    flags = []
    label = (labels or {}).get(unit, unit)
    allowed = allowed_units(course, home_unit, known_units)
    if allowed is not None and unit not in allowed:
        if course["scope"] == "units":
            where = "its own unit" if not course["units"] else "its units"
            flags.append("%s is outside %s for %s." % (label, where, course["name"]))
        else:
            flags.append("%s is a peripheral unit and %s does not include peripheral postings."
                         % (label, course["name"]))
    cap = course["maxPeripheralMonths"] if course else None
    if course and cap and unit in set(course["peripheralUnits"]) and course["allowPeripheral"]:
        try:
            a = datetime.date.fromisoformat(start_date)
            b = datetime.date.fromisoformat(end_date) if end_date else a
            new_days = (b - a).days + 1
        except (TypeError, ValueError):
            new_days = 0
        used = peripheral_days(existing_postings, course)
        if (used + new_days) / 30.4 > cap:
            flags.append("Peripheral time would reach about %.1f months; %s allows %d."
                         % ((used + new_days) / 30.4, course["name"], cap))
    return flags


# ------------------------------------------------------------- validation
def validate_course(body, known_units, existing=None):
    """Returns (clean, error). `existing` set when editing."""
    if not isinstance(body, dict):
        return None, "Malformed course."

    def text(k, lim):
        v = body.get(k)
        return v.strip()[:lim] if isinstance(v, str) else ""

    name = text("name", 120)
    if not name:
        return None, "A course needs a name."
    role = body.get("role", existing["role"] if existing else None)
    if role not in ("resident", "senior_resident", "fellow"):
        return None, "A course is for Residents, Senior Residents or Fellows."
    try:
        dur = int(body.get("durationMonths"))
    except (TypeError, ValueError):
        return None, "Duration must be a whole number of months."
    if not (1 <= dur <= 120):
        return None, "Duration must be between 1 and 120 months."
    scope = body.get("scope")
    if scope not in ("department", "units"):
        return None, "Scope must be the whole department or particular units."
    units = body.get("units") or []
    if not isinstance(units, list) or not all(isinstance(u, str) for u in units):
        return None, "Units must be a list of unit keys."
    per = body.get("peripheralUnits") or []
    if not isinstance(per, list) or not all(isinstance(u, str) for u in per):
        return None, "Peripheral units must be a list of unit keys."
    for u in list(units) + list(per):
        if u not in known_units:
            return None, "Unknown unit '%s'." % u
    cap = body.get("maxPeripheralMonths")
    if cap in ("", None):
        cap = None
    else:
        try:
            cap = int(cap)
        except (TypeError, ValueError):
            return None, "Peripheral limit must be a whole number of months."
        if not (1 <= cap <= dur):
            return None, "Peripheral limit must be between 1 month and the course length."
    labels = body.get("yearLabels") or []
    if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels) or len(labels) > 12:
        return None, "Year labels must be a short list of names."
    labels = [x.strip()[:30] for x in labels]
    try:
        sm = int(body.get("startMonth") or 1)
    except (TypeError, ValueError):
        return None, "Start month must be 1 to 12."
    if not (1 <= sm <= 12):
        return None, "Start month must be 1 to 12."
    allow = bool(body.get("allowPeripheral"))
    clean = {
        "name": name, "short_name": text("shortName", 30) or name[:30], "role": role,
        "duration_months": dur, "scope": scope,
        "units": sorted(set(units)), "allow_peripheral": 1 if allow else 0,
        # Kept even when peripheral postings are switched off: the list is
        # what says WHICH units are peripheral, which is how the switch knows
        # what to refuse.
        "peripheral_units": sorted(set(per)),
        "max_peripheral_months": cap if allow else None,
        "year_labels": labels, "start_month": sm, "notes": text("notes", 600),
        "active": 0 if body.get("active") is False else 1,
    }
    return clean, None


def slug(name, taken):
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "course"
    out, n = base, 2
    while out in taken:
        out = "%s-%d" % (base, n)
        n += 1
    return out
