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

from . import demo, services, tabular
from .forms import ProjectForm, RegisterForm, StudentForm, SupervisorForm, UploadForm
from .models import (HND, LEVEL_NAMES, LEVELS, ND, Allocation, Cycle, Department, FitScore, Institution,
                     ModelVersion, PastProject, Student, Supervisor, User)


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
            if role == User.COORDINATOR and not request.user.approved:
                return render(request, "core/pending.html", {"dept": request.user.department})
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
    departments = (Department.objects.select_related("institution")
                   .annotate(n_sup=Count("supervisors", distinct=True),
                             n_stu=Count("students", distinct=True)).order_by("name"))
    return render(request, "core/landing.html", {
        "demo_dept": dept, "version": version, "has_demo": demo.present(),
        "departments": departments,
        "stats": {"departments": departments.count(),
                  "supervisors": Supervisor.objects.count(),
                  "students": Student.objects.count(),
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
        return JsonResponse({"error": "No supervisors have been added yet."}, status=503)
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
                    st.level = d["level"]
                    st.save()
                else:
                    Student.objects.create(matric_no=d["matric_no"], user=user, department=d["department"],
                                           full_name=d["full_name"].strip(), cgpa=0, level=d["level"])
            elif d["role"] == "supervisor":
                # a coordinator may already have imported this supervisor: link to that record
                sup = Supervisor.objects.filter(department=d["department"], user__isnull=True,
                                                full_name__iexact=d["full_name"].strip()).first()
                if sup:
                    sup.user = user
                    sup.save()
                else:
                    Supervisor.objects.create(user=user, department=d["department"],
                                              full_name=d["full_name"].strip(), approved=False)
            else:
                user.department = d["department"]
                user.approved = False
                user.save()
        login(request, user)
        if d["role"] == "coordinator":
            messages.success(request, "Account created. The platform administrator will approve it.")
        else:
            messages.success(request, "Account created. Complete your profile to be included in the allocation.")
        return redirect("home")
    return render(request, "core/register.html", {
        "form": form,
        "examples": json.dumps({str(d.pk): d.matric_example for d in Department.objects.all()})})


@login_required
def home(request):
    if request.user.is_superuser and not request.user.department_id:
        return redirect("/admin/")
    return redirect({"student": "student_home", "supervisor": "supervisor_home",
                     "coordinator": "c_overview"}[request.user.role])


TEMPLATES = {
    "students_template": (["matric_no", "full_name", "level", "cgpa", "interest_text"], [
        ["F/HD/24/3210099", "Example HND Student", "HND", 3.21,
         "I want to build an online shop where people can buy thrift clothes"],
        ["F/ND/24/3210199", "Example ND Student", "ND", 2.95,
         "a website where students can buy and sell used textbooks"]]),
    "supervisors_template": (["full_name", "specialisation", "hnd_capacity", "nd_capacity"], [
        ["Dr. Example Lecturer", "Machine learning, predictive analytics and data science", 5, 3],
        ["Mr. Example Lecturer", "Computer networks, Internet of Things and embedded systems", 4, 2]]),
    "past_projects_template": (["supervisor_name", "title", "keywords", "abstract", "session"], [
        ["Dr. Example Lecturer", "Design and implementation of an online marketplace for locally made footwear",
         "e-commerce, web, payment", "", "2023/2024"]]),
}


def csv_template(request, name, ext="csv"):
    if name not in TEMPLATES:
        raise Http404
    headers, rows = TEMPLATES[name]
    if ext == "xlsx":
        return tabular.xlsx_response(f"{name}.xlsx", "Template", headers, rows)
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{name}.csv"'
    w = csv.writer(resp)
    w.writerow(headers)
    w.writerows(rows)
    return resp


# ---------------------------------------------------------------- student
@role_required(User.STUDENT)
def student_home(request):
    student = get_object_or_404(Student.objects.select_related("department__institution"), user=request.user)
    dept = student.department
    cycle = dept.cycle(student.level)
    locked = cycle.published
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
    if alloc and alloc.supervisor and cycle.last_run_version:
        try:
            why = services.explain(student, alloc.supervisor, cycle.last_run_version)
        except Exception:
            why = []
    return render(request, "core/student.html", {
        "student": student, "dept": dept, "cycle": cycle, "form": form, "alloc": alloc, "why": why,
        "locked": locked, "step": 3 if locked else (2 if student.ready else 1)})


# ---------------------------------------------------------------- supervisor
@role_required(User.SUPERVISOR)
def supervisor_home(request):
    sup = get_object_or_404(Supervisor.objects.select_related("department__institution"), user=request.user)
    dept = sup.department
    frozen = dept.any_published
    form = SupervisorForm(instance=sup, prefix="p")
    pform = ProjectForm(prefix="j")
    if request.method == "POST":
        if frozen:
            messages.error(request, "An allocation has been published. Ask the coordinator to make changes.")
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
    groups = []
    for cycle in dept.cycles.filter(published=True).order_by("-level"):
        rows = (Allocation.objects.filter(supervisor=sup, student__level=cycle.level)
                .select_related("student").order_by("student__matric_no"))
        groups.append({"cycle": cycle, "rows": rows, "capacity": sup.capacity_for(cycle.level)})
    return render(request, "core/supervisor.html", {
        "sup": sup, "dept": dept, "form": form, "pform": pform, "groups": groups, "frozen": frozen,
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
    if p.supervisor.department.any_published:
        messages.error(request, "Unpublish the allocation before changing records.")
    else:
        p.delete()
        messages.success(request, "Past project removed.")
    return redirect("c_projects" if coord else "supervisor_home")


# ---------------------------------------------------------------- coordinator
def _dept(request):
    return Department.objects.select_related("institution").get(pk=request.user.department_id)


def _level(request):
    """The programme level the coordinator is working on, kept in the session.
    `?level=ND` or `?level=HND` on any coordinator page switches it."""
    chosen = request.GET.get("level", "").upper()
    if chosen in LEVEL_NAMES:
        request.session["level"] = chosen
    return request.session.get("level", HND)


def _cycle(request, dept):
    return dept.cycle(_level(request))


def _guard_published(request, cycle):
    if cycle.published:
        messages.error(request, f"The {cycle.level} allocation is published. Unpublish it before changing records.")
        return True
    return False


def _counts(dept, cycle):
    level = cycle.level
    students = dept.students.filter(level=level)
    allocs = Allocation.objects.filter(student__department=dept, student__level=level)
    ready = [s for s in dept.supervisors.all() if s.takes(level)]
    return {
        "students": students.count(),
        "students_ready": students.exclude(interest_text="").count(),
        "students_other": dept.students.exclude(level=level).count(),
        "supervisors": dept.supervisors.count(),
        "supervisors_ready": len(ready),
        "pending": dept.supervisors.filter(approved=False).count(),
        "capacity": sum(s.capacity_for(level) for s in ready),
        "projects": PastProject.objects.filter(supervisor__department=dept).count(),
        "placed": allocs.filter(supervisor__isnull=False).count(),
        "open_flags": allocs.filter(flagged=True, resolved=False).count(),
        "flags": allocs.filter(flagged=True).count(),
    }


def _ctx(request, dept, cycle, **extra):
    other = ND if cycle.level == HND else HND
    c = {"dept": dept, "cycle": cycle, "level": cycle.level, "level_name": cycle.level_name,
         "other_level": other, "counts": _counts(dept, cycle), "version": ModelVersion.active(),
         "levels": LEVELS}
    c.update(extra)
    return c


@role_required(User.COORDINATOR)
def c_overview(request):
    dept = _dept(request)
    cycle = _cycle(request, dept)
    counts = _counts(dept, cycle)
    stage = 1
    if counts["students_ready"] and counts["supervisors_ready"]:
        stage = 2
    if cycle.last_run_at:
        stage = 3 if counts["open_flags"] else 4
    if cycle.published:
        stage = 5
    loads = []
    if cycle.last_run_at:
        for s in dept.supervisors.order_by("full_name"):
            if s.capacity_for(cycle.level) >= 1:
                loads.append({"sup": s, "n": s.load(cycle.level), "capacity": s.capacity_for(cycle.level)})
    other_cycle = dept.cycles.filter(level=ND if cycle.level == HND else HND).first()
    coordinators = User.objects.filter(role=User.COORDINATOR, department=dept).order_by("-approved", "email")
    return render(request, "core/c_overview.html", _ctx(request, dept, cycle, stage=stage, loads=loads,
                                                        other_cycle=other_cycle, coordinators=coordinators,
                                                        nav="overview"))


@require_POST
@role_required(User.COORDINATOR)
def c_coordinator_decide(request, pk):
    """An approved coordinator approves or declines a coordinator who signed up for the same department."""
    dept = _dept(request)
    other = get_object_or_404(User, pk=pk, role=User.COORDINATOR, department=dept, approved=False)
    if "approve" in request.POST:
        other.approved = True
        other.save(update_fields=["approved"])
        messages.success(request, f"{other.display_name()} can now coordinate the Department of {dept.name}.")
    else:
        name = other.display_name()
        other.delete()
        messages.success(request, f"The coordinator request from {name} was declined.")
    return redirect("c_overview")


@role_required(User.COORDINATOR)
def c_students(request):
    dept = _dept(request)
    cycle = _cycle(request, dept)
    q = request.GET.get("q", "").strip()
    qs = dept.students.filter(level=cycle.level).select_related("allocation__supervisor", "user")
    if q:
        qs = qs.filter(Q(matric_no__icontains=q) | Q(full_name__icontains=q) | Q(interest_text__icontains=q))
    return render(request, "core/c_students.html", _ctx(request, dept, cycle, students=qs, q=q, nav="students",
                                                         upload=UploadForm()))


@role_required(User.COORDINATOR)
def c_student_form(request, matric=None):
    dept = _dept(request)
    cycle = _cycle(request, dept)
    inst = get_object_or_404(Student, pk=matric, department=dept) if matric else None
    if inst and dept.cycle(inst.level).published or (not inst and cycle.published):
        _guard_published(request, dept.cycle(inst.level) if inst else cycle)
        return redirect("c_students")
    form = StudentForm(request.POST or None, instance=inst, department=dept, require_interest=False,
                       level=cycle.level)
    if request.method == "POST" and form.is_valid():
        s = form.save(commit=False)
        s.department = dept
        s.save()
        if s.level != cycle.level:
            request.session["level"] = s.level
        messages.success(request, f"Saved {s.matric_no} ({s.level}).")
        return redirect("c_students")
    return render(request, "core/c_form.html", _ctx(
        request, dept, cycle, form=form, nav="students", back="c_students",
        title="Edit student" if inst else "Add a student",
        lead="Changes take effect the next time you run the allocation for that programme."))


@require_POST
@role_required(User.COORDINATOR)
def c_student_delete(request, matric):
    dept = _dept(request)
    s = get_object_or_404(Student, pk=matric, department=dept)
    if not _guard_published(request, dept.cycle(s.level)):
        s.delete()
        messages.success(request, f"Removed {matric}.")
    return redirect("c_students")


@require_POST
@role_required(User.COORDINATOR)
def c_students_import(request):
    dept = _dept(request)
    cycle = _cycle(request, dept)
    form = UploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
        return redirect("c_students")
    try:
        cols, rows = tabular.read_rows(form.cleaned_data["file"])
    except Exception:
        messages.error(request, "That file could not be read. Save it again as .xlsx or .csv and retry.")
        return redirect("c_students")
    need = {"matric_no", "full_name", "cgpa"}
    if not need.issubset(set(cols)):
        messages.error(request, "The file needs these columns: matric_no, full_name, cgpa, interest_text "
                                "(and optionally level: ND or HND).")
        return redirect("c_students")
    locked = {c.level for c in dept.cycles.filter(published=True)}
    saved, problems = 0, []
    for n, row in enumerate(rows, start=2):
        if not any(row.values()):
            continue
        m = pp.normalise_matric(row.get("matric_no"))
        interest = pp.clean_text(row.get("interest_text", ""))
        level = (row.get("level") or "").upper() or pp.level_from_matric(m) or cycle.level
        err = (pp.matric_error(m, dept.matric_pattern or None) or pp.cgpa_error(row.get("cgpa"), dept.cgpa_scale)
               or (None if row.get("full_name") else "Full name is missing.")
               or (pp.interest_error(interest) if interest else None)
               or (None if level in LEVEL_NAMES else f"Level must be ND or HND, not {level}.")
               or (f"This {level} allocation is published." if level in locked else None))
        if not err and pp.level_from_matric(m) and pp.level_from_matric(m) != level:
            err = f"The matric number is an {pp.level_from_matric(m)} number but the level column says {level}."
        if not err and Student.objects.filter(pk=m).exclude(department=dept).exists():
            err = "This matric number belongs to another department."
        if err:
            problems.append(f"Row {n} ({m or 'no matric'}): {err}")
            continue
        Student.objects.update_or_create(pk=m, defaults={
            "department": dept, "full_name": row["full_name"], "cgpa": round(float(row["cgpa"]), 2),
            "interest_text": interest, "level": level})
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
    request.session["level"] = student.level
    cycle = dept.cycle(student.level)
    scores = list(FitScore.objects.filter(student=student).select_related("supervisor").order_by("rank"))
    alloc = Allocation.objects.filter(student=student).select_related("supervisor").first()
    for f in scores:
        f.load = f.supervisor.load(student.level)
        f.cap = f.supervisor.capacity_for(student.level)
        f.is_assigned = bool(alloc and alloc.supervisor_id == f.supervisor_id)
    why = []
    if alloc and alloc.supervisor and cycle.last_run_version and student.ready:
        why = services.explain(student, alloc.supervisor, cycle.last_run_version)
    return render(request, "core/c_student_detail.html", _ctx(
        request, dept, cycle, student=student, scores=scores, alloc=alloc, why=why, nav="run"))


@role_required(User.COORDINATOR)
def c_supervisors(request):
    dept = _dept(request)
    cycle = _cycle(request, dept)
    sups = list(dept.supervisors.annotate(n_projects=Count("past_projects", distinct=True)))
    for s in sups:
        s.n_hnd, s.n_nd = s.load(HND), s.load(ND)
    return render(request, "core/c_supervisors.html", _ctx(request, dept, cycle, supervisors=sups,
                                                            upload=UploadForm(), nav="supervisors"))


@role_required(User.COORDINATOR)
def c_supervisor_form(request, pk=None):
    dept = _dept(request)
    cycle = _cycle(request, dept)
    if dept.any_published:
        messages.error(request, "An allocation is published. Unpublish it before changing supervisors.")
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
        request, dept, cycle, form=form, nav="supervisors", back="c_supervisors",
        title="Edit supervisor" if inst else "Add a supervisor",
        lead="The specialisation statement and past projects together form the supervisor's profile. "
             "Capacity is set separately for HND and ND students."))


@require_POST
@role_required(User.COORDINATOR)
def c_supervisor_delete(request, pk):
    dept = _dept(request)
    if dept.any_published:
        messages.error(request, "An allocation is published. Unpublish it before removing supervisors.")
    else:
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
    cycle = _cycle(request, dept)
    sups = {s.full_name.lower(): s for s in dept.supervisors.all()}
    if request.method == "POST":
        if dept.any_published:
            messages.error(request, "An allocation is published. Unpublish it before changing records.")
            return redirect("c_projects")
        form = UploadForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
            return redirect("c_projects")
        try:
            cols, rows = tabular.read_rows(form.cleaned_data["file"])
        except Exception:
            messages.error(request, "That file could not be read. Save it again as .xlsx or .csv and retry.")
            return redirect("c_projects")
        if not {"supervisor_name", "title"}.issubset(set(cols)):
            messages.error(request, "The file needs these columns: supervisor_name, title, keywords, abstract, session.")
            return redirect("c_projects")
        saved, dupes, problems = 0, 0, []
        for n, row in enumerate(rows, start=2):
            row = {k: pp.clean_text(v) for k, v in row.items()}
            if not any(row.values()):
                continue
            sup = sups.get(row.get("supervisor_name", "").lower())
            if not sup:
                problems.append(f"Row {n}: no supervisor named “{row.get('supervisor_name', '')}”.")
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
    return render(request, "core/c_projects.html", _ctx(request, dept, cycle, groups=groups, upload=UploadForm(),
                                                         nav="projects"))


@role_required(User.COORDINATOR)
def c_models(request):
    dept = _dept(request)
    cycle = _cycle(request, dept)
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
    return render(request, "core/c_models.html", _ctx(request, dept, cycle, versions=versions, base=base,
                                                       nav="models"))


@role_required(User.COORDINATOR)
def c_run(request):
    dept = _dept(request)
    cycle = _cycle(request, dept)
    if request.method == "POST":
        if _guard_published(request, cycle):
            return redirect("c_run")
        try:
            threshold = float(request.POST.get("threshold", ""))
            if not 0 <= threshold <= 1:
                raise ValueError
        except ValueError:
            messages.error(request, "The threshold must be a number between 0 and 1.")
            return redirect("c_run")
        try:
            result = services.run_allocation(cycle, threshold)
        except services.NoModel as e:
            messages.error(request, str(e))
            return redirect("c_run")
        if not result["ok"]:
            messages.error(request, result["error"])
        else:
            msg = (f"{cycle.level} allocation complete. {result['placed']} of {result['students']} students "
                   f"placed, {result['flagged']} flagged for review.")
            if result["skipped"]:
                msg += f" {result['skipped']} students without an interest statement were left out."
            messages.success(request, msg)
        return redirect("c_run")
    allocs = (Allocation.objects.filter(student__department=dept, student__level=cycle.level)
              .select_related("student", "supervisor").order_by("priority_position"))
    return render(request, "core/c_run.html", _ctx(request, dept, cycle, allocs=allocs, nav="run",
                                                    default_threshold=settings.DEFAULT_THRESHOLD))


@role_required(User.COORDINATOR)
def c_flagged(request):
    dept = _dept(request)
    cycle = _cycle(request, dept)
    level = cycle.level
    if request.method == "POST":
        a = get_object_or_404(Allocation, pk=request.POST.get("matric"), student__department=dept)
        cycle = dept.cycle(a.student.level)
        if _guard_published(request, cycle):
            return redirect("c_flagged")
        note = pp.clean_text(request.POST.get("note", ""))[:150]
        if "accept" in request.POST and a.supervisor_id:
            a.resolved, a.resolution = True, note or "Weak match accepted by the coordinator"
            a.save()
            messages.success(request, f"{a.pk}: match accepted.")
        elif "assign" in request.POST:
            sup = get_object_or_404(Supervisor, pk=request.POST.get("supervisor"), department=dept)
            load = Allocation.objects.filter(supervisor=sup, student__level=a.student.level).exclude(pk=a.pk).count()
            cap = sup.capacity_for(a.student.level)
            if load >= cap:
                messages.error(request, f"{sup.full_name} is full ({load} of {cap} {a.student.level} places). "
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
    flagged = list(Allocation.objects.filter(student__department=dept, student__level=level, flagged=True)
                   .select_related("student", "supervisor").order_by("resolved", "priority_position"))
    sups = [s for s in dept.supervisors.order_by("full_name") if s.capacity_for(level) >= 1]
    for s in sups:
        s.n = s.load(level)
    for a in flagged:
        fits = {f.supervisor_id: f.score for f in FitScore.objects.filter(student=a.student)}
        a.options = sorted(({"sup": s, "score": fits.get(s.pk), "free": s.capacity_for(level) - s.n} for s in sups),
                           key=lambda o: -(o["score"] or -1))
    return render(request, "core/c_flagged.html", _ctx(request, dept, cycle, flagged=flagged, nav="flagged"))


def _report_groups(dept, level):
    groups = []
    for s in dept.supervisors.all():
        if s.capacity_for(level) < 1 and not s.allocations.filter(student__level=level).exists():
            continue
        rows = list(Allocation.objects.filter(supervisor=s, student__level=level)
                    .select_related("student").order_by("student__matric_no"))
        groups.append({"sup": s, "rows": rows, "capacity": s.capacity_for(level)})
    return groups


@role_required(User.COORDINATOR)
def c_report(request):
    dept = _dept(request)
    cycle = _cycle(request, dept)
    counts = _counts(dept, cycle)
    if request.method == "POST":
        if "unpublish" in request.POST:
            cycle.published, cycle.published_at = False, None
            cycle.save()
            messages.success(request, f"{cycle.level} allocation unpublished. Students and supervisors can no "
                                      "longer see it.")
        elif not cycle.last_run_at:
            messages.error(request, "Run the allocation before publishing.")
        elif counts["open_flags"]:
            messages.error(request, f"Resolve the {counts['open_flags']} flagged cases before publishing.")
        else:
            cycle.published, cycle.published_at = True, timezone.now()
            cycle.save()
            messages.success(request, f"{cycle.level} allocation published. Students and supervisors can now "
                                      "see their results.")
        return redirect("c_report")
    checks = services.verify_cycle(cycle) if cycle.last_run_at else None
    fits = [a.fit_score for a in Allocation.objects.filter(student__department=dept, student__level=cycle.level,
                                                           fit_score__isnull=False)]
    bands = [("0.60 and above", lambda v: v >= .6), ("0.45 to 0.59", lambda v: .45 <= v < .6),
             ("0.30 to 0.44", lambda v: .3 <= v < .45), ("Below 0.30", lambda v: v < .3)]
    dist = [{"label": lab, "n": sum(1 for v in fits if fn(v)),
             "pct": round(100 * sum(1 for v in fits if fn(v)) / len(fits)) if fits else 0} for lab, fn in bands]
    summary = {"mean": sum(fits) / len(fits) if fits else None, "min": min(fits) if fits else None,
               "first_choice": Allocation.objects.filter(student__department=dept, student__level=cycle.level,
                                                         choice_rank=1).count()}
    return render(request, "core/c_report.html", _ctx(request, dept, cycle, groups=_report_groups(dept, cycle.level),
                                                       checks=checks, dist=dist, summary=summary, nav="report"))


@role_required(User.COORDINATOR)
def c_report_csv(request):
    dept = _dept(request)
    cycle = _cycle(request, dept)
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = (f'attachment; filename="allocation_{cycle.level}_{dept.name.replace(" ", "_")}'
                                   f'_{dept.session.replace("/", "-")}.csv"')
    w = csv.writer(resp)
    w.writerow(["matric_no", "full_name", "level", "cgpa", "supervisor", "fit_score", "choice_rank", "flagged", "note"])
    for a in (Allocation.objects.filter(student__department=dept, student__level=cycle.level)
              .select_related("student", "supervisor").order_by("supervisor__full_name", "student__matric_no")):
        w.writerow([a.student.matric_no, a.student.full_name, a.student.level, a.student.cgpa,
                    a.supervisor.full_name if a.supervisor else "NOT PLACED",
                    f"{a.fit_score:.3f}" if a.fit_score is not None else "", a.choice_rank or "",
                    "yes" if a.flagged else "no", a.resolution])
    return resp


@require_POST
@role_required(User.COORDINATOR)
def c_supervisors_import(request):
    """Add or update supervisors from Excel or CSV. Matched by name within this department;
    nothing is ever deleted."""
    dept = _dept(request)
    if dept.any_published:
        messages.error(request, "An allocation is published. Unpublish it before changing supervisors.")
        return redirect("c_supervisors")
    form = UploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
        return redirect("c_supervisors")
    try:
        cols, rows = tabular.read_rows(form.cleaned_data["file"])
    except Exception:
        messages.error(request, "That file could not be read. Save it again as .xlsx or .csv and retry.")
        return redirect("c_supervisors")
    if not {"full_name", "specialisation"}.issubset(set(cols)):
        messages.error(request, "The file needs these columns: full_name, specialisation, hnd_capacity, "
                                "nd_capacity.")
        return redirect("c_supervisors")
    added, updated, problems = 0, 0, []

    def number(v, default):
        if v in ("", None):
            return default
        n = float(v)
        if n < 0 or n != int(n):
            raise ValueError
        return int(n)

    for n, row in enumerate(rows, start=2):
        if not any(row.values()):
            continue
        name = pp.clean_text(row.get("full_name", ""))[:120]
        spec = pp.clean_text(row.get("specialisation", ""))
        try:
            hnd = number(row.get("hnd_capacity"), 5)
            nd = number(row.get("nd_capacity"), 3)
        except ValueError:
            problems.append(f"Row {n} ({name or 'no name'}): capacities must be whole numbers, 0 or more.")
            continue
        if not name:
            problems.append(f"Row {n}: the full name is missing.")
            continue
        if len(spec) < 10:
            problems.append(f"Row {n} ({name}): describe the specialisation in at least a few words.")
            continue
        if not (hnd or nd):
            problems.append(f"Row {n} ({name}): at least one capacity must be 1 or more.")
            continue
        sup = dept.supervisors.filter(full_name__iexact=name).first()
        if sup:
            if hnd < sup.load(HND) or nd < sup.load(ND):
                problems.append(f"Row {n} ({name}): the new capacity is below the students already allocated.")
                continue
            sup.specialisation_text, sup.capacity, sup.capacity_nd = spec, hnd, nd
            sup.save()
            updated += 1
        else:
            Supervisor.objects.create(department=dept, full_name=name, specialisation_text=spec,
                                      capacity=hnd, capacity_nd=nd, approved=True)
            added += 1
    if added or updated:
        messages.success(request, f"Added {added} and updated {updated} supervisors.")
    if problems:
        more = f" and {len(problems) - 6} more" if len(problems) > 6 else ""
        messages.error(request, f"{len(problems)} rows were skipped. " + " ".join(problems[:6]) + more)
    return redirect("c_supervisors")


def _slug(dept):
    return dept.name.replace(" ", "_")


@role_required(User.COORDINATOR)
def c_students_xlsx(request):
    dept = _dept(request)
    cycle = _cycle(request, dept)
    rows = []
    for s in dept.students.filter(level=cycle.level).select_related("allocation__supervisor").order_by("matric_no"):
        a = getattr(s, "allocation", None)
        rows.append([s.matric_no, s.full_name, s.level, float(s.cgpa), s.interest_text,
                     a.supervisor.full_name if a and a.supervisor else ""])
    return tabular.xlsx_response(
        f"{cycle.level}_students_{_slug(dept)}.xlsx", f"{cycle.level} students",
        ["matric_no", "full_name", "level", "cgpa", "interest_text", "allocated_supervisor"], rows)


@role_required(User.COORDINATOR)
def c_supervisors_xlsx(request):
    dept = _dept(request)
    rows = [[s.full_name, s.specialisation_text, s.capacity, s.capacity_nd, s.load(HND), s.load(ND)]
            for s in dept.supervisors.order_by("full_name")]
    return tabular.xlsx_response(
        f"supervisors_{_slug(dept)}.xlsx", "Supervisors",
        ["full_name", "specialisation", "hnd_capacity", "nd_capacity", "hnd_allocated", "nd_allocated"], rows)


@role_required(User.COORDINATOR)
def c_report_xlsx(request):
    dept = _dept(request)
    cycle = _cycle(request, dept)
    rows = []
    for a in (Allocation.objects.filter(student__department=dept, student__level=cycle.level)
              .select_related("student", "supervisor").order_by("supervisor__full_name", "student__matric_no")):
        rows.append([a.supervisor.full_name if a.supervisor else "NOT PLACED", a.student.matric_no,
                     a.student.full_name, a.student.level, float(a.student.cgpa), a.student.interest_text,
                     round(a.fit_score, 3) if a.fit_score is not None else "", a.choice_rank or "",
                     "yes" if a.flagged else "no", a.resolution])
    return tabular.xlsx_response(
        f"allocation_{cycle.level}_{_slug(dept)}_{dept.session.replace('/', '-')}.xlsx", f"{cycle.level} allocation",
        ["supervisor", "matric_no", "full_name", "level", "cgpa", "interest_text", "fit_score", "choice_rank",
         "flagged", "note"], rows)
