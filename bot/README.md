# Paper-Trading-Bot

Ein automatischer Day-Trading-Bot für ein **Alpaca-Papierkonto** (Spielgeld).
Die Handelslogik kommt aus den Tools in `../day-trader-skill/`, der Bot verkettet
sie und schickt die Orders an Alpaca. Er verweigert jedes Live-Konto.

## Was er macht

Jede Minute während der Börsenzeit (New York):

1. Holt Cash und Positionen vom Papierkonto.
2. Prüft für jede Aktie auf der Liste, ob sie aus der Spanne der ersten
   15 Minuten nach oben ausbricht (`trader-entry`).
3. Bei einem Ausbruch: Stop und Ziel festlegen (`trader-exit`), den Trade
   2.000-mal simulieren (`trader-timemachine`) und nur weitermachen, wenn der
   erwartete Gewinn (avg R) mindestens `min_avg_r` ist.
4. Positionsgröße berechnen (`trader-budget`), gegen die Limits prüfen
   (`trader-risk`) und eine Bracket-Order senden: Kauf + Stop-Loss + Take-Profit.
5. Um 15:55 Uhr New York (21:55 Uhr bei uns): alle offenen Orders stornieren und alle Positionen schließen.

Er hört von selbst auf, neue Trades zu machen, wenn das Tagesverlust-Limit
erreicht ist oder die maximale Zahl Trades pro Tag erreicht ist.

## Einrichten

1. Kostenloses Konto bei [alpaca.markets](https://alpaca.markets) anlegen,
   auf **Paper Trading** wechseln und dort einen API-Key erzeugen.
2. Python 3.8 oder neuer. Nichts zu installieren.
3. Keys als Umgebungsvariablen setzen (nie in eine Datei im Repo):

   ```bash
   export APCA_API_KEY_ID="dein-key"
   export APCA_API_SECRET_KEY="dein-secret"
   ```

   Windows (PowerShell): `$env:APCA_API_KEY_ID="dein-key"` usw.
4. Optional eigene Einstellungen: `bot/config.example.json` nach
   `bot/config.json` kopieren und anpassen (wird nicht committet).

## Starten

```bash
python3 bot/bot.py           # läuft bis Strg+C
python3 bot/bot.py --once    # ein einziger Durchlauf
```

Der Rechner muss während der Börsenzeit an sein (15:30–22:00 Uhr deutscher
Zeit). Alles Protokoll steht in `bot/trader/bot.log`, die Zwischenergebnisse
der Tools in `bot/trader/`.

## Einstellungen (`config.json`)

| Feld | Standard | Bedeutung |
| --- | --- | --- |
| `budget` | 5000 | So viel Geld darf der Bot einsetzen, auch wenn das Papierkonto mehr hat |
| `max_loss_per_trade_usd` | 50 | Maximaler Verlust pro Trade, wenn der Stop greift |
| `max_daily_loss_usd` | 150 | Danach keine neuen Trades an diesem Tag |
| `max_trades_per_day` | 3 | Maximal so viele Käufe pro Tag |
| `no_entries_before` / `after` | 09:45 / 15:30 | Zeitfenster für neue Trades (New York) |
| `flat_by` | 15:55 | Ab dann wird alles geschlossen |
| `bot.symbols` | TSLA, NVDA, … | Aktien, die beobachtet werden |
| `bot.scanner` | false | `true`: zusätzlich alle ~5.900 US-Aktien nach Ausbrüchen scannen (langsam) |
| `bot.target` | 1R | Kursziel: 1R = gleich weit wie der Stop, 2R = doppelt so weit |
| `bot.stop` | or-mid | Stop in der Mitte der Eröffnungsspanne (`or-low`, `pct:1`, `atr:1.5` gehen auch) |
| `bot.min_avg_r` | 0.0 | Mindest-Erwartungswert aus der Simulation; höher = wählerischer |

## Tests

```bash
python3 -m unittest discover -s bot/tests -v
```

Die Tests laufen offline mit echten TSLA-Kursen vom 19.10.2026 und einem
simulierten Alpaca-Konto.

## Wichtig

- **Nur Papierkonto.** Der Bot bricht ab, wenn `paper` nicht `true` ist oder eine
  Live-URL benutzt wird.
- **Nur Long.** Er kauft nur und verkauft nur zum Schließen.
- **Kursdaten von Yahoo** sind kostenlos, aber inoffiziell und können
  verzögert sein oder ausfallen.
- **Keine Gewinngarantie.** Die Simulation ist ein Realitätscheck, keine Vorhersage.
  Erst wochenlang auf Papier beobachten, bevor man irgendetwas daraus ableitet.
