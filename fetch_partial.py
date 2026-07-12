"""Costruisce observatory_YYYY-MM.json dai job gia' completati (per job id).
Zero quota QPU. Le QPU ancora in coda vengono semplicemente omesse:
il run in background le aggiungera' quando escono.
Uso: python fetch_partial.py 2026-07 ibm_fez=JOBID ibm_kingston=JOBID
"""
import json
import math
import sys
from datetime import date
from pathlib import Path

from qiskit_ibm_runtime import QiskitRuntimeService

HERE = Path(__file__).parent
GHZ_SIZES = [4, 12, 32]
MONTH = sys.argv[1]


def correlation(counts):
    total = sum(counts.values())
    same = counts.get("00", 0) + counts.get("11", 0)
    e = (2 * same - total) / total
    return e, math.sqrt(max(1e-12, 1 - e * e) / total)


service = QiskitRuntimeService()
runs = {}
for pair in sys.argv[2:]:
    name, job_id = pair.split("=")
    job = service.job(job_id)
    if str(job.status()) not in ("DONE", "JobStatus.DONE"):
        print(f"[{name}] {job.status()}, salto")
        continue
    result = job.result()
    es, errs = [], []
    for i in range(4):
        e, err = correlation(result[i].data.meas.get_counts())
        es.append(e); errs.append(err)
    s = es[0] + es[1] + es[2] - es[3]
    s_err = math.sqrt(sum(x * x for x in errs))
    gcounts = result[4].data.meas.get_counts()
    hit = gcounts.get("101", 0) / sum(gcounts.values())
    ghz = {}
    for k, n in enumerate(GHZ_SIZES):
        counts = result[5 + k].data.meas.get_counts()
        total = sum(counts.values())
        ghz[str(n)] = (counts.get("0" * n, 0) + counts.get("1" * n, 0)) / total
    try:
        qpu_s = job.usage()
    except Exception:
        qpu_s = None
    runs[name] = {"job_id": job_id,
                  "chsh": {"E": es, "err": errs, "S": s, "S_err": s_err,
                           "sigmas_over_classical": (s - 2) / s_err},
                  "grover_hit": hit, "ghz_fidelity": ghz, "qpu_seconds": qpu_s}
    print(f"[{name}] S={s:.3f}±{s_err:.3f} grover={hit*100:.1f}% "
          f"ghz32={ghz['32']*100:.1f}% qpu={qpu_s}s")

out = {"month": MONTH, "date": date.today().isoformat(), "shots": 2048,
       "ghz_sizes": GHZ_SIZES, "runs": runs}
(HERE / f"observatory_{MONTH}.json").write_text(json.dumps(out, indent=2))
idx = HERE / "observatory_index.json"
index = json.loads(idx.read_text()) if idx.exists() else []
index = sorted(set(index + [MONTH]))
idx.write_text(json.dumps(index, indent=2))
print(f"OK: observatory_{MONTH}.json ({len(runs)} QPU)")
