"""Hello World Qiskit: validazione LOCALE su simulatore (zero secondi QPU).

Stesso identico pattern in 4 fasi della guida ufficiale, eseguito su un fake
backend. Se questo passa, hello_qpu.py può girare sull'hardware vero.
Guida: https://quantum.cloud.ibm.com/docs/en/guides/hello-world
"""
from qiskit import QuantumCircuit
from qiskit.quantum_info import SparsePauliOp
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime import EstimatorV2 as Estimator
from qiskit_ibm_runtime.fake_provider import FakeBelemV2

# --- Fase 1: map, il Bell state |00> + |11>
qc = QuantumCircuit(2)
qc.h(0)
qc.cx(0, 1)

observables_labels = ["IZ", "IX", "ZI", "XI", "ZZ", "XX"]
observables = [SparsePauliOp(label) for label in observables_labels]

# --- Fase 2: optimize, transpilation ISA per il backend
backend = FakeBelemV2()
pm = generate_preset_pass_manager(backend=backend, optimization_level=1)
isa_circuit = pm.run(qc)

# --- Fase 3: execute, primitive EstimatorV2
mapped_observables = [obs.apply_layout(isa_circuit.layout) for obs in observables]
estimator = Estimator(backend)
job = estimator.run([(isa_circuit, mapped_observables)])

# --- Fase 4: post-process
pub_result = job.result()[0]
values = pub_result.data.evs

print("Osservabile | Valore atteso")
for label, value in zip(observables_labels, values):
    print(f"  {label:>4}      | {value:+.3f}")

# Firma dell'entanglement: X e Z dei singoli qubit ~0, correlazioni ZZ/XX ~1.
# Soglie larghe (0.5): il fake backend simula il rumore di un device reale.
singles = dict(zip(observables_labels, values))
assert abs(singles["ZZ"]) > 0.5 and abs(singles["XX"]) > 0.5, "correlazioni assenti"
assert all(abs(singles[k]) < 0.5 for k in ("IZ", "IX", "ZI", "XI")), "singoli non nulli"
print("\nOK: entanglement rilevato, pipeline valida. Pronto per la QPU reale.")
