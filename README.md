# NOX Quantum Lab

Public, reproducible experiments on IBM's freely accessible quantum computers, run from a desk in Puglia, Italy, on the free open plan (10 minutes of QPU time per month).

Every claim in this repository comes with a date, an IBM job ID and raw data. The job IDs are the receipts of our runs; since IBM jobs are only visible to the account that submitted them, independent verification works the other way around: run the same scripts on your own free account and compare the numbers.

Website (Italian, with an English version): **[quantum.growtrend.uk](https://quantum.growtrend.uk)** · Public log of every run: [quantum.growtrend.uk/registro](https://quantum.growtrend.uk/registro/)

*Leggi il README in italiano: [README.it.md](README.it.md)*

## Results so far

| Date | Experiment | Machine | Result | Job ID |
|---|---|---|---|---|
| 2026-07-11 | First contact: 2-qubit Bell state | ibm_kingston | ZZ and XX correlations as expected, 14 s of QPU | `d9989u8tcv6s73dmvn40` |
| 2026-07-11 | CHSH (Bell test), raw counts, no mitigation | ibm_kingston | **S = 2.519 ± 0.024**, about 21 statistical standard deviations above the classical limit of 2 | `d9995mkqp3as739tr2rg` |
| 2026-07-11 | Grover search, 3 qubits, 2 iterations | ibm_kingston | target found in **75.7%** of 4,096 shots (single random guess: 12.5%, ideal: 94.5%) | `d9995mkqp3as739tr2rg` |
| 2026-07-12 | Observatory, monthly battery | ibm_fez | S = 2.544 ± 0.034, Grover 74.8%, GHZ-32 fidelity 39.1% | `d999tgif47jc73a8qlvg` |
| 2026-07-12 | Observatory, monthly battery | ibm_kingston | S = 2.571 ± 0.034, Grover 83.7%, GHZ-32 fidelity 52.1% | `d999thl2su3c739k6b60` |
| 2026-07-12 | Observatory, monthly battery | ibm_marrakesh | **S = 2.669 ± 0.033** (best of the month), Grover 72.5%, GHZ-32 fidelity 41.6% | `d999thd2su3c739k6b50` |
| 2026-07-12 | QRNG for the quantum coin flip | ibm_fez | 32,768 raw bits in 3 s (50.67% ones), 8,165 unbiased bits after von Neumann extraction | `d99mukif47jc73a9a0k0` |

Raw data for all of the above is in this repository (`observatory_2026-07.json`, `experiments_results.json`, `qrng_pool.json`, `agent_run_*.json`).

## What's in here

| File | What it does |
|---|---|
| `setup_account.py` | Saves your IBM Quantum API key to your local profile. Used once. |
| `hello_local.py` | The Bell-state hello world on the local Aer simulator. Zero quota. |
| `hello_qpu.py` | The same hello world on real hardware, following IBM's official guide. |
| `experiments.py` | The Report 001 battery: 4 CHSH circuits plus a 3-qubit Grover search, in a single job. Pass a job ID as argument to re-fetch an existing job at zero quota cost. |
| `observatory.py` | The monthly battery (CHSH, Grover, GHZ chains at 4/12/32 qubits) on all public IBM QPUs, submitted in parallel. Produces the JSON files behind the website. |
| `fetch_partial.py` | Rebuilds an observatory JSON from already-completed jobs, skipping the ones still queued. |
| `retrieve_job.py` | Fetches any job's status and results by ID. Works with both Estimator and Sampler jobs. |
| `quantum_agent.py` | Experiment 004: a local LLM (Qwen2.5-Coder-14B-Qiskit via Ollama) writes a circuit from a natural-language sentence, an execution sandbox and a semantic judge validate it on the simulator, and only approved circuits may reach the real QPU. |
| `nox_router.py` | NOX Router: given a task, decides between classical CPU, local simulator, real QPU and, for text generation, local LLM vs cloud API, explains the choice and writes a receipt. See below. |
| `router_config.json` | The router's price list: cloud model rates (dated; edit them when they change) and the local model preference order. |
| `qrng_submit.py` / `qrng_fetch.py` | Quantum random bits: 8 qubits in superposition measured 4,096 times, then debiased with the von Neumann extractor. Powers the coin-flip page on the website. |
| `make_charts_dark.py` | Renders the dark-theme charts used in the PDF report. |

## Reproduce it

1. Create a free IBM Quantum account at [quantum.cloud.ibm.com](https://quantum.cloud.ibm.com) (open plan, no credit card) and copy your API key.
2. Install the dependencies (Python 3.10+):

   ```
   pip install -r requirements.txt
   ```

3. Save your credentials once (they stay on your machine, in `~/.qiskit`):

   ```
   python setup_account.py YOUR_API_KEY
   ```

4. Run the experiments:

   ```
   python hello_local.py          # simulator only, zero quota
   python hello_qpu.py            # first contact with real hardware, ~15 s of quota
   python experiments.py          # the Report 001 battery, ~8 s of quota
   python observatory.py 2026-07  # the full monthly battery on 3 QPUs
   ```

   Jobs on the public queue can wait for hours. Every script saves its job ID immediately, and `retrieve_job.py <JOB_ID>` fetches the results later at no extra cost.

On Windows, prefix commands with `PYTHONIOENCODING=utf-8` (or set it in the environment): the default console code page chokes on some Unicode output.

## The agent (experiment 004)

`quantum_agent.py` implements a small but complete agentic workflow:

```
natural language -> local LLM writes the circuit -> sandboxed execution
-> Aer simulation -> semantic judge (same LLM, different question)
-> only if approved: real QPU
```

The interesting result is not the success (a 5-qubit GHZ state, correct on the first attempt in 6.8 s) but the failure: asked for a 3-qubit W state, the model produced code that ran fine yet built the wrong state, and the judge rejected it three times in a row. The agent gave up rather than send a wrong circuit to the hardware. Both runs are logged verbatim in `agent_run_20260712_*.json`.

A note on safety: the agent executes LLM-generated Python in-process behind a crude denylist, which is acceptable for a Qiskit-only model running on your own machine but is not a real sandbox. Treat it accordingly.

## NOX Router v0

The thesis of this lab is that the interesting engineering problem is not "can we run something on a QPU" (anyone can) but **where, when and whether a given computation is worth running**. The router is a first, deliberately small implementation of that idea:

```
python nox_router.py search --space 8 --target 101
# -> runs the exhaustive classical search (microseconds) and tells you why
#    using a QPU here would be marketing

python nox_router.py search --space 8 --target 101 --objective hardware-proof
# -> validates the Grover circuit on the simulator first (the gate),
#    then decides for the QPU, but does not spend quota without --allow-qpu

python nox_router.py bell                     # simulated CHSH statistics, with the caveat spelled out
python nox_router.py bell --objective certify --allow-qpu   # the real thing
python nox_router.py qrng --bits 128          # OS entropy, honestly labeled non-quantum
python nox_router.py qrng --bits 128 --objective quantum --allow-qpu
```

Since v0.2 the same pattern covers language models. The router discovers what is running on the local Ollama instance, estimates cloud costs from the dated price list in `router_config.json`, and applies the objective you declare:

```
python nox_router.py llm "Summarize this in three lines: ..." --objective draft
# -> runs on the local GPU model (marginal cost ~0) and says why paying
#    for a cloud API here would be wasted money

python nox_router.py llm "..." --objective quality --allow-cloud
# -> picks the top-tier cloud model with the estimated cost on the receipt;
#    without --allow-cloud it decides but refuses to spend

python nox_router.py llm "confidential text ..." --objective private
# -> local only; if no local model is available it stops rather than
#    sending the prompt to a third party
```

Cloud execution uses the official `anthropic` SDK (an optional dependency: `pip install anthropic`, with `ANTHROPIC_API_KEY` in the environment) and reports the real token counts and cost from the API response, not just the estimate. Token estimates for the decision step use a deliberately crude ~4 chars/token heuristic, labeled as such on the receipt.

Since v0.3 the receipts are also the router's memory. Before estimating, it re-reads `receipts/` and corrects its a-priori guesses with observed medians: the real tokens-per-second of each local model, the real dollar cost of past cloud calls. The more it runs, the better it estimates, and everything it has learned is inspectable in the `experience` block of every receipt. No database, no magic: just its own paper trail.

Every invocation writes a JSON receipt to `receipts/`: the candidates it considered, the estimated costs, the choice, the reason, and what was actually executed. Paid resources are never touched without an explicit flag: `--allow-qpu` for IBM Quantum quota, `--allow-cloud` for paid APIs. Example receipts from real runs are included.

## Honest limitations

- The 3-qubit Grover search is a demonstration that the algorithm works on hardware, not a speed advantage. A laptop checks all 8 possibilities faster than the job leaves the queue.
- The 21 sigma figure for the CHSH violation counts statistical sampling error only; device systematics are not independently characterized here.
- No error mitigation is applied anywhere in the observatory battery, on purpose: we measure the machines as they are.
- The CHSH test certifies the violation under the usual assumptions of trust in the device's basis settings; this is not a loophole-free Bell test.
- Job IDs prove that we ran what we say we ran; they are not independently browsable. Reproduction on your own account is the verification path.

## License

MIT. Built by [Valerio Bonetti](https://beezy.growtrend.uk) (beezy). Not affiliated with IBM; "IBM Quantum" is a service of IBM Corp. that anyone can use, which is rather the point.
