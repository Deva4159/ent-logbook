"""v7.4 routes: permission panel, user detail and rename, alerts, courses,
backups. Kept apart from api.py (which is already four thousand lines) and
registered on the same /api prefix. Everything here is Developer-only except
the three endpoints a signed-in person needs for themselves (their own alerts,
and the public course list the sign-up form reads).
"""
import datetime
import json

from flask import Blueprint, Response, g, jsonify, request

import alerts as alerts_mod
import backup as backup_mod
import courses as courses_mod
import perms
import usernames
from api import (
    _account_event, _display_name, _lifecycle_of, _text, _now_iso, get_config, get_postings,
    known_unit_keys, require_perm, row_to_user, row_to_user as _row_to_user,
)
from auth import (
    clear_session_cookie, current_user, rate_limit, record_attempt, verify_password,
    client_ip,
)
from db import get_db

admin = Blueprint("admin", __name__, url_prefix="/api")


def _json():
    b = request.get_json(force=True, silent=True)
    return b if isinstance(b, dict) else {}


# ===================================================================
#  PERMISSIONS
# ===================================================================
@admin.get("/permissions/catalogue")
@require_perm("perms.manage")
def perm_catalogue():
    db = get_db()
    tpls = perms.all_templates(db)
    out = []
    for key in perms.TEMPLATE_KEYS:
        label, desc = perms.TEMPLATE_META[key]
        default = perms.default_template(key)
        out.append({"key": key, "label": label, "description": desc,
                    "perms": tpls[key], "default": default,
                    "modified": tpls[key] != default,
                    "onlyFellowPermissions": key == "fellow"})
    return jsonify({
        "groups": [{"key": k, "label": l} for k, l in perms.GROUPS],
        "permissions": perms.CATALOGUE,
        "fellowOk": sorted(perms.FELLOW_OK),
        "templates": out,
    })


@admin.put("/permissions/templates/<key>")
@require_perm("perms.manage")
def perm_template_save(key):
    body = _json()
    db = get_db()
    diff, err = perms.save_template(db, key, body.get("perms"), g.user["username"])
    if err:
        db.rollback()
        return jsonify({"error": err}), 400
    db.commit()
    return jsonify({"changed": diff, "perms": perms.template(db, key)})


@admin.post("/permissions/templates/<key>/reset")
@require_perm("perms.manage")
def perm_template_reset(key):
    if key not in perms.TEMPLATE_META:
        return jsonify({"error": "Unknown template."}), 404
    db = get_db()
    diff = perms.reset_template(db, key, g.user["username"])
    db.commit()
    return jsonify({"changed": diff, "perms": perms.template(db, key)})


def _person_row(db, r):
    eff = perms.compute(r["username"])
    n_over = db.execute("SELECT COUNT(*) c FROM permission_overrides WHERE username = ?",
                        (r["username"],)).fetchone()["c"]
    appts = perms.active_role_assignments(r["username"])
    return {
        "username": r["username"], "displayName": r["display_name"], "role": r["role"],
        "designation": r["designation"], "unit": r["unit"],
        "appointments": [{"role": a["assignment_role"], "unit": a["unit"]} for a in appts],
        "overrides": n_over, "effective": len(eff),
    }


@admin.get("/permissions/people")
@require_perm("perms.manage")
def perm_people():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM users WHERE role IN ('consultant','fellow') AND approval_status = 'approved'"
        " AND lifecycle != 'deleted' ORDER BY role, display_name").fetchall()
    return jsonify({"people": [_person_row(db, r) for r in rows]})


@admin.get("/permissions/people/<username>")
@require_perm("perms.manage")
def perm_person(username):
    db = get_db()
    ex = perms.explain(db, username)
    if ex is None:
        return jsonify({"error": "not_found"}), 404
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    trail = db.execute(
        "SELECT * FROM permission_audit WHERE target_kind = 'user' AND target = ? ORDER BY id DESC LIMIT 40",
        (username,)).fetchall()
    ex["user"] = _person_row(db, row)
    ex["audit"] = [{"at": t["at"], "by": t["actor_username"], "byName": _display_name(db, t["actor_username"]),
                    "action": t["action"], "detail": json.loads(t["detail"] or "{}")} for t in trail]
    ex["templates"] = {k: v for k, v in perms.all_templates(db).items()}
    return jsonify(ex)


