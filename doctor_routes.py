"""v7.5 routes: the doctors list, invites and claims, the entry-form picker,
and the entry-speed helpers (recents, suggestions, typed-text review, starter
lists). Same /api prefix as the rest.
"""
import datetime
import json
from collections import Counter

from flask import Blueprint, g, jsonify, request

import doctors as docs
import perms
import starter_lists
from api import (
    _account_event, _text, _trainee_profile, bad_unit_response, get_config, known_unit_keys,
    require_perm, row_to_user, user_capabilities, _valid_approver,
)
from auth import (
    client_ip, create_session, current_user, hash_password, login_required,
    set_session_cookie, record_attempt,
)
from db import get_db

dr = Blueprint("doctors", __name__, url_prefix="/api")



def _json():
    b = request.get_json(force=True, silent=True)
    return b if isinstance(b, dict) else {}


def _now():
    return datetime.datetime.utcnow().isoformat() + "Z"


def _too_many(key, limit):
    db = get_db()
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(minutes=15)).isoformat() + "Z"
    n = db.execute("SELECT COUNT(*) c FROM login_attempts WHERE key = ? AND attempted_at > ?",
                   (key, cutoff)).fetchone()["c"]
    return n >= limit


# ===================================================================
#  PUBLIC (before sign-in)
# ===================================================================
@dr.post("/auth/invite/preview")
def invite_preview():
    key = "invite:" + client_ip()
    if _too_many(key, 10):
        return jsonify({"error": "Too many attempts. Wait 15 minutes and try again."}), 429
    db = get_db()
    c = docs.find_invite(db, _text(_json().get("code"), 40))
    if not c:
        record_attempt(key)
        return jsonify({"error": "That code is not valid, or it has expired or been used. Ask the Head of Department for a new one."}), 404
    row = docs.get(db, c["doctor_id"])
    return jsonify({"doctor": {"displayName": row["display_name"], "designation": row["designation"],
                               "units": docs._units(db, row["id"])},
                    "username": c["username"], "expiresAt": c["expires_at"]})


@dr.post("/auth/invite/use")
def invite_use():
    key = "invite:" + client_ip()
    if _too_many(key, 10):
        return jsonify({"error": "Too many attempts. Wait 15 minutes and try again."}), 429
    body = _json()
    password = _text(body.get("password"), 200) or ""
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400
    if password != (_text(body.get("confirm"), 200) or ""):
        return jsonify({"error": "Passwords do not match."}), 400
    db = get_db()
    c = docs.find_invite(db, _text(body.get("code"), 40))
    if not c:
        record_attempt(key)
        return jsonify({"error": "That code is not valid, or it has expired or been used."}), 404
    row = docs.get(db, c["doctor_id"])
    ok, why = docs.linkable(db, row)
    if not ok:
        return jsonify({"error": why}), 409
    import usernames
    if usernames.holder_of(db, c["username"]):   # registered by another route since the invite was made
        return jsonify({"error": "The username on this invite has been taken. Ask for a new invite."}), 409
    role = docs.kind_of(row["designation"])
    unit = row["home_unit"] if role in ("consultant", "fellow") else None
    course_id, joined_ym, cerr = _trainee_profile(db, role, unit, {})
    if cerr:
        course_id = joined_ym = None
    desig = row["designation"] if role == "consultant" else None
    try:
        db.execute(
            "INSERT INTO users (username, password_hash, role, display_name, pg_year, designation, unit, active,"
            " approval_status, created_at, course_id, joined_ym) VALUES (?,?,?,?,?,?,?,1,'approved',?,?,?)",
            (c["username"], hash_password(password), role, row["display_name"], None, desig, unit,
             _now(), course_id, joined_ym))
        result = docs.link(db, row["id"], c["username"], c["requested_by"], "invite")
        db.execute("UPDATE doctor_claims SET state = 'used', decided_by = ?, decided_at = ? WHERE id = ?",
                   (c["username"], _now(), c["id"]))
        _account_event(db, c["username"], "created", c["requested_by"],
                       "Account made from the doctors list by invite; %d waiting record(s) moved to them."
                       % result["entriesRouted"])
        docs.sync_user(db, c["username"])
        db.commit()
    except Exception:
        db.rollback()
        raise
    token = create_session(c["username"])
    user = row_to_user(db.execute("SELECT * FROM users WHERE username = ?", (c["username"],)).fetchone())
    resp = jsonify({"user": user, "capabilities": user_capabilities(c["username"])})
    return set_session_cookie(resp, token)


