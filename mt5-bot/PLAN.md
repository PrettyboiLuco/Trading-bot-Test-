# Plan: Rust-Trading-System für MetaTrader 5 (Gold)

Stand: 24.10.2026. Dieser Plan wird abgestimmt, bevor Code entsteht.
Jede Phase kommt als eigener Pull Request, den du vor dem Merge siehst.

## 1. Ziel

Ein eigenständiges Trading-System in **Rust**, das auf einem **MT5-Demokonto**
**Gold (XAU/USD)** handelt und auf deinem **MacBook** läuft.
Die Strategie steht fest (EMA kreuzt VWAP) und wird vorher an über 20 Jahren
Gold-Daten getestet.
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

## 3. Die Strategie: EMA kreuzt VWAP – genaue Regeln für den Bot

Grundidee aus dem Video: EMA kreuzt VWAP → nach Kerzenschluss mit der nächsten
Kerze einsteigen, Stop 1,5 × ATR(14), Ziel 2R, 1 % Risiko. Ausgangspunkt
**EMA 20 + Wochen-VWAP auf 15 Minuten.** Unten jede Einzelheit so, dass der
Bot nichts „nach Gefühl“ entscheiden muss. **V** = Variante, die der Backtest
vergleicht; der Rest ist fest.

### 3.1 Preise und Kerzen
- Signale werden auf dem **Mittelkurs** gerechnet: (Bid + Ask) / 2.
- Gehandelt wird realistisch: **Kauf zum Ask, Verkauf zum Bid**.
- 15-Minuten-Kerzen (bzw. 5/30/60 im Sweep) baut Rust aus 1-Minuten-Kerzen.
  Zeitbasis ist die Broker-Serverzeit (live) bzw. UTC (Backtest).

### 3.2 Indikatoren
- **EMA(n)** auf dem Schlusskurs, Glättung 2/(n+1), Start mit dem
  Durchschnitt der ersten n Kerzen. Vor 3 × n Kerzen kein Signal (Einlaufzeit).
- **VWAP** = Σ(typischer Preis × Volumen) / Σ Volumen seit dem Startpunkt,
  typischer Preis = (Hoch + Tief + Schluss) / 3.
  - Wochen-VWAP: Start mit der ersten Kerze der Handelswoche (Sonntagabend nach der Wochenend-Pause)
  - Tages-VWAP: Start mit der ersten Kerze des Handelstags (nach der täglichen Pause)
  - Volumen: im Backtest das Dukascopy-Volumen, live das Tick-Volumen von MT5.
    **V:** Der Backtest rechnet zusätzlich mit „Anzahl Preisänderungen“ als
    Volumen – ist das Ergebnis ähnlich, passt die Live-Rechnung zum Backtest.
- **ATR(14)** nach Wilder, auf demselben Zeitrahmen, Wert der Signal-Kerze.

### 3.3 Signal
- **Long:** Vorherige Kerze EMA ≤ VWAP **und** Signal-Kerze EMA > VWAP
  (beide Kerzen geschlossen). **Short:** genau umgekehrt.
- Gleichstand (EMA = VWAP) zählt nicht als Kreuz.

### 3.4 Einstieg
- Mit der Eröffnung der nächsten Kerze, als Market-Order.
- Im Backtest mit Verzögerung (z. B. 300 ms) und Slippage-Aufschlag.
- Kein Einstieg, wenn: schon eine Position offen ist · Spread über Grenze
  (Start 0,50 $) · weniger als 15 Min bis zur täglichen Handelspause oder
  zum Wochenschluss · Tageslimit erreicht · Brücke/Kurse gestört.
- Handelszeit: **rund um die Uhr** (wie im Video), nur mit diesen Filtern.

### 3.5 Stop und Ziel
- Gemessen ab dem **tatsächlichen Einstiegspreis**:
  Stop = Einstieg ∓ 1,5 × ATR, Ziel = Einstieg ± 3 × ATR (= 2R).
- Beide werden sofort mit der Order an MT5 übergeben.
- Springt der Kurs über den Stop (z. B. nach einer Pause), wird zum ersten
  verfügbaren Kurs geschlossen – im Backtest genauso.
- Backtest: Werden Stop und Ziel in derselben 1-Minuten-Kerze berührt, zählt
  der **Stop** (vorsichtige Annahme); für 2023–heute entscheiden die Ticks.