@admin.put("/permissions/people/<username>")
@require_perm("perms.manage")
def perm_person_save(username):
    """`changes`: [{perm, effect: grant|deny|clear, scope, units, note}]. All
    applied or none."""
    body = _json()
    changes = body.get("changes")
    if not isinstance(changes, list) or not changes or len(changes) > 60:
        return jsonify({"error": "Send a list of changes."}), 400
    db = get_db()
    known = known_unit_keys()
    for c in changes:
        if not isinstance(c, dict):
            db.rollback()
            return jsonify({"error": "Malformed change."}), 400
        err = perms.set_override(db, username, c.get("perm"), c.get("effect"), c.get("scope"),
                                 c.get("units"), _text(c.get("note"), 300), g.user["username"], known)
        if err:
            db.rollback()
            perms.invalidate()
            return jsonify({"error": err, "perm": c.get("perm")}), 400
    db.commit()
    perms.invalidate(username)
    # A sign-off right or a view right changing is exactly the kind of thing
    # the person should be able to see on their own account history.
    _account_event(db, username, "permissions_changed", g.user["username"],
                   "; ".join("%s %s" % (c.get("effect"), c.get("perm")) for c in changes)[:900])
    db.commit()
    return jsonify(perms.explain(db, username))


@admin.get("/permissions/audit")
@require_perm("perms.manage")
def perm_audit():
    db = get_db()
    rows = db.execute("SELECT * FROM permission_audit ORDER BY id DESC LIMIT 150").fetchall()
    return jsonify({"audit": [{
        "at": r["at"], "by": r["actor_username"], "byName": _display_name(db, r["actor_username"]),
        "kind": r["target_kind"], "target": r["target"],
        "targetName": _display_name(db, r["target"]) if r["target_kind"] == "user" else
        perms.TEMPLATE_META.get(r["target"], (r["target"],))[0],
        "action": r["action"], "detail": json.loads(r["detail"] or "{}")} for r in rows]})


# ===================================================================
#  USER DETAIL AND RENAME
# ===================================================================
@admin.get("/users/<username>/detail")
@require_perm("accounts.edit_profile")
def user_detail(username):
    """Everything the per-user edit page shows, in one call."""
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    is_dev = g.user["role"] == "developer"
    u = row_to_user(row, contact=is_dev)
    c_by = {c["id"]: c for c in courses_mod.list_courses(db)}
    course = c_by.get(row["course_id"])
    postings = get_postings(username)
    counts = {r["entry_type"]: r["c"] for r in db.execute(
        "SELECT entry_type, COUNT(*) c FROM entries WHERE author_username = ? AND status = 'final'"
        " GROUP BY entry_type", (username,))}
    events = []
    if perms.can(g.user["username"], "accounts.view_events"):
        events = [{"action": e["action"], "actor": e["actor_username"],
                   "actorName": _display_name(db, e["actor_username"]) if e["actor_username"] else None,
                   "detail": e["detail"], "createdAt": e["created_at"]}
                  for e in db.execute("SELECT * FROM account_events WHERE username = ? ORDER BY id DESC LIMIT 25",
                                      (username,))]
    appts = [{"id": a["id"], "role": a["assignment_role"], "unit": a["unit"], "startAt": a["start_at"],
              "endAt": a["end_at"], "active": perms.is_assignment_active(dict(a))}
             for a in db.execute("SELECT * FROM role_assignments WHERE consultant_username = ?"
                                 " ORDER BY id DESC", (username,))]
    return jsonify({
        "user": u,
        "lifecycleReason": row["lifecycle_reason"], "lifecycleAt": row["lifecycle_at"],
        "course": course,
        "postings": postings,
        "peripheralDays": courses_mod.peripheral_days(postings, course) if course else 0,
        "allowedUnits": sorted(courses_mod.allowed_units(course, row["unit"], known_unit_keys()) or [])
        if course else None,
        "entryCounts": counts,
        "appointments": appts,
        "overrides": db.execute("SELECT COUNT(*) c FROM permission_overrides WHERE username = ?",
                                (username,)).fetchone()["c"],
        "events": events,
        "isLastDeveloper": False,
    })


