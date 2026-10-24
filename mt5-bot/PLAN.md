# Plan: Rust-Trading-System für MetaTrader 5 (Gold)

Stand: 24.10.2026. Dieser Plan wird vor dem ersten Code abgestimmt.

## 1. Ziel

Ein eigenständiges Trading-System in **Rust**, das auf einem **MT5-Demokonto**
**Gold (XAU/USD)** handelt, auf deinem **MacBook** läuft und vorher an über
25 Jahren Kursdaten getestet wird. Getrennt vom Alpaca-Bot (eigener Ordner
`mt5-bot/`, eigene Branches). Kein echtes Geld, bis die Tests das rechtfertigen.

## 2. Aufbau

```
MacBook
├─ MetaTrader 5 (Mac-App, Demokonto)
│    └─ MQL5-Brücke (Expert Advisor "RustBridge")
│              ▲   JSON-Nachrichten über TCP, nur 127.0.0.1
│              ▼
└─ mt5-bot (Rust)
     ├─ Marktdaten      Ticks + Kerzen (Bid/Ask) live oder aus CSV
     ├─ Sitzungen       Asien/London/New York, Sommerzeit, Broker-Serverzeit
     ├─ Strategie       Scalping-Ansätze (austauschbar)
     ├─ Risiko          Lotgröße, Limits, Spread-Filter, Not-Aus
     ├─ Ausführung      simuliert (Backtest) | MT5 (live) – gleiche Schnittstelle
     ├─ Zustand         Abgleich mit MT5 nach jedem Start
     └─ Protokoll       Log, Trade-Tagebuch (CSV), Tagesbericht
```

**Rust steuert das komplette System.** Jede Entscheidung fällt in Rust:
Daten auswerten, Signal, Lotgröße, Limits, Einstieg, Ausstieg, Not-Aus,
Abgleich nach Neustart. Die MQL5-Brücke enthält **keine Handelslogik**; sie ist
nur der Bote, der Kurse an Rust schickt und Rusts Befehle 1:1 an MT5 weitergibt,
weil MT5 Orders nur aus dem Terminal heraus annimmt. Das ganze System ist Rust;
einzige Ausnahme ist das einmalige Laden der Gold-Daten (Werkzeug in Node.js,
läuft nur auf GitHub).

Grundsatz wie bei barter-rs: **Backtest und Live laufen durch denselben Code**,
nur die Ausführung wird ausgetauscht. Was im Backtest funktioniert, ist genau
das, was live läuft.

Zur Geschwindigkeit: Bei vielen kleinen Trades zählt sie. Rust entscheidet in
Mikrosekunden und verarbeitet jeden Tick sofort; die Strecke Rust → MT5 →
Broker dauert Millisekunden (lokal über TCP, die Brücke reagiert auf jeden Tick,
nicht im Sekundentakt). Den größten Teil der Verzögerung macht der Broker – das
bildet der Backtest ab. Dazu kommt **Zuverlässigkeit**: strenge Typen für Preise,
Lots und Zeiten fangen die Fehler ab, die beim Traden am meisten kosten.

## 3. Ordner und Bausteine

```
mt5-bot/
├─ Cargo.toml
├─ config.example.toml        Symbol, Risiko, Uhrzeiten, Strategie-Parameter
├─ src/
│  ├─ main.rs                 Befehle: backtest | live | selftest
│  ├─ data.rs                 Kerzen + Ticks (CSV.gz) laden, Lücken/Duplikate prüfen
│  ├─ session.rs              Zeitzonen, Sitzungen, Feiertage, Handelspausen
│  ├─ strategy/mod.rs         Strategie-Schnittstelle
│  ├─ strategy/breakout.rs    Mikro-Ausbruch zur Sitzungseröffnung
│  ├─ strategy/meanrev.rs     Rückkehr zum Mittelwert
│  ├─ strategy/momentum.rs    Momentum-Fortsetzung
│  ├─ risk.rs                 Lotgröße, Tageslimits, Spread-Filter
│  ├─ broker/mod.rs           Ausführungs-Schnittstelle
│  ├─ broker/sim.rs           Simulation auf Ticks: Bid/Ask, Kommission, Verzögerung
│  ├─ broker/mt5.rs           Verbindung zur MQL5-Brücke
│  ├─ backtest.rs             Lauf über historische Kerzen + Kennzahlen
│  └─ journal.rs              Trade-Tagebuch, Tagesbericht
├─ tests/                     Ablauf-Tests mit simulierter Brücke
└─ mql5/RustBridge.mq5        Expert Advisor für MT5
```

Rust-Bibliotheken: `tokio` (Netzwerk), `serde`/`serde_json` (Nachrichten),
`chrono` + `chrono-tz` (Zeitzonen), `rust_decimal` (exakte Preise),
`csv` + `flate2` (Daten), `ta` oder eigene Funktionen (ATR, EMA),
`clap` (Befehle), `tracing` (Log).

## 4. Strategie: viele kleine Trades (Scalping) auf Gold

