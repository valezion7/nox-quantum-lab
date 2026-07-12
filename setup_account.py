"""Salva le credenziali IBM Quantum e verifica la connessione.

Uso:  python setup_account.py <API_KEY>
Le credenziali finiscono in ~/.qiskit/qiskit-ibm.json (gestito da qiskit-ibm-runtime).
"""
import sys

from qiskit_ibm_runtime import QiskitRuntimeService

if len(sys.argv) != 2:
    sys.exit("Uso: python setup_account.py <API_KEY>")

# plans_preference=["open"] + region: doppia sicurezza: se in futuro sul conto
# compare un instance a pagamento, il default resta quello gratuito.
QiskitRuntimeService.save_account(
    token=sys.argv[1],
    region="us-east",
    plans_preference=["open"],
    set_as_default=True,
    overwrite=True,
)
print("Credenziali salvate.")

service = QiskitRuntimeService()
print(f"Instance attivo: {service.active_instance()}")
print("QPU disponibili:")
for backend in service.backends(simulator=False, operational=True):
    print(f"  - {backend.name} ({backend.num_qubits} qubit)")
