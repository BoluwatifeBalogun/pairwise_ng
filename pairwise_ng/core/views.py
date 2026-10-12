import csv
import io
import json
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from engine import preprocess as pp

from . import services
from .forms import ProjectForm, RegisterForm, StudentForm, SupervisorForm, UploadForm
from .models import (ZONES, Allocation, Department, FitScore, Institution, ModelVersion, PastProject,
                     Student, Supervisor, User)


def role_required(role):
    def deco(fn):
        @wraps(fn)
        @login_required
        def inner(request, *a, **kw):
            if request.user.role != role:
                return redirect("home")
            if role == User.COORDINATOR and not request.user.department_id:
                messages.error(request, "Your account is not attached to a department yet.")
                return redirect("landing")
            return fn(request, *a, **kw)
        return inner
    return deco


# ---------------------------------------------------------------- public
def demo_department():
    return (Department.objects.annotate(n=Count("supervisors")).filter(n__gt=1)
            .select_related("institution").order_by("-n").first())


def landing(request):
    dept = demo_department()
    version = ModelVersion.active()
    return render(request, "core/landing.html", {
        "demo_dept": dept, "version": version,
        "institutions": Institution.objects.all(), "zones": ZONES,
        "stats": {"institutions": Institution.objects.count(),
                  "departments": Department.objects.count(),
                  "supervisors": Supervisor.objects.count(),
                  "projects": PastProject.objects.count()},
    })


@require_POST
def api_match(request):
    """Live demo: rank the demo department's supervisors for one interest statement."""
    try:
        text = pp.clean_text(json.loads(request.body or b"{}").get("text", ""))[:300]
    except (ValueError, AttributeError):
        return JsonResponse({"error": "Send JSON with a text field."}, status=400)
    err = pp.interest_error(text)
    if err:
        return JsonResponse({"error": "Write a few more words so there is enough meaning to match."}, status=400)
    dept = demo_department()
    if not dept:
        return JsonResponse({"error": "No demonstration data is loaded."}, status=503)
    try:
        return JsonResponse({"results": services.quick_match(dept, text, k=4)})
    except services.NoModel as e:
        return JsonResponse({"error": str(e)}, status=503)


def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = RegisterForm(request.POST or None, initial={"role": request.GET.get("role", "student")})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        with transaction.atomic():
            first, _, last = d["full_name"].strip().partition(" ")
            user = User.objects.create_user(username=d["email"], email=d["email"], password=d["password"],
                                            role=d["role"], first_name=first, last_name=last)
            if d["role"] == "student":
                st = Student.objects.filter(pk=d["matric_no"]).first()
                if st:
                    st.user = user
                    st.save()
                else:
                    Student.objects.create(matric_no=d["matric_no"], user=user, department=d["department"],
                                           full_name=d["full_name"].strip(), cgpa=0)
            else:
                Supervisor.objects.create(user=user, department=d["department"],
                                          full_name=d["full_name"].strip(), approved=False)
        login(request, user)
        messages.success(request, "Account created. Complete your profile to be included in the allocation.")
        return redirect("home")
    return render(request, "core/register.html", {
        "form": form,
        "examples": json.dumps({str(d.pk): d.matric_example for d in Department.objects.all()})})


@login_required
def home(request):
    if request.user.is_superuser and request.user.role != User.COORDINATOR:
        return redirect("/admin/")
    return redirect({"student": "student_home", "supervisor": "supervisor_home",
                     "coordinator": "c_overview"}[request.user.role])


def csv_template(request, name):
    if name not in ("students_template", "past_projects_template"):
        raise Http404
    return FileResponse(open(settings.BASE_DIR / "data" / f"{name}.csv", "rb"),
                        as_attachment=True, filename=f"{name}.csv")


