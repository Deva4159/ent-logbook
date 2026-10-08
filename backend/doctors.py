"""The department's doctors list (v7.5).

Why this exists
---------------
A logbook entry names the consultant who supervised the case and the people
who were in the room. Until v7.4 those were either an account (only if the
doctor had signed up) or free text (anything typed). Most consultants never
sign up, so most names were typed, spelled five different ways, and a record
"sent for sign-off" had nobody to receive it.

The list is a separate thing from accounts: a row is a *person*; an account is
a *login*. A row may have no account, and gets one later without the entries
that already name them being lost.

Invariants (enforced by the database, not by hope)
--------------------------------------------------
* a row links to at most one account  -- UNIQUE index on linked_username
* an account links to at most one row -- the same index, read the other way
* a row has at most one OPEN claim    -- partial UNIQUE index on doctor_claims
  (a pending self-claim or an unused invite), so two people cannot both be on
  their way to "being" the same doctor.

Account routes (both end in the same linked row)
------------------------------------------------
INVITE   The HOD / Developer types only a username for a listed doctor. That
         produces a one-time code. The doctor opens "I have an invite code",
         sets their OWN password and is in. The HOD never knows the password.
CLAIM    At sign-up the doctor picks their name from the list. The account is
         created as usual (pending) and the row is locked as "claim pending".
         The HOD / Developer approves or rejects; approving links the row and
         takes designation and unit FROM THE LIST, so a self-claim cannot
         award itself "Professor".

Until a row has an account
--------------------------
An entry that names such a doctor as approver is routed to the Head of Unit
for the entry's unit, or the HOD (the existing "sign off for an absent
approver" permission, nothing new). When the account is linked, entries still
waiting flip to the doctor.
"""
import datetime
import difflib
import hashlib
import json
import re
import secrets

# designation -> (rank, account kind)
DESIGNATIONS = [
    ("Professor", 5, "consultant"),
    ("Associate Professor", 4, "consultant"),
    ("Assistant Professor", 3, "consultant"),
    ("Consultant", 3, "consultant"),
    ("Fellow", 2, "fellow"),
    ("Senior Resident", 1, "senior_resident"),
]
_DESIG = {d.lower(): (r, k) for d, r, k in DESIGNATIONS}
LIST_ROLES = ("consultant", "fellow", "senior_resident")
APPROVER_MIN_RANK = 3          # a consultant; nobody below can be sent a sign-off by name alone
STRONG, POSSIBLE = 0.88, 0.72  # name similarity thresholds
INVITE_DAYS = 7
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

_ALIASES = {
    "prof": "Professor", "professor": "Professor",
    "assoc prof": "Associate Professor", "associate professor": "Associate Professor",
    "associate prof": "Associate Professor", "assoc professor": "Associate Professor",
    "asst prof": "Assistant Professor", "assistant professor": "Assistant Professor",
    "assistant prof": "Assistant Professor", "asst professor": "Assistant Professor",
    "consultant": "Consultant", "lecturer": "Consultant", "visiting consultant": "Consultant",
    "fellow": "Fellow", "fellowship": "Fellow",
    "sr": "Senior Resident", "senior resident": "Senior Resident",
}

_TITLES = {"dr", "doctor", "prof", "professor", "mr", "mrs", "ms", "miss", "md", "dnb",
           "mch", "mbbs", "ms.", "phd", "frcs", "dlo"}


def now_iso():
    return datetime.datetime.utcnow().isoformat() + "Z"


# ----------------------------------------------------------------- naming
def name_key(name):
    s = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower().replace(".", " "))
    toks = [t for t in s.split() if t not in _TITLES]
    return " ".join(toks)


def _tok_score(x, y):
    if x == y:
        return 1.0
    if len(x) == 1 or len(y) == 1:
        return 0.8 if x[0] == y[0] else 0.0
    r = difflib.SequenceMatcher(None, x, y).ratio()
    return r if r >= 0.8 else 0.0