@admin.get("/usernames/check")
@require_perm("accounts.rename")
def username_check():
    db = get_db()
    name = request.args.get("name") or ""
    current = request.args.get("for") or None
    clean, err = usernames.check_format(name)
    if err:
        return jsonify({"status": "invalid", "detail": err})
    if current and clean == current:
        return jsonify({"status": "same", "detail": "That is the current username."})
    status, detail = usernames.availability(db, clean, ignore=current)
    return jsonify({"status": status, "detail": detail, "name": clean})


@admin.post("/users/<username>/rename")
@require_perm("accounts.rename")
def user_rename(username):
    body = _json()
    db = get_db()
    result, err = usernames.rename_user(db, username, body.get("username"), g.user["username"])
    if err:
        code = 404 if err == "No such account." else 409 if err.startswith("That username is not available") else 400
        return jsonify({"error": err}), code
    resp = jsonify({
        "ok": True, "old": result["old"], "new": result["new"], "retired": result["retired"],
        "rowsUpdated": sum(result["touched"].values()),
        "touched": result["touched"],
        # Renaming yourself ends your own session (every session of the
        # renamed account is destroyed), so the page must send you back to
        # sign in under the new name.
        "signedOut": g.user["username"] == username,
    })
    if g.user["username"] == username:
        clear_session_cookie(resp)
    return resp


# ===================================================================
#  ALERTS
# ===================================================================
@admin.get("/alerts")
def my_alerts():
    user = current_user()
    if not user:
        return jsonify({"error": "not_authenticated"}), 401
    db = get_db()
    alerts_mod.sweep(db)
    items = alerts_mod.visible_for(db, user["username"])
    return jsonify({"alerts": items, "unread": sum(1 for a in items if not a["read"])})


@admin.post("/alerts/read-all")
def alerts_read_all():
    user = current_user()
    if not user:
        return jsonify({"error": "not_authenticated"}), 401
    db = get_db()
    for a in alerts_mod.visible_for(db, user["username"]):
        if not a["read"]:
            alerts_mod.mark(db, user["username"], a["id"], "read")
    db.commit()
    return jsonify({"ok": True})


@admin.post("/alerts/<int:alert_id>/<what>")
def alert_mark(alert_id, what):
    user = current_user()
    if not user:
        return jsonify({"error": "not_authenticated"}), 401
    if what not in ("read", "dismiss", "unread"):
        return jsonify({"error": "not_found"}), 404
    db = get_db()
    if not alerts_mod.mark(db, user["username"], alert_id, what):
        return jsonify({"error": "not_found"}), 404
    db.commit()
    return jsonify({"ok": True})


def _alert_manage_row(db, r, live_users_cache):
    try:
        aud = json.loads(r["audience"])
    except (TypeError, ValueError):
        aud = {}
    who = alerts_mod.recipients(db, aud)
    reads = db.execute("SELECT COUNT(*) c FROM alert_reads WHERE alert_id = ? AND read_at IS NOT NULL",
                       (r["id"],)).fetchone()["c"]
    now = _now_iso()
    state = ("resolved" if r["resolved_at"] else "muted" if not r["active"]
             else "scheduled" if r["starts_at"] and r["starts_at"] > now
             else "expired" if r["expires_at"] and r["expires_at"] <= now else "live")
    return {
        "id": r["id"], "kind": r["kind"], "rule": r["rule"], "title": r["title"], "body": r["body"] or "",
        "severity": r["severity"], "audience": aud, "startsAt": r["starts_at"], "expiresAt": r["expires_at"],
        "active": bool(r["active"]), "resolvedAt": r["resolved_at"], "createdBy": r["created_by"],
        "createdAt": r["created_at"], "state": state, "recipients": len(who), "read": reads,
    }


