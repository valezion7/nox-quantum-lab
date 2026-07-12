"""NOX Router v0: dato un task, sceglie il backend giusto e lascia lo scontrino.

L'idea di NOX in una frase: un agente non deve soltanto eseguire, deve sapere
DOVE, QUANDO e SE conviene eseguire. Questo router v0 la applica ai backend
del laboratorio (CPU classica, simulatore Aer, QPU IBM reale) su tre task:

  search   trovare una stringa marcata tra 2^n possibilita' (il problema di Grover)
  bell     il test CHSH: riprodurre le statistiche oppure certificarle su hardware
  qrng     generare bit casuali

Per ogni richiesta il router valuta i candidati, spiega la scelta ed esegue
solo quando ha senso. Tutto finisce in uno scontrino JSON in receipts/.
La QPU reale non viene mai toccata senza --allow-qpu: la quota e' preziosa
e la coda e' lunga, quindi il default e' decidere senza spendere.

Esempi:
  python nox_router.py search --space 8 --target 101
  python nox_router.py search --space 8 --target 101 --objective hardware-proof
  python nox_router.py bell
  python nox_router.py bell --objective certify --allow-qpu
  python nox_router.py qrng --bits 128
  python nox_router.py qrng --bits 128 --objective quantum --allow-qpu

Nota onesta, da tenere a mente leggendo gli scontrini: su questi problemi
giocattolo il classico vince sempre in velocita'. Il valore della QPU oggi
non e' la velocita', e' cio' che il classico non puo' produrre per principio:
correlazioni di Bell certificate dall'hardware e casualita' non deterministica.
"""
import argparse
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
RECEIPTS = HERE / "receipts"


# ---------------------------------------------------------------- circuiti

def grover_circuit(target: str):
    """Grover generico per una stringa target di n bit (n >= 2)."""
    from qiskit import QuantumCircuit
    n = len(target)
    iters = max(1, math.floor(math.pi / 4 * math.sqrt(2 ** n)))
    qc = QuantumCircuit(n)
    qc.h(range(n))
    for _ in range(iters):
        # oracolo: flip di fase su |target> (stringa letta come q_{n-1}..q_0)
        for q, bit in enumerate(reversed(target)):
            if bit == "0":
                qc.x(q)
        qc.h(n - 1)
        qc.mcx(list(range(n - 1)), n - 1)
        qc.h(n - 1)
        for q, bit in enumerate(reversed(target)):
            if bit == "0":
                qc.x(q)
        # diffusore
        qc.h(range(n))
        qc.x(range(n))
        qc.h(n - 1)
        qc.mcx(list(range(n - 1)), n - 1)
        qc.h(n - 1)
        qc.x(range(n))
        qc.h(range(n))
    qc.measure_all()
    return qc, iters


def chsh_circuits():
    """I 4 circuiti CHSH del Report 001 (coppia di Bell, basi ruotate)."""
    from qiskit import QuantumCircuit
    settings = [(0, math.pi / 4), (0, -math.pi / 4),
                (math.pi / 2, math.pi / 4), (math.pi / 2, -math.pi / 4)]
    out = []
    for ta, tb in settings:
        qc = QuantumCircuit(2)
        qc.h(0)
        qc.cx(0, 1)
        qc.ry(-ta, 0)
        qc.ry(-tb, 1)
        qc.measure_all()
        out.append(qc)
    return out


def chsh_s(results: list) -> float:
    es = []
    for counts in results:
        total = sum(counts.values())
        same = counts.get("00", 0) + counts.get("11", 0)
        es.append((2 * same - total) / total)
    return es[0] + es[1] + es[2] - es[3]


# ---------------------------------------------------------------- esecutori

def run_simulator(circuits, shots=2048):
    from qiskit.transpiler import generate_preset_pass_manager
    from qiskit_aer import AerSimulator
    sim = AerSimulator()
    pm = generate_preset_pass_manager(backend=sim, optimization_level=1)
    out = []
    for qc in circuits:
        counts = sim.run(pm.run(qc), shots=shots).result().get_counts()
        out.append(counts)
    return out


def submit_qpu(circuits, shots=2048):
    """Invia un job alla QPU meno occupata e torna subito (non aspetta la coda)."""
    from qiskit.transpiler import generate_preset_pass_manager
    from qiskit_ibm_runtime import QiskitRuntimeService
    from qiskit_ibm_runtime import SamplerV2 as Sampler
    service = QiskitRuntimeService()
    backend = service.least_busy(simulator=False, operational=True)
    pm = generate_preset_pass_manager(backend=backend, optimization_level=1)
    isa = [pm.run(qc) for qc in circuits]
    job = Sampler(mode=backend).run(isa, shots=shots)
    return {"backend": backend.name, "job_id": job.job_id(),
            "note": "in coda; recupera i risultati con retrieve_job.py"}


