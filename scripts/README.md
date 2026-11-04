# Comandi rapidi

Dalla directory del repository:

```bash
./scripts/start_paper.sh
```

Per una durata diversa, in secondi:

```bash
PAPER_DURATION=3600 ./scripts/start_paper.sh
```

Controllo dello stato:

```bash
./scripts/paper_status.sh
```

Dopo la chiusura dei mercati, regola un log:

```bash
./scripts/settle_paper.sh data/paper/live_YYYY-MM-DDTHH-MM-SSZ.jsonl
```

Il paper-trader non effettua ordini reali e non richiede login.
