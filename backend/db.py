"""SQLite connection + schema bootstrap + default config seed."""
import json
import os
import sqlite3
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("ENTLOG_DB_PATH", os.path.join(BASE_DIR, "..", "data", "entlogbook.db"))
SCHEMA_PATH = os.path.join(BASE_DIR, "schema_sqlite.sql")

_local = threading.local()


def get_db():
    """One connection per thread (Flask's dev/prod WSGI servers are
    thread-based); sqlite3 connections are not safe to share across
    threads."""
    if not hasattr(_local, "conn"):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        # WAL mode (persists in the db file itself once set, so this is a
        # no-op after the first connection ever made) lets readers proceed
        # without blocking on a writer -- worth having under gunicorn's
        # multi-worker model, where each worker is a separate OS process
        # opening its own connection to the same file, not just separate
        # threads sharing one. Without it, the plain rollback-journal
        # default can surface as "database is locked" under concurrent
        # requests far sooner than WAL does.
        conn.execute("PRAGMA journal_mode = WAL")
        _local.conn = conn
    return _local.conn


DEFAULT_CATEGORIES = [
    {"key": "ear", "name": "Ear", "color": "var(--cat-ear)"},
    {"key": "nose", "name": "Nose & Paranasal Sinus", "color": "var(--cat-nose)"},
    {"key": "throat", "name": "Throat & Larynx", "color": "var(--cat-throat)"},
    {"key": "hn", "name": "Head & Neck", "color": "var(--cat-hn)"},
    {"key": "skull", "name": "Skull Base", "color": "var(--cat-skull)"},
    {"key": "trauma", "name": "Trauma & Emergency", "color": "var(--cat-trauma)"},
]

DEFAULT_PROCEDURES = {
    "ear": ["Myringotomy ± grommet (ventilation tube) insertion", "Myringoplasty", "Tympanoplasty (Type I–V)", "Mastoidectomy – cortical / simple", "Mastoidectomy – canal wall down (CWD)", "Mastoidectomy – canal wall up (CWU)", "Ossiculoplasty", "Stapedotomy / stapedectomy", "Cochlear implantation", "Bone-anchored hearing implant (BAHA / Bonebridge)", "EUA ear + microsuction / debridement", "Pinnaplasty / otoplasty", "Microtia / ear reconstruction", "Facial nerve decompression", "Glomus tumour excision"],
    "nose": ["Septoplasty / SMR", "FESS – Type I (limited)", "FESS – Type II / III (extended)", "Endoscopic DCR", "Turbinate reduction / turbinoplasty", "Nasal polypectomy", "Septorhinoplasty", "Choanal atresia repair", "Epistaxis – cautery / packing", "Epistaxis – endoscopic vessel ligation (SPA / AEA)", "Medial / partial maxillectomy", "Orbital decompression", "Adenoidectomy", "Endoscopic CSF rhinorrhoea repair"],
    "throat": ["Tonsillectomy", "Adenotonsillectomy", "Uvulopalatopharyngoplasty (UPPP)", "Direct laryngoscopy ± biopsy", "Microlaryngeal surgery (MLS)", "Laryngeal framework surgery (thyroplasty)", "Vocal cord injection / medialisation", "Tracheostomy", "Cricothyroidotomy", "Partial laryngectomy", "Total laryngectomy", "Rigid / flexible oesophagoscopy ± FB removal", "Panendoscopy"],
    "hn": ["Hemithyroidectomy", "Total thyroidectomy", "Parotidectomy – superficial", "Parotidectomy – total / radical", "Submandibular gland excision", "Neck node biopsy / excision", "Neck dissection – selective", "Neck dissection – modified radical / radical", "Branchial cyst / sinus excision", "Thyroglossal cyst excision (Sistrunk)", "Oral cavity tumour excision", "Flap reconstruction (pedicled / free)"],
    "skull": ["Endoscopic skull base surgery", "CSF leak repair (skull base)", "Combined approach (ENT + Neurosurgery)"],
    "trauma": ["Nasal bone fracture reduction", "Zygomatic / orbital fracture repair", "Mandible fracture fixation (ENT-assisted)", "Foreign body removal – ear", "Foreign body removal – nose", "Foreign body removal – throat / airway", "Peritonsillar abscess drainage", "Deep neck space abscess drainage"],
}