# ===================================================================
#  THE LIST (HOD / Developer)
# ===================================================================
def _manager_list(db):
    docs.expire_invites(db)
    out = []
    for r in db.execute("SELECT * FROM doctors ORDER BY rank DESC, display_name").fetchall():
        out.append(docs.doctor_dict(db, r, perms, manager=True))
    return out


@dr.get("/doctors")
@require_perm("directory.manage")
def list_doctors():
    db = get_db()
    # Pending self-claims, with the sign-up each belongs to.
    claims = []
    for c in db.execute("SELECT * FROM doctor_claims WHERE state = 'pending' ORDER BY requested_at").fetchall():
        d = docs.get(db, c["doctor_id"])
        u = db.execute("SELECT * FROM users WHERE username = ?", (c["username"],)).fetchone()
        claims.append({"id": c["id"], "username": c["username"], "requestedAt": c["requested_at"],
                       "doctor": {"id": d["id"], "displayName": d["display_name"],
                                  "designation": d["designation"], "units": docs._units(db, d["id"])},
                       "signup": row_to_user(u) if u else None})
    return jsonify({"doctors": _manager_list(db), "claims": claims,
                    "designations": [d for d, _, _ in docs.DESIGNATIONS]})


@dr.get("/doctors/username-check")
@require_perm("directory.manage")
def username_check():
    """Live availability while an invite is being made. Format first, then the
    holder check (which also honours another doctor's pending invite)."""
    import usernames
    clean, err = usernames.check_format(request.args.get("name") or "")
    if err:
        return jsonify({"status": "invalid", "detail": err})
    status, detail = usernames.availability(get_db(), clean)
    return jsonify({"status": status, "detail": detail, "username": clean})


@dr.get("/doctors/picker")
@login_required()
def doctor_picker():
    unit = (request.args.get("unit") or "").strip() or None
    date = (request.args.get("date") or "").strip() or None
    return jsonify({"doctors": docs.picker(get_db(), perms, unit, date)})


def _clean_row_fields(db, body, current=None):
    """-> (fields, error). Validates a create/update body."""
    cur = current
    f = {}
    if "displayName" in body or cur is None:
        nm = " ".join(str(body.get("displayName") or "").split())[:120]
        if len(docs.name_key(nm)) < 2:
            return None, "Enter the doctor's name."
        f["display_name"] = nm
        f["name_key"] = docs.name_key(nm)
    if "designation" in body or cur is None:
        d = docs.normalise_designation(body.get("designation")) or (body.get("designation") or "").strip()
        if d.lower() not in docs._DESIG:
            return None, "Choose a designation from the list."
        d = [x for x, _, _ in docs.DESIGNATIONS if x.lower() == d.lower()][0]
        f["designation"] = d
        f["rank"] = docs.rank_of(d)
    if "department" in body or cur is None:
        dep = " ".join(str(body.get("department") or "").split())[:60]
        f["department"] = None if dep.upper() in ("", "ENT") else dep
    for key, col, lim in (("regNo", "reg_no", 60), ("email", "email", 120), ("phone", "phone", 40), ("notes", "notes", 1000)):
        if key in body:
            v = " ".join(str(body.get(key) or "").split())[:lim] if key != "notes" else str(body.get(key) or "").strip()[:lim]
            f[col] = v or None
    if "homeUnit" in body or cur is None:
        hu = body.get("homeUnit") or None
        if hu and hu not in known_unit_keys():
            return None, "Unknown unit."
        f["home_unit"] = hu
    if "email" in f and f["email"] and "@" not in f["email"]:
        return None, "That email address does not look right."
    return f, None


def _check_units(units):
    if not isinstance(units, list):
        return None, "Units must be a list."
    clean = []
    for u in units[:20]:
        if not isinstance(u, str) or u not in known_unit_keys():
            return None, "Unknown unit."
        clean.append(u)
    return clean, None


