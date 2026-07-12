# NOX Quantum Lab

Esperimenti pubblici e riproducibili sui computer quantistici IBM accessibili a tutti, eseguiti da una scrivania in Puglia con il piano gratuito (10 minuti di QPU al mese).

Ogni affermazione in questo repository ha una data, un job ID IBM e i dati grezzi. I job ID sono le ricevute delle nostre esecuzioni; dato che i job IBM sono visibili solo all'account che li ha lanciati, la verifica indipendente funziona al contrario: esegui gli stessi script sul tuo account gratuito e confronta i numeri.

Sito (italiano, con versione inglese): **[quantum.growtrend.uk](https://quantum.growtrend.uk)** · Registro pubblico di ogni esecuzione: [quantum.growtrend.uk/registro](https://quantum.growtrend.uk/registro/)

*Read this in English: [README.md](README.md)*

## Risultati finora

| Data | Esperimento | Macchina | Risultato | Job ID |
|---|---|---|---|---|
| 2026-07-11 | Primo contatto: stato di Bell a 2 qubit | ibm_kingston | correlazioni ZZ e XX come attese, 14 s di QPU | `d9989u8tcv6s73dmvn40` |
| 2026-07-11 | CHSH (test di Bell), conteggi grezzi, zero mitigazione | ibm_kingston | **S = 2,519 ± 0,024**, circa 21 deviazioni standard statistiche sopra il limite classico 2 | `d9995mkqp3as739tr2rg` |
| 2026-07-11 | Ricerca di Grover, 3 qubit, 2 iterazioni | ibm_kingston | target trovato nel **75,7%** di 4.096 shot (tentativo a caso: 12,5%, ideale: 94,5%) | `d9995mkqp3as739tr2rg` |
| 2026-07-12 | Osservatorio, batteria mensile | ibm_fez | S = 2,544 ± 0,034, Grover 74,8%, fedeltà GHZ-32 39,1% | `d999tgif47jc73a8qlvg` |
| 2026-07-12 | Osservatorio, batteria mensile | ibm_kingston | S = 2,571 ± 0,034, Grover 83,7%, fedeltà GHZ-32 52,1% | `d999thl2su3c739k6b60` |
| 2026-07-12 | Osservatorio, batteria mensile | ibm_marrakesh | **S = 2,669 ± 0,033** (migliore del mese), Grover 72,5%, fedeltà GHZ-32 41,6% | `d999thd2su3c739k6b50` |
| 2026-07-12 | QRNG per le monete quantistiche | ibm_fez | 32.768 bit grezzi in 3 s (50,67% di 1), 8.165 bit puliti dopo l'estrattore di von Neumann | `d99mukif47jc73a9a0k0` |

I dati grezzi di tutto quanto sopra sono in questo repository (`observatory_2026-07.json`, `experiments_results.json`, `qrng_pool.json`, `agent_run_*.json`).

## Cosa c'è qui dentro

| File | Cosa fa |
|---|---|
| `setup_account.py` | Salva la tua API key IBM Quantum nel profilo locale. Si usa una volta. |
| `hello_local.py` | Lo stato di Bell "hello world" sul simulatore Aer locale. Zero quota. |
| `hello_qpu.py` | Lo stesso hello world su hardware reale, seguendo la guida ufficiale IBM. |
| `experiments.py` | La batteria del Report 001: 4 circuiti CHSH più una ricerca di Grover a 3 qubit, in un unico job. Con un job ID come argomento recupera un job esistente a costo zero. |
| `observatory.py` | La batteria mensile (CHSH, Grover, catene GHZ a 4/12/32 qubit) su tutte le QPU pubbliche IBM, inviata in parallelo. Produce i JSON dietro al sito. |
| `fetch_partial.py` | Ricostruisce un JSON dell'osservatorio dai job già completati, saltando quelli ancora in coda. |
| `retrieve_job.py` | Recupera stato e risultati di qualsiasi job per ID. Funziona sia con job Estimator sia Sampler. |
| `quantum_agent.py` | Esperimento 004: un LLM locale (Qwen2.5-Coder-14B-Qiskit via Ollama) scrive un circuito da una frase in linguaggio naturale, una sandbox di esecuzione e un giudice semantico lo validano sul simulatore, e solo i circuiti approvati possono raggiungere la QPU reale. |
| `nox_router.py` | NOX Router: dato un task, decide tra CPU classica, simulatore locale, QPU reale e, per la generazione di testo, LLM locale contro API cloud; spiega la scelta e scrive uno scontrino. Vedi sotto. |
| `router_config.json` | Il listino del router: tariffe dei modelli cloud (datate; aggiornale quando cambiano) e ordine di preferenza dei modelli locali. |
| `qrng_submit.py` / `qrng_fetch.py` | Bit casuali quantistici: 8 qubit in superposizione misurati 4.096 volte, poi ripuliti con l'estrattore di von Neumann. Alimentano la pagina delle monete sul sito. |
| `make_charts_dark.py` | Genera i grafici in tema scuro usati nel report PDF. |

## Riprodurre gli esperimenti

1. Crea un account IBM Quantum gratuito su [quantum.cloud.ibm.com](https://quantum.cloud.ibm.com) (piano open, nessuna carta) e copia la tua API key.
2. Installa le dipendenze (Python 3.10+):

   ```
   pip install -r requirements.txt
   ```

3. Salva le credenziali una volta sola (restano sulla tua macchina, in `~/.qiskit`):

   ```
   python setup_account.py LA_TUA_API_KEY
   ```

4. Lancia gli esperimenti:

   ```
   python hello_local.py          # solo simulatore, zero quota
   python hello_qpu.py            # primo contatto con l'hardware, ~15 s di quota
   python experiments.py          # la batteria del Report 001, ~8 s di quota
   python observatory.py 2026-07  # la batteria mensile completa su 3 QPU
   ```

   I job in coda pubblica possono aspettare ore. Ogni script salva subito il proprio job ID, e `retrieve_job.py <JOB_ID>` recupera i risultati in seguito senza costi aggiuntivi.

Su Windows, anteponi `PYTHONIOENCODING=utf-8` ai comandi (o impostalo nell'ambiente): la code page di default della console inciampa su alcuni caratteri Unicode.

## L'agente (esperimento 004)

`quantum_agent.py` implementa un workflow agentico piccolo ma completo:

```
linguaggio naturale -> LLM locale scrive il circuito -> esecuzione in sandbox
-> simulazione Aer -> giudice semantico (stesso LLM, domanda diversa)
-> solo se approvato: QPU reale
```

Il risultato interessante non è il successo (uno stato GHZ a 5 qubit, corretto al primo tentativo in 6,8 s) ma il fallimento: alla richiesta di uno stato W a 3 qubit, il modello ha prodotto codice che girava bene ma costruiva lo stato sbagliato, e il giudice lo ha bocciato tre volte di fila. L'agente ha rinunciato piuttosto che mandare un circuito sbagliato all'hardware. Entrambe le run sono nei log `agent_run_20260712_*.json`, parola per parola.

Una nota di sicurezza: l'agente esegue Python generato dall'LLM nello stesso processo, dietro una denylist grezza. Per un modello Qiskit-only che gira sulla tua macchina va bene, ma non è una vera sandbox. Trattalo di conseguenza.

## NOX Router v0

La tesi di questo laboratorio è che il problema ingegneristico interessante non sia "riusciamo a far girare qualcosa su una QPU" (chiunque può) ma **dove, quando e se una certa computazione conviene**. Il router è una prima implementazione, volutamente piccola, di quest'idea:

```
python nox_router.py search --space 8 --target 101
# -> esegue la ricerca esaustiva classica (microsecondi) e ti dice perché
#    usare una QPU qui sarebbe marketing

python nox_router.py search --space 8 --target 101 --objective hardware-proof
# -> prima valida il circuito di Grover sul simulatore (il gate),
#    poi decide per la QPU, ma non spende quota senza --allow-qpu

python nox_router.py bell                     # statistiche CHSH simulate, con l'avvertenza esplicita
python nox_router.py bell --objective certify --allow-qpu   # quella vera
python nox_router.py qrng --bits 128          # entropia del sistema operativo, etichettata onestamente come non quantistica
python nox_router.py qrng --bits 128 --objective quantum --allow-qpu
```

Dalla v0.2 lo stesso pattern copre i modelli di linguaggio. Il router scopre cosa gira sull'istanza Ollama locale, stima i costi cloud dal listino datato in `router_config.json` e applica l'obiettivo che dichiari:

```
python nox_router.py llm "Riassumi in tre righe: ..." --objective draft
# -> esegue sul modello locale della GPU (costo marginale ~0) e ti dice
#    perché pagare un'API cloud qui sarebbe denaro sprecato

python nox_router.py llm "..." --objective quality --allow-cloud
# -> sceglie il modello cloud di fascia alta con il costo stimato sullo
#    scontrino; senza --allow-cloud decide ma si rifiuta di spendere

python nox_router.py llm "testo riservato ..." --objective private
# -> solo locale; se nessun modello locale è disponibile si ferma invece
#    di mandare il prompt a terzi
```

L'esecuzione cloud usa l'SDK ufficiale `anthropic` (dipendenza opzionale: `pip install anthropic`, con `ANTHROPIC_API_KEY` nell'ambiente) e riporta sullo scontrino i conteggi token e il costo reali dalla risposta dell'API, non solo la stima. Le stime token per la fase di decisione usano un'euristica volutamente grezza (~4 caratteri per token), dichiarata come tale sullo scontrino.

Dalla v0.3 gli scontrini sono anche la memoria del router. Prima di stimare, rilegge `receipts/` e corregge le ipotesi a priori con le mediane osservate: i token al secondo reali di ogni modello locale, il costo in dollari reale delle chiamate cloud passate. Più gira, meglio stima, e tutto ciò che ha imparato è ispezionabile nel blocco `experience` di ogni scontrino. Niente database, niente magia: solo la sua stessa carta straccia.

Dalla v0.4 il router guarda anche le code: ogni volta che la decisione cade sulla QPU, controlla prima le code reali di tutti i backend pubblici (chiamata di sola lettura, zero quota) e mette i conteggi dei job in attesa sullo scontrino. Non inventa un tempo di attesa preciso, perché non esiste: lo scontrino riporta i conteggi e l'osservazione onesta che i nostri job hanno aspettato da pochi minuti a una notte intera.

Ogni invocazione scrive uno scontrino JSON in `receipts/`: i candidati considerati, le stime di costo, la scelta, il motivo e cosa è stato eseguito davvero. Le risorse a pagamento non vengono mai toccate senza un flag esplicito: `--allow-qpu` per la quota IBM Quantum, `--allow-cloud` per le API a pagamento. Nel repository ci sono scontrini di esempio da esecuzioni reali.

## Limiti, detti chiaramente

- La ricerca di Grover a 3 qubit dimostra che l'algoritmo funziona su hardware, non un vantaggio di velocità. Un laptop controlla tutte e 8 le possibilità prima che il job esca dalla coda.
- Le 21 sigma della violazione CHSH contano il solo errore statistico di campionamento; le sistematiche del dispositivo non sono caratterizzate indipendentemente qui.
- Nessuna mitigazione d'errore in tutta la batteria dell'osservatorio, di proposito: misuriamo le macchine così come sono.
- Il test CHSH certifica la violazione sotto le consuete assunzioni di fiducia nelle basi di misura del dispositivo; non è un test di Bell loophole-free.
- I job ID provano che abbiamo eseguito ciò che diciamo; non sono consultabili da terzi. La strada per la verifica è riprodurre sul proprio account.

## Licenza

MIT. Costruito da [Valerio Bonetti](https://beezy.growtrend.uk) (beezy). Nessuna affiliazione con IBM; "IBM Quantum" è un servizio di IBM Corp. che chiunque può usare, ed è proprio questo il punto.
