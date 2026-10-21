# Project Supervisor Allocation: plan, algorithm and flow

Implementation of "Design and Implementation of Students-to-Supervisor Allocation System for
Final Year Projects Using Sentence-BERT (SBERT) Semantic Matching Model" (Chapters 1 to 4).
Case study: the departments of Yaba College of Technology, with ND and HND final year projects
allocated separately. Names come from `INSTITUTION_NAME` and `SITE_NAME` in `yctalloc/settings.py`.

## 1. What the report asks for, and where it lives in the code

| Report | Requirement | Where |
|---|---|---|
| 3.4.1 Steps 1-2, Listing 4.1 | Supervisor profile = normalised average of SBERT embeddings; fit = dot product | `engine/vectors.py`, `engine/encoders.py`, `core/services.py` |
| 3.4.1 Steps 3-8, Listing 4.2 | CGPA-priority allocation, capacity, threshold flagging | `engine/allocation.py` |
| 3.4.2 | Fine-tuning in rounds, held-out testing, keep a round only if not worse | `training/finetune_sbert.py`, `manage.py register_model` |
| 3.9, 4.7.2 | Top-1, Top-3, MRR on held-out records | `engine/evaluate.py`, Model versions page |
| Fig 3.1 | Three tiers: portals, logic, data | `templates/`, `core/` + `engine/`, `core/models.py` |
| Table 4.2 | Seven tables | `core/models.py` |
| Table 4.5 | Eleven screens in three portals | `core/views.py`, `templates/core/` |
| Table 4.6 | Eight unit tests | `tests/test_engine.py` |
| 4.7.3 | Integration and system testing | `tests/test_app.py` |

## 2. Algorithm

```
1. For each supervisor v:
     texts     = [specialisation] + [title + keywords of each past project]
     v.profile = NORMALISE(AVERAGE(SBERT.encode(texts)))
     v.vacancy = v.capacity
2. For each student s:
     s.emb     = NORMALISE(SBERT.encode(interest))
     Fit[s, v] = DOT(s.emb, v.profile)          for every supervisor v
     s.ranked  = supervisors by Fit, highest first
3. Sort students: CGPA high to low; ties by higher best Fit, then lower matric number
4. For each student in that order:
     take the first supervisor in s.ranked with vacancy > 0, decrement vacancy
     if Fit < threshold      -> also add to flagged list (weak match)
     if no supervisor has room -> add to flagged list (no place)
5. Coordinator resolves every flagged case, then publishes
```

SBERT is the only learning model. Step 3-4 is a priority rule (serial dictatorship), not a model.
Every text is encoded once and stored (`EmbeddingCache`), so a run costs one matrix product.

## 3. Flow

```
Student: register -> matric, CGPA, interest (validated) ----.
Supervisor: register -> specialisation, capacity, projects --+-> Coordinator: records, CSV uploads
                                                             |        |
                                             validation + text cleaning (engine/preprocess.py)
                                                             |
                                    SBERT embeddings -> fit matrix -> CGPA-priority allocation
                                                             |
                                    flagged cases -> accept / reassign within capacity
                                                             |
                                    publish -> student sees supervisor and why;
                                               supervisor sees student list; CSV / print report
```

## 4. Data model

Report tables: `users`, `students` (matric_no primary key), `supervisors`, `past_projects`,
`model_versions`, `fit_scores`, `allocations` (matric_no primary key, so one supervisor per student).

Added beyond the report:
- `institutions`: name, type, state, geopolitical zone, CGPA scale (4.00 or 5.00).
- `departments`: session and matric format.
- `cycles`: one per department and level (ND, HND): threshold, last run, publication state.
  Each allocation runs inside one cycle, so ND and HND students never compete for the same places
  and CGPAs are always compared on the same scale. Supervisors carry a capacity per level.
- `embedding_cache`: the "stored embeddings" box of Figure 3.1.

Integrity rules in the database itself: CGPA within range, capacity at least one, unique matric.

## 5. Tools

| Layer | Tool |
|---|---|
| Web framework | Django 5.2 (as in Table 4.1) |
| Database | SQLite by default; MySQL 8 (tested, PyMySQL driver) or Postgres through `DATABASE_URL` |
| Model inference | all-MiniLM-L6-v2 exported to ONNX, run with ONNX Runtime + tokenizers |
| Model training | sentence-transformers + PyTorch (separate machine), contrastive ranking loss |
| Arithmetic | NumPy |
| Front end | Django templates, hand-written CSS and JavaScript, no build step |
| Type and icons | Instrument Serif, Geist, Lucide (all bundled, works offline) |
| Serving | gunicorn + WhiteNoise |

Why ONNX for inference: PyTorch needs more memory than a free hosting tier gives. The bundled
model is the same network with 8-bit weights (23 MB). On the held-out demo records it ranks
identically to the full 32-bit model.

## 6. Design system

Generated with the ui-ux-pro-max skill (`search.py --design-system`, product type: education /
administration portal). Applied from it: the "Accessible and Ethical" style rules (4.5:1 text
contrast, visible focus rings, 44 px touch targets, reduced-motion support, labels and inline
errors on every field, tables that scroll inside their own wrapper) and the "Product demo +
features" landing pattern. Its suggested navy palette was replaced by the green and white brief.

- Colour: ink `#06281C`, green `#007A49`, bright green `#00A862`, leaf `#E3F4EA`, mist `#F4F9F6`, white.
- Type: Instrument Serif for headings, Geist for interface text, tabular numerals for scores.
- Effects (own vanilla CSS/JS versions of patterns popular on 21st.dev): border beam on the live
  matcher, pointer-following spotlight cards, shimmer on primary buttons, word-by-word headline
  reveal, number tickers, growing fit bars, view-transition page fades.
- Signature moment: the hero is a live SBERT matcher, and the report's worked example
  (Tables 4.3 and 4.4) plays as an animation.

## 7. Work plan as executed

1. Read the report; fix scope and departures (section 8).
2. Engine: vectors, allocation, verification, evaluation; the eight Table 4.6 tests.
3. Real pretrained SBERT running through ONNX Runtime; quantised and compared.
4. Database models, seed data for two departments in two zones, baseline evaluation.
5. Three portals, CSV imports, flag resolution, publishing, report export.
6. Interface, then a browser pass at desktop and phone widths.
7. End-to-end tests; fine-tuning script; hosting files.

## 8. Departures from the write-up (state these in the report)

1. CGPA range: the report fixes 0.00 to 4.00. The scale is a setting per institution (4.00 for YabaTech).
2. Tables: four added (institutions, departments, cycles, embedding cache). Students carry a level and supervisors a capacity per level, because ND and HND projects are allocated separately (supervisor's review).
3. Inference library: ONNX Runtime serves the model; sentence-transformers and PyTorch are used for fine-tuning only.
4. Supervisors who register themselves must be confirmed by the coordinator before they receive students.
5. Publishing is blocked until every flagged case is resolved, and records are locked while published.
6. Model versions are shared by the whole platform. A department-specific model would need a department column on `model_versions`.

## 9. Still open

- Table 4.7, fine-tuned row: run `training/finetune_sbert.py` on real past project records. The
  script could not be executed in the build sandbox (no PyTorch there), so treat its first run as a test.
- All demonstration people and records are fictional. The baseline scores come from those records.
- Section 4.7.3 user acceptance feedback must come from the real coordinator, supervisors and students.
