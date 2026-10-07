"""Changing a username without losing anything (v7.4).

Why this is not `UPDATE users SET username = ?`
----------------------------------------------
`users.username` is the primary key and is written into about forty columns
across twenty tables: the author of every entry, the person who signed it
off, who edited what, every audit event, every appointment. Five of them are
declared foreign keys with no ON UPDATE action (SQLite would refuse a rename
there -- the safe failure); the rest are plain TEXT with nothing to stop them
being orphaned in silence. A naive rename would leave each edit-history line
and each sign-off signature naming a person who no longer exists, which is
exactly the evidence a logbook is kept for.

So a rename is ONE transaction that rewrites every one of those columns, and
this module keeps the list of columns in one place (USERNAME_COLUMNS) with a
guard (uncovered_columns) that walks the live schema and refuses to rename if
any column that looks like it holds a username is missing from the list. A
table added in a later release cannot be missed quietly: the rename fails
loudly and the test suite fails with it.

A username that belongs to a closed account
-------------------------------------------
Closing an account keeps its row (a tombstone) because its entries and
sign-offs are other people's evidence. The Developer asked that a username
only be refused if an *active* user has it, so a closed account's name can be
taken -- but that must not let the new holder inherit the closed account's
records. The tombstone is therefore RENAMED out of the way (to "name~closed",
a form nobody can type or sign in with) by this same routine first, and all
its records move with it.

Accounts that are deactivated, pending deletion, or awaiting sign-up approval
are not closed -- the person may return -- so their names stay reserved.
"""
import json
import re

from auth import clean_username
from db import get_db

# (table, column, optional extra WHERE). Every column in the schema that holds
# a username belongs here; uncovered_columns() enforces it.
USERNAME_COLUMNS = [
    ("postings", "username", None),
    ("entries", "author_username", None),
    ("entries", "consultant_username", None),
    ("entries", "approver_username", None),
    ("entries", "locked_by", None),
    ("entry_edits", "edited_by", None),
    ("entry_approvals", "actor_username", None),
    ("entry_approvals", "approver_username", None),
    ("entry_approvals", "on_behalf_of", None),
    ("role_assignments", "consultant_username", None),
    ("role_assignments", "assigned_by", None),
    ("password_resets", "username", None),
    ("password_resets", "resolved_by", None),
    ("sessions", "username", None),
    ("feedback", "author_username", None),
    ("feedback_notes", "actor_username", None),
    ("users", "lifecycle_by", None),
    ("account_requests", "username", None),
    ("account_requests", "requested_by", None),
    ("account_requests", "decided_by", None),
    ("account_events", "username", None),
    ("account_events", "actor_username", None),
    ("account_archives", "username", None),
    ("account_archives", "archived_by", None),
    ("permission_templates", "updated_by", None),
    ("permission_overrides", "username", None),
    ("permission_overrides", "set_by", None),
    ("permission_audit", "actor_username", None),
    ("permission_audit", "target", "target_kind = 'user'"),
    ("alerts", "created_by", None),
    ("alert_reads", "username", None),
    ("courses", "updated_by", None),
    ("backup_log", "actor_username", None),
]

# Columns that look like usernames and are not, or are deliberately left.
IGNORED_COLUMNS = {
    # "login:<username>:<ip>" rate-limit keys; expire on their own in 15 minutes.
    ("login_attempts", "key"),
    # A role name ("consultant"), frozen on the approval row, not a username.
    ("entry_approvals", "actor_role"),
}

_SUSPECT = re.compile(r"username|_by$|^on_behalf_of$|approver|actor|^target$")

MIN_LEN, MAX_LEN = 3, 40


def _tables(db):
    return [r["name"] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]


def uncovered_columns(db):
    """Columns that hold (or look like they hold) a username but are not in
    USERNAME_COLUMNS. Empty means the rename list is complete."""
    covered = {(t, c) for t, c, _ in USERNAME_COLUMNS} | IGNORED_COLUMNS
    missing = []
    for t in _tables(db):
        cols = [r["name"] for r in db.execute("PRAGMA table_info(%s)" % t)]
        for c in cols:
            if (t, c) in covered or (t == "users" and c == "username"):
                continue
            if _SUSPECT.search(c):
                missing.append((t, c))
        for fk in db.execute("PRAGMA foreign_key_list(%s)" % t):
            if fk["table"] == "users" and (t, fk["from"]) not in covered:
                if (t, fk["from"]) not in missing:
                    missing.append((t, fk["from"]))
    return missing


def check_format(raw):
    """(clean, error). The username must already BE its cleaned form: silently
    rewriting what somebody typed would hand them an account name they did not
    choose."""
    if not isinstance(raw, str):
        return None, "Enter a username."
    typed = raw.strip().lower()
    clean = clean_username(typed)
    if clean != typed:
        return None, "Usernames use only letters, numbers, dots, underscores and hyphens."
    if len(clean) < MIN_LEN:
        return None, "Username must be at least %d characters." % MIN_LEN
    if len(clean) > MAX_LEN:
        return None, "Username must be at most %d characters." % MAX_LEN
    return clean, None


