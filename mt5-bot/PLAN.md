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
**EMA 20 + Wochen-VWAP auf 15 Minuten.** Unten jede Einzelheit, damit der Bot
nichts „nach Gefühl“ entscheidet. **V** = Variante, die der Backtest
vergleicht; alles andere ist fest. Die Abschnitte stehen in der Reihenfolge,
in der der Bot arbeitet.

### 3.1 Preise und Kerzen
- Signale und Indikatoren auf dem **Bid-Kurs** – so wie die Kerzen, die du in
  MT5 siehst (MT5 zeichnet Bid). Backtest und Live rechnen damit identisch.
- Gehandelt wird realistisch: **Kauf zum Ask, Verkauf zum Bid**; ein Long-Stop
  löst am Bid aus, ein Short-Stop am Ask.
- 15-Minuten-Kerzen (bzw. 5/30/60 im Sweep) baut Rust aus 1-Minuten-Kerzen,
  ausgerichtet an der Broker-Serverzeit. Backtest: Dukascopy-UTC wird
  umgerechnet; bis dein Broker feststeht, mit der üblichen Forex-Serverzeit
  (UTC+2, im US-Sommer UTC+3 – der Handelstag endet um 17:00 New York).
- Eine Kerze gilt als geschlossen, sobald der erste Kurs der nächsten Kerze
  eintrifft (live) bzw. die nächste Kerze beginnt (Backtest). Signal und
  Einstieg passieren damit im selben Moment: zur Eröffnung der nächsten Kerze.
- **Pause** = Zeitraum ohne Handel laut Broker (live) bzw. Datenlücke von
  mindestens 30 Minuten (Backtest). Kerzen ohne 1-Minuten-Daten entstehen
  nicht; sie werden nicht aufgefüllt.

### 3.2 Indikatoren
- **EMA(n)** auf dem Schlusskurs, Glättung 2/(n+1), Start mit dem Durchschnitt
  der ersten n Kerzen. Läuft über Pausen und Wochenenden einfach weiter.
- **VWAP** = Σ(typischer Preis × Volumen) / Σ Volumen seit dem Startpunkt,
  typischer Preis = (Hoch + Tief + Schluss) / 3.
  - Wochen-VWAP: Neustart mit der ersten Kerze der Handelswoche
  - Tages-VWAP: Neustart mit der ersten Kerze nach der täglichen Pause
  - Ist das Volumen seit dem Startpunkt 0 (z. B. fehlende Daten in alten
    Jahren), gibt es keinen VWAP und damit kein Signal. Wie viele Jahre
    betroffen sind, zeigt die Datenprüfung in Phase 0.
  - Volumen: Backtest Dukascopy-Volumen, live MT5-Tick-Volumen.
    **V:** zusätzlich „Anzahl Preisänderungen“ als Volumen; nur wenn beide
    ähnlich abschneiden, gilt der Backtest auch für live.
- **ATR(14)** nach Wilder, gleicher Zeitrahmen, Wert der Signal-Kerze.

### 3.3 Signal
- Ein Signal ist das **Ereignis „Kreuz“**, nicht der Zustand „EMA über VWAP“.
- **Long:** vorherige Kerze EMA ≤ VWAP **und** Signal-Kerze EMA > VWAP
  (beide geschlossen). **Short:** umgekehrt. Gleichstand ist kein Kreuz.
- **Kein Signal**, wenn
  - die vorherige Kerze zu einem anderen VWAP-Abschnitt gehört (beim
    Neustart des VWAP springt er auf den aktuellen Preis – ein „Kreuz“ dort
    ist ein Rechen-Effekt, kein Marktsignal); zusätzlich erst ab der
    **4. Kerze** nach dem Neustart, weil der VWAP vorher kaum Daten hat (**V:** 1/4/8 Kerzen)
  - zwischen den beiden Kerzen eine Handelspause lag (Wochenende, tägliche Pause)
  - die Einlaufzeit noch läuft: weniger als 3 × n Kerzen EMA-Historie
- Ein Signal, das nicht sofort zu einem Einstieg führt (Filter, offene
  Position), **verfällt**. Es wird später nicht nachgeholt.

### 3.4 Ablauf

