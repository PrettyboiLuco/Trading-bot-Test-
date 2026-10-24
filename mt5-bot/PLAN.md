# Plan: Rust-Trading-System für MetaTrader 5 (Gold)

Stand: 24.10.2026. Dieser Plan wird abgestimmt, bevor Code entsteht.
Jede Phase kommt als eigener Pull Request, den du vor dem Merge siehst.

## 1. Ziel

Ein eigenständiges Trading-System in **Rust**, das auf einem **MT5-Demokonto**
**Gold (XAU/USD)** handelt und auf deinem **MacBook** läuft. Zwei Strategien
laufen parallel; beide werden vorher an über 20 Jahren Gold-Daten getestet.
Getrennt vom Alpaca-Bot (eigener Ordner `mt5-bot/`). **Kein echtes Geld** in
diesem Plan.

## 2. Herkunft der Idee

Video von @florian.hilger (TikTok), der 40 Varianten auf Nasdaq-Futures
2022–2026 getestet hat:

| Rang | Strategie | Gewinn nach Modellkosten | größter Rückgang | Trades |
| --- | --- | --- | --- | --- |
| 1 | EMA 20 kreuzt Wochen-VWAP, 15 Min | +174,9 % | −16,3 % | 832 |
| 2 | Opening Range Breakout | +12,0 % | −21,6 % | – |

Sein eigener Hinweis: *„Rückblickend ausgewählt. Auf neuen Daten noch
unbestätigt.“* Genau das holen wir nach: anderer Markt (Gold), viel längerer
Zeitraum, und eine Prüfung auf Jahren, die bei der Auswahl nicht benutzt wurden.

Verworfene Ideen (zur Erinnerung): Trades von 1 Sekunde Dauer und reines
Scalping – bei Gold frisst der Spread (0,10–0,30 $) in so kurzer Zeit den
Gewinn, und über MT5 vom Mac sind wir zu langsam gegen professionelle
Hochfrequenz-Händler.

## 3. Die zwei Strategien

### Strategie 1: EMA kreuzt VWAP (Hauptstrategie)

| Regel | Wert |
| --- | --- |
| Signal Long | EMA kreuzt den VWAP von unten nach oben |
| Signal Short | EMA kreuzt den VWAP von oben nach unten |
| Bestätigung | Kerze mit dem Kreuz muss geschlossen sein |
| Einstieg | Eröffnung der nächsten Kerze |
| Stop-Loss | 1,5 × ATR(14) vom Einstieg |
| Take-Profit | 2 × Stop-Abstand (2R) |
| Risiko | 1 % des Kontos pro Trade |
| Gegensignal | neues Kreuz in Gegenrichtung schließt den offenen Trade (im Backtest prüfen: ja/nein) |

Getestet werden alle **40 Kombinationen** wie im Video:
- EMA-Länge: 5 Werte (z. B. 9, 20, 50, 100, 200)
- VWAP: Tages-VWAP (Start 00:00 Serverzeit) oder Wochen-VWAP (Start Wochenöffnung)
- Zeitrahmen: 5, 15, 30, 60 Minuten

Erwartung vorab (nicht Ziel): EMA 20 + Wochen-VWAP auf 15 Minuten, wie im Video.

### Strategie 2: Opening Range Breakout (Vergleich)

Gold hat keine einzelne Börseneröffnung; wir nehmen die zwei wichtigsten
Sitzungsstarts und testen beide:

| Regel | Wert |
| --- | --- |
| Spanne | erste 15 bzw. 30 Minuten nach London-Start (08:00 London) bzw. New-York-Start (09:30 New York) |
| Einstieg | erste Kerze, die über dem Hoch (Long) / unter dem Tief (Short) schließt |
| Stop-Loss | Mitte der Spanne (wie Alpaca-Bot) oder 1,5 × ATR(14) – Backtest entscheidet |
| Take-Profit | 2R |
| Pro Sitzung | höchstens 1 Trade |
| Schließen | spätestens zum Ende der Sitzung |
| Risiko | 1 % pro Trade |

### Für beide gilt

- Jede Order **immer** mit Stop-Loss und Take-Profit
- Kein Einstieg, wenn der Spread über einer Grenze liegt (z. B. 0,50 $)
- Kein neuer Einstieg 15 Min vor/nach wichtigen US-Daten (Arbeitsmarkt, Inflation, Zinsentscheid) – im Backtest prüfen, ob das hilft
- Eigene **Magic Number** je Strategie (1001 = EMA/VWAP, 1002 = ORB), damit Trades und Ergebnisse getrennt bleiben

## 4. Risiko-Regeln (gemeinsam)

- **1 % des Kontos pro Trade**. Lotgröße = Risiko in $ / (Stop-Abstand × Kontraktgröße),
  abgerundet auf die Lot-Schrittweite des Brokers (Gold meist 100 oz pro Lot, 0,01 Lot).
  Wäre selbst 0,01 Lot zu groß, wird der Trade ausgelassen, nicht vergrößert.
