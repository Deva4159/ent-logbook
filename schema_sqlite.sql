-- ENT Surgical Logbook - SQLite schema (real backend).
-- Applied automatically on first run by db.py. SQLite is used here because
-- it needs no separate database server -- one file, on one persistent disk,
-- is enough for a single department's logbook. If you outgrow it (multiple
-- departments, heavy concurrent writes), the column layout below maps
-- directly onto Postgres; see README.md "Moving to Postgres later".

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  username        TEXT PRIMARY KEY,
  password_hash   TEXT NOT NULL,
  role            TEXT NOT NULL CHECK (role IN ('resident','senior_resident','fellow','consultant','developer')),
  display_name    TEXT NOT NULL,
  pg_year         TEXT,
  designation     TEXT,
  unit            TEXT,
  active          INTEGER NOT NULL DEFAULT 1,
  approval_status TEXT NOT NULL DEFAULT 'approved' CHECK (approval_status IN ('pending','approved')),
  created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS postings (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  username        TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
  unit            TEXT NOT NULL,
  start_date      TEXT NOT NULL,
  end_date        TEXT
);
CREATE INDEX IF NOT EXISTS idx_postings_username ON postings(username);

CREATE TABLE IF NOT EXISTS entries (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  author_username       TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
  entry_type            TEXT NOT NULL CHECK (entry_type IN ('surgical','other','case','academic','seminar')),
  unit                  TEXT,
  entry_date            TEXT NOT NULL,
  created_at            TEXT NOT NULL,
  site                  TEXT,
  procedures            TEXT NOT NULL DEFAULT '[]',
  -- Surgical/Other Procedure entries: one block per site touched in the
  -- same sitting, each {site, procedures, laterality, role} -- JSON array.
  -- Supports a genuine multi-organ combined case (e.g. Ear+Nose) with its
  -- own entrustment level per site, rather than one shared per entry. The
  -- flat site/procedures/laterality/role_level columns above are kept for
  -- every other entry type and for reading pre-migration rows, but a
  -- surgical/other entry's real data lives here from this schema version
  -- on -- see migrate_entries_table in db.py for the one-time backfill.
  procedure_blocks      TEXT NOT NULL DEFAULT '[]',
  setting               TEXT,
  other_setting_type    TEXT,
  hospital_number       TEXT,
  age                   TEXT,
  sex                   TEXT,
  diagnoses             TEXT NOT NULL DEFAULT '[]',
  diagnoses_secondary   TEXT NOT NULL DEFAULT '[]',
  comorbidities         TEXT NOT NULL DEFAULT '[]',
  laterality            TEXT,
  role_level            TEXT,
  consultant            TEXT,
  consultant_username   TEXT,
  assistants            TEXT,
  comments              TEXT,
  case_report           TEXT,
  linked_from_id        INTEGER REFERENCES entries(id) ON DELETE SET NULL,
  history               TEXT,
  examination           TEXT,
  academic_type         TEXT,
  academic_type_other   TEXT,
  seminar_type          TEXT,
  seminar_type_other    TEXT,
  topic                 TEXT,
  venue                 TEXT,
  details               TEXT,
  -- PG write-up tracking for an Interesting Case linked to a surgical entry:
  -- 'not_done' | 'in_progress' | 'done'. NULL for every other entry --
  -- validated in the app layer, not a CHECK, so it stays a plain ADD COLUMN
  -- on an existing database (see migrate_entries_table in db.py).
  paper_status          TEXT,
  -- 'draft' | 'final'. Only ever 'draft' for a Surgical/Other Procedure
  -- entry mid-fill; every other entry type is written 'final' straight
  -- away. A draft is visible only to its own author -- excluded from the
  -- roster, stats and CSV export queries every consultant/HOD-facing
  -- endpoint runs (see list_entries/roster/stats/export in api.py).
  status                TEXT NOT NULL DEFAULT 'final' CHECK (status IN ('draft','final')),
  -- Consultant sign-off. A CACHE of entry_approvals below, maintained by the
  -- same code that writes it -- the log is the truth. Cached because the
  -- entries list and the approval queue would otherwise each need a join and
  -- a walk of the log per row.
  approval_state        TEXT NOT NULL DEFAULT 'not_submitted',
  -- Who it was sent to. NOT consultant_username: that is free text plus an
  -- optional account, is frequently NULL, and an Interesting Case has no
  -- consultant field at all. The PG nominates a real account at submit.
  approver_username     TEXT
);
CREATE INDEX IF NOT EXISTS idx_entries_approver ON entries(approver_username, approval_state);
CREATE INDEX IF NOT EXISTS idx_entries_author ON entries(author_username);
CREATE INDEX IF NOT EXISTS idx_entries_unit ON entries(unit);

-- One row per actual change made to an entry after it was first created,
-- so authors and the relevant oversight roles can see who edited what and
-- when -- never overwritten, entries.id cascade-deletes its history with it.
CREATE TABLE IF NOT EXISTS entry_edits (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id        INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
  edited_by       TEXT NOT NULL,
  edited_at       TEXT NOT NULL,
  changes         TEXT NOT NULL -- JSON: {"field": {"old": ..., "new": ...}, ...}
);
CREATE INDEX IF NOT EXISTS idx_entry_edits_entry ON entry_edits(entry_id);