# ---------------------------------------------------------------- student
@role_required(User.STUDENT)
def student_home(request):
    student = get_object_or_404(Student.objects.select_related("department__institution"), user=request.user)
    dept = student.department
    locked = dept.published
    form = StudentForm(request.POST or None, instance=student, department=dept, lock_matric=True)
    if request.method == "POST":
        if locked:
            messages.error(request, "The allocation has been published, so your profile can no longer be changed.")
            return redirect("student_home")
        if form.is_valid():
            form.save()
            messages.success(request, "Profile saved. You will be included in the next allocation run.")
            return redirect("student_home")
    alloc = Allocation.objects.filter(student=student).select_related("supervisor").first() if locked else None
    why = []
    if alloc and alloc.supervisor and dept.last_run_version:
        try:
            why = services.explain(student, alloc.supervisor, dept.last_run_version)
        except Exception:
            why = []
    return render(request, "core/student.html", {
        "student": student, "dept": dept, "form": form, "alloc": alloc, "why": why, "locked": locked,
        "step": 3 if locked else (2 if student.ready else 1)})


# ---------------------------------------------------------------- supervisor
@role_required(User.SUPERVISOR)
def supervisor_home(request):
    sup = get_object_or_404(Supervisor.objects.select_related("department__institution"), user=request.user)
    dept = sup.department
    form = SupervisorForm(instance=sup, prefix="p")
    pform = ProjectForm(prefix="j")
    if request.method == "POST":
        if dept.published:
            messages.error(request, "The allocation has been published. Ask the coordinator to make changes.")
            return redirect("supervisor_home")
        if "save_profile" in request.POST:
            form = SupervisorForm(request.POST, instance=sup, prefix="p")
            if form.is_valid():
                form.save()
                messages.success(request, "Profile saved.")
                return redirect("supervisor_home")
        else:
            pform = ProjectForm(request.POST, prefix="j")
            if pform.is_valid():
                p = pform.save(commit=False)
                p.supervisor = sup
                p.save()
                messages.success(request, "Past project added to your profile.")
                return redirect("supervisor_home")
    assigned = (Allocation.objects.filter(supervisor=sup).select_related("student")
                .order_by("student__matric_no") if dept.published else [])
    return render(request, "core/supervisor.html", {
        "sup": sup, "dept": dept, "form": form, "pform": pform, "assigned": assigned,
        "projects": sup.past_projects.all()})


@require_POST
@login_required
def project_delete(request, pk):
    p = get_object_or_404(PastProject.objects.select_related("supervisor__department"), pk=pk)
    u = request.user
    own = u.role == User.SUPERVISOR and p.supervisor.user_id == u.id
    coord = u.role == User.COORDINATOR and p.supervisor.department_id == u.department_id
    if not (own or coord):
        raise Http404
    if p.supervisor.department.published:
        messages.error(request, "Unpublish the allocation before changing records.")
    else:
        p.delete()
        messages.success(request, "Past project removed.")
    return redirect("c_projects" if coord else "supervisor_home")


# ---------------------------------------------------------------- coordinator
def _dept(request):
    return Department.objects.select_related("institution", "last_run_version").get(pk=request.user.department_id)


def _guard_published(request, dept):
    if dept.published:
        messages.error(request, "The allocation is published. Unpublish it before changing records.")
        return True
    return False


def _counts(dept):
    allocs = Allocation.objects.filter(student__department=dept)
    return {
        "students": dept.students.count(),
        "students_ready": dept.students.exclude(interest_text="").count(),
        "supervisors": dept.supervisors.count(),
        "supervisors_ready": dept.supervisors.filter(approved=True).exclude(specialisation_text="").count(),
        "pending": dept.supervisors.filter(approved=False).count(),
        "capacity": sum(s.capacity for s in dept.supervisors.filter(approved=True).exclude(specialisation_text="")),
        "projects": PastProject.objects.filter(supervisor__department=dept).count(),
        "placed": allocs.filter(supervisor__isnull=False).count(),
        "open_flags": allocs.filter(flagged=True, resolved=False).count(),
        "flags": allocs.filter(flagged=True).count(),
    }


def _ctx(request, dept, **extra):
    c = {"dept": dept, "counts": _counts(dept), "version": ModelVersion.active()}
    c.update(extra)
    return c