@admin.get("/alerts/manage")
@require_perm("alerts.compose")
def alerts_manage():
    db = get_db()
    alerts_mod.sweep(db)
    rows = db.execute("SELECT * FROM alerts ORDER BY (resolved_at IS NOT NULL), id DESC LIMIT 200").fetchall()
    return jsonify({
        "alerts": [_alert_manage_row(db, r, None) for r in rows],
        "rules": alerts_mod.get_rules(db),
    })


def _alert_fields(body, existing=None):
    """-> (fields, error)"""
    title = (_text(body.get("title"), 160) or "").strip()
    if not title:
        return None, "An alert needs a title."
    sev = body.get("severity", existing["severity"] if existing else "info")
    if sev not in alerts_mod.SEVERITIES:
        return None, "Severity must be info, warning or urgent."
    aud, err = alerts_mod.clean_audience(body.get("audience"), known_unit_keys())
    if err:
        return None, err
    out = {"title": title, "body": (_text(body.get("body"), 2000) or "").strip(), "severity": sev,
           "audience": aud}
    for k in ("startsAt", "expiresAt"):
        v = body.get(k)
        if v in (None, ""):
            out[k] = None
            continue
        if not isinstance(v, str):
            return None, "Dates must be YYYY-MM-DD."
        try:
            d = datetime.date.fromisoformat(v[:10])
        except ValueError:
            return None, "Dates must be YYYY-MM-DD."
        # Whole days: starts at the start of the day, expires at the end of it.
        out[k] = d.isoformat() + ("T00:00:00Z" if k == "startsAt" else "T23:59:59Z")
    if out["startsAt"] and out["expiresAt"] and out["expiresAt"] < out["startsAt"]:
        return None, "The end date is before the start date."
    return out, None


