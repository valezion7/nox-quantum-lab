"""Hello World Qiskit: esecuzione su QPU REALE (piano open, ~pochi secondi di quota).

Segue la guida ufficiale passo-passo:
https://quantum.cloud.ibm.com/docs/en/guides/hello-world
Il job ID viene salvato subito su file: se la coda è lunga si può recuperare
il risultato in un secondo momento senza rilanciare (retrieve_job.py).
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt
from qiskit import QuantumCircuit
from qiskit.quantum_info import SparsePauliOp
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime import EstimatorV2 as Estimator
from qiskit_ibm_runtime import QiskitRuntimeService

HERE = Path(__file__).parent

# --- Fase 1: map, il Bell state |00> + |11>
qc = QuantumCircuit(2)
qc.h(0)
qc.cx(0, 1)

observables_labels = ["IZ", "IX", "ZI", "XI", "ZZ", "XX"]
observables = [SparsePauliOp(label) for label in observables_labels]

# --- Fase 2: optimize, scelta della QPU meno occupata + transpilation ISA
service = QiskitRuntimeService()
backend = service.least_busy(simulator=False, operational=True)
print(f"Backend selezionato: {backend.name} ({backend.num_qubits} qubit)")

pm = generate_preset_pass_manager(backend=backend, optimization_level=1)
isa_circuit = pm.run(qc)

# --- Fase 3: execute, EstimatorV2 con error mitigation livello 1 (come da guida)
mapped_observables = [obs.apply_layout(isa_circuit.layout) for obs in observables]
estimator = Estimator(mode=backend)
estimator.options.resilience_level = 1
estimator.options.default_shots = 5000

job = estimator.run([(isa_circuit, mapped_observables)])
(HERE / "last_job_id.txt").write_text(f"{job.job_id()}\n{backend.name}\n")
print(f"Job ID: {job.job_id()}  (salvato in last_job_id.txt)")
print("In attesa del risultato (coda pubblica, può richiedere minuti)...")

# --- Fase 4: post-process
pub_result = job.result()[0]
values = pub_result.data.evs
errors = pub_result.data.stds

print("\nOsservabile | Valore atteso | Errore std")
for label, value, err in zip(observables_labels, values, errors):
    print(f"  {label:>4}      | {value:+.4f}       | {err:.4f}")

try:
    usage = job.usage()
    print(f"\nTempo QPU consumato: {usage:.1f}s")
except Exception:
    usage = None

results = {
    "job_id": job.job_id(),
    "backend": backend.name,
    "shots": 5000,
    "observables": observables_labels,
    "values": [float(v) for v in values],
    "stds": [float(e) for e in errors],
    "qpu_seconds": usage,
}
(HERE / "qpu_results.json").write_text(json.dumps(results, indent=2))

plt.plot(observables_labels, values, "-o")
plt.xlabel("Observables")
plt.ylabel("Values")
plt.title(f"Bell state su {backend.name} (5000 shots, resilience 1)")
plt.savefig(HERE / "qpu_results.png", dpi=150, bbox_inches="tight")
print("Salvati: qpu_results.json, qpu_results.png")
