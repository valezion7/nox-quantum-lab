"""NOX Quantum Lab, Report 001: due esperimenti seri su QPU reale.

1. Test CHSH (disuguaglianza di Bell): per ogni teoria classica locale S <= 2.
   La meccanica quantistica arriva a 2*sqrt(2) = 2.828. Misuriamo S su hardware
   con conteggi GREZZI (SamplerV2, nessuna mitigazione che gonfi il risultato).
2. Grover su chiave a 3 bit: trovare |101> tra 8 possibilita' con 2 iterazioni.
   Ideale ~94.5%; tirare a caso: 12.5%.

Un solo job QPU (5 circuiti), pochi secondi di quota. Output: JSON + 2 PNG.
"""
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt
from qiskit import QuantumCircuit
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_ibm_runtime import SamplerV2 as Sampler

HERE = Path(__file__).parent
SHOTS = 4096

# ---------- CHSH: 4 circuiti, coppia di Bell misurata in basi ruotate ----------
# Misurare lungo l'angolo theta (piano Z-X) = applicare Ry(-theta) e misurare Z.
# Angoli: A in {0, pi/2}, B in {pi/4, -pi/4}  ->  S ideale = 2*sqrt(2).
SETTINGS = [(0, math.pi / 4), (0, -math.pi / 4),
            (math.pi / 2, math.pi / 4), (math.pi / 2, -math.pi / 4)]


def chsh_circuit(theta_a: float, theta_b: float) -> QuantumCircuit:
    qc = QuantumCircuit(2)
    qc.h(0)
    qc.cx(0, 1)
    qc.ry(-theta_a, 0)
    qc.ry(-theta_b, 1)
    qc.measure_all()
    return qc


def correlation(counts: dict) -> tuple[float, float]:
    """E = P(uguali) - P(diversi), con errore standard binomiale."""
    total = sum(counts.values())
    same = counts.get("00", 0) + counts.get("11", 0)
    e = (2 * same - total) / total
    err = math.sqrt(max(1e-12, 1 - e * e) / total)
    return e, err


# ---------- Grover: chiave segreta |101>, 2 iterazioni ----------
def grover_circuit(target: str = "101") -> QuantumCircuit:
    n = 3
    qc = QuantumCircuit(n)
    qc.h(range(n))
    for _ in range(2):
        # oracolo: flip di fase su |target> (bit string letta come q2 q1 q0)
        for q, bit in enumerate(reversed(target)):
            if bit == "0":
                qc.x(q)
        qc.h(2); qc.ccx(0, 1, 2); qc.h(2)
        for q, bit in enumerate(reversed(target)):
            if bit == "0":
                qc.x(q)
        # diffusore
        qc.h(range(n)); qc.x(range(n))
        qc.h(2); qc.ccx(0, 1, 2); qc.h(2)
        qc.x(range(n)); qc.h(range(n))
    qc.measure_all()
    return qc


# ---------- esecuzione: un solo job, 5 circuiti ----------
# Con un job id come argomento recupera un job gia' eseguito (zero quota QPU).
import sys

service = QiskitRuntimeService()
if len(sys.argv) > 1:
    job = service.job(sys.argv[1])
    backend_name = job.backend().name
    print(f"Recupero job esistente {sys.argv[1]} su {backend_name}")
else:
    backend = service.least_busy(simulator=False, operational=True)
    backend_name = backend.name
    print(f"Backend: {backend_name} ({backend.num_qubits} qubit)")

    pm = generate_preset_pass_manager(backend=backend, optimization_level=1)
    circuits = [chsh_circuit(a, b) for a, b in SETTINGS] + [grover_circuit("101")]
    isa_circuits = [pm.run(qc) for qc in circuits]

    sampler = Sampler(mode=backend)
    job = sampler.run(isa_circuits, shots=SHOTS)
    (HERE / "last_job_id.txt").write_text(f"{job.job_id()}\n{backend_name}\n")
    print(f"Job ID: {job.job_id()} (in coda...)")

result = job.result()

# ---------- CHSH: post-process ----------
labels = ["E(a,b)", "E(a,b')", "E(a',b)", "E(a',b')"]
es, errs = [], []
for i in range(4):
    counts = result[i].data.meas.get_counts()
    e, err = correlation(counts)
    es.append(e)
    errs.append(err)

s_value = es[0] + es[1] + es[2] - es[3]
s_err = math.sqrt(sum(x * x for x in errs))
sigmas = (s_value - 2) / s_err

print("\n--- CHSH ---")
for label, e, err in zip(labels, es, errs):
    print(f"  {label:9s} = {e:+.4f} ± {err:.4f}")
print(f"  S = {s_value:.4f} ± {s_err:.4f}")
print(f"  Limite classico 2 violato di {sigmas:.1f} deviazioni standard"
      f" (max quantistico 2*sqrt(2) = {2*math.sqrt(2):.4f})")

# ---------- Grover: post-process ----------
gcounts = result[4].data.meas.get_counts()
total = sum(gcounts.values())
hit = gcounts.get("101", 0) / total
print("\n--- Grover (chiave segreta: 101) ---")
print(f"  Chiave trovata nel {hit*100:.1f}% degli shot (caso: 12.5%)")

try:
    qpu_seconds = job.usage()
except Exception:
    qpu_seconds = None
print(f"\nTempo QPU: {qpu_seconds}s")

# ---------- salvataggi ----------
out = {
    "job_id": job.job_id(),
    "backend": backend_name,
    "shots": SHOTS,
    "chsh": {"labels": labels, "E": es, "err": errs,
             "S": s_value, "S_err": s_err, "sigmas_over_classical": sigmas},
    "grover": {"target": "101", "hit_rate": hit,
               "counts": {k: v for k, v in sorted(gcounts.items())}},
    "qpu_seconds": qpu_seconds,
}
(HERE / "experiments_results.json").write_text(json.dumps(out, indent=2))

# grafico CHSH
fig, ax = plt.subplots(figsize=(6, 3.4))
ax.bar(labels, es, yerr=errs, color=["#37e2d5"] * 3 + ["#7c6cff"], width=0.55)
ax.axhline(0, color="#888", lw=0.6)
ax.set_title(f"CHSH su {backend_name}: S = {s_value:.3f} (classico ≤ 2, quantistico ≤ 2.828)")
ax.set_ylabel("Correlazione E")
fig.tight_layout()
fig.savefig(HERE / "chsh_results.png", dpi=150)

# grafico Grover
fig, ax = plt.subplots(figsize=(6, 3.4))
keys = sorted(set(list(gcounts.keys()) + [format(i, "03b") for i in range(8)]))
vals = [gcounts.get(k, 0) / total * 100 for k in keys]
ax.bar(keys, vals, color=["#7c6cff" if k == "101" else "#3a4258" for k in keys])
ax.axhline(12.5, color="#e05c5c", lw=1, ls="--", label="caso (12.5%)")
ax.set_title(f"Grover su {backend_name}: chiave 101 trovata nel {hit*100:.1f}% degli shot")
ax.set_ylabel("% shot")
ax.legend()
fig.tight_layout()
fig.savefig(HERE / "grover_results.png", dpi=150)
print("Salvati: experiments_results.json, chsh_results.png, grover_results.png")
