# Grid Shift Planner

An auditable day-ahead battery dispatch optimizer for a small site. Compare a no-storage baseline with an exact discrete schedule; test what changes when carbon is a hard constraint rather than a carbon price.

```sh
python planner.py --output report.json
python planner.py --carbon-budget-g 54000 --output carbon-constrained.json
python -m unittest -v
```

The bundled 24-hour profile is fictional: a late-afternoon price and load peak follows low-carbon midday hours. The JSON report ties costs, peak and emissions back to each interval. If the import cap makes the no-storage case infeasible, its baseline and the savings are reported as null rather than invented.

## Example decision

| Scenario | Total cost | Peak import | Carbon |
|:--|--:|--:|--:|
| No storage | $50.06 | 13 kW | 53.015 kg |
| Lowest cost | $46.85 | 10 kW | 56.360 kg |
| 54 kg carbon cap | $47.87 | 11 kW | 53.990 kg |

The cheapest dispatch saves $3.21, but increases emissions by 3.345 kg compared with no storage. Constraining it to 54 kg preserves $2.19 of savings. The capped plan still emits more than the baseline; a cap should be selected against the comparison the operator actually cares about.

## Model

Each interval lasts one hour. Load and metered imports are integer kWh; the maximum hourly import is treated as kW for a simplified demand charge. This is not a utility's billing calculation. The battery's internal state and action are also integer kWh. Charging imports round up and usable discharge rounds down. The power parameter caps the internal energy movement per interval, not the AC rating. The plan cannot export energy, violate the per-hour grid cap, or finish under the terminal energy floor. The exact objective in cents is the sum of purchased energy, an internal-throughput penalty and a single charge on the largest import. The optional grams cap covers all grid import; initial stored energy is treated as sunk, and the end floor makes comparison more meaningful.

The dynamic program stores state of charge, peak import and candidate records. When emissions are capped, it retains the nondominated cost/carbon histories at each state; without a cap only the best record by cost, emissions, then schedule is retained. Costs/emissions are additive and future feasibility depends on state (and remaining carbon), so pruning is exact for the declared model. The method is intended for small horizons and discrete capacities; Pareto-front sizes can grow. The unit tests cross-check a small instance against exhaustive enumeration.

## Inputs

- Hour CSV: `hour,load,cent_per_kwh,carbon_g_per_kwh,import_limit`; consecutive integer hour indices.
- Contract JSON: `capacity,power,initial,terminal,charge_percent,discharge_percent,demand_cent_per_kw,cycle_cent_per_kwh`; efficiencies are integer percentages.

Python 3.10+; no third-party dependencies. No live dispatch, physical warranties, tariff advice, degradation model, forecast errors, or client claims. The demo and fixture assumptions are synthetic portfolio material.
