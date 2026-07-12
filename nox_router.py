"""NOX Router v0: dato un task, sceglie il backend giusto e lascia lo scontrino.

L'idea di NOX in una frase: un agente non deve soltanto eseguire, deve sapere
DOVE, QUANDO e SE conviene eseguire. Questo router la applica ai backend del
laboratorio (CPU classica, simulatore Aer, QPU IBM reale) e, dalla v0.2,
anche ai modelli di linguaggio (LLM locale su GPU contro API cloud):

  search   trovare una stringa marcata tra 2^n possibilita' (il problema di Grover)
  bell     il test CHSH: riprodurre le statistiche oppure certificarle su hardware
  qrng     generare bit casuali
  llm      generare testo: modello locale (Ollama) o API cloud, con stima dei costi

Per ogni richiesta il router valuta i candidati, spiega la scelta ed esegue
solo quando ha senso. Tutto finisce in uno scontrino JSON in receipts/.
Le risorse che costano non vengono mai toccate senza un flag esplicito:
--allow-qpu per la quota IBM Quantum, --allow-cloud per le API a pagamento.

Esempi:
  python nox_router.py search --space 8 --target 101
  python nox_router.py search --space 8 --target 101 --objective hardware-proof
  python nox_router.py bell
  python nox_router.py bell --objective certify --allow-qpu
  python nox_router.py qrng --bits 128
  python nox_router.py qrng --bits 128 --objective quantum --allow-qpu
  python nox_router.py llm "Riassumi in tre righe: ..." --objective draft
  python nox_router.py llm "..." --objective quality --allow-cloud

Nota onesta, da tenere a mente leggendo gli scontrini: sui problemi
giocattolo il classico vince sempre in velocita'. Il valore della QPU oggi
non e' la velocita', e' cio' che il classico non puo' produrre per principio:
correlazioni di Bell certificate dall'hardware e casualita' non deterministica.
"""
import argparse
import json
import math
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
RECEIPTS = HERE / "receipts"
CONFIG = json.loads((HERE / "router_config.json").read_text(encoding="utf-8"))


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


# ---------------------------------------------------------------- esperienza
# Gli scontrini non sono solo trasparenza: sono la memoria del router.
# Prima di stimare, rilegge le esecuzioni passate e usa i numeri osservati
# (token al secondo reali, costi reali) al posto delle ipotesi a priori.

def _median(xs: list) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def load_experience() -> dict:
    exp = {"receipts_read": 0, "local": {}, "cloud": {}}
    if not RECEIPTS.exists():
        return exp
    for f in sorted(RECEIPTS.glob("receipt_*.json")):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        exp["receipts_read"] += 1
        ex = r.get("executed") or {}
        backend = ex.get("backend", "")
        if backend.startswith("local:") and ex.get("tokens_per_s"):
            exp["local"].setdefault(backend[6:], []).append(ex["tokens_per_s"])
        elif backend.startswith("cloud:") and ex.get("cost_usd") is not None:
            exp["cloud"].setdefault(backend[6:], []).append(ex["cost_usd"])
    return exp


def experience_summary(exp: dict) -> dict:
    out = {"receipts_read": exp["receipts_read"], "local": {}, "cloud": {}}
    for model, speeds in exp["local"].items():
        out["local"][model] = {"runs": len(speeds),
                               "median_tokens_per_s": round(_median(speeds), 1)}
    for model, costs in exp["cloud"].items():
        out["cloud"][model] = {"runs": len(costs),
                               "median_cost_usd": round(_median(costs), 5)}
    return out


# ---------------------------------------------------------------- llm

def ollama_models(timeout: float = 3.0) -> list:
    """Modelli disponibili sull'istanza Ollama locale ([] se non raggiungibile)."""
    try:
        with urllib.request.urlopen(CONFIG["ollama_url"] + "/api/tags", timeout=timeout) as r:
            tags = json.loads(r.read())
        return [m["name"] for m in tags.get("models", [])]
    except Exception:
        return []