@admin.post("/alerts")
@require_perm("alerts.compose")
def alert_create():
    f, err = _alert_fields(_json())
    if err:
        return jsonify({"error": err}), 400
    db = get_db()
    cur = db.execute(
        "INSERT INTO alerts (kind, title, body, severity, audience, starts_at, expires_at, active,"
        " created_by, created_at) VALUES ('manual',?,?,?,?,?,?,1,?,?)",
        (f["title"], f["body"], f["severity"], json.dumps(f["audience"], sort_keys=True),
         f["startsAt"], f["expiresAt"], g.user["username"], _now_iso()))
    db.commit()
    row = db.execute("SELECT * FROM alerts WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify({"alert": _alert_manage_row(db, row, None)})


@admin.patch("/alerts/<int:alert_id>")
@require_perm("alerts.compose")
def alert_edit(alert_id):
    db = get_db()
    row = db.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    body = _json()
    if row["kind"] == "system":
        # A system alert's wording and audience belong to its rule; the only
        # thing to change is whether it is shown.
        if "active" not in body:
            return jsonify({"error": "System alerts can only be muted or unmuted."}), 400
        db.execute("UPDATE alerts SET active = ?, updated_at = ? WHERE id = ?",
                   (1 if body["active"] else 0, _now_iso(), alert_id))
    elif set(body) == {"active"}:
        db.execute("UPDATE alerts SET active = ?, updated_at = ? WHERE id = ?",
                   (1 if body["active"] else 0, _now_iso(), alert_id))
    else:
        f, err = _alert_fields(body, row)
        if err:
            return jsonify({"error": err}), 400
        db.execute(
            "UPDATE alerts SET title = ?, body = ?, severity = ?, audience = ?, starts_at = ?, expires_at = ?,"
            " active = ?, updated_at = ? WHERE id = ?",
            (f["title"], f["body"], f["severity"], json.dumps(f["audience"], sort_keys=True),
             f["startsAt"], f["expiresAt"], 0 if body.get("active") is False else 1, _now_iso(), alert_id))
        # An edited alert is a changed alert: anyone who had dismissed the
        # old wording should see the new.
        db.execute("DELETE FROM alert_reads WHERE alert_id = ?", (alert_id,))
    db.commit()
    row = db.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    return jsonify({"alert": _alert_manage_row(db, row, None)})


@admin.delete("/alerts/<int:alert_id>")
@require_perm("alerts.compose")
def alert_delete(alert_id):
    db = get_db()
    row = db.execute("SELECT kind FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404
    if row["kind"] == "system":
        return jsonify({"error": "System alerts are managed by their rule. Mute it, or switch the rule off."}), 400
    db.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
    db.commit()
    return jsonify({"ok": True})


@admin.post("/alerts/audience-preview")
@require_perm("alerts.compose")
def alert_audience_preview():
    aud, err = alerts_mod.clean_audience(_json().get("audience"), known_unit_keys())
    if err:
        return jsonify({"error": err}), 400
    db = get_db()
    who = alerts_mod.recipients(db, aud)
    return jsonify({"count": len(who), "sample": [
        {"username": u, "displayName": _display_name(db, u)} for u in who[:15]]})


@admin.put("/alerts/rules")
@require_perm("alerts.compose")
def alert_rules_save():
    db = get_db()
    rules, err = alerts_mod.save_rules(db, _json().get("rules"))
    if err:
        return jsonify({"error": err}), 400
    db.commit()
    res = alerts_mod.sweep(db, force=True)
    return jsonify({"rules": rules, "sweep": res})


@admin.post("/alerts/sweep")
@require_perm("alerts.compose")
def alert_sweep_now():
    return jsonify({"sweep": alerts_mod.sweep(get_db(), force=True)})


# ===================================================================
#  COURSES
# ===================================================================
@admin.get("/courses")
def courses_public():
    # Public, like /config: the sign-up form needs it before anyone has a
    # session, and it is dropdown metadata.
    return jsonify({"courses": courses_mod.list_courses(get_db(), active_only=True)})


@admin.get("/courses/manage")
@require_perm("courses.manage")
def courses_manage():
    db = get_db()
    out = []
    for c in courses_mod.list_courses(db):
        c["users"] = db.execute("SELECT COUNT(*) c FROM users WHERE course_id = ?", (c["id"],)).fetchone()["c"]
        c["entries"] = db.execute("SELECT COUNT(*) c FROM entries WHERE course_id = ?", (c["id"],)).fetchone()["c"]
        out.append(c)
    return jsonify({"courses": out})


@admin.post("/courses")
@require_perm("courses.manage")
def course_create():
    db = get_db()
    clean, err = courses_mod.validate_course(_json(), known_unit_keys())
    if err:
        return jsonify({"error": err}), 400
    taken = {r["id"] for r in db.execute("SELECT id FROM courses")}
    cid = courses_mod.slug(clean["name"], taken)
    nxt = (db.execute("SELECT COALESCE(MAX(sort), 0) m FROM courses").fetchone()["m"] or 0) + 1
    db.execute(
        "INSERT INTO courses (id, name, short_name, role, duration_months, scope, units, allow_peripheral,"
        " peripheral_units, max_peripheral_months, year_labels, start_month, notes, active, sort,"
        " created_at, updated_at, updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (cid, clean["name"], clean["short_name"], clean["role"], clean["duration_months"], clean["scope"],
         json.dumps(clean["units"]), clean["allow_peripheral"], json.dumps(clean["peripheral_units"]),
         clean["max_peripheral_months"], json.dumps(clean["year_labels"]), clean["start_month"],
         clean["notes"], clean["active"], nxt, _now_iso(), _now_iso(), g.user["username"]))
    db.commit()
    return jsonify({"course": courses_mod.get_course(db, cid)})


@admin.patch("/courses/<cid>")
@require_perm("courses.manage")
def course_edit(cid):
    db = get_db()
    cur = courses_mod.get_course(db, cid)
    if not cur:
        return jsonify({"error": "not_found"}), 404
    body = _json()
    merged = dict(cur)
    merged.update(body)
    merged["role"] = cur["role"]            # a course's kind is fixed once people are on it
    if "role" in body and body["role"] != cur["role"]:
        n = db.execute("SELECT COUNT(*) c FROM users WHERE course_id = ?", (cid,)).fetchone()["c"]
        if n:
            return jsonify({"error": "People are enrolled on this course, so it cannot change kind."}), 400
        merged["role"] = body["role"]
    clean, err = courses_mod.validate_course(merged, known_unit_keys(), cur)
    if err:
        return jsonify({"error": err}), 400
    # Shortening a course shortens everyone's remaining time; say so rather
    # than letting it pass as a cosmetic edit.
    db.execute(
        "UPDATE courses SET name=?, short_name=?, role=?, duration_months=?, scope=?, units=?,"
        " allow_peripheral=?, peripheral_units=?, max_peripheral_months=?, year_labels=?, start_month=?,"
        " notes=?, active=?, updated_at=?, updated_by=? WHERE id=?",
        (clean["name"], clean["short_name"], clean["role"], clean["duration_months"], clean["scope"],
         json.dumps(clean["units"]), clean["allow_peripheral"], json.dumps(clean["peripheral_units"]),
         clean["max_peripheral_months"], json.dumps(clean["year_labels"]), clean["start_month"],
         clean["notes"], clean["active"], _now_iso(), g.user["username"], cid))
    db.commit()
    return jsonify({"course": courses_mod.get_course(db, cid),
                    "affectedPeople": db.execute("SELECT COUNT(*) c FROM users WHERE course_id = ?",
                                                 (cid,)).fetchone()["c"]})


@admin.delete("/courses/<cid>")
@require_perm("courses.manage")
def course_delete(cid):
    db = get_db()
    if not courses_mod.get_course(db, cid):
        return jsonify({"error": "not_found"}), 404
    n_u = db.execute("SELECT COUNT(*) c FROM users WHERE course_id = ?", (cid,)).fetchone()["c"]
    n_e = db.execute("SELECT COUNT(*) c FROM entries WHERE course_id = ?", (cid,)).fetchone()["c"]
    if n_u or n_e:
        return jsonify({"error": "%d people and %d entries refer to this course. Retire it instead "
                                 "(untick Active) - nothing is lost and nobody new can pick it." % (n_u, n_e)}), 409
    db.execute("DELETE FROM courses WHERE id = ?", (cid,))
    db.commit()
    return jsonify({"ok": True})


@admin.get("/courses/<cid>/people")
@require_perm("courses.manage")
def course_people(cid):
    """Who is on the course, where they are in it, and what does not fit."""
    db = get_db()
    course = courses_mod.get_course(db, cid)
    if not course:
        return jsonify({"error": "not_found"}), 404
    known = known_unit_keys()
    out = []
    for r in db.execute("SELECT * FROM users WHERE course_id = ? AND lifecycle != 'deleted'"
                        " ORDER BY display_name", (cid,)):
        postings = get_postings(r["username"])
        allowed = courses_mod.allowed_units(course, r["unit"], known)
        outside = sorted({p["unit"] for p in postings if allowed is not None and p["unit"] not in allowed})
        pr = courses_mod.progress(course, r["joined_ym"])
        out.append({
            "username": r["username"], "displayName": r["display_name"], "unit": r["unit"],
            "joinedYm": r["joined_ym"], "study": pr, "typedYear": r["pg_year"],
            "postingsOutside": outside,
            "peripheralDays": courses_mod.peripheral_days(postings, course),
            "active": bool(r["active"]),
        })
    return jsonify({"course": course, "people": out})


@admin.post("/courses/joined")
@require_perm("courses.manage")
def course_bulk_joined():
    """Set joining months for several trainees at once -- how the existing
    department gets its dates without opening forty profiles."""
    body = _json()
    rows = body.get("updates")
    if not isinstance(rows, list) or not rows or len(rows) > 300:
        return jsonify({"error": "Send a list of updates."}), 400
    db = get_db()
    done, bad = [], []
    for u in rows:
        if not isinstance(u, dict):
            continue
        row = db.execute("SELECT username, role, course_id FROM users WHERE username = ?",
                         (u.get("username"),)).fetchone()
        if not row or row["role"] not in ("resident", "senior_resident", "fellow"):
            bad.append({"username": u.get("username"), "error": "Not a trainee."})
            continue
        course = courses_mod.get_course(db, row["course_id"])
        ym, err = courses_mod.normalise_join(u.get("joinedYm"), course["startMonth"] if course else 1)
        if err:
            bad.append({"username": row["username"], "error": err})
            continue
        db.execute("UPDATE users SET joined_ym = ? WHERE username = ?", (ym, row["username"]))
        _account_event(db, row["username"], "profile_edited", g.user["username"], "joined: %s" % ym)
        done.append(row["username"])
    db.commit()
    return jsonify({"updated": done, "errors": bad})


# ===================================================================
#  BACKUPS
# ===================================================================
@admin.get("/backup/status")
@require_perm("backup.manage")
def backup_status():
    db = get_db()
    st = backup_mod.status(db)
    st["rule"] = alerts_mod.get_rules(db)["backup_due"]
    return jsonify(st)


@admin.post("/backup/download")
@require_perm("backup.manage")
def backup_download():
    db = get_db()
    data, name, sha = backup_mod.make_download()
    backup_mod.log(db, "download", g.user["username"], name, len(data), sha)
    db.commit()
    alerts_mod.sweep(db, force=True)        # clears "backup due" at once
    return Response(data, mimetype="application/octet-stream", headers={
        "Content-Disposition": "attachment; filename=%s" % name,
        "X-Backup-SHA256": sha, "X-Backup-Name": name, "Cache-Control": "no-store"})


@admin.post("/backup/restore/preview")
@require_perm("backup.manage")
def backup_restore_preview():
    db = get_db()
    try:
        if request.files.get("file"):
            rep = backup_mod.stage_upload(request.files["file"], g.user["username"], db)
        else:
            rep = backup_mod.stage_safety(_text(_json().get("safety"), 80), g.user["username"], db)
    except backup_mod.BackupError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"preview": rep})


