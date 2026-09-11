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
  paper_status          TEXT
);
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