def run_ollama(model: str, prompt: str, max_out: int) -> dict:
    def call(payload: dict) -> dict:
        req = urllib.request.Request(CONFIG["ollama_url"] + "/api/generate",
                                     data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read())

    base = {"model": model, "prompt": prompt, "stream": False,
            "options": {"num_predict": max_out}}
    t0 = time.perf_counter()
    try:
        # think=False evita il ragionamento esteso sui modelli che lo supportano
        out = call({**base, "think": False})
    except Exception:
        # alcuni modelli rifiutano il parametro think: riprova senza
        out = call(base)
    wall = time.perf_counter() - t0
    n_out = out.get("eval_count", 0)
    return {"text": out.get("response", ""), "output_tokens": n_out,
            "wall_s": round(wall, 2),
            "tokens_per_s": round(n_out / wall, 1) if wall > 0 else None}


def est_tokens(text: str) -> int:
    """Stima grezza (~4 caratteri per token). Per conteggi precisi usare
    l'endpoint count_tokens del provider; qui serve solo a ordinare i costi."""
    return max(1, len(text) // 4)


def task_llm(args, receipt):
    prompt = args.prompt
    tok_in = est_tokens(prompt)
    tok_out = args.max_out
    local = ollama_models()
    local_pick = next((m for m in CONFIG["local_preference"] if m in local), None)
    exp = load_experience()
    receipt["experience"] = experience_summary(exp)

    candidates = []
    if local_pick:
        est = "costo marginale ~0 (hardware locale gia' ammortizzato, resta l'elettricita')"
        speeds = exp["local"].get(local_pick, [])
        if speeds:
            med = _median(speeds)
            est += (f"; osservato su {len(speeds)} run: ~{med:.0f} tok/s mediani, "
                    f"quindi ~{tok_out / med:.0f}s stimati per questa richiesta")
        candidates.append({
            "backend": f"local:{local_pick}", "can_answer": True,
            "est": est,
            "note": "il prompt non lascia mai questa macchina",
        })
    else:
        candidates.append({
            "backend": "local", "can_answer": False,
            "est": "n/a", "note": "Ollama non raggiungibile o nessun modello della lista di preferenza",
        })
    for m in CONFIG["cloud_models"]:
        cost = tok_in / 1e6 * m["price_in_usd_mtok"] + tok_out / 1e6 * m["price_out_usd_mtok"]
        est = (f"~${cost:.4f} stimati ({tok_in} tok in + {tok_out} tok out, "
               f"listino {CONFIG['pricing_date']})")
        costs = exp["cloud"].get(m["name"], [])
        if costs:
            est += f"; osservato su {len(costs)} run: ~${_median(costs):.4f} mediani"
        candidates.append({
            "backend": f"cloud:{m['name']}", "can_answer": True,
            "est": est,
            "note": f"tier {m['tier']}; il prompt viene inviato a {m['provider']}",
        })
    receipt["candidates"] = candidates
    receipt["token_estimate_note"] = ("stima grezza ~4 char/token, serve solo a "
                                      "ordinare i costi tra candidati; dove ci sono "
                                      "run passate, le stime osservate le correggono")
    if exp["receipts_read"]:
        print(f"Esperienza: {exp['receipts_read']} scontrini riletti"
              + (f", {sum(len(v) for v in exp['local'].values())} run locali misurate"
                 if exp["local"] else ""))

    if args.objective == "private":
        if not local_pick:
            receipt["chosen"] = None
            receipt["reason"] = ("richiesta privacy: solo un modello locale puo' "
                                 "rispondere, ma Ollama non e' disponibile. Il "
                                 "router si ferma invece di mandare il prompt nel cloud.")
            receipt["executed"] = None
            print("BLOCCATO: obiettivo private ma nessun modello locale disponibile.")
            return
        receipt["chosen"] = f"local:{local_pick}"
        receipt["reason"] = "il prompt non deve lasciare la macchina: locale obbligato."
    elif args.objective == "draft" and local_pick:
        receipt["chosen"] = f"local:{local_pick}"
        receipt["reason"] = ("per una bozza il modello locale basta e il costo "
                             "marginale e' ~0: il cloud qui sarebbe spesa inutile.")
    else:
        # quality, oppure draft senza un modello locale disponibile
        pick = min((m for m in CONFIG["cloud_models"] if m["tier"] == "top"),
                   key=lambda m: m["price_out_usd_mtok"], default=CONFIG["cloud_models"][0]) \
            if args.objective == "quality" else \
            min(CONFIG["cloud_models"], key=lambda m: m["price_out_usd_mtok"])
        receipt["chosen"] = f"cloud:{pick['name']}"
        receipt["reason"] = ("serve la massima qualita': il modello cloud di fascia "
                             "alta e' la scelta giusta, con il costo stimato sullo scontrino."
                             if args.objective == "quality" else
                             "nessun modello locale disponibile: il cloud piu' economico fa da riserva.")
        if not args.allow_cloud:
            receipt["executed"] = None
            receipt["outcome"] = "deciso ma non eseguito: rilancia con --allow-cloud per spendere sull'API"
            print("Decisione presa (cloud). Per eseguire davvero: aggiungi --allow-cloud")
            return
        if pick["provider"] == "anthropic":
            try:
                import anthropic  # dipendenza opzionale: pip install anthropic
            except ImportError:
                receipt["executed"] = None
                receipt["outcome"] = "SDK anthropic non installato: pip install anthropic"
                print("Manca l'SDK: pip install anthropic")
                return
            try:
                client = anthropic.Anthropic()  # legge ANTHROPIC_API_KEY dall'ambiente
                t0 = time.perf_counter()
                resp = client.messages.create(model=pick["name"], max_tokens=tok_out,
                                              messages=[{"role": "user", "content": prompt}])
            except Exception as e:
                receipt["executed"] = None
                receipt["outcome"] = f"esecuzione cloud fallita: {e}"
                print(f"Chiamata cloud fallita (API key mancante o errore API): {e}")
                return
            wall = time.perf_counter() - t0
            text = "".join(b.text for b in resp.content if b.type == "text")
            usage = resp.usage
            cost = (usage.input_tokens / 1e6 * pick["price_in_usd_mtok"]
                    + usage.output_tokens / 1e6 * pick["price_out_usd_mtok"])
            receipt["executed"] = {"backend": f"cloud:{pick['name']}",
                                   "input_tokens": usage.input_tokens,
                                   "output_tokens": usage.output_tokens,
                                   "cost_usd": round(cost, 5),
                                   "wall_s": round(wall, 2),
                                   "preview": text[:200]}
            print(f"CLOUD {pick['name']}: {usage.output_tokens} token in {wall:.1f}s, "
                  f"~${cost:.4f}\n---\n{text[:400]}")
        else:
            receipt["executed"] = None
            receipt["outcome"] = f"provider {pick['provider']} non implementato in v0"
            print(f"Provider {pick['provider']} non implementato.")
        return

    # esecuzione locale
    res = run_ollama(local_pick, prompt, tok_out)
    receipt["executed"] = {"backend": f"local:{local_pick}", **{k: v for k, v in res.items() if k != "text"},
                           "preview": res["text"][:200]}
    print(f"LOCALE {local_pick}: {res['output_tokens']} token in {res['wall_s']}s "
          f"({res['tokens_per_s']} tok/s), costo marginale ~0\n---\n{res['text'][:400]}")


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

    pl = sub.add_parser("llm", help="generazione testo: LLM locale o API cloud")
    pl.add_argument("prompt", help="il prompt da eseguire")
    pl.add_argument("--objective", choices=["draft", "quality", "private"], default="draft")
    pl.add_argument("--max-out", type=int, default=512, help="token di output previsti")
    pl.add_argument("--allow-cloud", action="store_true")

    args = p.parse_args()

    receipt = {"router": "nox-router-v0.3", "task": args.task,
               "params": {k: v for k, v in vars(args).items() if k not in ("task", "prompt")},
               "started": datetime.now(timezone.utc).isoformat()}
    if args.task == "llm":
        receipt["prompt_chars"] = len(args.prompt)
    t0 = time.perf_counter()

    {"search": task_search, "bell": task_bell, "qrng": task_qrng,
     "llm": task_llm}[args.task](args, receipt)

    receipt["total_wall_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    RECEIPTS.mkdir(exist_ok=True)
    out = RECEIPTS / f"receipt_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{args.task}.json"
    out.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nScontrino: {out.relative_to(HERE)}")
    print(f"Scelto: {receipt.get('chosen') or 'nessun backend'}. {receipt.get('reason', '')}")


if __name__ == "__main__":
    main()