def similarity(ka, kb):
    """0..1. Token-wise, so "A Kumar" ~ "Arun Kumar" and word order is
    ignored. An initial matches a full name only weakly (0.8), which is why a
    lone-initial match is a *prompt*, never an automatic merge."""
    ta, tb = ka.split(), kb.split()
    if not ta or not tb:
        return 0.0
    if ka == kb:
        return 1.0
    if len(ta) > len(tb):
        ta, tb = tb, ta
    used, total, hits = set(), 0.0, 0
    for x in ta:
        best, bi = 0.0, None
        for i, y in enumerate(tb):
            if i in used:
                continue
            s = _tok_score(x, y)
            if s > best:
                best, bi = s, i
        if bi is not None:
            used.add(bi)
            total += best
            hits += 1
    score = total / len(tb)
    if len(ta) >= 2 and hits == len(ta):
        score = max(score, 0.75)       # every word of the shorter name is in the longer one
    return min(score, 0.99) if ka != kb else 1.0


def normalise_designation(raw):
    """-> canonical designation or None."""
    s = re.sub(r"[^a-z ]+", " ", (raw or "").lower()).strip()
    s = re.sub(r"\s+", " ", s)
    if not s:
        return None
    if s in _ALIASES:
        return _ALIASES[s]
    if s in _DESIG:
        return [d for d, _, _ in DESIGNATIONS if d.lower() == s][0]
    return None


def rank_of(designation):
    r = _DESIG.get((designation or "").strip().lower())
    return r[0] if r else 0


def kind_of(designation):
    r = _DESIG.get((designation or "").strip().lower())
    return r[1] if r else "consultant"


# ------------------------------------------------------------------ rows
def _units(db, doctor_id):
    return [r["unit"] for r in db.execute(
        "SELECT unit FROM doctor_units WHERE doctor_id = ? ORDER BY unit", (doctor_id,))]


def _set_units(db, doctor_id, units):
    db.execute("DELETE FROM doctor_units WHERE doctor_id = ?", (doctor_id,))
    for u in dict.fromkeys(units or []):
        db.execute("INSERT OR IGNORE INTO doctor_units (doctor_id, unit) VALUES (?,?)", (doctor_id, u))


def _account_state(db, username):
    if not username:
        return "none"
    r = db.execute("SELECT active, lifecycle, approval_status FROM users WHERE username = ?",
                   (username,)).fetchone()
    if not r:
        return "none"
    if r["approval_status"] == "pending":
        return "pending"
    if r["lifecycle"] == "deleted":
        return "closed"
    return "active" if r["active"] else "inactive"


def can_receive_signoff(db, row, perms_mod):
    """Can a record be *sent* to this doctor? A linked doctor needs the
    sign-off permission on an active, approved account (the same test
    `_valid_approver` applies); an unlinked one is eligible if they are a
    consultant of this department -- the Head of Unit / HOD then acts for
    them until they have an account."""
    if row["status"] != "active":
        return False
    if row["department"] and row["department"].upper() != "ENT":
        return False
    if row["linked_username"]:
        u = row["linked_username"]
        r = db.execute("SELECT role, active, approval_status FROM users WHERE username = ?", (u,)).fetchone()
        return bool(r and r["role"] in ("consultant", "fellow") and r["active"]
                    and r["approval_status"] == "approved" and perms_mod.can(u, "signoff.approve"))
    return row["rank"] >= APPROVER_MIN_RANK


def doctor_dict(db, row, perms_mod, manager=False):
    d = {
        "id": row["id"],
        "displayName": row["display_name"],
        "designation": row["designation"],
        "rank": row["rank"],
        "homeUnit": row["home_unit"],
        "units": _units(db, row["id"]),
        "department": row["department"] or "ENT",
        "status": row["status"],
        "hasAccount": bool(row["linked_username"]),
        "linkedUsername": row["linked_username"],
        "accountState": _account_state(db, row["linked_username"]),
        "canSignOff": can_receive_signoff(db, row, perms_mod),
        "kind": kind_of(row["designation"]),
    }
    if manager:
        claim = open_claim(db, row["id"])
        d.update({
            "regNo": row["reg_no"], "email": row["email"], "phone": row["phone"],
            "notes": row["notes"], "source": row["source"],
            "createdAt": row["created_at"], "updatedAt": row["updated_at"],
            "claim": claim,
        })
    return d