**Jede Minute (unabhängig vom Zeitrahmen):**
- Wochenende, Variante „schließen“: ab Freitag 15 Min vor Handelsschluss
  offene Position schließen. (Bei 60-Minuten-Kerzen läge der Kerzenschluss
  sonst bis zu einer Stunde daneben.)
- Wächter: kommen keine Kurse oder antwortet die Brücke nicht → Warnung,
  keine neuen Einstiege. Eine offene Position bleibt geschützt, weil Stop und
  Ziel beim Broker liegen, nicht im Bot.

**Bei jedem Kerzenschluss (feste Reihenfolge):**
1. **Abgleich mit MT5:** Ist die Position noch offen? (Stop/Ziel löst MT5
   zwischen den Kerzen selbst aus.) Kontostand, Tagesergebnis aktualisieren.
2. **Tageslimit prüfen** (siehe 3.8).
3. Ist die Position durch die Wochenend-Regel schon geschlossen und ist
   Freitag nach dieser Uhrzeit: nichts weiter tun.
4. **Indikatoren** mit der geschlossenen Kerze aktualisieren, Signal prüfen.
5. **Gegensignal** bei offener Position (**V**): 1 schließen und drehen ·
   2 nur schließen · 3 ignorieren. Schließen ist immer erlaubt, auch nach
   erreichtem Tageslimit; Drehen zählt als neuer Einstieg und braucht die
   Freigaben aus Schritt 6. Beim Drehen erst schließen, dann die neue
   Lotgröße mit dem neuen Kontostand berechnen.
6. **Einstieg** nur, wenn alle zutreffen: Signal vorhanden · keine offene
   Position · Tageslimit nicht erreicht · Spread ≤ Grenze (Start 0,50 $) ·
   die **nächste** Kerze ist keine erste Kerze nach einer Pause und es sind
   mehr als 15 Min bis zur nächsten Pause/zum Wochenschluss · Kurse und
   Brücke ohne Störung · Stop-Abstand ≥ Mindestabstand des Brokers ·
   Lotgröße ≥ Mindest-Lot · (**V:** keine wichtigen US-Daten in ±15 Min).
7. **Order** zur Eröffnung der nächsten Kerze als Market-Order, mit Stop und
   Ziel. Lehnt MT5 ab: einmal sofort neu versuchen, sonst auslassen und
   protokollieren.
8. **Protokoll:** jedes Signal mit Entscheidung und Grund („Einstieg“,
   „ausgelassen: Spread 0,62 $“, …).

Handelszeit: **rund um die Uhr** (wie im Video), nur mit diesen Filtern.

### 3.5 Stop und Ziel
- Ab dem **tatsächlichen Ausführungspreis**: Stop = Einstieg ∓ 1,5 × ATR,
  Ziel = Einstieg ± 3 × ATR (= 2R). ATR der Signal-Kerze.
- Ablauf, damit eine Position **nie ohne Stop** ist: Order mit Stop/Ziel
  berechnet vom aktuellen Ask/Bid senden; nach der Ausführung Stop/Ziel auf
  den echten Ausführungspreis nachstellen, wenn er um mehr als 1 Tick abweicht.
  Lotgröße wird mit dem aktuellen Ask/Bid berechnet.
- Teilausführung: es gilt die tatsächlich ausgeführte Menge.
- Springt der Kurs über den Stop (Pause, Nachricht), wird zum ersten
  verfügbaren Kurs geschlossen – im Backtest genauso.
- Backtest: Berühren Stop und Ziel dieselbe 1-Minuten-Kerze, zählt der
  **Stop**; für 2023–heute entscheiden die Ticks.
- Kein Nachziehen des Stops, kein Teil-Schließen (wie im Video).

### 3.6 Positionen
- Höchstens **eine** Position gleichzeitig.
- Nach Stop oder Ziel wird erst beim **nächsten neuen Kreuz** wieder eingestiegen.

### 3.7 Über Nacht und Wochenende
- Über Nacht halten ist erlaubt. Swap wird im Backtest pro Nacht abgezogen,
  an einem Wochentag dreifach (meist Mittwoch, je nach Broker), getrennt für
  Long und Short.
- Wochenende – **V:** (a) halten oder (b) freitags 15 Min vor Handelsschluss
  schließen. Gehalten wird nur, wenn Swap + Wochenend-Lücken im Backtest
  höchstens 10 % des Strategie-Gewinns kosten; sonst – und auch wenn die
  Strategie insgesamt keinen Gewinn macht – (b).

