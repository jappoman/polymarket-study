# Comandi rapidi

Dalla directory del repository:

```bash
./scripts/start_paper.sh
```

Su Windows PowerShell:

```powershell
.\scripts\start_paper.ps1
```

Il comando resta in primo piano: per interromperlo premi `Ctrl+C`. Per esempio,
per raccogliere dati per due ore:

```powershell
.\scripts\start_paper.ps1 -Duration 7200
```

Il comando include un supervisore: se il recorder termina con errore, viene
riavviato automaticamente in un nuovo file `live_*.jsonl`. Gli eventi di
riavvio sono registrati in `supervisor_*.log`.

Per una durata diversa, in secondi:

```bash
PAPER_DURATION=3600 ./scripts/start_paper.sh
```

Controllo dello stato:

```bash
./scripts/paper_status.sh
```

In PowerShell:

```powershell
.\scripts\paper_status.ps1
```

Ogni avvio crea un nuovo file `data/paper/live_*.jsonl`, quindi si può fermare
e riprendere la raccolta in sessioni diverse. Per unire tutte le sessioni:

```powershell
.\scripts\merge_paper.ps1
```

Il merge canonico include solo osservazioni Chainlink fresche (massimo 5 secondi
di ritardo) e rimuove i duplicati; i vecchi log Binance vengono lasciati fuori.

Le sessioni nuove registrano anche il book Polymarket "as-of": per ogni istante
X vengono conservati best ask/bid di Up e Down con timestamp non successivo a X,
oltre a size, range e variazione assoluta del TWAP Chainlink osservati fino a X.

Il file unito viene salvato in `data/paper/all_sessions.jsonl` e può poi essere
regolato con:

```powershell
.\scripts\settle_paper.ps1 data/paper/all_sessions.jsonl
```

Dopo la chiusura dei mercati, regola un log:

```bash
./scripts/settle_paper.sh data/paper/live_YYYY-MM-DDTHH-MM-SSZ.jsonl
```

Il paper-trader non effettua ordini reali e non richiede login.
Il segnale BTC principale viene dal TWAP Chainlink a 60 secondi trasmesso dal
feed pubblico RTDS di Polymarket; Binance non viene usato per decidere i trade.
Il timestamp numerico nello slug `btc-updown-5m-<timestamp>` indica l'inizio
del mercato; la chiusura è `start + 300` secondi.
All'avvio il recorder aspetta circa un minuto per costruire lo storico Chainlink
minimo necessario. L'attesa ha un limite di tre minuti: se il feed non è pronto,
il processo continua a ritentare senza salvare dati stantii e scrive heartbeat
di salute nel log.

Per eseguire insieme merge, settlement e analisi dei soli dati canonici:

```powershell
.\scripts\analyze_canonical.ps1
```

Se Gamma non ha ancora impostato `closed=true`, il settlement usa solo il
`close_snapshot` Chainlink canonico e applica la regola ufficiale `close TWAP >=
opening TWAP`; il risultato viene marcato come derivato.