@role_required(User.COORDINATOR)
def c_overview(request):
    dept = _dept(request)
    counts = _counts(dept)
    stage = 1
    if counts["students_ready"] and counts["supervisors_ready"]:
        stage = 2
    if dept.last_run_at:
        stage = 3 if counts["open_flags"] else 4
    if dept.published:
        stage = 5
    loads = (dept.supervisors.annotate(n=Count("allocations")).order_by("full_name")
             if dept.last_run_at else [])
    return render(request, "core/c_overview.html", _ctx(request, dept, stage=stage, loads=loads, nav="overview"))


@role_required(User.COORDINATOR)
def c_students(request):
    dept = _dept(request)
    q = request.GET.get("q", "").strip()
    qs = dept.students.select_related("allocation__supervisor", "user")
    if q:
        qs = qs.filter(Q(matric_no__icontains=q) | Q(full_name__icontains=q) | Q(interest_text__icontains=q))
    return render(request, "core/c_students.html", _ctx(request, dept, students=qs, q=q, nav="students",
                                                         upload=UploadForm()))


@role_required(User.COORDINATOR)
def c_student_form(request, matric=None):
    dept = _dept(request)
    if _guard_published(request, dept):
        return redirect("c_students")
    inst = get_object_or_404(Student, pk=matric, department=dept) if matric else None
    form = StudentForm(request.POST or None, instance=inst, department=dept, require_interest=False)
    if request.method == "POST" and form.is_valid():
        s = form.save(commit=False)
        s.department = dept
        s.save()
        messages.success(request, f"Saved {s.matric_no}.")
        return redirect("c_students")
    return render(request, "core/c_form.html", _ctx(
        request, dept, form=form, nav="students", back="c_students",
        title="Edit student" if inst else "Add a student",
        lead="Changes take effect the next time you run the allocation."))


@require_POST
@role_required(User.COORDINATOR)
def c_student_delete(request, matric):
    dept = _dept(request)
    if not _guard_published(request, dept):
        get_object_or_404(Student, pk=matric, department=dept).delete()
        messages.success(request, f"Removed {matric}.")
    return redirect("c_students")


@require_POST
@role_required(User.COORDINATOR)
def c_students_import(request):
    dept = _dept(request)
    if _guard_published(request, dept):
        return redirect("c_students")
    form = UploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
        return redirect("c_students")
    rows = csv.DictReader(io.StringIO(form.cleaned_data["file"].read().decode("utf-8-sig", "replace")))
    need = {"matric_no", "full_name", "cgpa"}
    if not rows.fieldnames or not need.issubset({f.strip() for f in rows.fieldnames}):
        messages.error(request, "The file needs these columns: matric_no, full_name, cgpa, interest_text.")
        return redirect("c_students")
    saved, problems = 0, []
    for n, row in enumerate(rows, start=2):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        if not any(row.values()):
            continue
        m = pp.normalise_matric(row.get("matric_no"))
        interest = pp.clean_text(row.get("interest_text", ""))
        err = (pp.matric_error(m, dept.matric_pattern or None) or pp.cgpa_error(row.get("cgpa"), dept.cgpa_scale)
               or (None if row.get("full_name") else "Full name is missing.")
               or (pp.interest_error(interest) if interest else None))
        other = Student.objects.filter(pk=m).exclude(department=dept).exists() if not err else False
        if other:
            err = "This matric number belongs to another department."
        if err:
            problems.append(f"Row {n} ({m or 'no matric'}): {err}")
            continue
        Student.objects.update_or_create(pk=m, defaults={
            "department": dept, "full_name": row["full_name"], "cgpa": round(float(row["cgpa"]), 2),
            "interest_text": interest})
        saved += 1
    if saved:
        messages.success(request, f"Imported {saved} student records.")
    if problems:
        more = f" and {len(problems) - 6} more" if len(problems) > 6 else ""
        messages.error(request, f"{len(problems)} rows were skipped. " + " ".join(problems[:6]) + more)
    return redirect("c_students")