DEFAULT_UNITS = [
    {"key": "ent1", "fullName": "Oto-laryngology Unit 1 – General ENT with specialization in Skull Base Surgery & Head and Neck Surgery", "shortForm": "ENT 1", "group": "Oto-laryngology Units"},
    {"key": "ent2", "fullName": "Oto-laryngology Unit 2 – General ENT with specialization in Pediatric ENT and Cochlear Implant Unit", "shortForm": "ENT 2", "group": "Oto-laryngology Units"},
    {"key": "ent3", "fullName": "Oto-laryngology Unit 3 – General ENT, Rhinology & Anterior Skull Base Surgery", "shortForm": "ENT 3", "group": "Oto-laryngology Units"},
    {"key": "ent4", "fullName": "Oto-laryngology Unit 4 – General ENT with specialization in Otology, Neurotology & Implant Otology", "shortForm": "ENT 4", "group": "Oto-laryngology Units"},
    {"key": "ent5", "fullName": "Oto-laryngology Unit 5 – General ENT with specialization in Laryngology, Airway and Phono Surgery", "shortForm": "ENT 5", "group": "Oto-laryngology Units"},
    {"key": "hns1", "fullName": "Head and Neck Surgery Unit 1", "shortForm": "HNS 1", "group": "Peripheral Postings"},
    {"key": "hns2", "fullName": "Head and Neck Surgery Unit 2", "shortForm": "HNS 2", "group": "Peripheral Postings"},
]

DEFAULT_CONFIG = {
    "categories": DEFAULT_CATEGORIES,
    "procedures": DEFAULT_PROCEDURES,
    "roleLevels": ["Observed only", "Assisted (2nd assistant)", "Assisted (1st assistant)", "Performed under direct supervision", "Performed under indirect supervision", "Performed independently"],
    "settings": ["Elective", "Emergency"],
    "laterality": ["Right", "Left", "Bilateral", "Not required"],
    "pgYears": ["JR-1", "JR-2", "JR-3"],
    "units": DEFAULT_UNITS,
    "consultantDesignations": ["Assistant Professor", "Associate Professor", "Professor"],
    "diagnoses": ["Chronic Otitis Media", "Chronic Rhinosinusitis", "Deviated Nasal Septum", "Obstructive Sleep Apnea", "Head & Neck Malignancy", "Vocal Cord Palsy", "Otosclerosis", "Congenital Aural Atresia", "Allergic Rhinitis", "Laryngeal Papillomatosis", "Cholesteatoma", "Thyroid Nodule / Goitre"],
    "comorbidities": ["Diabetes Mellitus", "Hypertension", "Coronary Artery Disease", "Chronic Kidney Disease", "COPD / Asthma", "Hypothyroidism", "Immunocompromised", "None"],
    "academicTypes": ["CME", "Journal club", "Paper presentation", "University"],
    "otherProcedureSettings": ["OPD procedure", "Bedside procedure", "Emergency department procedure", "Treatment room procedure"],
    "sexOptions": ["Male", "Female", "Other"],
    "seminarTypes": ["Seminar", "Lecture", "Case presentation", "Guest talk"],
}


def _existing_tables(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


def migrate_users_table(conn):
    """Adds senior_resident/fellow to the role CHECK constraint and adds the
    approval_status column. SQLite can't ALTER a CHECK constraint or add a
    NOT NULL column with a CHECK in place, so an existing `users` table (from
    a database deployed before this feature) has to be rebuilt: create the
    new-shape table, copy every row across (existing accounts default to
    'approved' -- they were already active users, nothing should lock them
    out), drop the old table, rename the new one into place. A brand new
    database has no `users` table yet at this point, so this is a no-op and
    the CREATE TABLE below just makes it fresh with the new shape directly.
    """
    if "users" not in _existing_tables(conn):
        return
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "approval_status" in cols:
        return  # already migrated
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        """CREATE TABLE users_new (
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
        )"""
    )
    conn.execute(
        """INSERT INTO users_new
             (username, password_hash, role, display_name, pg_year, designation, unit, active, approval_status, created_at)
           SELECT username, password_hash, role, display_name, pg_year, designation, unit, active, 'approved', created_at
           FROM users"""
    )
    conn.execute("DROP TABLE users")
    conn.execute("ALTER TABLE users_new RENAME TO users")
    problems = conn.execute("PRAGMA foreign_key_check").fetchall()
    conn.execute("PRAGMA foreign_keys = ON")
    if problems:
        conn.rollback()
        raise RuntimeError(f"users table migration left dangling foreign keys: {[dict(p) for p in problems]}")
    conn.commit()