def get(db, doctor_id):
    return db.execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)).fetchone()


def by_username(db, username):
    return db.execute("SELECT * FROM doctors WHERE linked_username = ?", (username,)).fetchone()


# ---------------------------------------------------------------- seeding
def _user_units(db, u):
    units = []
    if u["unit"]:
        units.append(u["unit"])
    today = datetime.date.today().isoformat()
    for r in db.execute(
            "SELECT DISTINCT unit FROM postings WHERE username = ? AND unit <> ''"
            " AND start_date <= ? AND (end_date IS NULL OR end_date >= ?)",
            (u["username"], today, today)):
        units.append(r["unit"])
    return list(dict.fromkeys(units))


def _default_designation(u):
    d = (u["designation"] or "").strip()
    if u["role"] == "consultant":
        return normalise_designation(d) or d or "Consultant"
    return "Fellow" if u["role"] == "fellow" else "Senior Resident"


def ensure_for_user(db, username, actor=None):
    """Give an account its list row, if it has none. Idempotent."""
    u = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not u or u["role"] not in LIST_ROLES or u["approval_status"] != "approved" \
            or u["lifecycle"] == "deleted":
        return None
    have = by_username(db, username)
    if have:
        return have["id"]
    desig = _default_designation(u)
    cur = db.execute(
        "INSERT INTO doctors (display_name, name_key, designation, rank, home_unit, status,"
        " linked_username, source, created_by, created_at) VALUES (?,?,?,?,?,'active',?,'account',?,?)",
        (u["display_name"], name_key(u["display_name"]), desig, rank_of(desig), u["unit"],
         username, actor, now_iso()))
    _set_units(db, cur.lastrowid, _user_units(db, u))
    return cur.lastrowid


def seed_from_users(db):
    n = 0
    for u in db.execute(
            "SELECT username FROM users WHERE role IN ('consultant','fellow','senior_resident')"
            " AND approval_status = 'approved' AND lifecycle <> 'deleted'"
            " AND username NOT IN (SELECT linked_username FROM doctors WHERE linked_username IS NOT NULL)"
    ).fetchall():
        if ensure_for_user(db, u["username"]):
            n += 1
    db.commit()
    return n


def sync_user(db, username):
    """An account's name / designation / unit changed: carry it to its row.
    Only rows that exist *because of* the account follow it; for a row the HOD
    typed first, the account is brought INTO LINE with the list when linked
    (see link()), and later edits to either happen on the account, which is
    the one that carries permissions. Units are only ever added to here."""
    row = by_username(db, username)
    u = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row or not u:
        return
    desig = _default_designation(u) if u["role"] in LIST_ROLES else row["designation"]
    db.execute(
        "UPDATE doctors SET display_name = ?, name_key = ?, designation = ?, rank = ?, home_unit = COALESCE(?, home_unit),"
        " updated_at = ? WHERE id = ?",
        (u["display_name"], name_key(u["display_name"]), desig, rank_of(desig), u["unit"],
         now_iso(), row["id"]))
    if u["unit"]:
        db.execute("INSERT OR IGNORE INTO doctor_units (doctor_id, unit) VALUES (?,?)", (row["id"], u["unit"]))


# ----------------------------------------------------------------- claims
def open_claim(db, doctor_id):
    expire_invites(db)
    c = db.execute("SELECT * FROM doctor_claims WHERE doctor_id = ? AND state IN ('pending','invited')",
                   (doctor_id,)).fetchone()
    if not c:
        return None
    return {"id": c["id"], "kind": c["kind"], "state": c["state"], "username": c["username"],
            "requestedBy": c["requested_by"], "requestedAt": c["requested_at"],
            "expiresAt": c["expires_at"]}


