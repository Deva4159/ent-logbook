# ENT Logbook — artwork + colour scheme

Everything in this archive mirrors your repository layout, so the folders
line up one-to-one with what's already on GitHub.

## Where each file goes

```
your-repo/
├── backend/
│   └── app.py            ← REPLACE
└── static/
    ├── app.js            ← REPLACE
    ├── styles.css        ← REPLACE
    ├── signin.webp       ← NEW
    └── art/              ← NEW FOLDER (13 files)
        ├── ear.png       ├── ossicles.png    ├── neuron.png
        ├── nose.png      ├── hearingaid.png  ├── facial.png
        ├── throat.png    ├── hands.png       └── theatre.png
        ├── hn.png        ├── frame.png
        ├── skull.png     └── trauma.png
```

Easiest route: on GitHub, open the repo → **Add file → Upload files** → drag
the whole `static` and `backend` folders in. GitHub keeps the folder
structure and will overwrite the three files that already exist. Commit, and
Render redeploys on push.

**Nothing else changes.** `requirements.txt`, `Procfile`, `api.py`, `db.py`,
`auth.py`, `schema_sqlite.sql` and `index.html` are all untouched. No
database migration — your stored categories already reference
`var(--cat-ear)` and friends, so the new colours land from CSS alone.

---

## What changed, and why

### The colour scheme is now derived from the paintings

Neutrals warmed, accent taken from the skull-base wash (`#1A6F8C`, which
lands within a few points of the teal you already had).

The six site colours use **option B — spread**. I want this recorded plainly:
these hues are *chosen*, not sampled. Once the new larynx arrived painted
blue, five of the six sites sat in two clusters — warm 0–35° and blue
190–225°. A greedy search over every swatch in every painting, taking for
each site the colour furthest in hue from those already claimed, could only
reach a **10° minimum gap**. Six series that close are unreadable on a chart.
The values below are spaced 46° apart and every hue appears somewhere in the
collage, but they are derived in spirit rather than measured.

|            | light     | dark      |
|------------|-----------|-----------|
| ear        | `#976C3E` | `#AD7C47` |
| nose       | `#3D7D94` | `#4690AB` |
| throat     | `#5C7F34` | `#76A343` |
| head & neck| `#B95465` | `#C46D7C` |
| skull base | `#35815B` | `#43A373` |
| trauma     | `#7667C1` | `#897CC9` |

If you'd rather stay literal, option C is one edit: point all six at
`var(--teal)` and let the artwork do the identifying. Every value above
clears 4.5:1 against its surface.

### A contrast bug, fixed

`.btn-primary` was `color:#fff` on `var(--teal)`. In dark mode `--teal` is a
pale blue, so white-on-accent measured **2.31:1** — below the 4.5 a button
label needs. There's now an `--on-teal` token: white in light, near-black in
dark. `.brand-mark` had the same problem and uses it too.

### The artwork

Each piece keeps its own pigment — nothing is recoloured. They were cut off
their sheets by **un-mixing** rather than masking: a watercolour edge is a
blend of ink and paper, so given `observed = a·ink + (1−a)·paper`, the true
pigment is `ink = (observed − (1−a)·paper) / a`. Masking alone leaves a grey
fringe that shows badly on dark surfaces.

Every piece then sits on a **paper plate** (`.plate` in styles.css). That is
not decoration: un-mixed watercolour dropped straight onto a dark surface
fluoresces — the thyroid goes hot pink — and the near-white pieces (gloved
hands, facial nerve) disappear entirely. The plate is invisible against a
light card and reads as a mounted tile in dark mode.

Placements in this build:

- **Stats page**, site breakdown — each organ beside its bar
- **Empty states** — gloved hands for "nothing logged yet", ossicles for
  "nothing waiting" in the approvals queue
- **Awaiting approval** — the printed border frame around the whole screen,
  the one page a new registrar sits and stares at
- **About / Roadmap** — the theatre scene as a page header

### Routes

`app.py` gains `/art/<name>.png`, served from an **allow-list** rather than a
directory wildcard, so it keeps the "every served path is named" rule the
existing routes follow. A new painting needs a line in `ART_FILES` — which is
the point. Anything not listed 404s.

---

## Still outstanding

**Trauma has no artwork of its own.** The theatre scene you sent for it is a
scene, not an injury — as a Trauma tile it would read as "any operation",
which is the one thing a category icon must not do. It's serving as the About
header instead, which is what it's actually good at. Trauma is currently
borrowing the sagittal airway from the collage. A nasal bone, a mandible, an
orbital floor or a plain fracture line would close it.

**The site step of the entry wizard is still a dropdown.** That's where the
organ plates would earn the most, but swapping a `<select>` for a card grid
changes form semantics inside the procedure-block editor, and I didn't want
to do that blind in the same change as everything else. Worth doing next, on
its own.

**Provenance.** Raised and decided already; noting it once so it isn't lost.
The theatre scene is signed **Mohd.Alfar**, so there is at least a name to
license from. The rest — the collage, the border frame, the ear-to-neuron
plate, the facial nerve, the larynx — have no attribution I can see, and two
of the originals carried a Pinterest watermark. Worth settling before the
site is shown outside the department.

**The sign-in screen still uses the theatre photograph** (`signin.webp`),
as you decided. The watercolour theatre scene is in `art/theatre.png` and
would work there instead — it's watercolour like the rest, carries no
trademark, and would retire the ZEISS question. Say the word and it's a
one-line swap in `styles.css`.