def migrate_entries_table(conn):
    """Adds nullable columns to an existing `entries` table as the app grows
    new per-entry fields. Each column is a plain ADD COLUMN with no CHECK
    constraint, so SQLite handles it directly -- no table rebuild needed
    (unlike migrate_users_table's role CHECK). A brand new database has no
    `entries` table yet at this point, so this whole function is a no-op and
    the CREATE TABLE below makes it fresh with every column already in place.

    Each column below is gated on its OWN presence check, not a single
    early return after the first migration -- an early return here would
    silently skip every migration added after the first one for any
    database that already has that first column (which, after this change
    ships, is every database, including the one currently ahead of you).
    """
    if "entries" not in _existing_tables(conn):
        return
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(entries)").fetchall()}

    if "paper_status" not in cols:
        # PG write-up tracking for an Interesting Case linked to a surgical entry.
        conn.execute("ALTER TABLE entries ADD COLUMN paper_status TEXT")
        conn.commit()
        cols.add("paper_status")

    if "procedure_blocks" not in cols:
        # Each Surgical/Other Procedure entry can now cover more than one
        # site in the same sitting (e.g. a combined Ear+Nose case), each
        # with its own site, procedures, laterality and entrustment level --
        # so those four fields move from flat columns into a JSON array of
        # blocks. create_entry/update_entry stop writing the old flat
        # site/procedures/laterality/role_level columns for these two entry
        # types from here on (case/academic/seminar entries never used them
        # and are untouched); this backfill turns every existing surgical/
        # other row's current flat values into an equivalent single-block
        # array so nothing already logged silently loses its site,
        # procedure, laterality or role the moment this migration runs.
        conn.execute("ALTER TABLE entries ADD COLUMN procedure_blocks TEXT NOT NULL DEFAULT '[]'")
        conn.commit()
        cols.add("procedure_blocks")
        rows = conn.execute(
            "SELECT id, site, procedures, laterality, role_level FROM entries WHERE entry_type IN ('surgical','other')"
        ).fetchall()
        for r in rows:
            try:
                procs = json.loads(r["procedures"]) if r["procedures"] else []
            except (TypeError, ValueError):
                procs = []
            block = {
                "site": r["site"] or "",
                "procedures": procs,
                "laterality": r["laterality"] or "",
                "role": r["role_level"] or "",
            }
            conn.execute("UPDATE entries SET procedure_blocks = ? WHERE id = ?", (json.dumps([block]), r["id"]))
        conn.commit()

    if "status" not in cols:
        # 'draft' | 'final'. Only Surgical/Other Procedure entries can ever
        # be 'draft' (see create_entry/_valid_procedure_block relaxation) --
        # every existing row predates this feature and was, by definition,
        # already a complete entry, so backfill to 'final' rather than NULL
        # so every pre-existing query that doesn't yet know about drafts
        # (roster, stats, CSV export) keeps seeing exactly what it saw
        # before this column existed.
        conn.execute("ALTER TABLE entries ADD COLUMN status TEXT NOT NULL DEFAULT 'final'")
        conn.commit()
        cols.add("status")


def init_db():
    conn = get_db()
    migrate_users_table(conn)
    migrate_entries_table(conn)
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    row = conn.execute("SELECT id, data FROM config WHERE id = 'lists'").fetchone()
    if row is None:
        conn.execute("INSERT INTO config (id, data) VALUES ('lists', ?)", (json.dumps(DEFAULT_CONFIG),))
    else:
        # Backfill any default key missing from an existing config doc,
        # the same "never silently stuck on an old shape" behaviour the
        # prototype had -- without this, a list added in a later update
        # never appears for an org whose config row predates it.
        current = json.loads(row["data"])
        changed = False
        for k, v in DEFAULT_CONFIG.items():
            if k not in current:
                current[k] = v
                changed = True
        if changed:
            conn.execute("UPDATE config SET data = ? WHERE id = 'lists'", (json.dumps(current),))
    conn.commit()