@dr.post("/doctors")
@require_perm("directory.manage")
def create_doctor():
    body = _json()
    db = get_db()
    f, err = _clean_row_fields(db, body)
    if err:
        return jsonify({"error": err}), 400
    units, uerr = _check_units(body.get("units", [f.get("home_unit")] if f.get("home_unit") else []))
    if uerr:
        return jsonify({"error": uerr}), 400
    if f.get("home_unit") and f["home_unit"] not in units:
        units.append(f["home_unit"])
    if not body.get("confirmDuplicate"):
        close = docs.near_matches(db, f["display_name"])
        if close:
            return jsonify({"error": "possible_duplicate", "matches": close,
                            "detail": "Someone with a similar name is already on the list."}), 409
    try:
        cur = db.execute(
            "INSERT INTO doctors (display_name, name_key, designation, rank, home_unit, department, reg_no, email,"
            " phone, notes, status, source, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?, 'active','manual',?,?)",
            (f["display_name"], f["name_key"], f["designation"], f["rank"], f.get("home_unit"),
             f.get("department"), f.get("reg_no"), f.get("email"), f.get("phone"), f.get("notes"),
             g.user["username"], _now()))
    except Exception as e:
        db.rollback()
        if "UNIQUE" in str(e).upper():
            return jsonify({"error": "That registration number is already on the list."}), 409
        raise
    docs._set_units(db, cur.lastrowid, units)
    db.commit()
    return jsonify({"doctor": docs.doctor_dict(db, docs.get(db, cur.lastrowid), perms, manager=True)})


@dr.patch("/doctors/<int:did>")
@require_perm("directory.manage")
def update_doctor(did):
    body = _json()
    db = get_db()
    row = docs.get(db, did)
    if not row:
        return jsonify({"error": "not_found"}), 404
    f, err = _clean_row_fields(db, body, current=row)
    if err:
        return jsonify({"error": err}), 400
    if row["linked_username"]:
        # The account carries permissions, so name / designation are edited THERE.
        locked = {"display_name", "designation"} & set(f)
        changed = [k for k in locked if f[k] != row[k]]
        if changed:
            return jsonify({"error": "This doctor has an account. Change the name or designation on "
                                     "their account (Users); the list follows it."}), 409
        f.pop("display_name", None); f.pop("name_key", None); f.pop("designation", None); f.pop("rank", None)
    if "status" in body:
        if body["status"] not in ("active", "left"):
            return jsonify({"error": "Status must be active or left."}), 400
        f["status"] = body["status"]
        if body["status"] == "left" and docs.open_claim(db, did):
            return jsonify({"error": "Cancel the open invite or claim first."}), 409
    units = None
    if "units" in body:
        units, uerr = _check_units(body.get("units"))
        if uerr:
            return jsonify({"error": uerr}), 400
    if f:
        sets = ", ".join("%s = ?" % k for k in f)
        try:
            db.execute("UPDATE doctors SET %s, updated_by = ?, updated_at = ? WHERE id = ?" % sets,
                       tuple(f.values()) + (g.user["username"], _now(), did))
        except Exception as e:
            db.rollback()
            if "UNIQUE" in str(e).upper():
                return jsonify({"error": "That registration number is already on the list."}), 409
            raise
    if units is not None:
        hu = f.get("home_unit", row["home_unit"])
        if hu and hu not in units:
            units.append(hu)
        docs._set_units(db, did, units)
    db.commit()
    return jsonify({"doctor": docs.doctor_dict(db, docs.get(db, did), perms, manager=True)})


@dr.delete("/doctors/<int:did>")
@require_perm("directory.manage")
def delete_doctor(did):
    db = get_db()
    row = docs.get(db, did)
    if not row:
        return jsonify({"error": "not_found"}), 404
    if row["linked_username"]:
        return jsonify({"error": "This doctor has an account. Mark them as left instead."}), 409
    used = db.execute("SELECT COUNT(*) c FROM entries WHERE consultant_doctor_id = ? OR approver_doctor_id = ?"
                      " OR involved LIKE ? OR involved LIKE ?",
                      (did, did, '%"doctorId": ' + str(did) + ',%', '%"doctorId": ' + str(did) + '}%')).fetchone()["c"]
    if used:
        return jsonify({"error": "%d record(s) name this doctor. Mark them as left instead; deleting would "
                                 "turn those names back into plain text." % used}), 409
    db.execute("DELETE FROM doctors WHERE id = ?", (did,))
    db.commit()
    return jsonify({"ok": True})


