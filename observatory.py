"""NOX Quantum Observatory: rilevazione mensile su tutte le QPU pubbliche IBM.

Batteria fissa per QPU (1 job, 8 circuiti, 2048 shot ciascuno):
  - 4x CHSH  -> S (violazione di Bell, conteggi grezzi)
  - 1x Grover 3-bit |101>, 2 iterazioni -> hit rate
  - 3x GHZ (n=4, 12, 32) -> fedelta' di popolazione P(00..0)+P(11..1)

I 3 job vengono inviati in parallelo e raccolti a fine coda.
Output: observatory_YYYY-MM.json (+ aggiornamento indice observatory_index.json).
Uso: PYTHONIOENCODING=utf-8 python observatory.py [YYYY-MM]
"""
import json
import math
import sys
from datetime import date
from pathlib import Path

from qiskit import QuantumCircuit
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_ibm_runtime import SamplerV2 as Sampler

HERE = Path(__file__).parent
SHOTS = 2048
BACKENDS = ["ibm_fez", "ibm_marrakesh", "ibm_kingston"]
GHZ_SIZES = [4, 12, 32]
SETTINGS = [(0, math.pi / 4), (0, -math.pi / 4),
            (math.pi / 2, math.pi / 4), (math.pi / 2, -math.pi / 4)]
MONTH = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime("%Y-%m")


def chsh_circuit(ta, tb):
    qc = QuantumCircuit(2)
    qc.h(0); qc.cx(0, 1)
    qc.ry(-ta, 0); qc.ry(-tb, 1)
    qc.measure_all()
    return qc


def grover_circuit(target="101"):
    qc = QuantumCircuit(3)
    qc.h(range(3))
    for _ in range(2):
        for q, bit in enumerate(reversed(target)):
            if bit == "0":
                qc.x(q)
        qc.h(2); qc.ccx(0, 1, 2); qc.h(2)
        for q, bit in enumerate(reversed(target)):
            if bit == "0":
                qc.x(q)
        qc.h(range(3)); qc.x(range(3))
        qc.h(2); qc.ccx(0, 1, 2); qc.h(2)
        qc.x(range(3)); qc.h(range(3))
    qc.measure_all()
    return qc


def ghz_circuit(n):
    qc = QuantumCircuit(n)
    qc.h(0)
    for i in range(n - 1):
        qc.cx(i, i + 1)
    qc.measure_all()
    return qc


def correlation(counts):
    total = sum(counts.values())
    same = counts.get("00", 0) + counts.get("11", 0)
    e = (2 * same - total) / total
    return e, math.sqrt(max(1e-12, 1 - e * e) / total)


circuits = ([chsh_circuit(a, b) for a, b in SETTINGS]
            + [grover_circuit()]
            + [ghz_circuit(n) for n in GHZ_SIZES])

service = QiskitRuntimeService()

# invio parallelo: 3 job in coda contemporaneamente
jobs = {}
for name in BACKENDS:
    backend = service.backend(name)
    pm = generate_preset_pass_manager(backend=backend, optimization_level=1)
    isa = [pm.run(qc) for qc in circuits]
    job = Sampler(mode=backend).run(isa, shots=SHOTS)
    jobs[name] = job
    print(f"[{name}] job {job.job_id()} inviato")

# raccolta risultati
runs = {}
for name, job in jobs.items():
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

    runs[name] = {
        "job_id": job.job_id(),
        "chsh": {"E": es, "err": errs, "S": s, "S_err": s_err,
                 "sigmas_over_classical": (s - 2) / s_err},
        "grover_hit": hit,
        "ghz_fidelity": ghz,
        "qpu_seconds": qpu_s,
    }
    print(f"[{name}] S={s:.3f}+-{s_err:.3f}  grover={hit*100:.1f}%  "
          f"ghz={ {k: round(v,3) for k, v in ghz.items()} }  qpu={qpu_s}s")

out = {"month": MONTH, "date": date.today().isoformat(),
       "shots": SHOTS, "ghz_sizes": GHZ_SIZES, "runs": runs}
(HERE / f"observatory_{MONTH}.json").write_text(json.dumps(out, indent=2))

# indice per il sito
index_path = HERE / "observatory_index.json"
index = json.loads(index_path.read_text()) if index_path.exists() else []
index = [m for m in index if m != MONTH] + [MONTH]
index_path.write_text(json.dumps(sorted(index), indent=2))
print(f"\nSalvato observatory_{MONTH}.json")