### 3.8 Größe und Limits
- Lotgröße = 1 % des Kontostands / (Stop-Abstand × Kontraktgröße), abgerundet
  auf den Lot-Schritt; unter Mindest-Lot → kein Trade.
- **Tageslimit:** Fällt das Kapital (Kontostand **inkl.** offener Position)
  um 3 % unter den Stand zu Beginn des Handelstags (Serverzeit), gibt es bis
  zum nächsten Handelstag keine neuen Einstiege. Eine offene Position läuft
  mit ihrem Stop weiter.
- Keine Begrenzung der Trades pro Tag.

### 3.9 Start und Neustart des Bots
- Beim Start lädt der Bot über die Brücke genug Historie, damit EMA, ATR und
  VWAP sofort stimmen: mindestens 3 × n Kerzen **und** alles seit Beginn der
  aktuellen Woche. Vorher kein Signal.
- Offene Position des Bots (erkannt an der Magic Number 1001) wird übernommen,
  nicht doppelt eröffnet. Ein Kreuz, das während der Ausfallzeit lag, wird
  nicht nachgeholt.

### 3.10 Was nur informiert und die Strategie nicht verändert
- **Time Machine** (aus dem Day-Trader-Skill): rechnet für jeden Einstieg die
  Trefferchance aus und schreibt sie in den Bericht. Sie **filtert nicht** –
  sonst wäre es eine andere Strategie als die getestete.

### 3.11 Weitere Varianten im Backtest (**V**) und Broker-Werte
- 40 Kombinationen: EMA 9/20/50/100/200 × Tages-/Wochen-VWAP × 5/15/30/60 Min
  (die fünf EMA-Längen hat das Video nicht genannt; das ist unsere Auswahl)
- Nachrichten-Filter an/aus. Dafür brauchen wir einen Terminkalender mit
  wichtigen US-Daten; live liefert MT5 ihn (Wirtschaftskalender), für den
  Backtest suchen wir eine historische Quelle. Gibt es keine verlässliche,
  bleibt der Filter aus.
- Kosten: Spread aus den Daten, Kommission und Swap einstellbar.

Broker-Werte, die mit deinem Demokonto feststehen (Phase 4) und nur
eingetragen werden: Symbolname, Kontraktgröße, Mindest-Lot und Lot-Schritt,
Mindest-Stop-Abstand, Serverzeit, Zeiten der täglichen Pause und des
Wochenschlusses, Swap-Sätze und Dreifach-Swap-Tag, Kommission.

**Reihenfolge der Entscheidungen im Backtest** (nur auf den Entwicklungsjahren
2004–2018, damit wir nicht tausende Varianten gleichzeitig ausprobieren und
uns ein Glückstreffer täuscht):
1. Grundeinstellung für alle anderen V-Punkte: Gegensignal = ignorieren,
   Wochenende = schließen, Wartezeit nach VWAP-Neustart = 4 Kerzen,
   Nachrichten-Filter aus, Dukascopy-Volumen.
2. Damit die 40 Kombinationen rechnen → beste stabile Kombination wählen.
3. Mit dieser Kombination die übrigen V-Punkte **einzeln nacheinander**
   prüfen: Gegensignal → Wochenende → Wartezeit → Nachrichten-Filter.
   Eine Änderung wird nur übernommen, wenn sie klar besser ist (mehr Ø R
   **und** nicht größerer Rückgang), sonst bleibt die Grundeinstellung.
4. Volumen-Gegenprobe (Tick-Anzahl statt Dukascopy-Volumen) – nur Kontrolle,
   keine Auswahl.
5. Erst danach die einmalige Prüfung auf 2019–heute.

Ergebnis des Backtests: **eine** feste Einstellung für jeden V-Punkt. Danach
ist die Strategie zu 100 % festgelegt und wird live nicht mehr verändert,
außer nach einem neuen, gleich strengen Backtest.

## 4. Risiko-Regeln (Kurzfassung, Details in 3.4–3.8)

- 1 % des Kontostands pro Trade (Standard; auf Demo änderbar)
- Tageslimit −3 % (inkl. offener Position), danach keine neuen Einstiege
- Höchstens 1 offene Position, immer mit Stop und Ziel
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