# ---- bulk add --------------------------------------------------------
@dr.post("/doctors/bulk/preview")
@require_perm("directory.manage")
def bulk_preview():
    body = _json()
    unit = body.get("unit")
    if not isinstance(unit, str) or unit not in known_unit_keys():
        return bad_unit_response(unit)
    text = _text(body.get("text"), 20000) or ""
    default = docs.normalise_designation(body.get("defaultDesignation")) if body.get("defaultDesignation") else None
    rows = docs.preview_bulk(get_db(), text, unit, default)
    if len(rows) > 200:
        return jsonify({"error": "Add at most 200 doctors at a time."}), 400
    return jsonify({"rows": rows, "unit": unit})


@dr.post("/doctors/bulk/apply")
@require_perm("directory.manage")
def bulk_apply():
    body = _json()
    unit = body.get("unit")
    if not isinstance(unit, str) or unit not in known_unit_keys():
        return bad_unit_response(unit)
    rows = body.get("rows")
    if not isinstance(rows, list) or not rows or len(rows) > 200:
        return jsonify({"error": "Nothing to add."}), 400
    rows = [r for r in rows if isinstance(r, dict)]
    db = get_db()
    try:
        out = docs.apply_bulk(db, rows, unit, g.user["username"], perms)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return jsonify(out)


# ---- invites and claims --------------------------------------------
def _can_make_account_for(row):
    kind = docs.kind_of(row["designation"])
    key = {"consultant": "accounts.approve_consultants", "fellow": "accounts.approve_fellows",
           "senior_resident": "accounts.approve_trainees"}[kind]
    return perms.can(g.user["username"], key)


@dr.post("/doctors/<int:did>/invite")
@require_perm("directory.manage")
def invite_doctor(did):
    db = get_db()
    row = docs.get(db, did)
    if not row:
        return jsonify({"error": "not_found"}), 404
    if not _can_make_account_for(row):
        return jsonify({"error": "forbidden", "detail": "You cannot approve this kind of account."}), 403
    res, err = docs.create_invite(db, did, _text(_json().get("username"), 60), g.user["username"])
    if err:
        db.rollback()
        return jsonify({"error": err}), 400
    db.commit()
    return jsonify(res)


@dr.post("/doctors/claims/<int:cid>/cancel")
@require_perm("directory.manage")
def cancel_invite(cid):
    db = get_db()
    c = db.execute("SELECT * FROM doctor_claims WHERE id = ?", (cid,)).fetchone()
    if not c or c["state"] != "invited":
        return jsonify({"error": "Only an unused invite can be cancelled here. Reject a self-claim from Account requests."}), 409
    docs.cancel_claim(db, cid, g.user["username"])
    db.commit()
    return jsonify({"ok": True})


@dr.post("/doctors/<int:did>/link")
@require_perm("directory.manage")
def link_existing(did):
    """The same person already has an account that was made without the list
    (an older sign-up). Join the two instead of keeping a duplicate."""
    db = get_db()
    row = docs.get(db, did)
    uname = _text(_json().get("username"), 60)
    u = db.execute("SELECT * FROM users WHERE username = ?", (uname,)).fetchone()
    if not row or not u:
        return jsonify({"error": "not_found"}), 404
    if row["linked_username"]:
        return jsonify({"error": "This doctor already has an account."}), 409
    if docs.by_username(db, uname):
        return jsonify({"error": "That account is already on the list as another doctor."}), 409
    if u["role"] != docs.kind_of(row["designation"]):
        return jsonify({"error": "That account is a different kind (%s) from this designation (%s)."
                                 % (u["role"].replace("_", " "), row["designation"])}), 409
    if docs.open_claim(db, did):
        return jsonify({"error": "Cancel the open invite or claim first."}), 409
    try:
        res = docs.link(db, did, uname, g.user["username"], "linked by %s" % g.user["username"])
        _account_event(db, uname, "doctor_linked", g.user["username"],
                       "Linked to the doctors list as %s; %d waiting record(s) moved." % (row["display_name"], res["entriesRouted"]))
        docs.sync_user(db, uname)
        # a stray auto-created duplicate row for this account was already blocked by the unique index
        db.commit()
    except Exception as e:
        db.rollback()
        if "UNIQUE" in str(e).upper():
            return jsonify({"error": "That account is already linked to another row."}), 409
        raise
    return jsonify({"doctor": docs.doctor_dict(db, docs.get(db, did), perms, manager=True), **res})


