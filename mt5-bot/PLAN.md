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
     ├─ Marktdaten      Kerzen + Bid/Ask live oder aus CSV
     ├─ Sitzungen       Asien/London/New York, Sommerzeit, Broker-Serverzeit
     ├─ Strategie       London Breakout (austauschbar)
     ├─ Risiko          Lotgröße, Limits, Spread-Filter, Not-Aus
     ├─ Ausführung      simuliert (Backtest) | MT5 (live) – gleiche Schnittstelle
     ├─ Zustand         Abgleich mit MT5 nach jedem Start
     └─ Protokoll       Log, Trade-Tagebuch (CSV), Tagesbericht
```

Grundsatz wie bei barter-rs: **Backtest und Live laufen durch denselben Code**,
nur die Ausführung wird ausgetauscht. Was im Backtest funktioniert, ist genau
das, was live läuft.

## 3. Ordner und Bausteine

```
mt5-bot/
├─ Cargo.toml
├─ config.example.toml        Symbol, Risiko, Uhrzeiten, Strategie-Parameter
├─ src/
│  ├─ main.rs                 Befehle: backtest | live | selftest
│  ├─ data.rs                 CSV(.gz) laden, Lücken/Duplikate prüfen
│  ├─ session.rs              Zeitzonen, Sitzungen, Feiertage, Handelspausen
│  ├─ strategy/mod.rs         Strategie-Schnittstelle
│  ├─ strategy/london.rs      London Breakout
│  ├─ risk.rs                 Lotgröße, Tageslimits, Spread-Filter
│  ├─ broker/mod.rs           Ausführungs-Schnittstelle
│  ├─ broker/sim.rs           Simulation: Spread, Kommission, Slippage
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

## 4. Strategie zum Start: London Breakout auf Gold (5-Minuten-Kerzen)

Vorlage: London Breakout aus je-suis-tm/quant-trading und GOLD_ORB.
Alle Zahlen sind **Startwerte**, die der Backtest bestätigen oder ändern muss.

| Regel | Startwert |
| --- | --- |
| Spanne | Hoch/Tief der Asien-Sitzung, 00:00–07:00 London-Zeit |
| Spanne zu klein/groß | Tag auslassen, wenn Spanne < 0,5 × oder > 2 × ATR(Tag, 14) |
| Einstieg | erste 5-Min-Kerze, die über dem Hoch (Kauf) bzw. unter dem Tief (Verkauf) schließt, zwischen 07:00 und 10:00 London |
| Stop-Loss | Mitte der Spanne (wie beim Alpaca-Bot), mindestens 1 × Spread-Puffer |
| Take-Profit | +50 $ pro Trade (wie Alpaca-Bot) **oder** fest in R – der Backtest entscheidet |
| Pro Tag | höchstens 1 Trade je Richtung, höchstens 2 insgesamt |
| Schließen | spätestens 16:00 London, alles, was noch offen ist |
| Spread-Filter | kein Einstieg, wenn Spread > festgelegter Wert (z. B. 0,50 $) |

Weitere Strategien (Dual Thrust, New-York-Breakout, EUR/USD) erst, wenn diese
sauber läuft.

## 5. Risiko-Regeln (Demokonto, wie Alpaca-Bot)

- Max. Verlust pro Trade: **50 $** → Lotgröße = 50 $ / (Stop-Abstand × Kontraktgröße),
  abgerundet auf die Lot-Schrittweite des Brokers (Gold meist 100 oz pro Lot, 0,01 Lot Schritt)
- Max. Verlust pro Tag: **150 $**, danach keine neuen Trades
- Jede Order **immer** mit Stop-Loss und Take-Profit
- Not-Aus: Datei/Befehl `stop` → alles schließen, keine neuen Trades
- **Demo erzwungen**: Das System prüft über die Brücke den Kontotyp und
  verweigert ein Echtgeld-Konto, bis das ausdrücklich freigeschaltet wird.

## 6. Daten (PR „Gold-Daten“)

