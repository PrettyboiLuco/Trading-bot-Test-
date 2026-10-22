"""Automatic paper-trading bot built on the day-trader-skill tools.

Every tick during market hours it:
  1. syncs cash and positions from the Alpaca paper account,
  2. flattens everything once it is past flat_by (15:55 New York by default),
  3. checks each candidate for an opening-range breakout (trader-entry),
  4. plans stop and target (trader-exit), replays the trade (trader-timemachine)
     and skips it unless the expected R clears min_avg_r,
  5. sizes it (trader-budget), checks it against the limits (trader-risk)
     and sends the bracket order to the paper account.

The skill tools do the trading logic; this file only chains them and talks to
the broker. It never trades a live account: see alpaca.py.

    python3 bot/bot.py            # run until stopped (Ctrl+C)
    python3 bot/bot.py --once     # one tick, then exit
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(os.path.dirname(HERE), "day-trader-skill")
TOOLS = {
    "scan": "trader-scanner/scan.py",
    "entry": "trader-entry/entry.py",
    "exit": "trader-exit/exit.py",
    "timemachine": "trader-timemachine/timemachine.py",
    "budget": "trader-budget/size.py",
    "risk": "trader-risk/check.py",
}
STATE = "trader/state/broker.json"


def load_config(path):
    if not os.path.exists(path):
        path = os.path.join(HERE, "config.example.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def ny_clock(clock):
    """Alpaca's clock timestamp is New York local time with its offset:
    '2026-10-19T10:15:03.1234-04:00' -> ('2026-10-19', '10:15')."""
    ts = clock["timestamp"]
    return ts[:10], ts[11:16]


def parse_ts(text):
    """Alpaca ISO time, possibly with nanoseconds, -> aware datetime."""
    text = re.sub(r"\.\d+", "", text).replace("Z", "+00:00")
    return datetime.datetime.fromisoformat(text)


def client_id(day, sym, max_loss):
    """bot-2026-10-19-TSLA-4688: the day, the symbol and the max loss in cents,
    so a fresh run can rebuild the day's risk from the broker alone."""
    return "bot-%s-%s-%d" % (day, sym, round(float(max_loss or 0) * 100))


def parse_client_id(cid):
    m = re.match(r"^bot-(\d{4}-\d{2}-\d{2})-(.+)-(\d+)$", cid or "")
    return (m.group(1), m.group(2), int(m.group(3)) / 100.0) if m else None