def expire_invites(db):
    db.execute("UPDATE doctor_claims SET state = 'expired', decided_at = ? WHERE state = 'invited'"
               " AND expires_at IS NOT NULL AND expires_at < ?", (now_iso(), now_iso()))


def invite_reserved(db, username, ignore_claim=None):
    """Is this username held for an invited doctor? (A pending self-claim
    already has a real, pending account row, so the ordinary check sees it.)"""
    expire_invites(db)
    r = db.execute("SELECT id FROM doctor_claims WHERE state = 'invited' AND lower(username) = lower(?)",
                   (username,)).fetchone()
    return bool(r and r["id"] != ignore_claim)


def _hash_code(code):
    norm = re.sub(r"[^A-Z0-9]", "", (code or "").upper())
    return hashlib.sha256(norm.encode()).hexdigest()


def new_code():
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(10))
    return raw[:5] + "-" + raw[5:]


def linkable(db, row):
    """(ok, reason). Can this row be given an account at all?"""
    if row["linked_username"]:
        return False, "This doctor already has an account."
    if row["status"] != "active":
        return False, "This doctor is marked as having left."
    if row["department"] and row["department"].upper() != "ENT":
        return False, "Only doctors of this department can have an account."
    if kind_of(row["designation"]) == "fellow" and not row["home_unit"]:
        return False, "Give this fellow a home unit before creating an account."
    return True, None


def create_invite(db, doctor_id, username, actor):
    """-> (result, error). `username` must be free everywhere, including
    against other invites. Returns the code ONCE; only its hash is kept."""
    import usernames
    row = get(db, doctor_id)
    if not row:
        return None, "No such doctor."
    ok, why = linkable(db, row)
    if not ok:
        return None, why
    clean, err = usernames.check_format(username)
    if err:
        return None, err
    status, detail = usernames.availability(db, clean)
    if status != "free":
        return None, "That username is not available: %s." % (detail or "taken")
    if open_claim(db, doctor_id):
        return None, "This doctor already has an open claim or invite. Cancel it first."
    code = new_code()
    exp = (datetime.datetime.utcnow() + datetime.timedelta(days=INVITE_DAYS)).isoformat() + "Z"
    db.execute(
        "INSERT INTO doctor_claims (doctor_id, kind, state, username, code_hash, expires_at,"
        " requested_by, requested_at) VALUES (?, 'invite', 'invited', ?,?,?,?,?)",
        (doctor_id, clean, _hash_code(code), exp, actor, now_iso()))
    return {"code": code, "username": clean, "expiresAt": exp}, None


def find_invite(db, code):
    expire_invites(db)
    return db.execute("SELECT * FROM doctor_claims WHERE state = 'invited' AND code_hash = ?",
                      (_hash_code(code),)).fetchone()


def cancel_claim(db, claim_id, actor, note=None):
    c = db.execute("SELECT * FROM doctor_claims WHERE id = ?", (claim_id,)).fetchone()
    if not c or c["state"] not in ("pending", "invited"):
        return False
    db.execute("UPDATE doctor_claims SET state = 'cancelled', decided_by = ?, decided_at = ?, note = ?"
               " WHERE id = ?", (actor, now_iso(), note, claim_id))
    return True


def start_self_claim(db, doctor_id, username):
    """Lock a row for a sign-up. -> (ok, error). Relies on the partial unique
    index for the race: two sign-ups arriving together, one loses."""
    row = get(db, doctor_id)
    if not row:
        return False, "That name is not on the list."
    ok, why = linkable(db, row)
    if not ok:
        return False, why
    try:
        db.execute(
            "INSERT INTO doctor_claims (doctor_id, kind, state, username, requested_by, requested_at)"
            " VALUES (?, 'self', 'pending', ?, ?, ?)", (doctor_id, username, username, now_iso()))
    except Exception as e:  # sqlite3.IntegrityError, kept generic to avoid an import cycle
        if "UNIQUE" in str(e).upper():
            return False, ("Someone has already asked for this name and it is waiting for the "
                           "Head of Department. If that was not you, tell them.")
        raise
    return True, None