def holder_of(db, name, ignore=None):
    """The account that currently holds `name` (case-insensitively), if any."""
    rows = db.execute("SELECT username, lifecycle, active, approval_status, display_name"
                      " FROM users WHERE lower(username) = lower(?)", (name,)).fetchall()
    for r in rows:
        if ignore and r["username"] == ignore:
            continue
        return r
    return None


def availability(db, name, ignore=None):
    """('free'|'closed'|'taken', detail). 'closed' = held only by a tombstone,
    which a rename may displace."""
    h = holder_of(db, name, ignore)
    if not h:
        return "free", None
    if h["lifecycle"] == "deleted":
        return "closed", "held by a closed account (%s); its records stay with it" % h["display_name"]
    if h["approval_status"] == "pending":
        return "taken", "a sign-up awaiting approval is using it"
    if h["lifecycle"] == "active" and h["active"]:
        return "taken", "an active account (%s) is using it" % h["display_name"]
    return "taken", ("a %s account (%s) is holding it; reactivate or close that account first"
                     % (h["lifecycle"].replace("_", " "), h["display_name"]))


def _rewrite(db, old, new):
    """Every column, one name. Returns {table.column: rows}. Must run inside
    the caller's transaction."""
    touched = {}
    for table, col, cond in USERNAME_COLUMNS:
        sql = "UPDATE %s SET %s = ? WHERE %s = ?" % (table, col, col)
        if cond:
            sql += " AND " + cond
        n = db.execute(sql, (new, old)).rowcount
        if n:
            touched["%s.%s" % (table, col)] = n
    # entry_edits.changes is JSON holding the old/new values of every field,
    # including the two that name an account.
    n_json = 0
    for r in db.execute("SELECT id, changes FROM entry_edits WHERE changes LIKE ?",
                        ('%' + old + '%',)).fetchall():
        try:
            ch = json.loads(r["changes"])
        except (TypeError, ValueError):
            continue
        dirty = False
        for field in ("consultantUsername", "approverUsername"):
            v = ch.get(field)
            if isinstance(v, dict):
                for side in ("old", "new"):
                    if v.get(side) == old:
                        v[side] = new
                        dirty = True
        if dirty:
            db.execute("UPDATE entry_edits SET changes = ? WHERE id = ?", (json.dumps(ch), r["id"]))
            n_json += 1
    if n_json:
        touched["entry_edits.changes"] = n_json
    # The primary key last.
    db.execute("UPDATE users SET username = ? WHERE username = ?", (new, old))
    return touched


def rename_user(db, old, raw_new, actor):
    """Returns (result, error). result = {old, new, retired, touched}."""
    new, err = check_format(raw_new)
    if err:
        return None, err
    if not db.execute("SELECT 1 FROM users WHERE username = ?", (old,)).fetchone():
        return None, "No such account."
    if new == old:
        return None, "That is already this account's username."
    status, detail = availability(db, new, ignore=old)
    if status == "taken":
        return None, "That username is not available: %s." % detail
    missing = uncovered_columns(db)
    if missing:
        # Fail closed. Better to refuse the rename than to leave records
        # pointing at a name that no longer exists.
        return None, ("Rename refused: the schema has username columns this release does not "
                      "know how to rewrite (%s)." % ", ".join("%s.%s" % m for m in missing))

    if db.in_transaction:
        db.commit()
    db.execute("BEGIN IMMEDIATE")
    try:
        # Foreign keys are checked at COMMIT instead of per statement, so the
        # parent and its children can be rewritten in any order, and a rename
        # that leaves ANY dangling reference fails the commit and rolls back.
        db.execute("PRAGMA defer_foreign_keys = ON")
        retired = None
        if status == "closed":
            h = holder_of(db, new, ignore=old)
            n = 1
            while True:
                retired = "%s~closed%s" % (h["username"], "" if n == 1 else n)
                if not db.execute("SELECT 1 FROM users WHERE username = ?", (retired,)).fetchone():
                    break
                n += 1
            _rewrite(db, h["username"], retired)
            from api import _account_event, _now_iso  # noqa: WPS433 (avoids an import cycle)
            _account_event(db, retired, "username_retired", actor,
                           "Name '%s' was released for %s; this closed account's records moved to '%s'."
                           % (h["username"], new, retired))
        touched = _rewrite(db, old, new)
        from api import _account_event
        _account_event(db, new, "renamed", actor, "%s → %s" % (old, new))
        db.execute("DELETE FROM sessions WHERE username = ?", (new,))
        problems = db.execute("PRAGMA foreign_key_check").fetchall()
        if problems:
            raise RuntimeError("dangling references after rename: %s" % [dict(p) for p in problems][:3])
        db.commit()
    except Exception:
        db.rollback()
        raise
    from perms import invalidate
    invalidate()
    return {"old": old, "new": new, "retired": retired, "touched": touched}, None
