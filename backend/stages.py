"""Stages (v7.7): finishing a course, keeping the records, moving on.

A person's training runs through stages: PG Residency, then Senior Residency
or a Fellowship, and finally Consultant. It is ONE account all the way
through, so their records and signatures never have to be copied anywhere.

* COMPLETING a stage saves a summary (how many entries of each kind, how many
  were signed off) and marks every entry the person has logged so far with
  that stage (entries.stage_id). Those entries become a read-only record.
  The person can still sign in, look at them and export them, but cannot add
  new ones until they are moved to a new stage.
* MOVING someone to the next stage (Senior Resident, Fellow or Consultant)
  gives the same account its new role, course and joining month. New entries
  belong to the new stage; the old ones stay with the stage they were logged
  in. A person can be moved long after completing, for example a former PG
  who joins a fellowship years later.
* A person who becomes a Consultant keeps their old records in an Archive.
* REOPENING undoes a completion, if nothing has been done with the account
  since, so a mistake is not permanent.

Everything is recorded in stage_history and the account's event log.
"""
import datetime
import json

import courses as courses_mod

TRAINEE_ROLES = ("resident", "senior_resident", "fellow")
# Where each kind of trainee may go next. A Fellow does not go "down" to
# residency, and nobody skips straight to Developer.
NEXT_ROLES = {
    "resident": ["senior_resident", "fellow", "consultant"],
    "senior_resident": ["fellow", "consultant"],
    "fellow": ["consultant"],
}
SIGNOFF_TYPES = ("surgical", "other", "case")

ACTIVE = "active"
COMPLETED = "completed"


def now_iso():
    return datetime.datetime.utcnow().isoformat() + "Z"


def status_of(row):
    keys = row.keys()
    return (row["stage_status"] if "stage_status" in keys and row["stage_status"] else ACTIVE)


def is_completed(row):
    return status_of(row) == COMPLETED


# ---------------------------------------------------------------- summaries
def _summarise(db, username, stage_id):
    """Counts for the entries of one stage. stage_id None = the stage the
    person is on now (entries not yet closed into a stage)."""
    if stage_id is None:
        rows = db.execute(
            "SELECT entry_type, status, approval_state, COUNT(*) c FROM entries"
            " WHERE author_username = ? AND stage_id IS NULL GROUP BY entry_type, status, approval_state",
            (username,)).fetchall()
    else:
        rows = db.execute(
            "SELECT entry_type, status, approval_state, COUNT(*) c FROM entries"
            " WHERE author_username = ? AND stage_id = ? GROUP BY entry_type, status, approval_state",
            (username, stage_id)).fetchall()
    by_type = {}
    out = {"total": 0, "drafts": 0, "final": 0, "approved": 0, "pending": 0,
           "changesRequested": 0, "notSent": 0, "byType": by_type}
    for r in rows:
        n = r["c"]
        out["total"] += n
        by_type[r["entry_type"]] = by_type.get(r["entry_type"], 0) + n
        if r["status"] == "draft":
            out["drafts"] += n
            continue
        out["final"] += n
        if r["entry_type"] in SIGNOFF_TYPES:
            st = r["approval_state"]
            if st == "approved":
                out["approved"] += n
            elif st == "pending":
                out["pending"] += n
            elif st == "changes_requested":
                out["changesRequested"] += n
            else:
                out["notSent"] += n
    return out


def current_summary(db, username):
    return _summarise(db, username, None)


def stage_dict(db, r):
    try:
        summary = json.loads(r["summary"]) if r["summary"] else {}
    except (TypeError, ValueError):
        summary = {}
    live = _summarise(db, r["username"], r["id"])
    return {
        "id": r["id"], "role": r["role"], "courseId": r["course_id"], "courseName": r["course_name"],
        "joinedYm": r["joined_ym"], "completedAt": r["completed_at"], "completedBy": r["completed_by"],
        "note": r["note"], "reopenedAt": r["reopened_at"],
        "movedToRole": r["moved_to_role"], "movedAt": r["moved_at"],
        # The summary saved on the day it was completed, and what is on file now.
        "summaryAtCompletion": summary, "summary": live,
    }


