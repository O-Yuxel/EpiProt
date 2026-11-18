"""Fixture for the Kotlin HealthMonitor: per-window quality of real patients + the Python episodes."""
import json, sys
from pathlib import Path
import numpy as np
from epiprot.app import health
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
cases = []
for sub in ["sub-115", "sub-001", "sub-050"]:
    z = np.load(f"epiprot_results/gbm/tc5s/{sub}.npz")
    q = health.window_quality(z["F"], [str(x) for x in z["names"]])
    n = len(z["F"])
    busy = [(n * 0.3 * health.W, n * 0.3 * health.W + 1800)]   # one 30 min alarm/recovery period
    eps = health.monitor(q, busy)
    cases.append({"sub": sub, "q": {k: "".join(map(str, v.astype(int).tolist())) for k, v in q.items()}, "busy_s": busy,
                  "episodes": [{"device": e.device, "code": e.code, "impact": e.impact_code, "problem": e.problem,
                                "warned_s": e.warned_s, "fixed_s": e.fixed_s, "reminders": e.reminders} for e in eps]})
    print(sub, n, len(eps))
(out / "health.json").write_text(json.dumps(cases))