def claim_for_user(db, username):
    return db.execute("SELECT * FROM doctor_claims WHERE state = 'pending' AND kind = 'self'"
                      " AND username = ?", (username,)).fetchone()


def role_matches(row, role):
    return kind_of(row["designation"]) == role


# ------------------------------------------------------------------ link
def link(db, doctor_id, username, actor, via):
    """Join a row to an account and carry everything that was waiting on the
    row across. Caller commits. Returns {entriesRouted, entriesNamed}."""
    row = get(db, doctor_id)
    u = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row or not u:
        raise ValueError("missing doctor or account")
    if row["linked_username"] and row["linked_username"] != username:
        raise ValueError("already linked")
    db.execute("UPDATE doctors SET linked_username = ?, updated_by = ?, updated_at = ? WHERE id = ?",
               (username, actor, now_iso(), doctor_id))
    # 1. sign-offs still waiting on this person now go to them.
    routed = 0
    for e in db.execute(
            "SELECT id, approval_state FROM entries WHERE approver_doctor_id = ?"
            " AND approval_state IN ('pending','changes_requested')", (doctor_id,)).fetchall():
        db.execute("UPDATE entries SET approver_username = ?, approver_doctor_id = NULL,"
                   " approver_name = NULL WHERE id = ?", (username, e["id"]))
        db.execute(
            "INSERT INTO entry_approvals (entry_id, action, actor_username, actor_role, approver_username,"
            " on_behalf_of, comment, edits_at_action, created_at, approver_label) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (e["id"], "reassigned", actor, None, username, None,
             "%s now has an account; the record has moved to them (%s)." % (row["display_name"], via),
             _max_edit(db, e["id"]), now_iso(), row["display_name"]))
        routed += 1
    # Approved ones keep the history they have; only the pointer is tidied so
    # the record reads "approved by <account>"-less but no longer dangling.
    db.execute("UPDATE entries SET approver_doctor_id = NULL WHERE approver_doctor_id = ?"
               " AND approval_state NOT IN ('pending','changes_requested')", (doctor_id,))
    # 2. entries that name the doctor as consultant gain the account.
    named = db.execute("UPDATE entries SET consultant_username = ? WHERE consultant_doctor_id = ?"
                       " AND (consultant_username IS NULL OR consultant_username = '')",
                       (username, doctor_id)).rowcount
    return {"entriesRouted": routed, "entriesNamed": named}


def _max_edit(db, entry_id):
    r = db.execute("SELECT COALESCE(MAX(id), 0) m FROM entry_edits WHERE entry_id = ?", (entry_id,)).fetchone()
    return r["m"] if r else 0


# --------------------------------------------------------- near-matching
def near_matches(db, display_name, units=None, limit=5):
    """Listed doctors (with or without an account) whose name resembles
    `display_name`. -> [{id, displayName, designation, score, strong,
    hasAccount}] best first. Used at sign-up and on bulk add."""
    k = name_key(display_name)
    if not k:
        return []
    out = []
    for r in db.execute("SELECT * FROM doctors WHERE status = 'active'").fetchall():
        s = similarity(k, r["name_key"])
        if s >= POSSIBLE:
            out.append({"id": r["id"], "displayName": r["display_name"],
                        "designation": r["designation"], "units": _units(db, r["id"]),
                        "score": round(s, 2), "strong": s >= STRONG,
                        "hasAccount": bool(r["linked_username"])})
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