@role_required(User.COORDINATOR)
def c_student_detail(request, matric):
    dept = _dept(request)
    student = get_object_or_404(Student, pk=matric, department=dept)
    scores = list(FitScore.objects.filter(student=student).select_related("supervisor").order_by("rank"))
    alloc = Allocation.objects.filter(student=student).select_related("supervisor").first()
    load = dict(dept.supervisors.annotate(n=Count("allocations")).values_list("pk", "n"))
    for f in scores:
        f.load = load.get(f.supervisor_id, 0)
        f.is_assigned = bool(alloc and alloc.supervisor_id == f.supervisor_id)
    why = []
    if alloc and alloc.supervisor and dept.last_run_version and student.ready:
        why = services.explain(student, alloc.supervisor, dept.last_run_version)
    return render(request, "core/c_student_detail.html", _ctx(
        request, dept, student=student, scores=scores, alloc=alloc, why=why, nav="run"))


@role_required(User.COORDINATOR)
def c_supervisors(request):
    dept = _dept(request)
    sups = dept.supervisors.annotate(n_projects=Count("past_projects", distinct=True),
                                     n_students=Count("allocations", distinct=True))
    return render(request, "core/c_supervisors.html", _ctx(request, dept, supervisors=sups, nav="supervisors"))


@role_required(User.COORDINATOR)
def c_supervisor_form(request, pk=None):
    dept = _dept(request)
    if _guard_published(request, dept):
        return redirect("c_supervisors")
    inst = get_object_or_404(Supervisor, pk=pk, department=dept) if pk else None
    form = SupervisorForm(request.POST or None, instance=inst)
    if request.method == "POST" and form.is_valid():
        s = form.save(commit=False)
        s.department = dept
        s.approved = True
        s.save()
        messages.success(request, f"Saved {s.full_name}.")
        return redirect("c_supervisors")
    return render(request, "core/c_form.html", _ctx(
        request, dept, form=form, nav="supervisors", back="c_supervisors",
        title="Edit supervisor" if inst else "Add a supervisor",
        lead="The specialisation statement and past projects together form the supervisor's profile."))


@require_POST
@role_required(User.COORDINATOR)
def c_supervisor_delete(request, pk):
    dept = _dept(request)
    if not _guard_published(request, dept):
        sup = get_object_or_404(Supervisor, pk=pk, department=dept)
        Allocation.objects.filter(supervisor=sup).update(
            supervisor=None, fit_score=None, choice_rank=None, flagged=True, flag_reason="no_place",
            resolved=False, resolution="Supervisor record was removed")
        sup.delete()
        messages.success(request, "Supervisor removed. Any students they held are now flagged for review.")
    return redirect("c_supervisors")


@require_POST
@role_required(User.COORDINATOR)
def c_supervisor_approve(request, pk):
    dept = _dept(request)
    sup = get_object_or_404(Supervisor, pk=pk, department=dept)
    sup.approved = True
    sup.save()
    messages.success(request, f"{sup.full_name} confirmed as a supervisor in this department.")
    return redirect("c_supervisors")


@role_required(User.COORDINATOR)
def c_projects(request):
    dept = _dept(request)
    sups = {s.full_name.lower(): s for s in dept.supervisors.all()}
    if request.method == "POST":
        if _guard_published(request, dept):
            return redirect("c_projects")
        form = UploadForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
            return redirect("c_projects")
        rows = csv.DictReader(io.StringIO(form.cleaned_data["file"].read().decode("utf-8-sig", "replace")))
        if not rows.fieldnames or not {"supervisor_name", "title"}.issubset({f.strip() for f in rows.fieldnames}):
            messages.error(request, "The file needs these columns: supervisor_name, title, keywords, abstract, session.")
            return redirect("c_projects")
        saved, dupes, problems = 0, 0, []
        for n, row in enumerate(rows, start=2):
            row = {(k or "").strip(): pp.clean_text(v) for k, v in row.items()}
            if not any(row.values()):
                continue
            sup = sups.get(row.get("supervisor_name", "").lower())
            if not sup:
                problems.append(f"Row {n}: no supervisor named \u201c{row.get('supervisor_name', '')}\u201d.")
                continue
            if len(row.get("title", "")) < 10:
                problems.append(f"Row {n}: the title is missing or too short.")
                continue
            if PastProject.objects.filter(supervisor=sup, title__iexact=row["title"]).exists():
                dupes += 1
                continue
            PastProject.objects.create(supervisor=sup, title=row["title"][:300],
                                       keywords=row.get("keywords", "")[:300],
                                       abstract=row.get("abstract", ""), session=row.get("session", "")[:12])
            saved += 1
        if saved or dupes:
            messages.success(request, f"Loaded {saved} past project records" +
                             (f"; {dupes} duplicates were ignored." if dupes else "."))
        if problems:
            more = f" and {len(problems) - 6} more" if len(problems) > 6 else ""
            messages.error(request, f"{len(problems)} rows were skipped. " + " ".join(problems[:6]) + more)
        return redirect("c_projects")
    groups = dept.supervisors.prefetch_related("past_projects")
    return render(request, "core/c_projects.html", _ctx(request, dept, groups=groups, upload=UploadForm(),
                                                         nav="projects"))


