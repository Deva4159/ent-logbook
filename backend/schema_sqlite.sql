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
  created_at      TEXT NOT NULL,
  -- `active` stays the single boolean every existing query filters on.
  -- `lifecycle` records WHY it is what it is, which is the part that has to
  -- differ: an account the user switched off themselves comes back the
  -- moment they sign in, and an account an admin switched off must not --
  -- otherwise deactivating someone is unenforceable, because they simply
  -- log in again.
  --   active | self_deactivated | admin_deactivated | pending_deletion | deleted
  lifecycle       TEXT NOT NULL DEFAULT 'active',
  lifecycle_reason TEXT,
  lifecycle_at    TEXT,
  lifecycle_by    TEXT,
  last_seen_at    TEXT
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
-- Both approval dashboards filter on approval_state alone before anything
-- else, and idx_entries_approver leads with approver_username so it cannot
-- serve them -- every consultant's dashboard load was a full scan of
-- `entries`.
CREATE INDEX IF NOT EXISTS idx_entries_approval_state ON entries(approval_state, status);
-- Roster membership and the unit scope checks both start from postings.
CREATE INDEX IF NOT EXISTS idx_postings_username ON postings(username);
CREATE INDEX IF NOT EXISTS idx_postings_unit ON postings(unit);
CREATE INDEX IF NOT EXISTS idx_entries_author ON entries(author_username);
CREATE INDEX IF NOT EXISTS idx_entries_unit ON entries(unit);


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


-- ===================================================================
--  ACCOUNT LIFECYCLE
-- ===================================================================

