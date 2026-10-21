"""Glue between the database and the engine: embeddings, fit scores, allocation, evaluation."""
import hashlib
import os

import numpy as np
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from engine import allocation as alloc_engine
from engine.encoders import load_encoder
from engine.evaluate import ranking_metrics
from engine.preprocess import clean_text, project_text
from engine.vectors import build_profile, fit_matrix

from .models import Allocation, EmbeddingCache, FitScore, ModelVersion, PastProject


class NoModel(Exception):
    pass


def encoder_for(version):
    return load_encoder(os.path.join(settings.MODELS_DIR, version.file_path))


def active_version():
    v = ModelVersion.active()
    if v is None:
        raise NoModel("No active SBERT model version. Run: python manage.py seed_demo")
    return v


def embed(version, texts):
    """Encode texts with the given model version, using the stored-embedding cache."""
    texts = [clean_text(t) for t in texts]
    hashes = [hashlib.sha1(t.encode("utf-8")).hexdigest() for t in texts]
    found = {c.text_hash: np.frombuffer(bytes(c.vector), dtype=np.float32)
             for c in EmbeddingCache.objects.filter(model_version=version, text_hash__in=set(hashes))}
    missing = {}
    for h, t in zip(hashes, texts):
        if h not in found:
            missing[h] = t
    if missing:
        vecs = encoder_for(version).encode(list(missing.values()))
        rows = []
        for h, v in zip(missing.keys(), vecs):
            found[h] = v
            rows.append(EmbeddingCache(model_version=version, text_hash=h, vector=v.tobytes()))
        EmbeddingCache.objects.bulk_create(rows, ignore_conflicts=True)
    return np.vstack([found[h] for h in hashes])


def supervisor_texts(sup, include_held_out=True):
    """Specialisation statement + titles and keywords of past projects (Section 3.4.1)."""
    projects = sup.past_projects.all()
    if not include_held_out:
        projects = projects.filter(held_out=False)
    return [clean_text(sup.specialisation_text)] + [project_text(p.title, p.keywords) for p in projects]


def profiles_for(dept, version, include_held_out=True):
    sups = [s for s in dept.supervisors.prefetch_related("past_projects") if s.ready]
    profiles = [build_profile(embed(version, supervisor_texts(s, include_held_out))) for s in sups]
    return sups, profiles


def quick_match(dept, text, k=5):
    """Rank a department's supervisors for one free-text interest (landing demo, previews)."""
    version = active_version()
    sups, profiles = profiles_for(dept, version)
    if not sups:
        return []
    q = encoder_for(version).encode([clean_text(text)])
    scores = fit_matrix(q, profiles)[0]
    order = np.argsort(-scores)[:k]
    return [{"name": sups[j].full_name, "specialisation": sups[j].specialisation_text,
             "score": round(float(scores[j]), 3)} for j in order]


def explain(student, sup, version, k=3):
    """Which of the supervisor's own texts lie closest to the student's interest."""
    texts = supervisor_texts(sup)
    labels = ["Specialisation statement"] + [p.title for p in sup.past_projects.all()]
    q = embed(version, [student.interest_text])
    sims = (embed(version, texts) @ q[0])
    order = np.argsort(-sims)[:k]
    return [{"label": labels[j], "score": float(sims[j])} for j in order]