@admin.post("/backup/restore/apply")
@require_perm("backup.manage")
def backup_restore_apply():
    body = _json()
    me = g.user["username"]
    if _text(body.get("confirm"), 20) != "RESTORE":
        return jsonify({"error": "Type RESTORE to confirm."}), 400
    key = "restore:%s" % me
    if rate_limit(key):
        return jsonify({"error": "Too many attempts. Wait 15 minutes and try again."}), 429
    db = get_db()
    row = db.execute("SELECT password_hash FROM users WHERE username = ?", (me,)).fetchone()
    if not row or not verify_password(row["password_hash"], _text(body.get("password"), 200) or ""):
        record_attempt(key)
        return jsonify({"error": "Your password is not correct."}), 403
    try:
        res = backup_mod.apply_restore(_text(body.get("token"), 60), me)
    except backup_mod.BackupError as e:
        return jsonify({"error": str(e)}), 400
    resp = jsonify({"ok": True, "safetyCopy": res["safetyCopy"], "signedOut": True})
    return clear_session_cookie(resp)


@admin.get("/backup/safety/<name>")
@require_perm("backup.manage")
def backup_safety_download(name):
    p = backup_mod.safety_path(name)
    if not p:
        return jsonify({"error": "not_found"}), 404
    with open(p, "rb") as f:
        data = f.read()
    return Response(data, mimetype="application/octet-stream", headers={
        "Content-Disposition": "attachment; filename=%s" % name, "Cache-Control": "no-store"})