# ---------------------------------------------------------------- i tre task

def task_search(args, receipt):
    n = args.space.bit_length() - 1
    if 2 ** n != args.space:
        raise SystemExit("--space deve essere una potenza di 2 (es. 8, 16, 1024)")
    target = args.target
    if len(target) != n or set(target) - {"0", "1"}:
        raise SystemExit(f"--target deve essere una stringa di {n} bit")

    receipt["candidates"] = [
        {"backend": "classical", "can_answer": True,
         "est": f"{args.space} confronti, microsecondi, costo zero",
         "note": "per qualunque spazio enumerabile in memoria e' imbattibile"},
        {"backend": "simulator", "can_answer": True,
         "est": f"Grover a {n} qubit su Aer, ~secondi",
         "note": "utile solo per validare il circuito, non per la risposta"},
        {"backend": "qpu", "can_answer": True,
         "est": f"Grover a {n} qubit, ~secondi di quota + coda",
         "note": "dimostra l'algoritmo su hardware; nessun vantaggio di velocita' a questa scala"},
    ]

    if args.objective == "answer":
        receipt["chosen"] = "classical"
        receipt["reason"] = ("l'obiettivo e' la risposta: la ricerca esaustiva "
                             "classica la da' con certezza in una frazione di "
                             "millisecondo. Usare la QPU qui sarebbe marketing.")
        t0 = time.perf_counter()
        wanted = int(target, 2)
        found = next(i for i in range(args.space) if i == wanted)
        ms = (time.perf_counter() - t0) * 1000
        receipt["executed"] = {"backend": "classical",
                               "found": format(found, f"0{n}b"),
                               "wall_ms": round(ms, 4), "certainty": 1.0}
        print(f"CLASSICO: trovato {format(found, f'0{n}b')} in {ms:.4f} ms")
        return

    # objective = hardware-proof: la QPU e' il punto, ma prima si valida gratis
    receipt["chosen"] = "qpu"
    receipt["reason"] = ("l'obiettivo e' dimostrare l'algoritmo su hardware "
                         "reale: solo la QPU risponde alla domanda. Prima di "
                         "spendere quota il circuito viene validato sul "
                         "simulatore (il gate di NOX).")
    qc, iters = grover_circuit(target)
    counts = run_simulator([qc], shots=2048)[0]
    top = max(counts, key=counts.get)
    receipt["simulator_gate"] = {"iterations": iters, "top_outcome": top,
                                 "top_share": round(counts[top] / 2048, 3)}
    if top != target:
        receipt["executed"] = None
        receipt["outcome"] = "bloccato: il simulatore non conferma il circuito"
        print(f"GATE FALLITO: il simulatore da' {top}, atteso {target}. Non spendo quota.")
        return
    print(f"GATE OK: simulatore conferma {top} ({counts[top]/2048:.1%} degli shot)")
    if not args.allow_qpu:
        receipt["executed"] = None
        receipt["outcome"] = "deciso ma non eseguito: rilancia con --allow-qpu per usare quota reale"
        print("Decisione presa (QPU). Per eseguire davvero: aggiungi --allow-qpu")
        return
    receipt["executed"] = {"backend": "qpu", **submit_qpu([qc])}
    print(f"QPU: job {receipt['executed']['job_id']} su {receipt['executed']['backend']}")


def task_bell(args, receipt):
    receipt["candidates"] = [
        {"backend": "classical", "can_answer": False,
         "est": "n/a",
         "note": "nessun sistema classico locale produce S > 2: non c'e' niente da eseguire"},
        {"backend": "simulator", "can_answer": args.objective == "simulate",
         "est": "4 circuiti su Aer, ~secondi",
         "note": "riproduce le statistiche quantistiche ma gira su un computer "
                 "classico: non certifica nulla sulla natura"},
        {"backend": "qpu", "can_answer": True,
         "est": "4 circuiti, ~5-8 s di quota + coda",
         "note": "l'unico backend che risponde alla domanda fisica"},
    ]

    if args.objective == "simulate":
        receipt["chosen"] = "simulator"
        receipt["reason"] = ("l'obiettivo e' riprodurre le statistiche attese: "
                             "il simulatore basta e costa zero.")
        results = run_simulator(chsh_circuits(), shots=4096)
        s = chsh_s(results)
        receipt["executed"] = {"backend": "simulator", "S": round(s, 4),
                               "shots_per_setting": 4096,
                               "caveat": "valore simulato: non e' una prova sperimentale"}
        print(f"SIMULATORE: S = {s:.4f} (ideale 2.828). Attenzione: e' una "
              f"simulazione, non un esperimento.")
        return

    receipt["chosen"] = "qpu"
    receipt["reason"] = ("l'obiettivo e' certificare la violazione su hardware: "
                         "per definizione serve un dispositivo quantistico reale.")
    if not args.allow_qpu:
        receipt["executed"] = None
        receipt["outcome"] = "deciso ma non eseguito: rilancia con --allow-qpu per usare quota reale"
        print("Decisione presa (QPU). Per eseguire davvero: aggiungi --allow-qpu")
        return
    receipt["executed"] = {"backend": "qpu", **submit_qpu(chsh_circuits(), shots=4096)}
    print(f"QPU: job {receipt['executed']['job_id']} su {receipt['executed']['backend']}")


