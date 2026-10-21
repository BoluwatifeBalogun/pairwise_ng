# Project Supervisor Allocation, Yaba College of Technology

Student-to-supervisor allocation for final year projects using Sentence-BERT semantic matching
and a CGPA-priority rule. Built for the departments of Yaba College of Technology; ND and HND
projects are allocated in separate runs.
See `PLAN.md` for the algorithm, flow and how each part maps to the report.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py setup_site         # registers the model; loads fictional demo data unless DEMO_MODE=0
python manage.py runserver
```

Open http://127.0.0.1:8000. All demonstration accounts use the password `demo12345`:

| Role | Email |
|---|---|
| Coordinator, Computer Science | coordinator@yabatech.demo |
| HND student, Computer Science | student@yabatech.demo |
| ND student, Computer Science | student.nd@yabatech.demo |
| Supervisor, Computer Science | supervisor@yabatech.demo |
| Coordinator, Electrical and Electronic Engineering | coordinator.ee@yabatech.demo |
| Platform administrator (`/admin/`) | admin@yabatech.demo |

A full cycle: sign in as the coordinator, pick HND or ND in the sidebar, Run allocation, resolve
Flagged cases, Publish, then sign in as the student and the supervisor to see their results. The
other programme is a separate run.

## Tests

```bash
python manage.py test tests
```

19 tests: the eight of report Table 4.6 (two of them on 1,000 random problems each), the worked
example of Table 4.4, seven end-to-end tests of the portals, database, SBERT module and
allocation module, and three for the administrator account and running without demo data.

## Real data

- Institutions, departments and coordinator accounts: `/admin/` (set role = Coordinator and pick the department).
- Students: Students page (on the level you are working on), Add or Import from CSV
  (`data/students_template.csv`; the optional `level` column takes ND or HND).
- Past projects: Past projects page, Upload (`data/past_projects_template.csv`). No student names or matric numbers.
- `python manage.py seed_demo --reset` wipes and reloads the demonstration data.
- Set `DEMO_MODE=0` to hide the demonstration sign-in shortcuts.

## Fine-tuning (Table 4.7, second row)

On a machine with PyTorch (RunPod, Colab):

```bash
pip install -r requirements-train.txt
python manage.py export_training_data --out training/data
python training/finetune_sbert.py --round 1
python manage.py register_model sbert-round-1 --round 1 --activate
```

Mark which past projects are held out in `/admin/` (the `held_out` tick) before exporting: about
one fifth, plus the most recent session. A round that scores below the active version on the
held-out records is registered but not activated.

## Database

SQLite by default. Set `DATABASE_URL` to use a hosted database; no code change is needed.

- MySQL (the report's database): `mysql://USER:PASSWORD@HOST:PORT/DBNAME`
- PostgreSQL: `postgres://USER:PASSWORD@HOST:PORT/DBNAME`

The MySQL driver is PyMySQL, which is pure Python, so nothing has to be compiled on the host.
Tested against MySQL 8.0 and PostgreSQL 16 (over SSL): migrations, demo seed, all 19 tests,
and a browser pass on each.

## Hosting on Render (free plan) with a hosted database

1. Create a free database: a Neon project (copy its `postgresql://...` connection string), or a
   filess.io MySQL 8 database (note its host, port, user, password and database name).
2. Push this folder to GitHub.
3. On Render choose New > Blueprint and pick the repo. `render.yaml` selects the free plan and
   asks for `DATABASE_URL`: paste the Neon string as it is, or enter
   `mysql://USER:PASSWORD@HOST:PORT/DBNAME` with the filess.io values.
4. In the Render dashboard set `ADMIN_EMAIL` and `ADMIN_PASSWORD`. `render.yaml` sets
   `DEMO_MODE=0`; change it to `1` if you want the fictional demonstration data.
5. The first start creates the tables. Later starts keep everything, so accounts made on the
   site survive restarts.

Notes: free databases allow few simultaneous connections, so the app closes its connection
after every request (`DB_CONN_MAX_AGE=0`) and runs one worker with two threads. The demo data
plus one allocation run uses about 1 MB of the 10 MB free allowance. Without `DATABASE_URL`
the site falls back to SQLite, which Render wipes on every restart.

## Layout

```
engine/      matching and allocation, no Django: vectors, encoders, allocation, evaluate, preprocess
core/        Django app: models, forms, views, services, management commands
templates/   portals      static/   CSS, JS, fonts, icons
models/      SBERT model folders (one per version)
training/    fine-tuning script     data/   demo data and CSV templates     tests/
```
