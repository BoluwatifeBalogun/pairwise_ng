"""Demonstration data: load it, detect it, remove it.

Everything loaded here is fictional. Institutions and departments are kept when the
demonstration people are removed, so real students and supervisors can still register.
"""
import random

from django.db.models import Q

from data import seed_data as sd

from .models import HND, ND, Allocation, Department, Institution, PastProject, Student, Supervisor, User

PASSWORD = "demo12345"
DEMO_ADMIN = "admin@yabatech.demo"
SESSIONS = ["2021/2022", "2022/2023", "2023/2024", "2024/2025"]
SPECS = (sd.CS, sd.EE)


def _demo_accounts():
    return User.objects.filter(email__endswith=".demo")


def _unclaimed():
    """Records nobody real has taken over: no account, or a demonstration account."""
    return Q(user__isnull=True) | Q(user__email__endswith=".demo")


def demo_students():
    matrics = [spec["matric_fmt"].format(i + 1) for spec in SPECS for i in range(len(spec["interests"]))]
    matrics += [spec["nd_matric_fmt"].format(i + 1) for spec in SPECS for i in range(len(spec["nd_interests"]))]
    return Student.objects.filter(_unclaimed(), matric_no__in=matrics)


def demo_supervisors():
    q = Q(pk__in=[])
    for spec in SPECS:
        q |= Q(department__name=spec["name"], department__institution__short_name=spec["institution"],
               full_name__in=[s[0] for s in spec["supervisors"]])
    return Supervisor.objects.filter(_unclaimed()).filter(q)


def present():
    return demo_supervisors().exists() or demo_students().exists() or _demo_accounts().exists()


def load_structure():
    """Institutions and departments only. Safe to run again."""
    inst = {}
    for name, short, kind, state, zone, scale in sd.INSTITUTIONS:
        inst[short], _ = Institution.objects.get_or_create(
            name=name, defaults={"short_name": short, "kind": kind, "state": state, "zone": zone,
                                 "cgpa_scale": scale})
    for short, dname in sd.EMPTY_DEPARTMENTS:
        Department.objects.get_or_create(institution=inst[short], name=dname)
    depts = []
    for spec in SPECS:
        d, _ = Department.objects.get_or_create(
            institution=inst[spec["institution"]], name=spec["name"],
            defaults={"session": spec["session"], "matric_pattern": spec["matric_pattern"],
                      "matric_example": spec["matric_example"]})
        depts.append(d)
    return depts


def _account(email, role, first, last, department=None):
    user = User.objects.filter(email=email).first()
    if user is None:
        user = User.objects.create_user(username=email, email=email, password=PASSWORD, role=role,
                                        first_name=first, last_name=last, department=department)
    return user


def load_people():
    """Fictional coordinators, supervisors, past projects and students for two departments."""
    depts = load_structure()
    names = [f"{f} {l}" for f, l in zip(sd.FIRST, sd.LAST)]
    for n, (spec, dept) in enumerate(zip(SPECS, depts)):
        rng = random.Random(2026 + n)
        slug = spec["institution"].lower()
        _account(f"coordinator{'' if n == 0 else '.ee'}@{slug}.demo", User.COORDINATOR, "Project", "Coordinator", dept)
        for k, (full, cap, specialisation, projects) in enumerate(spec["supervisors"]):
            if Supervisor.objects.filter(department=dept, full_name=full).exists():
                continue
            user = (_account(f"supervisor{'' if n == 0 else '.ee'}@{slug}.demo", User.SUPERVISOR,
                             full.split()[1], full.split()[-1]) if k == 0 else None)
            if user is not None and Supervisor.objects.filter(user=user).exists():
                user = None
            sup = Supervisor.objects.create(department=dept, user=user, full_name=full, capacity=cap,
                                            capacity_nd=spec["nd_capacity"], specialisation_text=specialisation)
            step = 5 if len(projects) >= 9 else 4
            for i, line in enumerate(projects):
                title, _, kw = line.partition(" | ")
                PastProject.objects.create(supervisor=sup, title=title, keywords=kw,
                                           session=SESSIONS[i % len(SESSIONS)], held_out=(i % step == 2))
        lo, hi = spec["cgpa_range"]
        pool = names if n == 0 else [f"{f} {l}" for f, l in zip(sd.FIRST[::-1], sd.LAST[7:] + sd.LAST[:7])]
        for level, key, fmt, suffix in ((HND, "interests", "matric_fmt", ""),
                                        (ND, "nd_interests", "nd_matric_fmt", ".nd")):
            order = list(range(len(spec[key])))
            rng.shuffle(order)
            offset = 0 if level == HND else len(pool) // 2
            for pos, idx in enumerate(order):
                cgpa = round(rng.uniform(lo, hi), 2)  # drawn even when skipped, so values never shift
                matric = spec[fmt].format(pos + 1)
                if Student.objects.filter(pk=matric).exists():
                    continue
                name = pool[(pos + offset) % len(pool)]
                user = None
                if pos == 0:
                    f, l = name.split()
                    user = _account(f"student{suffix}{'' if n == 0 else '.ee'}@{slug}.demo", User.STUDENT, f, l)
                    if Student.objects.filter(user=user).exists():
                        user = None
                Student.objects.create(matric_no=matric, user=user, department=dept, full_name=name,
                                       level=level, cgpa=cgpa, interest_text=spec[key][idx])


def remove():
    """Delete the fictional people and their records. Keeps institutions, departments, and any
    record a real person has registered against. Returns counts of what was removed."""
    students = demo_students()
    supervisors = demo_supervisors()
    counts = {"students": students.count(), "supervisors": supervisors.count(),
              "past_projects": PastProject.objects.filter(supervisor__in=supervisors).count(),
              "accounts": _demo_accounts().count()}
    touched = set(students.values_list("department_id", flat=True)) | set(
        supervisors.values_list("department_id", flat=True))
    # Students whose supervisor is about to go are flagged, not silently left hanging.
    Allocation.objects.filter(supervisor__in=supervisors).exclude(student__in=students).update(
        supervisor=None, fit_score=None, choice_rank=None, flagged=True, flag_reason="no_place",
        resolved=False, resolution="Supervisor record was removed")
    students.delete()
    supervisors.delete()
    _demo_accounts().delete()
    for dept in Department.objects.filter(pk__in=touched):
        for cycle in dept.cycles.all():
            if not Allocation.objects.filter(student__department=dept, student__level=cycle.level).exists():
                cycle.last_run_at = cycle.last_run_version = cycle.published_at = None
                cycle.published = False
                cycle.save()
    return counts