def history(db, username):
    rows = db.execute("SELECT * FROM stage_history WHERE username = ? AND reopened_at IS NULL ORDER BY id",
                      (username,)).fetchall()
    return [stage_dict(db, r) for r in rows]


def open_stage_row(db, username):
    """The completed-but-not-yet-moved stage, if the account is in that state."""
    return db.execute(
        "SELECT * FROM stage_history WHERE username = ? AND reopened_at IS NULL AND moved_at IS NULL"
        " ORDER BY id DESC LIMIT 1", (username,)).fetchone()


def overview(db, user_row):
    """Everything the stage card on a person's page needs."""
    u = user_row
    role = u["role"]
    status = status_of(u)
    out = {
        "role": role, "status": status,
        "canComplete": role in TRAINEE_ROLES and status == ACTIVE,
        "canMove": role in TRAINEE_ROLES and status == COMPLETED,
        "canReopen": False,
        "nextRoles": NEXT_ROLES.get(role, []),
        "current": current_summary(db, u["username"]),
        "stages": history(db, u["username"]),
    }
    if status == COMPLETED:
        out["canReopen"] = open_stage_row(db, u["username"]) is not None
    return out


# ----------------------------------------------------------------- actions
def complete(db, user_row, actor, note=None, acknowledge=False):
    """Close the person's current stage. -> (stage_id, error, detail)."""
    u = user_row
    if u["role"] not in TRAINEE_ROLES:
        return None, "Only a trainee has a stage to complete.", None
    if status_of(u) == COMPLETED:
        return None, "This stage is already complete.", None
    cur = current_summary(db, u["username"])
    unfinished = cur["drafts"] + cur["pending"] + cur["changesRequested"]
    if unfinished and not acknowledge:
        return None, "unfinished", cur
    course = courses_mod.get_course(db, u["course_id"]) if u["course_id"] else None
    cur_row = db.execute(
        "INSERT INTO stage_history (username, role, course_id, course_name, joined_ym, completed_at,"
        " completed_by, note, summary) VALUES (?,?,?,?,?,?,?,?,?)",
        (u["username"], u["role"], u["course_id"], course["name"] if course else None, u["joined_ym"],
         now_iso(), actor, (note or "").strip()[:500] or None, json.dumps(cur)))
    sid = cur_row.lastrowid
    db.execute("UPDATE entries SET stage_id = ? WHERE author_username = ? AND stage_id IS NULL",
               (sid, u["username"]))
    db.execute("UPDATE users SET stage_status = ? WHERE username = ?", (COMPLETED, u["username"]))
    return sid, None, cur


def reopen(db, user_row, actor):
    u = user_row
    st = open_stage_row(db, u["username"])
    if status_of(u) != COMPLETED or not st:
        return "There is no completed stage to reopen."
    db.execute("UPDATE entries SET stage_id = NULL WHERE author_username = ? AND stage_id = ?",
               (u["username"], st["id"]))
    db.execute("UPDATE stage_history SET reopened_at = ?, reopened_by = ? WHERE id = ?",
               (now_iso(), actor, st["id"]))
    db.execute("UPDATE users SET stage_status = ? WHERE username = ?", (ACTIVE, u["username"]))
    return None


def mark_moved(db, user_row, actor, new_role):
    st = open_stage_row(db, user_row["username"])
    if st:
        db.execute("UPDATE stage_history SET moved_to_role = ?, moved_at = ?, moved_by = ? WHERE id = ?",
                   (new_role, now_iso(), actor, st["id"]))
    db.execute("UPDATE users SET stage_status = ? WHERE username = ?", (ACTIVE, user_row["username"]))


def has_archive(db, username):
    """A consultant who once trained here has records to look back on."""
    return db.execute("SELECT 1 FROM entries WHERE author_username = ? LIMIT 1", (username,)).fetchone() is not None