@role_required(User.COORDINATOR)
def c_models(request):
    dept = _dept(request)
    if request.method == "POST":
        v = get_object_or_404(ModelVersion, pk=request.POST.get("version"))
        try:
            if "activate" in request.POST:
                services.encoder_for(v)  # make sure the files load before switching
                ModelVersion.objects.update(is_active=False)
                v.is_active = True
                v.save()
                messages.success(request, f"{v.name} is now the active model. Run the allocation again to use it.")
            else:
                if services.evaluate_version(v):
                    messages.success(request, f"Evaluated {v.name} on {v.n_eval} held-out records.")
                else:
                    messages.error(request, "There are no held-out past project records to evaluate on.")
        except Exception as e:  # missing files, missing library
            messages.error(request, f"Could not load {v.name}: {e}")
        return redirect("c_models")
    versions = list(ModelVersion.objects.all())
    base = next((v for v in versions if v.training_round == 0), None)
    return render(request, "core/c_models.html", _ctx(request, dept, versions=versions, base=base, nav="models"))


@role_required(User.COORDINATOR)
def c_run(request):
    dept = _dept(request)
    if request.method == "POST":
        if _guard_published(request, dept):
            return redirect("c_run")
        try:
            threshold = float(request.POST.get("threshold", ""))
            if not 0 <= threshold <= 1:
                raise ValueError
        except ValueError:
            messages.error(request, "The threshold must be a number between 0 and 1.")
            return redirect("c_run")
        try:
            result = services.run_allocation(dept, threshold)
        except services.NoModel as e:
            messages.error(request, str(e))
            return redirect("c_run")
        if not result["ok"]:
            messages.error(request, result["error"])
        else:
            msg = (f"Allocation complete. {result['placed']} of {result['students']} students placed, "
                   f"{result['flagged']} flagged for review.")
            if result["skipped"]:
                msg += f" {result['skipped']} students without an interest statement were left out."
            messages.success(request, msg)
        return redirect("c_run")
    allocs = (Allocation.objects.filter(student__department=dept)
              .select_related("student", "supervisor").order_by("priority_position"))
    return render(request, "core/c_run.html", _ctx(request, dept, allocs=allocs, nav="run",
                                                    default_threshold=settings.DEFAULT_THRESHOLD))