CREATE TABLE IF NOT EXISTS role_assignments (
  id                      INTEGER PRIMARY KEY AUTOINCREMENT,
  consultant_username     TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
  consultant_display_name TEXT,
  assignment_role         TEXT NOT NULL CHECK (assignment_role IN ('head_of_unit','coordinator','hod')),
  unit                    TEXT,
  start_at                TEXT,
  end_at                  TEXT,
  assigned_by             TEXT,
  assigned_at             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_role_assignments_consultant ON role_assignments(consultant_username);

CREATE TABLE IF NOT EXISTS password_resets (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  username        TEXT NOT NULL,
  note            TEXT,
  status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','resolved')),
  requested_at    TEXT NOT NULL,
  resolved_at     TEXT,
  resolved_by     TEXT
);

-- Single-row table holding every editable dropdown/list (categories,
-- procedures, role levels, units, diagnoses, etc.) as one JSON blob,
-- mirroring the field design already proven in the prototype.
CREATE TABLE IF NOT EXISTS config (
  id      TEXT PRIMARY KEY,
  data    TEXT NOT NULL
);

-- Server-side sessions: the cookie only ever carries a random opaque token,
-- never any user data. Lets a developer's "deactivate user" action or a
-- password change immediately invalidate that user's other open sessions.
CREATE TABLE IF NOT EXISTS sessions (
  token           TEXT PRIMARY KEY,
  username        TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
  created_at      TEXT NOT NULL,
  expires_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_username ON sessions(username);

-- Failed-login tracking for rate limiting (per username+IP).
CREATE TABLE IF NOT EXISTS login_attempts (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  key             TEXT NOT NULL,
  attempted_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_attempts_key ON login_attempts(key, attempted_at);


-- Append-only record of every approval event, mirroring entry_edits.
--
-- Deliberately NOT a boolean on entries that flips: flipping it back when a
-- record is re-edited destroys the evidence that approval ever happened. If
-- this logbook is put in front of an examiner, "was this case signed off, by
-- whom, and of which version" has to remain answerable after the entry has
-- been edited twice since.
--
-- edits_at_action is MAX(entry_edits.id) at the instant of the action. That
-- is what pins an approval to a *version* of the entry, so "approved, then
-- materially changed" is exact rather than inferred.
CREATE TABLE IF NOT EXISTS entry_approvals (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id          INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
  -- submitted | approved | changes_requested | withdrawn | released
  -- | unlock_requested | reopened_by_edit
  action            TEXT NOT NULL,
  actor_username    TEXT NOT NULL,
  actor_role        TEXT,            -- frozen at the time of the action
  approver_username TEXT,            -- who it was sent to (on 'submitted')
  on_behalf_of      TEXT,            -- set when a HoU/HOD acts for an absent consultant
  comment           TEXT,
  edits_at_action   INTEGER NOT NULL DEFAULT 0,
  created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entry_approvals_entry ON entry_approvals(entry_id);


-- ---------------------------------------------------------------- feedback
-- Feedback, complaints and suggestions from anyone with an account, readable
-- only by HOD / Course Coordinator / Developer.
--
-- author_username is NULL for an anonymous submission and that is the whole
-- mechanism: there is no separate "hidden author" column, so an anonymous
-- row genuinely does not contain who wrote it and nobody with database
-- access can look it up afterwards. The trade is that an anonymous
-- submission cannot be followed up or tracked by its own author -- the
-- submit screen says so before they choose.
--
-- The submitter's ROLE is deliberately not stored either, even though it
-- would help triage: in a department with one fellow, "anonymous, from a
-- fellow" is not anonymous.
--
-- ON DELETE SET NULL, not CASCADE: closing an account should not erase a
-- complaint that account raised. It becomes anonymous, which is the safe
-- direction to fail in.
CREATE TABLE IF NOT EXISTS feedback (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  kind            TEXT NOT NULL,   -- feedback | complaint | suggestion | bug
  subject         TEXT NOT NULL,
  body            TEXT NOT NULL,
  author_username TEXT REFERENCES users(username) ON DELETE SET NULL,
  status          TEXT NOT NULL DEFAULT 'open',  -- open | in_progress | closed
  created_at      TEXT NOT NULL,
  updated_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status, id DESC);

-- Internal handling trail: status changes and private notes, in one
-- append-only table for the same reason entry_approvals is one -- "when did
-- this get picked up, by whom, and what was decided" stays answerable.
-- Never shown to the submitter; they only ever see the status.
CREATE TABLE IF NOT EXISTS feedback_notes (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  feedback_id     INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
  actor_username  TEXT NOT NULL,
  action          TEXT NOT NULL,   -- note | status
  note            TEXT,
  status          TEXT,
  created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_notes_fb ON feedback_notes(feedback_id);