@transaction.atomic
def run_allocation(cycle, threshold):
    """Steps 1-8 of the algorithm for one level of one department (an allocation cycle).
    Replaces any earlier run of the same cycle; the other level is untouched."""
    dept, level = cycle.department, cycle.level
    version = active_version()
    all_sups, all_profiles = profiles_for(dept, version)
    pairs = [(s, p) for s, p in zip(all_sups, all_profiles) if s.capacity_for(level) >= 1]
    sups, profiles = [s for s, _ in pairs], [p for _, p in pairs]
    pool = dept.students.filter(level=level)
    students = [s for s in pool if s.ready]
    skipped = pool.count() - len(students)
    if not sups or not students:
        return {"ok": False, "error": f"You need at least one supervisor who takes {level} students "
                                      f"and one {level} student with an interest statement."}
    fit = fit_matrix(embed(version, [s.interest_text for s in students]), profiles)
    rows = [{"matric": s.matric_no, "cgpa": float(s.cgpa)} for s in students]
    capacities = [s.capacity_for(level) for s in sups]
    allocation, flagged = alloc_engine.allocate(rows, capacities, fit.tolist(), threshold)
    checks = alloc_engine.verify(rows, capacities, fit.tolist(), allocation, flagged)
    order = alloc_engine.priority_order(rows, fit.tolist())

    FitScore.objects.filter(student__in=pool).delete()
    Allocation.objects.filter(student__in=pool).delete()
    scores, allocs = [], []
    position = {i: p + 1 for p, i in enumerate(order)}
    for i, s in enumerate(students):
        ranked = np.argsort(-fit[i], kind="stable")
        rank_of = {int(j): r + 1 for r, j in enumerate(ranked)}
        for j, sup in enumerate(sups):
            scores.append(FitScore(student=s, supervisor=sup, model_version=version,
                                   score=float(fit[i][j]), rank=rank_of[j]))
        j = allocation.get(s.matric_no)
        is_flagged = s.matric_no in flagged
        allocs.append(Allocation(
            student=s, supervisor=sups[j] if j is not None else None,
            fit_score=float(fit[i][j]) if j is not None else None,
            choice_rank=rank_of[j] if j is not None else None,
            priority_position=position[i], flagged=is_flagged,
            flag_reason=("no_place" if j is None else "weak_fit") if is_flagged else ""))
    FitScore.objects.bulk_create(scores)
    Allocation.objects.bulk_create(allocs)
    cycle.threshold = threshold
    cycle.last_run_at = timezone.now()
    cycle.last_run_version = version
    cycle.published = False
    cycle.published_at = None
    cycle.save()
    return {"ok": True, "students": len(students), "skipped": skipped, "placed": len(allocation),
            "flagged": len(flagged), "checks": checks, "version": version}


def verify_cycle(cycle):
    """Re-check the stored result of one cycle against the promises of Section 3.9,
    including any manual changes the coordinator made afterwards."""
    dept, level = cycle.department, cycle.level
    sups = list(dept.supervisors.all())
    load = {s.pk: 0 for s in sups}
    allocs = list(Allocation.objects.filter(student__department=dept, student__level=level)
                  .select_related("student", "supervisor"))
    for a in allocs:
        if a.supervisor_id:
            load[a.supervisor_id] = load.get(a.supervisor_id, 0) + 1
    capacity_ok = all(load[s.pk] <= s.capacity_for(level) for s in sups)
    # CGPA priority: among automatic placements, nobody turned away from a supervisor
    # outranks someone admitted there.
    scores = {}
    for f in FitScore.objects.filter(student__department=dept, student__level=level):
        scores[(f.student_id, f.supervisor_id)] = f.score
    admitted = {}
    for a in allocs:
        if a.supervisor_id and not a.manual:
            admitted.setdefault(a.supervisor_id, []).append(a.priority_position)
    priority_ok = True
    for a in allocs:
        if a.manual:
            continue
        got = a.fit_score if a.fit_score is not None else float("-inf")
        for s in sups:
            sc = scores.get((a.student_id, s.pk))
            if sc is None or s.pk == a.supervisor_id or sc <= got:
                continue
            if any(p > a.priority_position for p in admitted.get(s.pk, [])):
                priority_ok = False
    return {"capacity": capacity_ok, "single": True, "priority": priority_ok,
            "load": load, "manual": sum(1 for a in allocs if a.manual)}


def evaluate_version(version):
    """Top-1, Top-3 and MRR on held-out past projects, pooled over departments.
    Profiles are rebuilt without the held-out records so the model has not seen the answer."""
    from .models import Department
    enc = encoder_for(version)
    ranks_fit, n_train = [], 0
    all_fit, all_correct = [], []
    for dept in Department.objects.all():
        sups = [s for s in dept.supervisors.prefetch_related("past_projects") if s.ready]
        held = list(PastProject.objects.filter(supervisor__in=sups, held_out=True))
        if len(sups) < 2 or not held:
            continue
        n_train += PastProject.objects.filter(supervisor__in=sups, held_out=False).count()
        profiles = [build_profile(enc.encode(supervisor_texts(s, include_held_out=False))) for s in sups]
        index = {s.pk: j for j, s in enumerate(sups)}
        q = enc.encode([project_text(p.title, p.keywords, p.abstract) for p in held])
        fit = fit_matrix(q, profiles)
        for i, p in enumerate(held):
            m = ranking_metrics(fit[i:i + 1], [index[p.supervisor_id]])
            all_fit.append(m)
    if not all_fit:
        return None
    n = len(all_fit)
    version.top1 = sum(m["top1"] for m in all_fit) / n
    version.top3 = sum(m["top3"] for m in all_fit) / n
    version.mrr = sum(m["mrr"] for m in all_fit) / n
    version.n_eval, version.n_train = n, n_train
    version.save()
    return version
