# PairWise NG

Student-to-supervisor allocation for final year projects using Sentence-BERT semantic matching
and a CGPA-priority rule. Built for departments in tertiary institutions across Nigeria.
See `PLAN.md` for the algorithm, flow and how each part maps to the report.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo          # fictional demo data + registers the pretrained model
python manage.py runserver
```

Open http://127.0.0.1:8000. All demonstration accounts use the password `demo12345`:

| Role | Email |
|---|---|
| Coordinator, Computer Science, YABATECH (4.00 scale) | coordinator@yabatech.demo |
| Student, same department | student@yabatech.demo |
| Supervisor, same department | supervisor@yabatech.demo |
| Coordinator, Electrical Engineering, ABU (5.00 scale) | coordinator@abu.demo |
| Platform administrator (`/admin/`) | admin@pairwise.demo |

A full cycle: sign in as the coordinator, Run allocation, resolve Flagged cases, Publish, then
sign in as the student and the supervisor to see their results.

## Tests

```bash
python manage.py test tests
```

16 tests: the eight of report Table 4.6 (two of them on 1,000 random problems each), the worked
example of Table 4.4, and seven end-to-end tests of the portals, database, SBERT module and
allocation module.

## Real data

- Institutions, departments and coordinator accounts: `/admin/` (set role = Coordinator and pick the department).
- Students: Students page, Add or Import from CSV (`data/students_template.csv`).
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

SQLite by default. For MySQL (the report's database) uncomment `mysqlclient` in
`requirements.txt` and set `DATABASE_URL=mysql://user:pass@host:3306/pairwise`.
Postgres works the same way with a `postgres://` URL.

## Hosting on Render (free plan)

Push to GitHub, then New > Blueprint and pick the repo; `render.yaml` selects the free plan.
The free disk is wiped on every restart, so with SQLite any account created on the site
disappears and the demo data is rebuilt. To keep accounts, create a free Postgres database
(Neon or Supabase) and add its URL as `DATABASE_URL` in the Render dashboard.

## Layout

```
engine/      matching and allocation, no Django: vectors, encoders, allocation, evaluate, preprocess
core/        Django app: models, forms, views, services, management commands
templates/   portals      static/   CSS, JS, fonts, icons
models/      SBERT model folders (one per version)
training/    fine-tuning script     data/   demo data and CSV templates     tests/
```
