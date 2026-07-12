"""NOX Esperimento 004: l'agente quantistico (v0).

Pipeline: linguaggio naturale -> LLM Qiskit locale (RTX 5090, via Ollama)
-> codice Qiskit -> esecuzione sandbox -> validazione su simulatore
-> (opzionale) submit su QPU IBM reale.

L'agente ha un feedback loop: se il codice generato fallisce, rimanda
l'errore al modello e ritenta (max 2 round).

Uso:
  python quantum_agent.py "Create a 5-qubit GHZ state and measure all qubits"
  python quantum_agent.py --qpu "..."      # dopo il simulatore, invia anche alla QPU
"""
import json
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from qiskit import QuantumCircuit
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_aer import AerSimulator

HERE = Path(__file__).parent
OLLAMA = "http://localhost:11434/api/generate"
MODEL = "hf.co/Qiskit/Qwen2.5-Coder-14B-Qiskit-GGUF"
MAX_ROUNDS = 3

SYSTEM = ("You are a Qiskit coding assistant. Reply ONLY with Python code that "
          "builds the requested quantum circuit using qiskit. Assign the final "
          "circuit to a variable named qc. Include measurements. Do not run or "
          "transpile the circuit. No explanations.")

# Nota: denylist grezza, non e' un sandbox vero. Per codice generato da un
# modello Qiskit-only eseguito in locale e' sufficiente; se in futuro il
# codice arrivasse da fonti non fidate, va spostato in un subprocess isolato.
FORBIDDEN = ("import os", "import sys", "import subprocess", "open(", "exec(",
             "eval(", "__import__", "shutil", "requests", "urllib", "socket")


def ask_model(prompt: str) -> str:
    body = json.dumps({
        "model": MODEL,
        "system": SYSTEM,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0, "top_k": 1, "num_predict": 700},
    }).encode()
    req = urllib.request.Request(OLLAMA, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["response"]


def extract_code(text: str) -> str:
    blocks = re.findall(r"```(?:python)?\s*(.*?)```", text, re.S)
    return (blocks[0] if blocks else text).strip()


def run_code(code: str) -> QuantumCircuit:
    low = code.lower()
    for bad in FORBIDDEN:
        if bad in low:
            raise ValueError(f"codice rifiutato: contiene '{bad}'")
    ns: dict = {}
    exec(compile(code, "<agent>", "exec"), ns)  # noqa: S102
    circuits = [v for v in ns.values() if isinstance(v, QuantumCircuit)]
    if "qc" in ns and isinstance(ns["qc"], QuantumCircuit):
        qc = ns["qc"]
    elif circuits:
        qc = circuits[-1]
    else:
        raise ValueError("nessun QuantumCircuit prodotto")
    if not qc.num_clbits:
        qc.measure_all()
    return qc


def simulate(qc: QuantumCircuit) -> list:
    sim = AerSimulator()
    isa = generate_preset_pass_manager(backend=sim, optimization_level=1).run(qc)
    counts = sim.run(isa, shots=1024).result().get_counts()
    return sorted(counts.items(), key=lambda kv: -kv[1])[:6]


def judge(task: str, top: list) -> tuple[bool, str]:
    """Giudice semantico: la distribuzione simulata corrisponde al task?"""
    q = (f"A quantum circuit was requested for this task: \"{task}\".\n"
         f"Simulating it (1024 shots) gave these top outcomes: {top}.\n"
         f"Does this measured distribution match the requested state? "
         f"Think about which basis states the requested state should produce. "
         f"Answer with exactly VALID or INVALID followed by a one-line reason.")
    reply = ask_model(q).strip()
    ok = reply.upper().startswith("VALID") or " VALID" in reply.upper()[:40]
    if "INVALID" in reply.upper()[:40]:
        ok = False
    return ok, reply.splitlines()[0][:200]


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--qpu"]
    use_qpu = "--qpu" in sys.argv
    task = args[0] if args else "Create a 3-qubit GHZ state and measure all qubits"

    log = {"task": task, "model": MODEL, "started": datetime.now().isoformat(),
           "rounds": []}
    print(f"TASK: {task}\n")

    prompt, qc, top, verdict_ok = task, None, [], False
    for round_n in range(1, MAX_ROUNDS + 1):
        print(f"--- round {round_n}: interrogo il modello locale...")
        t0 = time.time()
        code = extract_code(ask_model(prompt))
        gen_s = time.time() - t0
        print(f"    generato in {gen_s:.1f}s ({len(code)} char)")
        rec = {"n": round_n, "gen_seconds": gen_s, "code": code}
        try:
            qc = run_code(code)
        except Exception as e:  # errore di esecuzione -> feedback
            print(f"    ERRORE ESECUZIONE: {e} | ritento col feedback")
            rec.update(ok=False, error=str(e))
            log["rounds"].append(rec)
            prompt = (f"{task}\n\nYour previous code:\n```python\n{code}\n```\n"
                      f"failed with error: {e}\nFix it. Reply only with the "
                      f"corrected Python code.")
            qc = None
            continue

        top = simulate(qc)
        print(f"    simulatore, top esiti: {top}")
        verdict_ok, why = judge(task, top)
        rec.update(ok=verdict_ok, sim_top=top, judge=why)
        log["rounds"].append(rec)
        if verdict_ok:
            print(f"    GIUDICE: VALID | {why}")
            break
        # errore semantico -> feedback al modello
        print(f"    GIUDICE: INVALID | {why} | ritento col feedback")
        prompt = (f"{task}\n\nYour previous code:\n```python\n{code}\n```\n"
                  f"executes but produces the WRONG state. Simulated outcomes: "
                  f"{top}. Judge verdict: {why}\n"
                  f"Write the CORRECT circuit for the task. Reply only with "
                  f"Python code.")
        qc = None

    if qc is None or not verdict_ok:
        log["outcome"] = "failed"
        (HERE / "agent_last_run.json").write_text(json.dumps(log, indent=2))
        sys.exit("L'agente non ha prodotto un circuito semanticamente valido.")

    print(f"\nCircuito approvato: {qc.num_qubits} qubit, depth {qc.depth()}")
    print(qc.draw(output="text"))
    log["simulator_counts_top"] = top

    # QPU reale (opzionale)
    if use_qpu:
        from qiskit_ibm_runtime import QiskitRuntimeService
        from qiskit_ibm_runtime import SamplerV2 as Sampler
        service = QiskitRuntimeService()
        backend = service.least_busy(simulator=False, operational=True)
        isa = generate_preset_pass_manager(backend=backend,
                                           optimization_level=1).run(qc)
        job = Sampler(mode=backend).run([isa], shots=2048)
        print(f"\nQPU: job {job.job_id()} inviato su {backend.name} (in coda)")
        log["qpu"] = {"backend": backend.name, "job_id": job.job_id()}

    log["outcome"] = "ok"
    out = HERE / f"agent_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(log, indent=2))
    (HERE / "agent_last_run.json").write_text(json.dumps(log, indent=2))
    print(f"\nLog: {out.name}")


if __name__ == "__main__":
    main()