- Live: Lehnt MT5 eine Order ab (z. B. Requote), versucht der Bot es einmal
  sofort neu; klappt es nicht, wird das Signal ausgelassen und protokolliert.

### 3.6 Position und Gegensignal
- Höchstens **eine** Position gleichzeitig. Neues Kreuz in dieselbe Richtung: ignorieren.
- Kreuz in die **Gegenrichtung** bei offener Position – **V**, drei Varianten:
  1. schließen und sofort drehen
  2. nur schließen
  3. ignorieren (bis Stop/Ziel)
  Der Backtest nimmt die stabilste.

### 3.7 Über Nacht und Wochenende
- Über Nacht halten ist erlaubt. Kosten (Swap) werden im Backtest pro Nacht
  abgezogen, mittwochs dreifach, getrennt für Long und Short. Die echten
  Swap-Sätze deines Brokers stellen wir in Phase 4 ein.
- Wochenende – **V:** (a) halten oder (b) freitags 15 Min vor Handelsschluss
  schließen. Regel: gehalten wird nur, wenn Swap + Wochenend-Lücken im Backtest
  **wenig kosten** (Grenze: höchstens 10 % des Gewinns der Strategie);
  sonst wird freitags geschlossen.

### 3.8 Größe und Limits
- Lotgröße = 1 % des Kontostands / (Stop-Abstand × Kontraktgröße), abgerundet
  auf den Lot-Schritt; unter Mindest-Lot → kein Trade.
- Tageslimit −3 % vom Kontostand zu Tagesbeginn → bis Tagesende keine neuen Trades.
- Keine Begrenzung der Trades pro Tag.

### 3.9 Weitere Varianten im Backtest (**V**)
- 40 Kombinationen: EMA 9/20/50/100/200 × Tages-/Wochen-VWAP × 5/15/30/60 Min
- Nachrichten-Filter an/aus (15 Min vor/nach wichtigen US-Daten)
- Kosten: Spread aus den Daten, Kommission und Swap einstellbar

Broker-Werte, die erst mit deinem Demokonto feststehen (Phase 4) und nur
eingetragen, nicht entschieden werden: Symbolname, Kontraktgröße, Mindest-Lot
und Lot-Schritt, Serverzeit, Zeiten der täglichen Pause, Swap-Sätze, Kommission.

Ergebnis des Backtests: **eine** feste Einstellung für jeden V-Punkt. Danach
ist die Strategie zu 100 % festgelegt und wird live nicht mehr verändert,
außer nach einem neuen, gleich strengen Backtest.

## 4. Risiko-Regeln

- **1 % des Kontos pro Trade** (auf Demo frei wählbar; 1 % bleibt Standard,
  damit die Demo-Ergebnisse dem entsprechen, was später realistisch wäre). Lotgröße = Risiko in $ / (Stop-Abstand × Kontraktgröße),
  abgerundet auf die Lot-Schrittweite des Brokers (Gold meist 100 oz pro Lot, 0,01 Lot).
  Wäre selbst 0,01 Lot zu groß, wird der Trade ausgelassen, nicht vergrößert.
- **Tageslimit:** −3 % → keine neuen Trades bis zum nächsten Tag
- **Höchstens 1 offene Position** gleichzeitig
- **Not-Aus:** Befehl `stop` → alles schließen, keine neuen Trades
- **Demo erzwungen:** Das System fragt über die Brücke den Kontotyp ab und
  verweigert ein Echtgeld-Konto, bis das ausdrücklich freigeschaltet wird.

## 5. Aufbau

