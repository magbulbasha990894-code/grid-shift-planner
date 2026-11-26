"""Exact finite-horizon dispatch over declared integer energy increments."""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class Hour:
    hour: int
    load: int
    cent_per_kwh: int
    carbon_g_per_kwh: int
    import_limit: int


@dataclass(frozen=True)
class Contract:
    capacity: int
    power: int
    initial: int
    terminal: int
    charge_percent: int
    discharge_percent: int
    demand_cent_per_kw: int
    cycle_cent_per_kwh: int

    def __post_init__(self):
        if any(type(x) is not int or x < 0 for x in asdict(self).values()):
            raise ValueError("contract fields must be nonnegative integers")
        if max(self.initial, self.terminal) > self.capacity:
            raise ValueError("initial and terminal energy must fit capacity")
        if not all(1 <= x <= 100 for x in (self.charge_percent, self.discharge_percent)):
            raise ValueError("efficiencies must be from 1 to 100 percent")


@dataclass(frozen=True)
class Step:
    hour: int
    storage_delta_kwh: int
    stored_kwh: int
    grid_kwh: int
    energy_cost_cent: int
    cycle_cost_cent: int
    carbon_g: int


def validate_hours(hours):
    if not hours or [h.hour for h in hours] != list(range(hours[0].hour, hours[0].hour + len(hours))):
        raise ValueError("need consecutive one-hour intervals")
    for h in hours:
        if min(h.load, h.cent_per_kwh, h.carbon_g_per_kwh, h.import_limit) < 0:
            raise ValueError("hourly input cannot be negative")


def solve(hours: list[Hour], c: Contract, carbon_budget_g: int | None = None) -> dict:
    """Minimize energy + cycling + peak cost, with optional hard carbon budget.

    Pareto-prune records only within identical (SOC, peak) states.
    If carbon is unconstrained, lexicographic (cost, carbon, dispatch) is enough.
    """
    validate_hours(hours)
    if carbon_budget_g is not None and (type(carbon_budget_g) is not int or carbon_budget_g < 0):
        raise ValueError("carbon budget must be a nonnegative integer")
    states = {(c.initial, 0): [(0, 0, ())]}
    for h in hours:
        nxt = {}
        for (soc, peak), records in states.items():
            for delta in range(-min(c.power, soc), min(c.power, c.capacity - soc) + 1):
                charge = (100 * delta + c.charge_percent - 1) // c.charge_percent if delta > 0 else 0
                discharge = (-delta * c.discharge_percent) // 100 if delta < 0 else 0
                grid = h.load + charge - discharge
                if not 0 <= grid <= h.import_limit:
                    continue
                next_soc = soc + delta
                key = next_soc, max(peak, grid)
                step = Step(h.hour, delta, next_soc, grid, grid * h.cent_per_kwh,
                            abs(delta) * c.cycle_cent_per_kwh, grid * h.carbon_g_per_kwh)
                for cents, grams, schedule in records:
                    candidate = cents + step.energy_cost_cent + step.cycle_cost_cent, grams + step.carbon_g, schedule + (delta,)
                    if carbon_budget_g is not None and candidate[1] > carbon_budget_g:
                        continue
                    bucket = nxt.setdefault(key, [])
                    if carbon_budget_g is None:
                        if not bucket or candidate < bucket[0]:
                            bucket[:] = [candidate]
                    elif not any(dominates(record, candidate) for record in bucket):
                        bucket[:] = [record for record in bucket if not dominates(candidate, record)]
                        bucket.append(candidate)
        states = nxt
    choices = [(cents + peak * c.demand_cent_per_kw, grams, schedule)
               for (soc, peak), records in states.items() if soc >= c.terminal
               for cents, grams, schedule in records]
    if not choices:
        raise ValueError("no feasible dispatch")
    cents, grams, schedule = min(choices)
    detail = []
    soc = c.initial
    for h, delta in zip(hours, schedule, strict=True):
        soc += delta
        net = ((100 * delta + c.charge_percent - 1) // c.charge_percent if delta > 0
               else -((-delta * c.discharge_percent) // 100))
        grid = h.load + net
        detail.append(asdict(Step(h.hour, delta, soc, grid, grid * h.cent_per_kwh,
                                  abs(delta) * c.cycle_cent_per_kwh, grid * h.carbon_g_per_kwh)))
    peak = max(step["grid_kwh"] for step in detail)
    return {"total_cost_cent": cents, "carbon_g": grams, "peak_kw": peak,
            "peak_cost_cent": peak * c.demand_cent_per_kw, "dispatch": detail}


def dominates(x, y):
    return x[0] <= y[0] and x[1] <= y[1] and (x[:2] != y[:2] or x[2] <= y[2])


def read_hours(path):
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return [Hour(**{name: int(row[name]) for name in Hour.__annotations__})
                for row in csv.DictReader(fh)]


def compare(hours, contract, carbon_budget=None):
    baseline_contract = Contract(0, 0, 0, 0, 100, 100, contract.demand_cent_per_kw, 0)
    try:
        baseline = solve(hours, baseline_contract)
    except ValueError:
        validate_hours(hours)
        baseline = None
    plan = solve(hours, contract, carbon_budget)
    return {"baseline": baseline, "plan": plan, "carbon_budget_g": carbon_budget,
            "savings_cent": None if baseline is None else baseline["total_cost_cent"] - plan["total_cost_cent"]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hours", default="fixtures/weekday.csv")
    p.add_argument("--contract", default="fixtures/contract.json")
    p.add_argument("--carbon-budget-g", type=int)
    p.add_argument("--output", type=Path, help="optional JSON report path")
    args = p.parse_args()
    try:
        report = compare(read_hours(args.hours), Contract(**json.loads(Path(args.contract).read_text())),
                         args.carbon_budget_g)
    except (OSError, ValueError, TypeError, KeyError) as ex:
        p.exit(2, f"input/feasibility error: {ex}\n")
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
