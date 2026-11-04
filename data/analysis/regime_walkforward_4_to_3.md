# BTC Up/Down 5m — regime walk-forward

## Regola selezionata

- osservazione a 90 secondi dall'inizio del mercato;
- usare il rendimento del minuto BTC precedente, già chiuso e quindi disponibile;
- entrare solo se il suo valore assoluto è almeno `0.0002` (0,02%);
- entrare nella direzione del movimento precedente;
- richiedere che il movimento precedente e il movimento BTC dall'inizio del round abbiano lo stesso segno;
- prezzo osservato della share + haircut conservativo di `0.04`;
- scartare prezzi stressati oltre `0.55`;
- sottrarre `0.01` per operazione.

I parametri sono stati scelti soltanto sui primi quattro periodi cronologici. Gli ultimi tre sono out-of-sample.

## Risultato

| Periodo | Operazioni | Win rate | PnL per stake unitario |
|---|---:|---:|---:|
| 2026-10-11/17 | 73 | 69,86% | +31,23 |
| 2026-10-18/24 | 108 | 72,22% | +51,53 |
| 2026-10-25/11-03 | 133 | 58,65% | +26,11 |
| **Totale OOS** | **314** | **65,92%** | **+108,87** |

Il confronto OOS con il gruppo che presenta segno opposto è 207/314 vittorie (65,92%) contro 138/271 (50,92%); z-test per due proporzioni: circa 3,68.

Una griglia di 8.640 combinazioni (sei tempi, quattro segnali, tre regimi e diverse soglie/cap) ha selezionato esattamente questa regola usando solo i primi quattro periodi, con criterio maximin sul PnL dei periodi. Un test di permutazione che rimescola gli outcome all'interno di ciascun periodo ha dato, su 5.000 simulazioni, nessuna simulazione con PnL almeno pari al risultato osservato, sia su tutti i periodi sia sul solo blocco OOS. È un controllo diagnostico, non una garanzia: la selezione della griglia introduce comunque rischio di data mining.

## Limitazioni

Il PnL è ancora un backtest su prezzo osservato, non una simulazione completa dell'esecuzione su best ask, slippage, latenza e liquidità disponibile. Non è una garanzia di profitto. Prima di usare capitale reale servono dati L2 sincronizzati e un periodo paper-trading prospettico.
