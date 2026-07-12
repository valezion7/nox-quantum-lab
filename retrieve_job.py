"""Recupera stato/risultato di un job QPU (da last_job_id.txt o argv).

Funziona sia con i job Estimator (hello_qpu.py) sia con i job Sampler
(experiments.py, observatory.py, qrng_submit.py).
Uso: python retrieve_job.py [JOB_ID]
"""
import sys
from pathlib import Path

from qiskit_ibm_runtime import QiskitRuntimeService

HERE = Path(__file__).parent

if len(sys.argv) > 1:
    job_id = sys.argv[1]
else:
    job_id = (HERE / "last_job_id.txt").read_text().splitlines()[0]

service = QiskitRuntimeService()
job = service.job(job_id)
status = str(job.status()).replace("JobStatus.", "")
print(f"Job {job_id}: {status}")

if status != "DONE":
    sys.exit(0)

result = job.result()
for i, pub in enumerate(result):
    data = pub.data
    if hasattr(data, "evs"):
        # job Estimator: valori attesi degli osservabili
        print(f"  pub {i}: valori attesi {[f'{float(v):+.4f}' for v in data.evs]}")
    elif hasattr(data, "meas"):
        # job Sampler: conteggi delle misure
        counts = data.meas.get_counts()
        top = sorted(counts.items(), key=lambda kv: -kv[1])[:6]
        print(f"  pub {i}: {sum(counts.values())} shot, esiti principali {top}")
    else:
        print(f"  pub {i}: formato dati non riconosciuto ({type(data).__name__})")