@dr.post("/doctors/<int:did>/unlink")
@require_perm("directory.manage")
def unlink(did):
    db = get_db()
    row = docs.get(db, did)
    if not row or not row["linked_username"]:
        return jsonify({"error": "not_found"}), 404
    if docs._account_state(db, row["linked_username"]) != "closed":
        return jsonify({"error": "Only a closed account can be unlinked. Mark the doctor as left instead."}), 409
    db.execute("UPDATE doctors SET linked_username = NULL, status = 'left', updated_by = ?, updated_at = ? WHERE id = ?",
               (g.user["username"], _now(), did))
    db.commit()
    return jsonify({"ok": True})


# ---- historical typed names ------------------------------------------
@dr.get("/doctors/typed-names")
@require_perm("directory.manage")
def typed_names():
    return jsonify({"names": docs.typed_names(get_db())})


@dr.post("/doctors/typed-names/assign")
@require_perm("directory.manage")
def typed_names_assign():
    body = _json()
    db = get_db()
    did = body.get("doctorId")
    if not isinstance(did, int) or not docs.get(db, did):
        return jsonify({"error": "Pick a doctor."}), 400
    n = docs.assign_typed_name(db, _text(body.get("key"), 200) or "", did)
    db.commit()
    return jsonify({"updated": n})


# ===================================================================
#  ENTRY SPEED
# ===================================================================
def _my_entries(db, limit=300):
    return db.execute("SELECT * FROM entries WHERE author_username = ? AND status = 'final'"
                      " ORDER BY entry_date DESC, id DESC LIMIT ?", (g.user["username"], limit)).fetchall()


def _blocks(row):
    try:
        b = json.loads(row["procedure_blocks"] or "[]")
        return b if isinstance(b, list) else []
    except (TypeError, ValueError):
        return []


@dr.get("/me/frequent")
@login_required()
def my_frequent():
    """What this person logs most, so the form can offer it first. Only their
    own entries; nothing about anyone else."""
    db = get_db()
    rows = _my_entries(db)
    cons, dx, procs, sites = Counter(), Counter(), Counter(), Counter()
    cons_by_unit = {}
    for r in rows:
        if r["consultant_doctor_id"]:
            cons[("d", r["consultant_doctor_id"])] += 1
            cons_by_unit.setdefault(r["unit"], Counter())[("d", r["consultant_doctor_id"])] += 1
        for d in json.loads(r["diagnoses"] or "[]"):
            dx[d] += 1
        for b in _blocks(r):
            for p in (b.get("procedures") or []):
                procs[(b.get("site"), p)] += 1
            if b.get("site"):
                sites[b["site"]] += 1
    cdocs = []
    for (_, did), n in cons.most_common(6):
        row = docs.get(db, did)
        if row and row["status"] == "active":
            cdocs.append({"id": did, "displayName": row["display_name"], "count": n})
    last = next((r for r in rows if r["entry_type"] in ("surgical", "other")), None)
    return jsonify({
        "consultants": cdocs,
        "diagnoses": [{"name": k, "count": n} for k, n in dx.most_common(8)],
        "procedures": [{"site": s, "name": p, "count": n} for (s, p), n in procs.most_common(8)],
        "lastEntryId": last["id"] if last else None,
    })


@dr.get("/suggest/diagnoses")
@login_required()
def suggest_diagnoses():
    """For a chosen procedure: what it is usually done for. This department's
    own entries first (the user's, then everyone's), the shipped hints after."""
    proc = (request.args.get("procedure") or "").strip()
    if not proc:
        return jsonify({"suggestions": []})
    db = get_db()
    mine, dept = Counter(), Counter()
    for r in db.execute("SELECT author_username, diagnoses, procedure_blocks FROM entries"
                        " WHERE entry_type IN ('surgical','other') AND status = 'final'"
                        " AND procedure_blocks LIKE ? ORDER BY id DESC LIMIT 4000",
                        ("%" + proc.replace("%", "") + "%",)):
        if not any(proc in (b.get("procedures") or []) for b in _blocks(r)):
            continue
        for d in json.loads(r["diagnoses"] or "[]"):
            (mine if r["author_username"] == g.user["username"] else dept)[d] += 1
    out, seen = [], set()
    for src, ctr in (("you", mine), ("department", dept)):
        for d, n in ctr.most_common(5):
            if d not in seen:
                seen.add(d)
                out.append({"name": d, "source": src, "count": n})
    for d in starter_lists.PROC_DX.get(proc, []):
        if d not in seen:
            seen.add(d)
            out.append({"name": d, "source": "suggested", "count": 0})
    cfg = get_config()
    have = {s.lower() for s in (cfg.get("diagnoses") or [])}
    for o in out:
        o["inList"] = o["name"].lower() in have
    return jsonify({"suggestions": out[:6]})