Ziel ist **viel Handel mit kleinen Gewinnen und kleinen Verlusten** statt
weniger großer Trades. Dafür gilt eine harte Wahrheit: **die Kosten entscheiden**.
Jeder Trade zahlt den Spread (Gold oft 0,10–0,30 $ pro Unze) plus evtl.
Kommission. Ein Scalp, der auf 1 $ Bewegung zielt, verliert bei 0,25 $ Spread
schon ein Viertel. Deshalb:

- Entscheidungen auf **1-Minuten-Kerzen und Ticks**, nicht auf 5 Minuten
- Backtest **immer mit echtem Spread** (Bid und Ask getrennt geladen)
- nur handeln, wenn Spread und Bewegung zusammenpassen
  (erwartete Bewegung ≥ mehrfacher Spread)

Mehrere Scalping-Ansätze werden im Backtest gegeneinander geprüft; nur was nach
Kosten im Plus bleibt, kommt weiter:

| Ansatz | Idee | Wann |
| --- | --- | --- |
| Mikro-Ausbruch zur Sitzungseröffnung | Ausbruch aus der Spanne der letzten 15–30 Min bei London- und New-York-Eröffnung, kurzes Ziel | 07:00–10:00 und 13:30–16:00 London |
| Rückkehr zum Mittelwert | Kurs weit vom kurzen Mittel (VWAP/EMA, Bollinger) in ruhigen Phasen → Gegenbewegung | ruhige Sitzungsteile, kein Trend |
| Momentum-Fortsetzung | starker Impuls (z. B. 3 Kerzen gleiche Richtung + Volumen) → kurzes Mitlaufen | nur bei engem Spread |

Gemeinsame Regeln (Startwerte, der Backtest stellt sie ein):

| Regel | Startwert |
| --- | --- |
| Ziel pro Trade | klein, z. B. 1–1,5 × Risiko, oder fester Dollarbetrag |
| Stop-Loss | eng, an der Volatilität (ATR auf 1 Min) ausgerichtet, nie fehlend |
| Max. Haltedauer | z. B. 30 Minuten, dann schließen |
| Trades pro Tag | z. B. bis 20–40 |
| Spread-Filter | kein Einstieg, wenn Spread > Grenze (z. B. 0,35 $) |
| Nachrichten | 15 Min vor/nach wichtigen US-Daten (Arbeitsmarkt, Inflation, Zinsentscheid) nicht handeln |
| Handelszeit | nur London- und New-York-Sitzung, nicht in der dünnen Nacht |

## 5. Risiko-Regeln (Demokonto)

- Max. Verlust pro Trade: **kleiner als beim Alpaca-Bot**, Startwert **10 $**
  → Lotgröße = 10 $ / (Stop-Abstand × Kontraktgröße), abgerundet auf die
  Lot-Schrittweite (Gold meist 100 oz pro Lot, 0,01 Lot Schritt).
  Achtung: Bei sehr engen Stops kann schon 0,01 Lot mehr als 10 $ riskieren –
  dann wird der Trade ausgelassen, nicht vergrößert.
- Max. Verlust pro Tag: **150 $**, danach Schluss für den Tag
- Max. Verlustserie: nach z. B. 6 Verlusten in Folge 1 Stunde Pause
- Höchstens 1 offene Position gleichzeitig (später evtl. mehr)
- Jede Order **immer** mit Stop-Loss und Take-Profit
- Not-Aus: Befehl `stop` → alles schließen, keine neuen Trades
- **Demo erzwungen**: Das System prüft über die Brücke den Kontotyp und
  verweigert ein Echtgeld-Konto, bis das ausdrücklich freigeschaltet wird.

## 6. Daten (PR „Gold-Daten“)

Zwei Läufe des Workflows, beide als Download im Repo-Release (nicht im Code):

| Lauf | Was | Zeitraum | Wofür |
| --- | --- | --- | --- |
| 1 | **1-Minuten-Kerzen, Bid und Ask** | Juni 1999 – heute | Strategien entwickeln, Spread aus Ask − Bid |
| 2 | **Ticks** (jede Preisänderung, Bid + Ask) | 2023 – heute | realistische Prüfung: Ausführung, Spread, Slippage |

- Quelle: Dukascopy (kostenlos). Größe grob: Kerzen einige hundert MB gepackt,
  Ticks einige GB – passt in Releases (max. 2 GB pro Datei, Ticks je Monat).
- Vorbehalt: Dukascopy-Kurse und -Spreads weichen von denen deines MT5-Brokers
  ab. In Phase 4 messen wir den echten Spread des Brokers und stellen den
  Backtest darauf ein.

## 7. Backtest: wie wir prüfen, ob es taugt

- **Tick-genaue Simulation** für die letzten Jahre: Einstieg zum Ask (Kauf)
  bzw. Bid (Verkauf), Stop/Ziel werden an echten Ticks ausgelöst, plus
  Verzögerung (z. B. 100–300 ms) und Kommission des Brokers
