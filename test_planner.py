import itertools
import json
from pathlib import Path
import subprocess
import sys
import unittest

from planner import Contract, Hour, compare, read_hours, solve


class DispatchTests(unittest.TestCase):
    def test_exact_against_independent_exhaustion(self):
        h = [Hour(0, 2, 2, 80, 4), Hour(1, 3, 7, 5, 4), Hour(2, 4, 9, 65, 4)]
        c = Contract(4, 2, 2, 2, 100, 100, 2, 1)
        for budget in (None, 370, 440):
            expected = []
            for d in itertools.product(range(-2, 3), repeat=3):
                s = [2 + sum(d[:j]) for j in range(1, 4)]
                g = [x.load + change for x, change in zip(h, d)]
                grams = 80 * g[0] + 5 * g[1] + 65 * g[2]
                if min(s) < 0 or max(s) > 4 or s[-1] < 2 or min(g) < 0 or max(g) > 4:
                    continue
                if budget is not None and grams > budget:
                    continue
                cents = 2 * g[0] + 7 * g[1] + 9 * g[2] + 2 * max(g) + sum(map(abs, d))
                expected.append((cents, grams, d))
            actual = solve(h, c, budget)
            self.assertEqual(min(expected), (actual["total_cost_cent"], actual["carbon_g"],
                                             tuple(x["storage_delta_kwh"] for x in actual["dispatch"])))

    def test_rounding_with_losses(self):
        h = [Hour(0, 2, 0, 0, 20), Hour(1, 10, 20, 0, 20)]
        c = Contract(4, 4, 0, 0, 80, 75, 0, 0)
        report = solve(h, c)
        self.assertEqual([7, 7], [x["grid_kwh"] for x in report["dispatch"]])

    def test_infeasible_baseline_can_still_dispatch(self):
        c = Contract(4, 4, 4, 0, 100, 100, 0, 0)
        r = compare([Hour(0, 5, 1, 3, 3)], c)
        self.assertIsNone(r["baseline"])
        self.assertEqual(1, r["plan"]["peak_kw"])

    def test_no_export_and_terminal(self):
        h = [Hour(0, 1, 10, 5, 2)]
        self.assertEqual(0, solve(h, Contract(4, 4, 4, 0, 100, 100, 0, 0))["peak_kw"])
        with self.assertRaisesRegex(ValueError, "no feasible"):
            solve(h, Contract(4, 4, 4, 4, 100, 100, 0, 0), 0)

    def test_gap_rejected(self):
        with self.assertRaisesRegex(ValueError, "consecutive"):
            solve([Hour(0, 1, 1, 1, 1), Hour(2, 1, 1, 1, 1)],
                  Contract(0, 0, 0, 0, 100, 100, 0, 0))

    def test_cli_and_accounting(self):
        root = Path(__file__).parent
        r = json.loads(subprocess.check_output([sys.executable, "planner.py"], cwd=root, text=True))
        s = r["plan"]
        self.assertGreater(r["savings_cent"], 0)
        self.assertEqual(s["total_cost_cent"], s["peak_cost_cent"] +
                         sum(x["energy_cost_cent"] + x["cycle_cost_cent"] for x in s["dispatch"]))
        self.assertEqual(s["carbon_g"], sum(x["carbon_g"] for x in s["dispatch"]))
        for a, b in zip(s["dispatch"], read_hours(root / "fixtures/weekday.csv"), strict=True):
            self.assertLessEqual(a["grid_kwh"], b.import_limit)


if __name__ == "__main__":
    unittest.main()