@dr.get("/suggest/people")
@login_required()
def suggest_people():
    """Who this person usually operates with in a unit: recents for the picker."""
    unit = (request.args.get("unit") or "").strip()
    db = get_db()
    c = Counter()
    for r in db.execute("SELECT consultant_doctor_id, involved FROM entries WHERE author_username = ?"
                        " AND unit = ? AND status = 'final' ORDER BY id DESC LIMIT 200",
                        (g.user["username"], unit)):
        if r["consultant_doctor_id"]:
            c[("c", r["consultant_doctor_id"])] += 2
        try:
            for it in json.loads(r["involved"] or "[]"):
                if it.get("doctorId"):
                    c[("i", it["doctorId"])] += 1
        except (TypeError, ValueError):
            pass
    return jsonify({"consultants": [did for (k, did), n in c.most_common() if k == "c"][:5],
                    "involved": [did for (k, did), n in c.most_common() if k == "i"][:6]})


# ===================================================================
#  TYPED-IN TEXT REVIEW AND STARTER LISTS  (lists.review)
# ===================================================================
LIST_FIELDS = (("diagnoses", "Primary / secondary diagnosis"), ("comorbidities", "Comorbidity"),
               ("procedures", "Procedure"))


def _dismissed(db):
    """Kept in its own config row, not in the lists: GET /config is public."""
    r = db.execute("SELECT data FROM config WHERE id = 'review'").fetchone()
    try:
        v = json.loads(r["data"]) if r else []
    except (TypeError, ValueError):
        v = []
    return v if isinstance(v, list) else []


def typed_values(db, cfg):
    """Values on entries that are not in the department's lists, with counts.
    Computed from the entries every time -- there is no capture table to keep
    in step -- minus anything the reviewer dismissed."""
    dismissed = {(d.get("list"), (d.get("value") or "").lower()) for d in _dismissed(db)}
    have_dx = {s.lower() for s in (cfg.get("diagnoses") or [])}
    have_co = {s.lower() for s in (cfg.get("comorbidities") or [])}
    procs = cfg.get("procedures") or {}
    have_pr = {site: {s.lower() for s in lst} for site, lst in procs.items()}
    all_pr = set().union(*have_pr.values()) if have_pr else set()
    dx, co, pr = Counter(), Counter(), Counter()
    seen_by = {"diagnoses": {}, "comorbidities": {}, "procedures": {}}
    for r in db.execute("SELECT author_username, diagnoses, diagnoses_secondary, comorbidities, procedures,"
                        " procedure_blocks FROM entries").fetchall():
        who = r["author_username"]
        for fld in ("diagnoses", "diagnoses_secondary"):
            for v in json.loads(r[fld] or "[]"):
                if isinstance(v, str) and v.lower() not in have_dx:
                    dx[v] += 1
                    seen_by["diagnoses"].setdefault(v, set()).add(who)
        for v in json.loads(r["comorbidities"] or "[]"):
            if isinstance(v, str) and v.lower() not in have_co and v.lower() != "none":
                co[v] += 1
                seen_by["comorbidities"].setdefault(v, set()).add(who)
        for b in _blocks(r):
            for v in (b.get("procedures") or []):
                if isinstance(v, str) and v.lower() not in have_pr.get(b.get("site"), set()) \
                        and v.lower() not in all_pr:
                    pr[(b.get("site"), v)] += 1
                    seen_by["procedures"].setdefault((b.get("site"), v), set()).add(who)
        for v in json.loads(r["procedures"] or "[]"):
            if isinstance(v, str) and v.lower() not in all_pr:
                pr[(None, v)] += 1
    out = {"diagnoses": [], "comorbidities": [], "procedures": []}
    for k, n in dx.most_common(200):
        if ("diagnoses", k.lower()) not in dismissed:
            out["diagnoses"].append({"value": k, "count": n, "people": len(seen_by["diagnoses"].get(k, ()))})
    for k, n in co.most_common(200):
        if ("comorbidities", k.lower()) not in dismissed:
            out["comorbidities"].append({"value": k, "count": n, "people": len(seen_by["comorbidities"].get(k, ()))})
    for (site, k), n in pr.most_common(300):
        if ("procedures", k.lower()) not in dismissed:
            out["procedures"].append({"value": k, "site": site, "count": n,
                                      "people": len(seen_by["procedures"].get((site, k), ()))})
    return out