# ---------------------------------------------------------------- picker
def picker(db, perms_mod, unit=None, date=None):
    """Every active doctor, each flagged `inUnit` for the posting unit, sorted
    highest rank first within the flag. The client groups; the payload is a
    department's worth of names, not a database."""
    date = date or datetime.date.today().isoformat()
    in_unit = set()
    if unit:
        in_unit |= {r["doctor_id"] for r in db.execute(
            "SELECT doctor_id FROM doctor_units WHERE unit = ?", (unit,))}
        # people who rotate: anyone linked and posted here on that date
        in_unit |= {r["id"] for r in db.execute(
            "SELECT d.id FROM doctors d JOIN postings p ON p.username = d.linked_username"
            " WHERE p.unit = ? AND p.start_date <= ? AND (p.end_date IS NULL OR p.end_date >= ?)",
            (unit, date, date))}
        in_unit |= {r["id"] for r in db.execute(
            "SELECT d.id FROM doctors d JOIN users u ON u.username = d.linked_username WHERE u.unit = ?",
            (unit,))}
    rows = db.execute("SELECT * FROM doctors WHERE status = 'active'").fetchall()
    out = []
    for r in rows:
        if r["linked_username"] and _account_state(db, r["linked_username"]) in ("closed", "pending"):
            continue
        d = doctor_dict(db, r, perms_mod)
        d["inUnit"] = r["id"] in in_unit
        out.append(d)
    out.sort(key=lambda d: (not d["inUnit"], -d["rank"], d["displayName"].lower()))
    return out


# ----------------------------------------------------------- entry people
def resolve_people(db, body, perms_mod, existing=None):
    """Normalise who an entry names, from the new picker's fields.

    `consultantDoctorId` -> consultant text, consultant_username, doctor id.
    `involved` [{doctorId|username|name}] -> assistants text + JSON.
    Text the client sent for a LISTED person is overwritten by the list's own
    spelling; free text is kept as typed. Returns (consultant_doctor_id,
    involved_json) and edits `body` in place (consultant, consultantUsername,
    assistants). Fields absent from `body` are left alone."""
    cdoc = existing["consultant_doctor_id"] if existing is not None and "consultant_doctor_id" in existing.keys() else None
    ijson = existing["involved"] if existing is not None and "involved" in existing.keys() else None
    if "consultantDoctorId" in body:
        raw = body.get("consultantDoctorId")
        row = None
        if isinstance(raw, int) and not isinstance(raw, bool):
            row = get(db, raw)
        if row:
            cdoc = row["id"]
            body["consultant"] = row["display_name"]
            body["consultantUsername"] = row["linked_username"] or None
        else:
            cdoc = None
            if raw not in (None, "", 0):
                body.pop("consultantDoctorId", None)
    elif ("consultantUsername" in body or "consultant" in body) and not (
            existing is not None and cdoc and body.get("consultant", existing["consultant"]) == existing["consultant"]
            and body.get("consultantUsername", existing["consultant_username"]) == existing["consultant_username"]):
        # An older client set the consultant by text/account: the list link no longer holds.
        cdoc = None
        if body.get("consultantUsername"):
            row = by_username(db, body["consultantUsername"])
            cdoc = row["id"] if row else None
    if "involved" in body:
        items = body.get("involved")
        clean, names = [], []
        if isinstance(items, list):
            for it in items[:12]:
                if not isinstance(it, dict):
                    continue
                row = None
                if isinstance(it.get("doctorId"), int) and not isinstance(it.get("doctorId"), bool):
                    row = get(db, it["doctorId"])
                elif isinstance(it.get("username"), str) and it.get("username"):
                    row = by_username(db, it["username"])
                if row:
                    clean.append({"doctorId": row["id"], "username": row["linked_username"],
                                  "name": row["display_name"]})
                    names.append(row["display_name"])
                else:
                    nm = str(it.get("name") or "").strip()[:80]
                    if nm:
                        clean.append({"name": nm})
                        names.append(nm)
        ijson = json.dumps(clean)
        body["assistants"] = ", ".join(dict.fromkeys(names))[:500] or None
    elif "assistants" in body:
        ijson = None     # an older client replaced the text; the structured copy is stale
    return cdoc, ijson