- **Tageslimit:** −3 % → keine neuen Trades bis zum nächsten Tag
- **Höchstens 1 offene Position je Strategie**, gemeinsames Gesamtrisiko max. 2 %
- **Not-Aus:** Befehl `stop` → alles schließen, keine neuen Trades
- **Demo erzwungen:** Das System fragt über die Brücke den Kontotyp ab und
  verweigert ein Echtgeld-Konto, bis das ausdrücklich freigeschaltet wird.

## 5. Aufbau

```
Dein MacBook
├─ MetaTrader 5 (Mac-App, Demokonto, Gold-Chart)
│    ├─ RustBridge (Expert Advisor): schickt Kurse/Konto an Rust,
│    │   führt Rusts Befehle 1:1 aus – keine eigene Handelslogik
│    └─ Anzeige-Indikator: zeichnet EMA, VWAP und Eröffnungsspannen in den Chart
│              ▲   JSON über TCP, nur innerhalb des Macs (127.0.0.1)
│              ▼
└─ mt5-bot (Rust) – steuert das komplette System
     ├─ Marktdaten       Kerzen + Bid/Ask live (MT5) oder aus CSV (Backtest)
     ├─ Indikatoren      EMA, VWAP (Tag/Woche), ATR, Eröffnungsspanne
     ├─ Sitzungen        London/New York, Sommerzeit, Broker-Serverzeit
     ├─ Strategien       EMA/VWAP-Kreuz, Opening Range Breakout
     ├─ Risiko           Lotgröße, Limits, Spread-Filter, Not-Aus
     ├─ Ausführung       simuliert (Backtest) | MT5 (live) – gleiche Schnittstelle
     ├─ Zustand          Abgleich mit MT5 nach jedem Start
     └─ Bericht          Trade-Tagebuch, Tagesbericht, Upload zu GitHub
```

**Rust trifft jede Entscheidung**; die MT5-Brücke ist nur der Bote, weil MT5
Orders nur aus dem Terminal heraus annimmt. Backtest und Live laufen durch
**denselben Code** – nur die Ausführung wird ausgetauscht.

### Ordner

```
mt5-bot/
├─ Cargo.toml
├─ config.example.toml        Symbol, Risiko, Zeiten, Strategie-Parameter
├─ src/
│  ├─ main.rs                 Befehle: backtest | sweep | live | selftest | stop
│  ├─ data.rs                 Kerzen laden (CSV.gz), 1 Min → 5/15/30/60 Min umrechnen
│  ├─ indicators.rs           EMA, VWAP (Tag/Woche), ATR
│  ├─ session.rs              Zeitzonen, Sitzungen, Wochenende, Feiertage
│  ├─ strategy/ema_vwap.rs    Strategie 1
│  ├─ strategy/orb.rs         Strategie 2
│  ├─ risk.rs                 Lotgröße, Limits, Spread-Filter
│  ├─ broker/sim.rs           Simulation: Spread, Kommission, Slippage
│  ├─ broker/mt5.rs           Verbindung zur Brücke
│  ├─ backtest.rs             Lauf + Kennzahlen
│  ├─ sweep.rs                alle Kombinationen testen, Rangliste
│  └─ journal.rs              Tagebuch, Tagesbericht
├─ tests/                     Ablauf-Tests mit simulierter Brücke
└─ mql5/
   ├─ RustBridge.mq5          Expert Advisor (Bote)
   └─ RustLines.mq5           Anzeige-Indikator
```

Rust-Bausteine: `tokio` (Netzwerk), `serde`/`serde_json` (Nachrichten),
`chrono` + `chrono-tz` (Zeitzonen), `rust_decimal` (exakte Preise),
`csv` + `flate2` (Daten), `clap` (Befehle), `tracing` (Log).
EMA, VWAP und ATR schreiben wir selbst (wenige Zeilen, voll getestet).

## 6. Daten (PR #6 „Gold-Daten“)

- Dukascopy XAU/USD, **1-Minuten-Kerzen, Bid und Ask, Juni 1999 – heute**,
  eine Datei pro Jahr, als Download im Repo-Release (nicht im Code).
  5/15/30/60-Minuten-Kerzen rechnet Rust daraus selbst.
- Spread im Backtest = Ask − Bid aus den Daten.
- Volumen: Gold ist bei MT5-Brokern ein CFD ohne echtes Börsenvolumen. Der VWAP
  nutzt das Volumen aus den Dukascopy-Daten bzw. live das Tick-Volumen von MT5 –
  ein Näherungswert. Im Backtest prüfen wir, ob die Strategie mit Tick-Volumen
  (Anzahl Preisänderungen) gleich gut läuft, weil MT5 live nur das liefert.
- Später (Phase 4): Kerzen direkt aus deinem MT5 exportieren und vergleichen.