@dr.get("/lists/review")
@require_perm("lists.review")
def lists_review():
    db = get_db()
    cfg = get_config()
    return jsonify({"typed": typed_values(db, cfg), "starter": starter_lists.diff_against(cfg),
                    "sites": [{"key": c["key"], "name": c["name"]} for c in cfg.get("categories", [])]})


def _save_cfg(db, cfg):
    db.execute("UPDATE config SET data = ? WHERE id = 'lists'", (json.dumps(cfg),))


def _add_unique(lst, items):
    have = {s.lower() for s in lst}
    added = 0
    for it in items:
        it = " ".join(str(it).split())[:200]
        if it and it.lower() not in have:
            lst.append(it)
            have.add(it.lower())
            added += 1
    return added


@dr.post("/lists/review/promote")
@require_perm("lists.review")
def lists_promote():
    """body: {items: [{list, value, site?, as?}]}. `as` renames on the way in
    (tidying a spelling); the entries keep what their authors typed."""
    body = _json()
    items = body.get("items")
    if not isinstance(items, list) or not items or len(items) > 200:
        return jsonify({"error": "Nothing selected."}), 400
    db = get_db()
    cfg = get_config()
    n = 0
    keys = {c["key"] for c in cfg.get("categories", [])}
    for it in items:
        if not isinstance(it, dict):
            continue
        val = it.get("as") or it.get("value")
        lst = it.get("list")
        if lst in ("diagnoses", "comorbidities"):
            cfg[lst] = list(cfg.get(lst) or [])
            n += _add_unique(cfg[lst], [val])
        elif lst == "procedures":
            site = it.get("site")
            if site not in keys:
                return jsonify({"error": "Choose a site for \"%s\"." % val}), 400
            procs = dict(cfg.get("procedures") or {})
            procs[site] = list(procs.get(site) or [])
            n += _add_unique(procs[site], [val])
            procs[site].sort(key=lambda s: s.lower())
            cfg["procedures"] = procs
    for k in ("diagnoses", "comorbidities"):
        if k in cfg:
            cfg[k] = sorted(cfg[k], key=lambda s: (s.lower() == "none", s.lower()))
    _save_cfg(db, cfg)
    db.commit()
    return jsonify({"added": n})


@dr.post("/lists/review/dismiss")
@require_perm("lists.review")
def lists_dismiss():
    body = _json()
    items = body.get("items")
    if not isinstance(items, list) or not items:
        return jsonify({"error": "Nothing selected."}), 400
    db = get_db()
    d = _dismissed(db)
    for it in items[:200]:
        if isinstance(it, dict) and it.get("list") in dict(LIST_FIELDS) and it.get("value"):
            d.append({"list": it["list"], "value": str(it["value"])[:200]})
    db.execute("INSERT INTO config (id, data) VALUES ('review', ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
               (json.dumps(d[-2000:]),))
    db.commit()
    return jsonify({"ok": True})


@dr.post("/lists/starter/apply")
@require_perm("lists.review")
def lists_starter_apply():
    """body: {diagnoses: [...], comorbidities: [...], procedures: {site: [...]}} --
    only items that are actually in the shipped starter set are accepted."""
    body = _json()
    db = get_db()
    cfg = get_config()
    offered = starter_lists.diff_against(cfg)
    n = 0
    for k in ("diagnoses", "comorbidities"):
        want = [x for x in (body.get(k) or []) if isinstance(x, str) and x in offered[k]]
        cfg[k] = list(cfg.get(k) or [])
        n += _add_unique(cfg[k], want)
        cfg[k].sort(key=lambda s: (s.lower() == "none", s.lower()))
    procs = dict(cfg.get("procedures") or {})
    for site, items in (body.get("procedures") or {}).items():
        if site in offered["procedures"] and isinstance(items, list):
            want = [x for x in items if x in offered["procedures"][site]]
            procs[site] = list(procs.get(site) or [])
            n += _add_unique(procs[site], want)
            procs[site].sort(key=lambda s: s.lower())
    cfg["procedures"] = procs
    _save_cfg(db, cfg)
    db.commit()
    return jsonify({"added": n})