-- A deactivation or deletion, from request to execution.
--
-- Deletion is never immediate and never destroys the work. After the buffer
-- the account is TOMBSTONED: the login is destroyed and the profile cleared,
-- while every entry, sign-off and consultant attribution stays exactly where
-- it is, rendered against an account marked "deleted". A trainee's logbook is
-- evidence for their certification and a consultant's name on an operation
-- record is part of someone else's evidence; neither survives a cascade.
CREATE TABLE IF NOT EXISTS account_requests (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  username       TEXT NOT NULL,
  kind           TEXT NOT NULL,          -- deactivate | delete
  reason         TEXT,
  -- pending | approved | rejected | cancelled | executed
  status         TEXT NOT NULL DEFAULT 'pending',
  requested_by   TEXT NOT NULL,
  requested_at   TEXT NOT NULL,
  decided_by     TEXT,
  decided_at     TEXT,
  decision_note  TEXT,
  -- The earliest moment the tombstone may be applied. Set when the request
  -- is approved, never on request, so the clock starts from the decision.
  scheduled_for  TEXT,
  executed_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_account_requests_status ON account_requests(status, id DESC);
CREATE INDEX IF NOT EXISTS idx_account_requests_user ON account_requests(username);

-- Append-only. "Who deleted Dr Menon's account, and when, and on whose
-- authority" has to stay answerable after the account itself is gone, which
-- is exactly when the users row can no longer answer it.
CREATE TABLE IF NOT EXISTS account_events (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  username       TEXT NOT NULL,
  action         TEXT NOT NULL,
  actor_username TEXT,
  detail         TEXT,
  created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_account_events_user ON account_events(username, id DESC);

-- The developer-only recoverable copy, taken when a deletion is approved.
-- Deliberately a snapshot blob rather than a set of live rows: the point is
-- that it still reads correctly after the account and its profile are gone.
CREATE TABLE IF NOT EXISTS account_archives (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  username       TEXT NOT NULL,
  display_name   TEXT,
  archived_at    TEXT NOT NULL,
  archived_by    TEXT,
  payload        TEXT NOT NULL           -- JSON snapshot
);
CREATE INDEX IF NOT EXISTS idx_account_archives_user ON account_archives(username);


-- ===================================================================
--  v7.4  PERMISSIONS, ALERTS, COURSES, BACKUPS
-- ===================================================================

-- Only how a role template DIFFERS from the one shipped in perms.py, so a
-- permission added in a later release reaches every template that has not
-- explicitly removed it. {"perm": "all"|"unit"|"off"}.
CREATE TABLE IF NOT EXISTS permission_templates (
  role_key    TEXT PRIMARY KEY,
  changes     TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  updated_by  TEXT
);

-- One person, one permission, granted or denied. A deny beats everything a
-- template gives. `units` is an optional explicit list for a unit-scoped
-- grant; absent means "their home unit".
CREATE TABLE IF NOT EXISTS permission_overrides (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  username  TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
  perm      TEXT NOT NULL,
  effect    TEXT NOT NULL CHECK (effect IN ('grant','deny')),
  scope     TEXT NOT NULL DEFAULT 'all',
  units     TEXT,
  note      TEXT,
  set_by    TEXT,
  set_at    TEXT NOT NULL,
  UNIQUE (username, perm)
);
CREATE INDEX IF NOT EXISTS idx_permission_overrides_user ON permission_overrides(username);

-- Append-only. Who changed whose rights, and what they were before.
CREATE TABLE IF NOT EXISTS permission_audit (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  actor_username TEXT,
  target_kind    TEXT NOT NULL,      -- user | template
  target         TEXT NOT NULL,      -- a username, or a template key
  action         TEXT NOT NULL,
  detail         TEXT,
  at             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_permission_audit_target ON permission_audit(target_kind, target, id DESC);

-- Alerts. 'manual' ones are written by the Developer; 'system' ones are
-- raised and cleared by alerts.sweep() from facts already in the database
-- (a posting about to end, an unfilled post...). dedupe_key makes a system
-- alert idempotent: the sweep runs on request from two workers and must not
-- raise the same thing twice.
CREATE TABLE IF NOT EXISTS alerts (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  kind        TEXT NOT NULL DEFAULT 'manual',
  rule        TEXT,
  dedupe_key  TEXT UNIQUE,
  title       TEXT NOT NULL,
  body        TEXT,
  severity    TEXT NOT NULL DEFAULT 'info',
  audience    TEXT NOT NULL,          -- JSON, see alerts.py
  link_view   TEXT,
  starts_at   TEXT,
  expires_at  TEXT,
  active      INTEGER NOT NULL DEFAULT 1,
  resolved_at TEXT,
  created_by  TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_live ON alerts(active, resolved_at);

CREATE TABLE IF NOT EXISTS alert_reads (
  alert_id     INTEGER NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
  username     TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
  read_at      TEXT,
  dismissed_at TEXT,
  PRIMARY KEY (alert_id, username)
);

-- Courses: what a trainee is enrolled in. See courses.py.
CREATE TABLE IF NOT EXISTS courses (
  id               TEXT PRIMARY KEY,
  name             TEXT NOT NULL,
  short_name       TEXT,
  role             TEXT NOT NULL CHECK (role IN ('resident','senior_resident','fellow')),
  duration_months  INTEGER NOT NULL,
  scope            TEXT NOT NULL DEFAULT 'department' CHECK (scope IN ('department','units')),
  units            TEXT NOT NULL DEFAULT '[]',
  allow_peripheral INTEGER NOT NULL DEFAULT 0,
  peripheral_units TEXT NOT NULL DEFAULT '[]',
  max_peripheral_months INTEGER,
  year_labels      TEXT NOT NULL DEFAULT '[]',
  start_month      INTEGER NOT NULL DEFAULT 1,
  notes            TEXT,
  active           INTEGER NOT NULL DEFAULT 1,
  sort             INTEGER NOT NULL DEFAULT 0,
  created_at       TEXT NOT NULL,
  updated_at       TEXT,
  updated_by       TEXT
);

CREATE TABLE IF NOT EXISTS backup_log (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  at             TEXT NOT NULL,
  kind           TEXT NOT NULL,       -- download | restore | safety
  actor_username TEXT,
  filename       TEXT,
  size_bytes     INTEGER,
  sha256         TEXT,
  detail         TEXT
);
CREATE INDEX IF NOT EXISTS idx_backup_log_at ON backup_log(id DESC);

-- v7.5: the department's doctors, whether or not they have an account.
-- See doctors.py. A row links to AT MOST ONE account (the unique index), and
-- an account to at most one row; that pair of constraints is what stops the
-- list and the accounts drifting into two versions of the same doctor.
CREATE TABLE IF NOT EXISTS doctors (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  display_name    TEXT NOT NULL,
  name_key        TEXT NOT NULL,          -- normalised, for matching only
  designation     TEXT NOT NULL,
  rank            INTEGER NOT NULL DEFAULT 0,
  home_unit       TEXT,
  department      TEXT,                   -- NULL / 'ENT' = this department; else e.g. 'Anaesthesia'
  reg_no          TEXT,                   -- optional council registration number
  email           TEXT,
  phone           TEXT,
  status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','left')),
  linked_username TEXT REFERENCES users(username) ON DELETE SET NULL,
  notes           TEXT,
  source          TEXT NOT NULL DEFAULT 'manual',
  created_by      TEXT,
  created_at      TEXT NOT NULL,
  updated_by      TEXT,
  updated_at      TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_doctors_linked ON doctors(linked_username) WHERE linked_username IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_doctors_reg ON doctors(reg_no) WHERE reg_no IS NOT NULL AND reg_no <> '';
CREATE INDEX IF NOT EXISTS idx_doctors_key ON doctors(name_key);

CREATE TABLE IF NOT EXISTS doctor_units (
  doctor_id INTEGER NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
  unit      TEXT NOT NULL,
  PRIMARY KEY (doctor_id, unit)
);
CREATE INDEX IF NOT EXISTS idx_doctor_units_unit ON doctor_units(unit);

-- A doctor asking for, or being offered, an account. `username` is plain TEXT
-- on purpose: an invite reserves a name before any account exists, and a
-- rejected sign-up deletes its account row.
CREATE TABLE IF NOT EXISTS doctor_claims (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  doctor_id    INTEGER NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
  kind         TEXT NOT NULL CHECK (kind IN ('self','invite')),
  state        TEXT NOT NULL CHECK (state IN ('pending','invited','approved','used','rejected','cancelled','expired')),
  username     TEXT NOT NULL,
  code_hash    TEXT,
  expires_at   TEXT,
  requested_by TEXT,
  requested_at TEXT NOT NULL,
  decided_by   TEXT,
  decided_at   TEXT,
  note         TEXT
);
-- At most ONE open claim per doctor. A second sign-up for the same row, or a
-- second invite, is refused by the database itself, not just by a check.
CREATE UNIQUE INDEX IF NOT EXISTS ux_claims_open ON doctor_claims(doctor_id) WHERE state IN ('pending','invited');
CREATE INDEX IF NOT EXISTS idx_claims_user ON doctor_claims(username);

-- v7.7: stages. A stage is one period on one course (PG, Senior Residency,
-- Fellowship). Finishing it saves a summary here and closes that stage's
-- entries (entries.stage_id), so they stay as a read-only record under the
-- same login. `username` columns are plain TEXT, like the other history tables.
CREATE TABLE IF NOT EXISTS stage_history (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT NOT NULL,
  role          TEXT NOT NULL,
  course_id     TEXT,
  course_name   TEXT,
  joined_ym     TEXT,
  completed_at  TEXT NOT NULL,
  completed_by  TEXT NOT NULL,
  note          TEXT,
  summary       TEXT NOT NULL,
  reopened_at   TEXT,
  reopened_by   TEXT,
  moved_to_role TEXT,
  moved_at      TEXT,
  moved_by      TEXT
);
CREATE INDEX IF NOT EXISTS idx_stage_user ON stage_history(username);

-- v7.7: where a consultant is posted, and requests to change it.
CREATE TABLE IF NOT EXISTS consultant_postings (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  username    TEXT NOT NULL,
  unit        TEXT NOT NULL,
  start_date  TEXT NOT NULL,
  end_date    TEXT,
  created_by  TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  request_id  INTEGER,
  note        TEXT
);
CREATE INDEX IF NOT EXISTS idx_cpost_user ON consultant_postings(username, start_date);
CREATE INDEX IF NOT EXISTS idx_cpost_unit ON consultant_postings(unit, start_date);

CREATE TABLE IF NOT EXISTS unit_requests (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  requester      TEXT NOT NULL,
  from_unit      TEXT,
  to_unit        TEXT NOT NULL,
  start_date     TEXT NOT NULL,
  end_date       TEXT,
  reason         TEXT,
  status         TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','approved','declined','withdrawn')),
  decided_by     TEXT,
  decided_at     TEXT,
  decision_note  TEXT,
  posting_id     INTEGER,
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ureq_status ON unit_requests(status, created_at);
CREATE INDEX IF NOT EXISTS idx_ureq_user ON unit_requests(requester);