- Dukascopy XAU/USD, **5-Minuten-Kerzen, Juni 1999 bis heute**, eine gepackte
  CSV pro Jahr, als Download im Release `data-xauusd-m5` (nicht im Repo).
- Das sind Bid-Preise. Der Spread wird im Backtest **aufgeschlagen**
  (einstellbar, z. B. 0,30 $; für alte Jahre höher). Optional später auch
  Ask-Daten laden, um echte Spreads zu messen.
- Vorbehalt: Dukascopy-Kurse weichen leicht von denen deines MT5-Brokers ab.
  Für die Feinabstimmung exportieren wir später zusätzlich Kerzen direkt aus MT5.

## 7. Backtest: wie wir prüfen, ob es taugt

- Kosten immer eingerechnet: Spread, Kommission (falls Broker eine hat), Slippage beim Stop
- **Trennung der Daten**, damit wir uns nicht selbst betrügen:
  - 2004–2018: Regeln entwickeln und Parameter wählen
  - 2019–heute: **einmal** prüfen, ohne danach nachzubessern
  - zusätzlich Walk-Forward (jedes Jahr mit den Jahren davor eingestellt)
- Kennzahlen: Gewinn/Verlust, Anzahl Trades, Trefferquote, Ø R pro Trade,
  größter Rückgang (Drawdown), längste Verlustserie, Ergebnis pro Jahr
- **Weiter nur, wenn** (Go/No-Go):
  - Ø R pro Trade nach Kosten > 0 im Prüfzeitraum 2019–heute
  - mindestens 300 Trades insgesamt
  - größter Rückgang < 20 × Risiko pro Trade
  - nicht nur 1–2 gute Jahre, die alles tragen
- Ergebnis: Bericht mit Kurve und Jahrestabelle, bevor irgendetwas live geht

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
| 0 | Gold-Daten laden (PR #6) | alle Jahre 1999–2026 als Download, Kerzen geprüft | PR mergen |
| 1 | Rust-Kern: Daten, Sitzungen, Risiko, Strategie, Simulation, Backtest | Tests grün, Backtest läuft über alle Jahre | – |
| 2 | Backtest-Auswertung | Bericht + Go/No-Go-Entscheidung | deine Entscheidung |
| 3 | MQL5-Brücke + Live-Teil in Rust | Ablauf-Test mit simulierter Brücke grün | – |
| 4 | Einrichtung auf deinem Mac | Selbsttest: Kurse kommen an, Test-Order 0,01 Lot auf Demo klappt | MT5 Mac-App, Demokonto, ca. 30 Min |
| 5 | Demo-Betrieb | 4 Wochen laufen lassen, Tagesbericht, Vergleich mit Backtest | Mac in Handelszeit an |
| 6 | Später | Server statt Mac, mehr Strategien, Benachrichtigungen | – |

Jede Phase kommt als eigener Pull Request, den du vor dem Merge sehen kannst.

## 10. Grenzen und Risiken

- Ein guter Backtest ist **keine Garantie**. Gold verhält sich heute anders als 2005.
- Dukascopy-Daten ≠ Kurse deines Brokers (Spread, Serverzeit, Wochenend-Lücken).
- Mac muss während der Handelszeit (ca. 08:00–17:00 deutsche Zeit) an sein und
  darf nicht schlafen.
- MT5 auf dem Mac ist eine Windows-Version in einer Kompatibilitätsschicht;
  dass die Netzwerk-Brücke dort läuft, wird in Phase 4 geprüft.
- Forex/Gold-CFDs sind gehebelt: auf Echtgeld können Verluste schnell wachsen.
  Echtgeld ist **nicht Teil dieses Plans**.

## 11. Offene Entscheidungen

1. Strategie zum Start: London Breakout auf Gold – einverstanden?
2. Take-Profit: +50 $ fest (wie Alpaca) oder vom Backtest bestimmt?
3. Risiko: 50 $ pro Trade / 150 $ pro Tag auf Demo – einverstanden?
4. Broker für das MT5-Demokonto (für Phase 4; Kontraktgröße und Symbolname hängen davon ab)
