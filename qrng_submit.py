"""Esperimento 003: Monete quantistiche.
Sottomette un job QRNG: 8 qubit in superposizione (H) misurati 4096 volte
= 32768 bit grezzi. Zero attesa: stampa il job id e esce.
Uso: python qrng_submit.py [backend]
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from qiskit import QuantumCircuit
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2

HERE = Path(__file__).parent
N_QUBITS = 8
SHOTS = 4096

backend_name = sys.argv[1] if len(sys.argv) > 1 else "ibm_fez"
service = QiskitRuntimeService()
backend = service.backend(backend_name)

qc = QuantumCircuit(N_QUBITS)
qc.h(range(N_QUBITS))
qc.measure_all()

isa = generate_preset_pass_manager(optimization_level=1, backend=backend).run(qc)
job = SamplerV2(mode=backend).run([isa], shots=SHOTS)

meta = {
    "job_id": job.job_id(),
    "backend": backend_name,
    "n_qubits": N_QUBITS,
    "shots": SHOTS,
    "submitted_at": datetime.now(timezone.utc).isoformat(),
}
(HERE / "qrng_job.json").write_text(json.dumps(meta, indent=2))
print(json.dumps(meta))