def resolve_approver(db, body, perms_mod, valid_approver):
    """The approver a submit names. -> (target, error, extra).
    target = {"username"} | {"doctorId", "name"} | {"name"}; extra carries a
    409 hint when a typed name closely matches a listed doctor."""
    un = body.get("approverUsername")
    if un:
        a = valid_approver(db, un)
        if not a:
            return None, "Pick an active consultant to send this to.", None
        return {"username": a["username"]}, None, None
    did = body.get("approverDoctorId")
    if isinstance(did, int) and not isinstance(did, bool):
        row = get(db, did)
        if not row or not can_receive_signoff(db, row, perms_mod):
            return None, "That doctor cannot be sent a sign-off.", None
        if row["linked_username"]:
            a = valid_approver(db, row["linked_username"])
            if not a:
                return None, "That doctor's account cannot take sign-offs right now.", None
            return {"username": a["username"]}, None, None
        return {"doctorId": row["id"], "name": row["display_name"]}, None, None
    nm = " ".join(str(body.get("approverName") or "").split())[:80]
    if len(nm) >= 3:
        if not body.get("confirmFreeText"):
            close = [m for m in near_matches(db, nm) if m["strong"]]
            if close:
                return None, "That name looks like someone on the list.", {"matches": close}
        return {"name": nm}, None, None
    return None, "Pick an active consultant to send this to.", None


# ------------------------------------------------------------- bulk add
def parse_bulk(text, default_designation=None):
    """One doctor per line: `Name`, or `Name, Designation`, or
    `Name | Designation | email | phone`. -> [{line, name, designation, email,
    phone, error}]"""
    rows = []
    for i, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip().strip(",;")
        if not line or line.startswith("#"):
            continue
        # " - " and " – " (spaced dashes) also separate; an unspaced hyphen is part of a name.
        sep = (r"[\t|;]" if re.search(r"[\t|;]", line)
               else r"\s[-\u2013\u2014]\s" if (re.search(r"\s[-\u2013\u2014]\s", line) and "," not in line)
               else ",")
        parts = [p.strip() for p in re.split(sep, line) if p.strip()]
        name = parts[0] if parts else ""
        desig = None
        email = phone = None
        for extra in parts[1:]:
            if "@" in extra:
                email = extra
            elif re.fullmatch(r"[+\d][\d \-]{6,}", extra):
                phone = extra
            else:
                desig = normalise_designation(extra) or desig
        item = {"line": i, "name": name, "designation": desig or default_designation,
                "email": email, "phone": phone, "error": None, "raw": raw.strip()}
        if len(name_key(name)) < 2:
            item["error"] = "No name found."
        elif not item["designation"]:
            item["error"] = "No designation (use Professor, Associate Professor, Assistant Professor, Consultant, Fellow or Senior Resident)."
        rows.append(item)
    return rows


def preview_bulk(db, text, unit, default_designation=None):
    rows = parse_bulk(text, default_designation)
    seen = {}
    for r in rows:
        r["matches"] = []
        r["action"] = "add"
        # A name with no designation is still fine if it is already listed
        # (the line then only adds a unit); the designation error stands otherwise.
        no_desig = r["error"] and r["error"].startswith("No designation")
        if r["error"] and not no_desig:
            r["action"] = "skip"
            continue
        k = name_key(r["name"])
        if k in seen:
            r["action"] = "skip"
            r["error"] = "Same name as line %d." % seen[k]
            continue
        seen[k] = r["line"]
        r["matches"] = near_matches(db, r["name"])
        exact = [m for m in r["matches"] if m["score"] >= 1.0]
        if no_desig and not exact:
            r["action"] = "skip"
            continue
        if no_desig:
            r["error"] = None
        if exact:
            m = exact[0]
            r["action"] = "merge"
            r["mergeId"] = m["id"]
            r["note"] = ("Already on the list; will be added to %s." % unit
                         if unit not in m["units"] else "Already on the list for %s." % unit)
            if unit in m["units"]:
                r["action"] = "skip"
        elif r["matches"]:
            r["action"] = "review"        # similar but not identical: a human decides
    return rows


