"""The eight unit tests of report Table 4.6. Run: python -m unittest tests.test_engine -v"""
import math
import random
import unittest

import numpy as np

from engine.allocation import allocate, verify
from engine.vectors import build_profile, fit_matrix, normalise


def random_problem(rng):
    n_students = rng.randint(5, 40)
    n_sup = rng.randint(2, 8)
    capacities = [rng.randint(1, 8) for _ in range(n_sup)]
    students = [{"matric": f"F/HD/24/{k:07d}", "cgpa": round(rng.uniform(1.5, 4.0), 2)}
                for k in rng.sample(range(1, 9999), n_students)]
    fit = [[round(rng.uniform(-0.1, 0.95), 4) for _ in range(n_sup)] for _ in range(n_students)]
    return students, capacities, fit, round(rng.uniform(0.1, 0.5), 2)


class Table46(unittest.TestCase):
    def test_1_normalisation(self):
        v = normalise([3, 4])
        self.assertAlmostEqual(float(np.linalg.norm(v)), 1.0)
        self.assertTrue(np.allclose(v, [0.6, 0.8]))

    def test_2_profile_averaging(self):
        p = build_profile([[1, 0], [0, 1]])
        self.assertAlmostEqual(float(np.linalg.norm(p)), 1.0)
        self.assertAlmostEqual(float(p[0]), float(p[1]))

    def test_3_fit_equals_cosine(self):
        a = [1, 0]
        b = normalise([1, 1])
        self.assertAlmostEqual(float(fit_matrix([a], [b])[0][0]), math.cos(math.radians(45)))

    def test_4_capacity_and_single_allocation(self):
        rng = random.Random(4)
        for _ in range(1000):
            students, caps, fit, th = random_problem(rng)
            alloc, flagged = allocate(students, caps, fit, th)
            res = verify(students, caps, fit, alloc, flagged)
            self.assertTrue(res["capacity"])
            self.assertTrue(res["single"])
            self.assertEqual(len(alloc), min(len(students), sum(caps)))

    def test_5_cgpa_priority(self):
        rng = random.Random(5)
        for _ in range(1000):
            students, caps, fit, th = random_problem(rng)
            alloc, flagged = allocate(students, caps, fit, th)
            self.assertTrue(verify(students, caps, fit, alloc, flagged)["priority"])

    def test_6_tie_breaking(self):
        students = [{"matric": "F/HD/24/0000002", "cgpa": 3.5},
                    {"matric": "F/HD/24/0000001", "cgpa": 3.5}]
        alloc, flagged = allocate(students, [1, 1], [[0.8, 0.2], [0.8, 0.2]], 0.1)
        self.assertEqual(alloc["F/HD/24/0000001"], 0)
        self.assertEqual(alloc["F/HD/24/0000002"], 1)

    def test_7_threshold_flagging(self):
        students = [{"matric": "A", "cgpa": 3.9}, {"matric": "B", "cgpa": 3.0}]
        alloc, flagged = allocate(students, [1, 1], [[0.9, 0.1], [0.8, 0.2]], 0.30)
        self.assertEqual(alloc, {"A": 0, "B": 1})
        self.assertEqual(flagged, ["B"])

    def test_8_repeatability(self):
        rng = random.Random(8)
        students, caps, fit, th = random_problem(rng)
        self.assertEqual(allocate(students, caps, fit, th), allocate(students, caps, fit, th))


class WorkedExample(unittest.TestCase):
    """Report Tables 4.3 and 4.4: ten students, three supervisors with three places each."""

    def test_table_4_4(self):
        cg = [3.92, 3.75, 3.61, 3.48, 3.30, 3.12, 2.95, 2.80, 2.64, 2.51]
        fit = [[.81, .42, .30], [.77, .55, .28], [.74, .40, .33], [.69, .51, .25], [.72, .60, .31],
               [.35, .79, .44], [.38, .71, .52], [.29, .66, .58], [.31, .64, .47], [.22, .48, .12]]
        students = [{"matric": f"F/HD/24/{i + 1:04d}", "cgpa": c} for i, c in enumerate(cg)]
        alloc, flagged = allocate(students, [3, 3, 3], fit, 0.30)
        got = [alloc.get(s["matric"]) for s in students]
        self.assertEqual(got, [0, 0, 0, 1, 1, 1, 2, 2, 2, None])
        self.assertEqual(flagged, ["F/HD/24/0010"])


if __name__ == "__main__":
    unittest.main()
