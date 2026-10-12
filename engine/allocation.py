"""CGPA-priority allocation rule (report Section 3.4.1 Steps 3-8, Code Listing 4.2).

A simple priority rule in the spirit of serial dictatorship. It is not a learning model.
"""


def priority_order(students, fit):
    """Step 3: highest CGPA first; ties by higher best fit, then lower matric number."""
    return sorted(
        range(len(students)),
        key=lambda i: (-students[i]["cgpa"], -max(fit[i]), students[i]["matric"]),
    )


def allocate(students, capacities, fit, threshold):
    """Allocate students to supervisors within capacity.

    students   list of {"matric": str, "cgpa": float}
    capacities list of int, one per supervisor
    fit        fit[i][j] = fit score of student i with supervisor j
    threshold  minimum acceptable fit score set by the coordinator

    Returns (allocation, flagged): allocation maps matric -> supervisor index,
    flagged lists matric numbers needing manual review (weak match or no place left).
    """
    n_sup = len(capacities)
    vacancies = list(capacities)
    ranked = [sorted(range(n_sup), key=lambda j: -fit[i][j]) for i in range(len(students))]
    order = priority_order(students, fit)
    allocation, flagged = {}, []
    for i in order:
        placed = False
        for j in ranked[i]:
            if vacancies[j] > 0:
                allocation[students[i]["matric"]] = j
                vacancies[j] -= 1
                placed = True
                if fit[i][j] < threshold:
                    flagged.append(students[i]["matric"])
                break
        if not placed:
            flagged.append(students[i]["matric"])
    return allocation, flagged


def verify(students, capacities, fit, allocation, flagged):
    """Check the three promises of Section 3.9 on a finished allocation.

    Returns a dict of booleans: capacity respected, every student allocated or
    flagged exactly once, and CGPA priority (no student prefers a supervisor
    that still had room, or that admitted a lower-priority student).
    """
    n_sup = len(capacities)
    load = [0] * n_sup
    for j in allocation.values():
        load[j] += 1
    capacity_ok = all(load[j] <= capacities[j] for j in range(n_sup))
    matrics = [s["matric"] for s in students]
    single_ok = len(set(matrics)) == len(matrics) and all(
        (m in allocation) or (m in flagged) for m in matrics
    )
    order = priority_order(students, fit)
    rank_of = {students[i]["matric"]: pos for pos, i in enumerate(order)}
    index_of = {s["matric"]: i for i, s in enumerate(students)}
    admitted = {j: [] for j in range(n_sup)}
    for m, j in allocation.items():
        admitted[j].append(m)
    priority_ok = True
    for m in matrics:
        i = index_of[m]
        got = allocation.get(m)
        got_fit = fit[i][got] if got is not None else float("-inf")
        for j in range(n_sup):
            if j == got or fit[i][j] <= got_fit:
                continue
            # student strictly prefers j: j must be full, and only with higher-priority students
            if load[j] < capacities[j] or any(rank_of[o] > rank_of[m] for o in admitted[j]):
                priority_ok = False
    return {"capacity": capacity_ok, "single": single_ok, "priority": priority_ok}