class Bot:
    def __init__(self, broker, cfg, workdir=HERE, tool_args=None, log=print):
        self.broker = broker
        self.cfg = cfg
        self.opts = cfg.get("bot", {})
        self.workdir = workdir
        self.tool_args = tool_args or {}
        self.log = log
        self.day = None
        self.skipped = set()
        self.flattened = False
        self.last_scan = None
        self.scan_hits = []
        if not cfg.get("paper", True):
            raise SystemExit("config says paper: false; this bot only trades the paper account")
        write_json(self.path("trader/config.json"), {k: v for k, v in cfg.items() if k != "bot"})

    def path(self, rel):
        return os.path.join(self.workdir, rel)

    def tool(self, name, *args):
        cmd = [sys.executable, os.path.join(SKILL, TOOLS[name])] + list(args) + self.tool_args.get(name, [])
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        p = subprocess.run(cmd, cwd=self.workdir, capture_output=True, text=True, env=env)
        return p.returncode, p.stdout, p.stderr.strip()

    def tool_json(self, name, *args):
        rc, out, err = self.tool(name, *args)
        try:
            return rc, json.loads(out), err
        except ValueError:
            return rc, None, err or out.strip()[-300:]

    # ---------------------------------------------------------------- state

    def new_day(self, day):
        self.day = day
        self.skipped = set()
        self.flattened = False
        self.last_scan = None
        self.scan_hits = []
        self.log("new session %s" % day)

    def sync_orders(self, clock):
        """Rebuild today's placed entries from the broker, so each GitHub
        Actions run (a fresh machine) knows what earlier runs did."""
        start = "%sT00:00:00%s" % (self.day, clock["timestamp"][-6:])
        recs = []
        for o in self.broker.orders_since(start) or []:
            parsed = parse_client_id(o.get("client_order_id"))
            if not parsed or parsed[0] != self.day:
                continue
            if o.get("status") in ("canceled", "rejected", "expired") and float(o.get("filled_qty") or 0) == 0:
                continue
            recs.append({"at": o.get("submitted_at"), "date": self.day, "symbol": parsed[1], "side": "buy",
                         "qty": o.get("qty"), "kind": "entry", "max_loss": parsed[2], "status": "placed",
                         "paper": True, "broker": "alpaca", "by": "bot", "broker_order_id": o.get("id")})
        write_json(self.path(STATE), {"orders": recs})

    def placed_today(self):
        state = read_json(self.path(STATE), {}) or {}
        return [r for r in state.get("orders", []) if r.get("date") == self.day and r.get("status") == "placed"]

    def record(self, order, resp):
        state = read_json(self.path(STATE), {}) or {}
        plan = order.get("plan", {})
        state.setdefault("orders", []).append({
            "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "date": self.day, "symbol": order["symbol"], "side": order["side"], "qty": order["qty"],
            "kind": "entry", "max_loss": plan.get("max_loss"), "stop": plan.get("stop"),
            "status": "placed", "paper": True, "broker": "alpaca", "by": "bot",
            "broker_order_id": (resp or {}).get("id"),
        })
        write_json(self.path(STATE), state)

    def sync_account(self):
        acct = self.broker.account()
        positions = self.broker.positions() or []
        cash = float(acct["cash"])
        if self.cfg.get("budget"):
            # the budget caps what the bot holds in total: the paper account
            # has far more cash than the bot is meant to use
            held = sum(abs(float(p.get("market_value") or 0)) for p in positions)
            cash = min(cash, max(0.0, float(self.cfg["budget"]) - held))
        write_json(self.path("trader/portfolio.json"), {
            "cash": cash,
            "positions": [{"symbol": p["symbol"], "shares": float(p["qty"])} for p in positions],
        })
        pnl = float(acct.get("equity", 0)) - float(acct.get("last_equity", acct.get("equity", 0)))
        return pnl, {p["symbol"] for p in positions}

    def sync_watchlist(self, name="Paper-Bot"):
        """Keep a watchlist in the Alpaca dashboard with the bot's symbols."""
        syms = [s.upper() for s in self.opts.get("symbols", [])]
        if not syms:
            return
        existing = [w for w in (self.broker.watchlists() or []) if w.get("name") == name]
        if existing:
            self.broker.update_watchlist(existing[0]["id"], name, syms)
        else:
            self.broker.create_watchlist(name, syms)
        self.log("Alpaca watchlist %s: %s" % (name, ", ".join(syms)))

    def selftest(self):
        """Check every outside service the trading day needs, without trading:
        the Alpaca account and Yahoo's bars for each symbol, plus one Time
        Machine replay. Returns the number of failures."""
        failed = 0
        clock, acct = self.broker.clock(), self.broker.account()
        self.log("selftest Alpaca: ok, equity %s, market %s" % (acct.get("equity"), "open" if clock.get("is_open") else "closed"))
        tm_done = False
        for sym in [s.upper() for s in self.opts.get("symbols", [])]:
            rc, entry, err = self.tool_json("entry", "check", sym, "--json")
            if entry is None:
                failed += 1
                self.log("selftest Yahoo %s: FAILED %s" % (sym, err))
                continue
            last = (entry.get("last") or {}).get("close")
            self.log("selftest Yahoo %s: ok, %s %s, last close %s" % (sym, entry.get("date"), entry.get("status"), last))
            if not tm_done and last:
                tm_done = True
                rc, tm, err = self.tool_json(
                    "timemachine", "run", "--symbol", sym, "--date", entry["date"], "--entry-time", "10:15 AM",
                    "--entry", "%.2f" % last, "--stop", "%.2f" % (last * 0.99), "--target", "%.2f" % (last * 1.01),
                    "--replays", "200", "--json")
                if tm is None:
                    failed += 1
                    self.log("selftest time machine %s: FAILED %s" % (sym, err))
                else:
                    self.log("selftest time machine %s: ok, %d past sessions, %s"
                             % (sym, (tm.get("history") or {}).get("sessions", 0), tm.get("verdict")))
        self.log("selftest: %s" % ("all ok" if not failed else "%d FAILED" % failed))
        return failed

    # ---------------------------------------------------------------- the tick

    def tick(self):
        clock = self.broker.clock()
        self.last_clock = clock
        if not clock.get("is_open"):
            if getattr(self, "last_result", None) != "closed":
                self.log("market closed, next open %s" % clock.get("next_open"))
            self.last_result = "closed"
            return "closed"
        self.last_result = "open"
        day, hm = ny_clock(clock)
        if day != self.day:
            self.new_day(day)
            self.sync_orders(clock)
        if hm >= self.cfg.get("flat_by", "15:55"):
            if not self.flattened:
                self.broker.close_all()
                self.flattened = True
                self.log("%s flat by %s: cancelled open orders and closed all positions" % (hm, self.cfg.get("flat_by", "15:55")))
            return "flat"
        pnl, held = self.sync_account()
        if pnl <= -float(self.cfg.get("max_daily_loss_usd", 1e18)):
            self.log("day P&L %.2f hit the daily loss limit: no new entries" % pnl)
            return "loss-limit"
        if hm < self.cfg.get("no_entries_before", "09:45") or hm > self.cfg.get("no_entries_after", "15:30"):
            return "outside-window"
        placed = self.placed_today()
        if len([r for r in placed if r.get("kind") == "entry"]) >= int(self.cfg.get("max_trades_per_day", 3)):
            return "max-trades"
        busy = held | {o["symbol"] for o in (self.broker.open_orders() or [])} | {r["symbol"] for r in placed}
        for sym in self.candidates(hm):
            if sym in busy or sym in self.skipped:
                continue
            if self.try_trade(sym):
                return "traded"
        return "watching"

    def candidates(self, hm):
        syms = [s.upper() for s in self.opts.get("symbols", [])]
        if self.opts.get("scanner"):
            every = int(self.opts.get("scan_every_min", 15))
            mins = int(hm[:2]) * 60 + int(hm[3:])
            if self.last_scan is None or mins - self.last_scan >= every:
                self.last_scan = mins
                rc, _, err = self.tool("scan", "orb", "--out", "trader/watchlist.json", "--quiet")
                doc = read_json(self.path("trader/watchlist.json"), {}) or {}
                self.scan_hits = [h["symbol"] for h in doc.get("hits", [])][: int(self.opts.get("scan_max", 10))]
                self.log("scanner: %d breakouts%s" % (len(self.scan_hits), "" if rc == 0 else " (%s)" % err))
            syms += [s for s in self.scan_hits if s not in syms]
        return syms

    def skip(self, sym, why):
        self.skipped.add(sym)
        self.log("%s skipped: %s" % (sym, why))

    def try_trade(self, sym):
        o = self.opts
        rc, entry, err = self.tool_json("entry", "check", sym, "--write", "--json")
        if entry is None:
            self.log("%s entry check failed: %s" % (sym, err))
            return False
        status = entry.get("status")
        if status != "triggered":
            if status == "expired":
                self.skipped.add(sym)
            return False
        age = entry.get("minutes_since") or 0
        if age > int(o.get("max_trigger_age_min", 10)):
            self.skip(sym, "breakout was %d minutes ago, too late" % age)
            return False
        self.log("%s triggered: %s" % (sym, entry.get("reason")))

        rc, _, err = self.tool("exit", "plan", "--stop", o.get("stop", "or-mid"), "--target", o.get("target", "1R"), "--write")
        if rc != 0:
            self.skip(sym, "no plan: %s" % err)
            return False

        if o.get("timemachine", True):
            rc, tm, err = self.tool_json("timemachine", "run", "--replays", str(o.get("replays", 2000)), "--json", "--write")
            if tm is None:
                self.skip(sym, "time machine failed: %s" % err)
                return False
            mc = tm["mc"]
            self.log("%s time machine: target %.1f%%, stop %.1f%%, avg R %+.3f. %s"
                     % (sym, mc["p_target"] * 100, mc["p_stop"] * 100, mc["avg_R"], tm.get("verdict", "")))
            if mc["avg_R"] < float(o.get("min_avg_r", 0.0)):
                self.skip(sym, "expected R %+.3f is under min_avg_r %s" % (mc["avg_R"], o.get("min_avg_r", 0.0)))
                return False

        rc, sized, err = self.tool_json("budget", "--write", "--json")
        if not sized or not sized.get("orders"):
            why = ((sized or {}).get("sizing") or {}).get("refusal") or err
            self.skip(sym, "no order: %s" % why)
            return False
        order = sized["orders"][0]

        rc, risk, err = self.tool_json("risk", "--json")
        if rc != 0 or not risk or risk.get("block"):
            reasons = [r for res in (risk or {}).get("results", []) for r in res.get("reasons", [])]
            self.skip(sym, "risk BLOCK: %s" % ("; ".join(reasons) or err))
            return False

        resp = self.broker.submit_bracket(order, client_id(self.day, sym, order.get("plan", {}).get("max_loss")))
        self.record(order, resp)
        self.log("%s BUY %s (paper): stop %s, target %s. %s"
                 % (sym, order["qty"], order["stop_loss_stop_price"], order["take_profit_limit_price"], order["why"]))
        return True