- Kerzen-Simulation für die lange Historie (schneller, etwas ungenauer)
- **Trennung der Daten**, damit wir uns nicht selbst betrügen:
  - 2004–2018 (Kerzen): Regeln entwickeln, Parameter wählen
  - 2019–2022 (Kerzen): erste Prüfung
  - 2023–heute (Ticks): **einmal** prüfen, ohne danach nachzubessern
  - zusätzlich Walk-Forward
- Kennzahlen: Ergebnis nach Kosten, Anzahl Trades, Trefferquote, Ø Gewinn/Verlust,
  **Kosten-Anteil** (wie viel vom Bruttogewinn der Spread frisst), Drawdown,
  längste Verlustserie, Ergebnis pro Jahr und pro Uhrzeit
- **Weiter nur, wenn** (Go/No-Go):
  - im Tick-Test 2023–heute nach allen Kosten im Plus
  - mindestens 2.000 Trades (bei vielen kleinen Trades nötig für Aussagekraft)
  - Spread frisst weniger als die Hälfte des Bruttogewinns
  - größter Rückgang < 30 × Risiko pro Trade
  - nicht nur einzelne Monate, die alles tragen
- Ergebnis: Bericht mit Kurve, Monats- und Uhrzeit-Tabelle, bevor etwas live geht

## 8. MQL5-Brücke (Expert Advisor)

- Läuft auf einem Gold-Chart in MT5, verbindet sich zu `127.0.0.1:<Port>`
- Sendet: neue Kerzen, Bid/Ask, Kontostand, Kontotyp (Demo/Live), offene Positionen, Order-Ergebnisse
- Empfängt: Order eröffnen (mit SL/TP), schließen, alles schließen
- Herzschlag alle paar Sekunden; ohne Verbindung keine neuen Orders
- Eigene „Magic Number“, damit nur die Trades des Bots angefasst werden
- Einrichtung auf dem Mac: EA kopieren, „Algo Trading“ einschalten,
  `127.0.0.1` in den Optionen für Netzwerkzugriffe erlauben (Anleitung folgt)

## 9. Phasen

| Phase | Inhalt | Ergebnis / fertig, wenn | Brauche von dir |
| --- | --- | --- | --- |
| 0 | Gold-Daten laden (PR #6): 1-Min-Kerzen 1999–heute, Ticks 2023–heute | alles als Download, Daten geprüft | PR mergen |
| 1 | Rust-Kern: Daten (Kerzen + Ticks), Sitzungen, Risiko, Scalping-Strategien, Tick-Simulation, Backtest | Tests grün, Backtest läuft über alle Daten | – |
| 2 | Backtest-Auswertung | Bericht + Go/No-Go-Entscheidung | deine Entscheidung |
| 3 | MQL5-Brücke + Live-Teil in Rust | Ablauf-Test mit simulierter Brücke grün | – |
| 4 | Einrichtung auf deinem Mac | Selbsttest: Kurse kommen an, Test-Order 0,01 Lot auf Demo klappt | MT5 Mac-App, Demokonto, ca. 30 Min |
| 5 | Demo-Betrieb | 4 Wochen laufen lassen, Tagesbericht, Vergleich mit Backtest | Mac in Handelszeit an |
| 6 | Später | Server statt Mac, mehr Strategien, Benachrichtigungen | – |

Jede Phase kommt als eigener Pull Request, den du vor dem Merge sehen kannst.

## 10. Grenzen und Risiken

- Ein guter Backtest ist **keine Garantie**. Gold verhält sich heute anders als 2005.
- Scalping ist die Strategie-Art, bei der die meisten Systeme nach Kosten
  verlieren. Gut möglich, dass der Backtest „No-Go“ sagt – dann ist das ein
  Ergebnis, kein Fehler.
- Demokonten führen Orders oft besser aus als echte Konten (keine echte
  Liquidität); Scalping-Ergebnisse auf Demo sind deshalb eher zu optimistisch.
- Dukascopy-Daten ≠ Kurse deines Brokers (Spread, Serverzeit, Wochenend-Lücken).
- Mac muss während der Handelszeit (ca. 08:00–18:00 deutsche Zeit) an sein und
  darf nicht schlafen.
- MT5 auf dem Mac ist eine Windows-Version in einer Kompatibilitätsschicht;
  dass die Netzwerk-Brücke dort läuft, wird in Phase 4 geprüft.
- Forex/Gold-CFDs sind gehebelt: auf Echtgeld können Verluste schnell wachsen.
  Echtgeld ist **nicht Teil dieses Plans**.

## 11. Offene Entscheidungen

1. Scalping auf Gold mit den drei Ansätzen oben – einverstanden?
2. Wie viele Trades pro Tag ungefähr gewünscht (z. B. 10, 20, 40)?
3. Risiko: 10 $ pro Trade / 150 $ pro Tag auf Demo – einverstanden?
4. Broker für das MT5-Demokonto (für Phase 4; Kontraktgröße und Symbolname hängen davon ab)