def apply_bulk(db, rows, unit, actor, perms_mod):
    """rows: [{name, designation, email, phone, action: add|merge, mergeId}].
    Everything is re-validated here; nothing from the preview is trusted."""
    added = merged = skipped = 0
    errors = []
    for r in rows:
        act = r.get("action")
        if act == "skip":
            skipped += 1
            continue
        if act == "merge":
            mid = r.get("mergeId")
            row = get(db, mid) if isinstance(mid, int) else None
            if not row:
                errors.append("%s: no such doctor to merge into." % r.get("name"))
                continue
            db.execute("INSERT OR IGNORE INTO doctor_units (doctor_id, unit) VALUES (?,?)", (row["id"], unit))
            merged += 1
            continue
        if act != "add":
            errors.append("%s: unknown action." % r.get("name"))
            continue
        desig = normalise_designation(r.get("designation")) or r.get("designation")
        if desig not in _DESIG and (desig or "").lower() not in _DESIG:
            errors.append("%s: unknown designation." % r.get("name"))
            continue
        desig = [d for d, _, _ in DESIGNATIONS if d.lower() == desig.lower()][0]
        nm = " ".join(str(r.get("name") or "").split())[:120]
        if len(name_key(nm)) < 2:
            errors.append("Blank name.")
            continue
        cur = db.execute(
            "INSERT INTO doctors (display_name, name_key, designation, rank, home_unit, email, phone,"
            " status, source, created_by, created_at) VALUES (?,?,?,?,?,?,?,'active','bulk',?,?)",
            (nm, name_key(nm), desig, rank_of(desig), unit, (r.get("email") or None),
             (r.get("phone") or None), actor, now_iso()))
        db.execute("INSERT OR IGNORE INTO doctor_units (doctor_id, unit) VALUES (?,?)", (cur.lastrowid, unit))
        added += 1
    return {"added": added, "merged": merged, "skipped": skipped, "errors": errors}


# ------------------------------------------- typed names on old entries
def typed_names(db):
    """Consultant names people TYPED (no list row, no account) on entries,
    grouped by spelling, each with the closest listed doctors. This is how the
    HOD tidies the history: one click assigns every entry with that spelling."""
    groups = {}
    for r in db.execute(
            "SELECT id, consultant FROM entries WHERE consultant IS NOT NULL AND trim(consultant) <> ''"
            " AND (consultant_username IS NULL OR consultant_username = '') AND consultant_doctor_id IS NULL"
    ).fetchall():
        k = name_key(r["consultant"])
        if not k:
            continue
        g = groups.setdefault(k, {"key": k, "samples": {}, "count": 0})
        g["samples"][r["consultant"].strip()] = g["samples"].get(r["consultant"].strip(), 0) + 1
        g["count"] += 1
    out = []
    for k, g in groups.items():
        spelling = max(g["samples"].items(), key=lambda kv: kv[1])[0]
        out.append({"key": k, "spelling": spelling, "spellings": sorted(g["samples"]),
                    "count": g["count"], "suggest": near_matches(db, spelling, limit=3)})
    out.sort(key=lambda x: -x["count"])
    return out


def assign_typed_name(db, key, doctor_id):
    row = get(db, doctor_id)
    if not row:
        return None
    n = 0
    for r in db.execute(
            "SELECT id, consultant FROM entries WHERE consultant IS NOT NULL AND trim(consultant) <> ''"
            " AND (consultant_username IS NULL OR consultant_username = '') AND consultant_doctor_id IS NULL"
    ).fetchall():
        if name_key(r["consultant"]) == key:
            db.execute("UPDATE entries SET consultant_doctor_id = ?, consultant = ?, consultant_username = ?"
                       " WHERE id = ?", (row["id"], row["display_name"], row["linked_username"], r["id"]))
            n += 1
    return n