```
Dein MacBook
├─ MetaTrader 5 (Mac-App, Demokonto, Gold-Chart)
│    ├─ RustBridge (Expert Advisor): schickt Kurse/Konto an Rust,
│    │   führt Rusts Befehle 1:1 aus – keine eigene Handelslogik
│    └─ Anzeige-Indikator: zeichnet EMA und VWAP in den Chart
│              ▲   JSON über TCP, nur innerhalb des Macs (127.0.0.1)
│              ▼
└─ mt5-bot (Rust) – steuert das komplette System
     ├─ Marktdaten       Kerzen + Bid/Ask live (MT5) oder aus CSV (Backtest)
     ├─ Indikatoren      EMA, VWAP (Tag/Woche), ATR
     ├─ Sitzungen        London/New York, Sommerzeit, Broker-Serverzeit
     ├─ Strategie        EMA kreuzt VWAP
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
│  ├─ strategy/ema_vwap.rs    die Strategie
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

1. **Entwickeln auf 2004–2018:** alle 40 EMA/VWAP-Kombinationen durchrechnen,
   Rangliste wie im Video.
2. **Auswahl:** die beste Kombination – und zusätzlich prüfen, ob
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

## 8. Betrieb: MacBook zum Start, später Mac mini als Dauer-Server

**Start (Phase 4–5): MacBook**
- MT5 Mac-App mit Demokonto, Gold-Chart, RustBridge + Anzeige-Indikator
- Rust-Programm im Terminal; der Mac darf während der Handelszeit nicht
  schlafen (z. B. App „Amphetamine“)
- Handelszeit: London + New York, ca. 08:00–22:00 deutsche Zeit

**Dauerbetrieb (Phase 6): eigener Mac mini als Server**
- Läuft durchgehend (Gold handelt Mo–Fr fast rund um die Uhr), gleiche
  Software wie auf dem MacBook – kein Umbau nötig, kein gemieteter Server
- Automatischer Start nach Stromausfall/Neustart: macOS „nach Stromausfall
  automatisch starten“, automatische Anmeldung, MT5 und der Rust-Bot starten
  von selbst (launchd-Dienst, der den Bot bei einem Absturz neu startet)
- Ruhezustand aus, Bildschirm darf aus
- Fernzugriff vom MacBook/iPhone: Bildschirmfreigabe bzw. SSH, um nachzusehen
  oder den Not-Aus auszulösen
- Wächter: Kommen 10 Minuten keine Kurse von MT5 an, schreibt der Bot eine
  Warnung in den Bericht (später auch aufs Handy)

**Berichte**
- Abends werden Tagebuch + Tagesbericht automatisch in dein GitHub-Repo
  hochgeladen (`mt5-bot/journal/`) – freigegeben
- Ich lese die Berichte über GitHub, vergleiche die Live-Trades mit dem
  Backtest und schlage Verbesserungen als Pull Request vor. Updates holst du
  mit einem Befehl auf den Mac.

## 9. Phasen

| Phase | Inhalt | Fertig, wenn | Brauche von dir |
| --- | --- | --- | --- |
| 0 | Plan + Gold-Daten laden (PR #6) | Plan abgestimmt, alle Jahre als Download, Daten geprüft | Plan lesen, PR mergen |
| 1 | Rust-Kern: Daten, Indikatoren, Sitzungen, Risiko, Strategie, Simulation, Backtest, Sweep | Tests grün, Sweep läuft über alle Daten | – |
| 2 | Auswertung | Bericht + Go/No-Go | deine Entscheidung |
| 3 | MQL5-Brücke, Anzeige-Indikator, Live-Teil in Rust, Tagebuch-Upload | Ablauf-Test mit simulierter Brücke grün | – |
| 4 | Einrichtung auf deinem Mac (Anleitung Schritt für Schritt) | Selbsttest grün, Test-Order 0,01 Lot auf Demo klappt | MT5 Mac-App, Demokonto, ca. 30–60 Min |
| 5 | Demo-Betrieb | 4 Wochen, Tagesberichte, Vergleich mit Backtest | Mac zur Handelszeit an |
| 6 | Mac mini als Dauer-Server | Bot läuft Mo–Fr durchgehend, startet nach Neustart/Stromausfall selbst, Handy-Benachrichtigungen | Mac mini kaufen, ca. 30 Min Einrichtung mit Anleitung |

## 10. Grenzen und Risiken

- Ein guter Backtest ist **keine Garantie**; Gold verhält sich heute anders als 2005.
- Die Video-Ergebnisse stammen von Nasdaq-Futures, rückblickend ausgewählt –
  auf Gold kann es ganz anders aussehen. „No-Go“ ist ein gültiges Ergebnis.
- Dukascopy-Kurse und -Volumen ≠ Kurse und Tick-Volumen deines Brokers.
- Demokonten führen Orders oft besser aus als echte Konten.
- MT5 auf dem Mac ist eine Windows-Version in einer Kompatibilitätsschicht;
  dass die Netzwerk-Brücke dort läuft, prüfen wir in Phase 4.
- Gold-CFDs sind gehebelt; Echtgeld ist **nicht Teil dieses Plans**.

## 11. Werkzeuge aus anderen Repos

Die Strategie steht; aus anderen Projekten übernehmen wir nur Werkzeuge und
bewährte Bauweisen. Code wird nur übernommen, wo die Lizenz es erlaubt;
sonst dient das Projekt als Vorlage und wir schreiben es selbst.

| Woher | Was wir nutzen | Wie |
| --- | --- | --- |
| **dukascopy-node** (MIT) | Download der Gold-Historie seit 1999, Kerzen + Ticks | läuft im Workflow „Gold-Daten“ |
| **claude-watch** (MIT, liegt im Repo) | Trading-Videos auswerten (Bilder + Text), z. B. neue Strategie-Videos prüfen | auf deinem Mac in Claude Code mit `/watch` |
| **day-trader-skill** (MIT, liegt im Repo) | 1) **Time Machine**: vor jedem Einstieg den Trade tausendfach mit den letzten Wochen Gold nachspielen → Trefferchance + Ø R im Tagesbericht; 2) Risiko-Prüfregeln (Stop Pflicht, Max-Verlust, Tageslimit, Duplikate); 3) Sitzungs-/Feiertagslogik | nach Rust übertragen |
| **unser Alpaca-Bot** | Wiederanlauf über Broker-Order-IDs (Tag + Symbol + Risiko im Order-Kommentar), Not-Aus, Selbsttest, Tagesbericht, Upload nach GitHub | nach Rust übertragen |
| **barter-rs** (MIT) | Bauweise: Engine / Marktdaten / Ausführung getrennt, simulierte und echte Ausführung hinter derselben Schnittstelle | Vorlage |
| **nautilus_trader** (LGPL) | Modell für Orders, Positionen und realistische Ausführung (Spread, Slippage, Teilausführung) | nur Vorlage, kein Code (Lizenz) |
| **hftbacktest** (MIT) | Verzögerung zwischen Signal und Ausführung im Backtest abbilden | Vorlage |
| **ta-rs** (MIT) | unabhängige Gegenprobe: unsere EMA/ATR müssen exakt dieselben Werte liefern | nur in den Tests |
| **backtesting.py** (AGPL, Python) | zweiter, unabhängiger Backtest derselben Strategie auf denselben Daten; Ergebnisse müssen zu unserem Rust-Backtest passen | nur zur Prüfung auf dem Rechner, nicht Teil des Bots |
| **EarnForex PositionSizer** (MQL5) | Referenz für korrekte Lotberechnung in MT5 (Tick-Wert, Kontraktgröße, Lot-Schritte) | Vorlage für Tests der Lotgröße |
| **GOLD_ORB** (MQL5) | Gold-spezifische MT5-Details: Serverzeit, Lot-Rundung, Orders mit SL/TP | Vorlage für die Brücke |
| **mtapi** (C#, MT4/5-Brücke) | bewährter Aufbau einer Terminal-Brücke (Befehle, Antworten, Fehler) | Vorlage für RustBridge |
| **Moon Dev / Harvard-Repo** | Vorgehen Research → Backtest → Implement, Leseliste | entspricht unserem Plan |

Bewusst **nicht** übernommen: fertige Bots aus diesen Repos (Krypto, andere
Börsen, Optimierung über alle Daten ohne Prüfzeitraum) und Rust-MT5-Bibliotheken
(mt5-rs kann keine Orders senden, RustMT5 schickt Zugangsdaten an einen fremden
Server).

## 12. Entscheidungen

Getroffen:
- Strategie: EMA kreuzt VWAP (Ausgangspunkt EMA 20 + Wochen-VWAP, 15 Min), genaue Regeln in Abschnitt 3
- Gegensignal: Backtest entscheidet zwischen drehen / schließen / ignorieren
- Halten über Nacht ja; übers Wochenende nur, wenn es wenig kostet (Backtest prüft)
- Neue Trades rund um die Uhr
- Risiko auf Demo: Standard 1 % pro Trade, Tageslimit −3 %
- Tagebuch-Upload nach GitHub: ja
- Dauerbetrieb: eigener Mac mini als Server

Offen:
- Broker für das MT5-Demokonto (erst für Phase 4 nötig)