def task_qrng(args, receipt):
    receipt["candidates"] = [
        {"backend": "classical", "can_answer": args.objective == "any",
         "est": "os.urandom, istantaneo",
         "note": "CSPRNG del sistema operativo: eccellente in pratica, "
                 "deterministico per costruzione"},
        {"backend": "simulator", "can_answer": False,
         "est": "n/a",
         "note": "un simulatore usa a sua volta un PRNG classico: quantistico solo di nome"},
        {"backend": "qpu", "can_answer": True,
         "est": f"~{max(1, args.bits // 8192) * 2} s di quota + coda",
         "note": "misure di qubit in superposizione: esiti non deterministici per fisica"},
    ]

    if args.objective == "any":
        receipt["chosen"] = "classical"
        receipt["reason"] = ("servono bit casuali generici: il CSPRNG del "
                             "sistema operativo e' la scelta giusta e gratuita. "
                             "La QPU serve solo se la richiesta e' proprio la "
                             "casualita' quantistica.")
        raw = os.urandom(math.ceil(args.bits / 8))
        bits = "".join(format(b, "08b") for b in raw)[:args.bits]
        receipt["executed"] = {"backend": "classical", "bits": len(bits),
                               "sample": bits[:64],
                               "quantum": False}
        print(f"CLASSICO: {len(bits)} bit da os.urandom (non quantistici). "
              f"Anteprima: {bits[:32]}...")
        return

    receipt["chosen"] = "qpu"
    receipt["reason"] = ("la richiesta e' casualita' quantistica autentica: "
                         "solo la misura di qubit reali la fornisce (vedi "
                         "qrng_submit.py / qrng_fetch.py per il flusso completo "
                         "con estrattore di von Neumann).")
    if not args.allow_qpu:
        receipt["executed"] = None
        receipt["outcome"] = "deciso ma non eseguito: rilancia con --allow-qpu per usare quota reale"
        print("Decisione presa (QPU). Per eseguire davvero: aggiungi --allow-qpu")
        return
    from qiskit import QuantumCircuit
    n = 8
    shots = math.ceil(args.bits / n)
    qc = QuantumCircuit(n)
    qc.h(range(n))
    qc.measure_all()
    receipt["executed"] = {"backend": "qpu", **submit_qpu([qc], shots=shots),
                           "note_extra": "bit grezzi: applicare von Neumann prima dell'uso (qrng_fetch.py)"}
    print(f"QPU: job {receipt['executed']['job_id']} su {receipt['executed']['backend']}")


# ---------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description="NOX Router v0: decide dove eseguire, con lo scontrino.")
    sub = p.add_subparsers(dest="task", required=True)

    ps = sub.add_parser("search", help="trova una stringa marcata tra 2^n possibilita'")
    ps.add_argument("--space", type=int, default=8, help="dimensione dello spazio (potenza di 2)")
    ps.add_argument("--target", default="101", help="stringa di bit da trovare")
    ps.add_argument("--objective", choices=["answer", "hardware-proof"], default="answer")
    ps.add_argument("--allow-qpu", action="store_true")

    pb = sub.add_parser("bell", help="test CHSH: statistiche simulate o certificazione su hardware")
    pb.add_argument("--objective", choices=["simulate", "certify"], default="simulate")
    pb.add_argument("--allow-qpu", action="store_true")

    pq = sub.add_parser("qrng", help="bit casuali")
    pq.add_argument("--bits", type=int, default=128)
    pq.add_argument("--objective", choices=["any", "quantum"], default="any")
    pq.add_argument("--allow-qpu", action="store_true")

    args = p.parse_args()

    receipt = {"router": "nox-router-v0", "task": args.task,
               "params": {k: v for k, v in vars(args).items() if k != "task"},
               "started": datetime.now(timezone.utc).isoformat()}
    t0 = time.perf_counter()

    {"search": task_search, "bell": task_bell, "qrng": task_qrng}[args.task](args, receipt)

    receipt["total_wall_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    RECEIPTS.mkdir(exist_ok=True)
    out = RECEIPTS / f"receipt_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{args.task}.json"
    out.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nScontrino: {out.relative_to(HERE)}")
    print(f"Scelto: {receipt['chosen']}. {receipt['reason']}")


if __name__ == "__main__":
    main()