def session_over(clock, started, max_hours, exit_when_closed=True):
    """Stop at the time limit, or (--session) when the market is closed and
    does not open within two hours (after the close, weekends, holidays).
    Returns the reason, or None to keep going."""
    now = parse_ts(clock["timestamp"])
    if max_hours and (now - started).total_seconds() >= max_hours * 3600:
        return "time limit of %.1f hours reached" % max_hours
    if exit_when_closed and not clock.get("is_open") and (parse_ts(clock["next_open"]) - now).total_seconds() > 2 * 3600:
        return "market closed, next open %s" % clock["next_open"]
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Paper-trading bot on the day-trader-skill tools.")
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--once", action="store_true", help="run one tick and exit")
    ap.add_argument("--session", action="store_true",
                    help="exit when the market is closed for more than two hours (for GitHub Actions)")
    ap.add_argument("--max-hours", type=float, help="exit after this many hours")
    ap.add_argument("--selftest", action="store_true", help="check Alpaca and Yahoo, update the watchlist, no trading")
    a = ap.parse_args(argv)
    from alpaca import Alpaca, AlpacaError

    cfg = load_config(a.config)
    logfile = os.path.join(HERE, "trader", "bot.log")
    os.makedirs(os.path.dirname(logfile), exist_ok=True)

    def log(msg):
        line = "%s  %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
        print(line, flush=True)
        with open(logfile, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    try:
        bot = Bot(Alpaca(), cfg, log=log)
    except AlpacaError as e:
        print("bot.py: %s" % e, file=sys.stderr)
        return 1
    try:
        bot.sync_watchlist()
    except AlpacaError as e:
        log("watchlist not updated: %s" % e)
    if a.selftest:
        try:
            return 1 if bot.selftest() else 0
        except AlpacaError as e:
            log("selftest Alpaca: FAILED %s" % e)
            return 1
    poll = float(cfg.get("bot", {}).get("poll_seconds", 60))
    log("bot started (paper), watching %s%s" % (", ".join(cfg.get("bot", {}).get("symbols", [])) or "-",
                                                " + scanner" if cfg.get("bot", {}).get("scanner") else ""))
    started = None
    try:
        while True:
            try:
                result = bot.tick()
            except AlpacaError as e:
                log("broker error: %s" % e)
                result = "error"
            except Exception as e:  # keep running: a crash would leave positions open past flat_by
                log("error: %r" % e)
                result = "error"
            if a.once:
                return 0
            clock = getattr(bot, "last_clock", None)
            if clock:
                started = started or parse_ts(clock["timestamp"])
                why = session_over(clock, started, a.max_hours, a.session) if (a.session or a.max_hours) else None
                if why:
                    log("exiting: %s" % why)
                    return 0
            time.sleep(300 if result == "closed" and not a.session else 60)
    except KeyboardInterrupt:
        log("stopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
