# ENT Surgical Logbook — real backend

This is the production rebuild of the logbook: a real Flask server, a real
SQLite database file, and server-side login with password hashing — not the
Claude Artifact prototype you were testing with PGs before. It runs the same
frontend you already reviewed; only what's underneath it changed.

## What actually changed, and why

You asked for "the real rebuild with its own domain, database and login." Two
things are true about what you're getting:

1. **The database and login are real now.** Passwords are hashed on the
   server with `scrypt` (memory-hard, not just SHA/MD5) the instant they
   arrive — the browser never hashes or stores them. Logins are opaque
   server-side session tokens in an httpOnly cookie, not a token you could
   read out of the browser and reuse. Ten wrong password attempts in 15
   minutes locks that username+IP out for the rest of the window. All of
   this replaces the prototype's client-side hash-and-compare, which was a
   workflow gate, not real security.

2. **The stack is Python/Flask/SQLite, not Node/Express/Postgres.** I built
   this in a cloud sandbox that blocks all outbound package installs (npm,
   pip, and apt registries are all firewalled off from where I was working).
   I could not install Express, Postgres drivers, or bcrypt. Flask and
   SQLite were already present, so I rebuilt on those instead. This is not
   a downgrade — Flask is a mainstream production framework and SQLite in
   WAL mode is a legitimate choice for one department's traffic (a handful
   of residents and consultants, not a hospital-wide system) — but it does
   mean the deployment steps below are Python-flavored, not Node-flavored.
   If you'd specifically rather have Postgres later, the schema
   (`backend/schema_sqlite.sql`) is written to map column-for-column onto
   Postgres, so migrating is a schema-port, not a rewrite.

I cannot register a domain or create a hosting account for you — those need
your payment details and identity. What follows is the exact sequence of
steps to do both yourself, plus everything already built and tested.

## What's in this folder

```
ent-logbook-app/
  backend/
    app.py              Flask app: routes, security headers, CSRF check
    api.py               All /api/... endpoints (entries, users, config, etc.)
    auth.py               Password hashing, sessions, rate limiting
    db.py                 SQLite connection + schema bootstrap + default lists
    schema_sqlite.sql     Table definitions
  static/
    index.html             The frontend (same UI you already tested)
  data/                    The SQLite database file lives here at runtime
  requirements.txt        Python dependencies
  Procfile                 Start command for Render/Railway
  README.md                This file
```

## Running it locally (to try it before deploying)

You'll need Python 3.10+ installed. Then, from this folder:

```
pip install -r requirements.txt
cd backend
python3 app.py
```

Open `http://127.0.0.1:8000`. The very first account you sign up with
automatically becomes the developer/admin account — sign that one up
yourself first, before sending the link to anyone else, so you end up as the
admin and not a random PG.

To reset and start over locally, stop the server and delete the three files
in `data/` (`entlogbook.db`, `entlogbook.db-shm`, `entlogbook.db-wal`).

## Environment variables

None are required to run it — sensible defaults are built in. These are
available if you want to override them:

| Variable | Default | What it does |
|---|---|---|
| `PORT` | `8000` | Port the server listens on |
| `ENTLOG_DB_PATH` | `data/entlogbook.db` | Where the SQLite file lives |
| `FLASK_DEBUG` | off | Never set this to `1` in production |

## Deploying it for real: Render

