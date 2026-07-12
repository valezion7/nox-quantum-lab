"""Recupera il job QRNG e produce il pool di bit per la pagina Monete.
I bit grezzi hanno un lieve bias hardware: applichiamo von Neumann
(01->0, 10->1, 00/11 scartati) per ottenere lanci non distorti.
Uso: python qrng_fetch.py [job_id]  (default: quello in qrng_job.json)
"""
import json
import sys
from datetime import date
from pathlib import Path

from qiskit_ibm_runtime import QiskitRuntimeService

HERE = Path(__file__).parent
meta = json.loads((HERE / "qrng_job.json").read_text())
job_id = sys.argv[1] if len(sys.argv) > 1 else meta["job_id"]

service = QiskitRuntimeService()
job = service.job(job_id)
status = str(job.status())
if status not in ("DONE", "JobStatus.DONE"):
    print(f"job {job_id}: {status} - riprova piu' tardi")
    sys.exit(1)

result = job.result()
shots_bits = result[0].data.meas.get_bitstrings()      # una stringa da 8 bit per shot
raw = "".join(shots_bits)

ones = raw.count("1")
coin = []
for i in range(0, len(raw) - 1, 2):                    # von Neumann
    pair = raw[i:i + 2]
    if pair == "01":
        coin.append("0")
    elif pair == "10":
        coin.append("1")
coin = "".join(coin)

try:
    qpu_s = job.usage()
except Exception:
    qpu_s = None

out = {
    "experiment": "003-monete-quantistiche",
    "job_id": job_id,
    "backend": meta["backend"],
    "date": date.today().isoformat(),
    "shots": meta["shots"],
    "n_qubits": meta["n_qubits"],
    "qpu_seconds": qpu_s,
    "raw_bits": len(raw),
    "raw_ones": ones,
    "coin_bits": len(coin),
    "coin": coin,
}
(HERE / "qrng_pool.json").write_text(json.dumps(out))
print(f"OK: raw={len(raw)} bit (bias grezzo {ones/len(raw)*100:.2f}% di 1), "
      f"lanci puliti={len(coin)}, qpu={qpu_s}s -> qrng_pool.json")