@role_required(User.COORDINATOR)
def c_flagged(request):
    dept = _dept(request)
    if request.method == "POST":
        if _guard_published(request, dept):
            return redirect("c_flagged")
        a = get_object_or_404(Allocation, pk=request.POST.get("matric"), student__department=dept)
        note = pp.clean_text(request.POST.get("note", ""))[:150]
        if "accept" in request.POST and a.supervisor_id:
            a.resolved, a.resolution = True, note or "Weak match accepted by the coordinator"
            a.save()
            messages.success(request, f"{a.pk}: match accepted.")
        elif "assign" in request.POST:
            sup = get_object_or_404(Supervisor, pk=request.POST.get("supervisor"), department=dept)
            load = Allocation.objects.filter(supervisor=sup).exclude(pk=a.pk).count()
            if load >= sup.capacity:
                messages.error(request, f"{sup.full_name} is full ({load} of {sup.capacity}). "
                               "Raise their capacity first or choose another supervisor.")
            else:
                f = FitScore.objects.filter(student=a.student, supervisor=sup).first()
                a.supervisor, a.fit_score = sup, f.score if f else None
                a.choice_rank = f.rank if f else None
                a.manual, a.resolved = True, True
                a.resolution = note or "Placed manually by the coordinator"
                a.save()
                messages.success(request, f"{a.pk} placed with {sup.full_name}.")
        return redirect("c_flagged")
    flagged = list(Allocation.objects.filter(student__department=dept, flagged=True)
                   .select_related("student", "supervisor").order_by("resolved", "priority_position"))
    sups = list(dept.supervisors.annotate(n=Count("allocations")).order_by("full_name"))
    for a in flagged:
        fits = {f.supervisor_id: f.score for f in FitScore.objects.filter(student=a.student)}
        a.options = sorted(({"sup": s, "score": fits.get(s.pk), "free": s.capacity - s.n} for s in sups),
                           key=lambda o: -(o["score"] or -1))
    return render(request, "core/c_flagged.html", _ctx(request, dept, flagged=flagged, nav="flagged"))


def _report_groups(dept):
    groups = []
    for s in dept.supervisors.all():
        rows = list(Allocation.objects.filter(supervisor=s).select_related("student").order_by("student__matric_no"))
        groups.append({"sup": s, "rows": rows})
    return groups


@role_required(User.COORDINATOR)
def c_report(request):
    dept = _dept(request)
    counts = _counts(dept)
    if request.method == "POST":
        if "unpublish" in request.POST:
            dept.published, dept.published_at = False, None
            dept.save()
            messages.success(request, "Allocation unpublished. Students and supervisors can no longer see it.")
        elif not dept.last_run_at:
            messages.error(request, "Run the allocation before publishing.")
        elif counts["open_flags"]:
            messages.error(request, f"Resolve the {counts['open_flags']} flagged cases before publishing.")
        else:
            dept.published, dept.published_at = True, timezone.now()
            dept.save()
            messages.success(request, "Allocation published. Students and supervisors can now see their results.")
        return redirect("c_report")
    checks = services.verify_department(dept) if dept.last_run_at else None
    fits = [a.fit_score for a in Allocation.objects.filter(student__department=dept, fit_score__isnull=False)]
    bands = [("0.60 and above", lambda v: v >= .6), ("0.45 to 0.59", lambda v: .45 <= v < .6),
             ("0.30 to 0.44", lambda v: .3 <= v < .45), ("Below 0.30", lambda v: v < .3)]
    dist = [{"label": lab, "n": sum(1 for v in fits if fn(v)),
             "pct": round(100 * sum(1 for v in fits if fn(v)) / len(fits)) if fits else 0} for lab, fn in bands]
    summary = {"mean": sum(fits) / len(fits) if fits else None, "min": min(fits) if fits else None,
               "first_choice": Allocation.objects.filter(student__department=dept, choice_rank=1).count()}
    return render(request, "core/c_report.html", _ctx(request, dept, groups=_report_groups(dept), checks=checks,
                                                       dist=dist, summary=summary, nav="report"))


@role_required(User.COORDINATOR)
def c_report_csv(request):
    dept = _dept(request)
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="allocation_{dept.institution.short_name}_{dept.session.replace("/", "-")}.csv"'
    w = csv.writer(resp)
    w.writerow(["matric_no", "full_name", "cgpa", "supervisor", "fit_score", "choice_rank", "flagged", "note"])
    for a in (Allocation.objects.filter(student__department=dept).select_related("student", "supervisor")
              .order_by("supervisor__full_name", "student__matric_no")):
        w.writerow([a.student.matric_no, a.student.full_name, a.student.cgpa,
                    a.supervisor.full_name if a.supervisor else "NOT PLACED",
                    f"{a.fit_score:.3f}" if a.fit_score is not None else "", a.choice_rank or "",
                    "yes" if a.flagged else "no", a.resolution])
    return resp