I'm recommending **Render** specifically, not just "a host" — I compared it
against Railway, Fly.io, PythonAnywhere, and a bare VPS on three things that
matter for this app: it needs a persistent disk (SQLite is a file, not a
connection string), it needs a custom domain with automatic HTTPS, and you
are not going to hand-manage a Linux server. Render is the one that gives
you all three through a plain web dashboard, for about **$7.25/month**
(a $7/month "Starter" web service plus $0.25/GB for a small persistent
disk — 1GB is more than enough for a single department's records). Railway's
free tier is gone (it's a one-time $5 trial credit, then ~$5/month minimum);
Fly.io is cheaper (~$3.50/month) but expects you to install and use a
command-line tool, which defeats the point. A VPS is cheaper still but makes
you responsible for security patches and HTTPS certificates yourself — not
appropriate to take on alone.

Prices and free-tier terms do shift over time — check
[render.com/pricing](https://render.com/pricing) before you commit, but this
was current as of writing.

### Step 1 — Buy a domain

Any of these are reputable and let you buy a domain yourself in a few
minutes, no developer needed:

- **[Porkbun](https://porkbun.com)** — flat pricing, no renewal price-hike
  trick (~$11/year for a `.com`). My default recommendation for a first
  domain.
- **[Namecheap](https://namecheap.com)** — similar, sometimes cheaper in
  year one, but the renewal price is noticeably higher than the first-year
  promo price — check that number before you buy.
- **[Cloudflare Registrar](https://www.cloudflare.com/products/registrar/)**
  — sold at Cloudflare's wholesale cost with no markup, so usually the
  cheapest — but it only works if you're also willing to point the domain's
  DNS at Cloudflare, which is one more concept to learn.

Something like `entlogbook.yourhospitalname.com` or `<department>-logbook.com`
works fine. You don't need anything else from the registrar yet — come back
to it in Step 4.

### Step 2 — Push this code to GitHub

Render deploys from a GitHub repository, not a zip upload. If you don't
already have a GitHub account, create one free at
[github.com](https://github.com), then create a new (private) repository
and upload this folder's contents to it — GitHub's own "upload files" button
in the browser works fine for this; you don't need git command-line
experience.

### Step 3 — Create the Render web service

1. Sign up at [render.com](https://render.com) (free) and connect your
   GitHub account.
2. Click **New → Web Service**, pick the repository you just created.
3. Set:
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn -w 2 -b 0.0.0.0:$PORT --chdir backend app:app`
   - **Instance Type**: Starter ($7/month) — the free tier doesn't support
     persistent disks, and you need one for the database file.
4. Under **Disks**, add a disk: name it `data`, mount path `/opt/render/project/src/data`,
   size 1GB.
5. Add an environment variable `ENTLOG_DB_PATH` = `/opt/render/project/src/data/entlogbook.db`
   so the app writes its database onto that persistent disk (not into the
   app's own code directory, which Render wipes on every deploy).
6. Click **Create Web Service**. Render will build and start it — you'll get
   a URL like `https://ent-logbook.onrender.com` within a couple of minutes.
7. Visit that URL and sign up as the very first user — this becomes your
   developer/admin account. Do this before sharing the link with anyone.

### Step 4 — Point your domain at it

1. In the Render dashboard, open your web service → **Settings → Custom
   Domains → Add Custom Domain**, and enter the domain you bought.
2. Render will show you a DNS record to add (usually a `CNAME`, or an `A`
   record if you're using the bare domain without `www`).
3. Go to your domain registrar's DNS settings for that domain, and add
   exactly the record Render showed you. This part looks different on each
   registrar's site but the concept is identical everywhere: you're telling
   the internet "this domain name points at Render's servers."
4. Wait 10–60 minutes for DNS to propagate, then reload your domain in a
   browser. Render issues the HTTPS certificate automatically once the DNS
   record is verified — no extra step from you.

From here on, `https://yourdomain.com` is the login link you send to PGs and
consultants.

## Backups

There are no automatic off-site backups yet. The database is one file on
Render's persistent disk — Render's own disks are backed by durable storage,
but that protects against hardware failure, not against you accidentally
deleting the wrong thing. Two options, in order of effort:

- **Manual**: periodically download the database file via Render's shell
  (`Shell` tab in the dashboard → `cat data/entlogbook.db > /dev/stdout` is
  awkward over a web shell; easier is adding a small scheduled job — ask a
  developer to help set up Render's **Cron Jobs** feature to copy the file
  somewhere, or just do it by hand monthly at first).
- **Better**: once you have real usage, it's worth paying a developer an
  hour to wire up automatic nightly backups to cloud storage (S3, or even
  emailing yourself the file). This is a reasonable thing to defer until
  you have real data worth protecting — don't let "no automated backups"
  block you from launching the pilot.

## What's already been tested

Before handing this over, I ran an automated end-to-end test against this
exact codebase (signup, session-cookie persistence across page reload,
admin user creation, posting + entry creation with automatic unit
resolution from posting dates, the consultant roster view, wrong-password
handling, and CSV export) — all passed. That's a check that the plumbing
works, not a substitute for a small group of real PGs trying it and telling
you what's confusing or missing.