## 7. Backtest: so prüfen wir ehrlich

1. **Entwickeln auf 2004–2018:** alle 40 EMA/VWAP-Kombinationen und die
   ORB-Varianten durchrechnen, Rangliste wie im Video.
2. **Auswahl:** die beste Variante je Strategie – und zusätzlich prüfen, ob
   ihre **Nachbarn** (z. B. EMA 15/25 statt 20) ähnlich gut sind. Ein einzelner
   Glückstreffer zwischen schlechten Nachbarn wird verworfen.
3. **Einmalige Prüfung auf 2019–heute** mit genau diesen Einstellungen, ohne
   danach nachzubessern. Erst das ist ein echtes Ergebnis.
4. **Walk-Forward** zusätzlich: jedes Jahr mit den Jahren davor eingestellt.

Immer eingerechnet: Spread, Kommission (falls der Broker eine hat), Slippage.

Kennzahlen: Gewinn %, größter Rückgang, Anzahl Trades, Trefferquote, Ø R pro
Trade, längste Verlustserie, Ergebnis pro Jahr, Anteil der Kosten.

**Go/No-Go – live auf Demo nur, wenn im Prüfzeitraum 2019–heute:**
- nach allen Kosten im Plus
- mindestens 300 Trades
- größter Rückgang unter 25 %
- nicht von 1–2 Jahren getragen
- Nachbar-Einstellungen ebenfalls im Plus

Ergebnis: Bericht mit Kurve, Rangliste und Jahrestabelle, bevor etwas live geht.

## 8. Betrieb auf deinem Mac

- MT5 Mac-App mit Demokonto, Gold-Chart, RustBridge + Anzeige-Indikator
- Rust-Programm im Terminal; der Mac darf während der Handelszeit nicht
  schlafen (z. B. App „Amphetamine“)
- Handelszeit: London + New York, ca. 08:00–22:00 deutsche Zeit
- Abends: Tagebuch + Tagesbericht werden automatisch in dein GitHub-Repo
  hochgeladen (eigener Ordner, z. B. `mt5-bot/journal/`)
- Ich lese die Berichte über GitHub, vergleiche beide Strategien mit dem
  Backtest und schlage Verbesserungen als Pull Request vor. Updates holst du
  mit einem Befehl auf den Mac.

## 9. Phasen

| Phase | Inhalt | Fertig, wenn | Brauche von dir |
| --- | --- | --- | --- |
| 0 | Plan + Gold-Daten laden (PR #6) | Plan abgestimmt, alle Jahre als Download, Daten geprüft | Plan lesen, PR mergen |
| 1 | Rust-Kern: Daten, Indikatoren, Sitzungen, Risiko, beide Strategien, Simulation, Backtest, Sweep | Tests grün, Sweep läuft über alle Daten | – |
| 2 | Auswertung | Bericht + Go/No-Go je Strategie | deine Entscheidung |
| 3 | MQL5-Brücke, Anzeige-Indikator, Live-Teil in Rust, Tagebuch-Upload | Ablauf-Test mit simulierter Brücke grün | – |
| 4 | Einrichtung auf deinem Mac (Anleitung Schritt für Schritt) | Selbsttest grün, Test-Order 0,01 Lot auf Demo klappt | MT5 Mac-App, Demokonto, ca. 30–60 Min |
| 5 | Demo-Betrieb | 4 Wochen, Tagesberichte, Vergleich mit Backtest | Mac zur Handelszeit an |
| 6 | Später | Server statt Mac, Handy-Benachrichtigungen, weitere Strategien | – |

## 10. Grenzen und Risiken

- Ein guter Backtest ist **keine Garantie**; Gold verhält sich heute anders als 2005.
- Die Video-Ergebnisse stammen von Nasdaq-Futures, rückblickend ausgewählt –
  auf Gold kann es ganz anders aussehen. „No-Go“ ist ein gültiges Ergebnis.
- Dukascopy-Kurse und -Volumen ≠ Kurse und Tick-Volumen deines Brokers.
- Demokonten führen Orders oft besser aus als echte Konten.
- MT5 auf dem Mac ist eine Windows-Version in einer Kompatibilitätsschicht;
  dass die Netzwerk-Brücke dort läuft, prüfen wir in Phase 4.
- Gold-CFDs sind gehebelt; Echtgeld ist **nicht Teil dieses Plans**.

## 11. Offene Entscheidungen

1. Beide Strategien parallel (EMA/VWAP als Haupt-, ORB als Vergleich) – einverstanden?
2. Risiko 1 % pro Trade, Tageslimit −3 % auf Demo – einverstanden?
3. Broker für das MT5-Demokonto (erst für Phase 4 nötig)
4. Darf der Bot das Tagebuch automatisch in dein GitHub-Repo hochladen? (dafür richtest du in Phase 4 einmal einen Zugang ein)
