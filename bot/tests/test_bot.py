"""Offline tests: the real skill tools on the TSLA fixtures from October 19 2026,
with a fake Alpaca paper account. No network.

    python3 -m unittest discover -s bot/tests -v
"""

import copy
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BOT = os.path.dirname(HERE)
sys.path.insert(0, BOT)

import alpaca  # noqa: E402
import bot  # noqa: E402

FIX = os.path.join(os.path.dirname(BOT), "day-trader-skill", "tests", "fixtures")
TSLA_5M = os.path.join(FIX, "trader-entry", "TSLA-2026-10-19-5m.json")
TSLA_60D = os.path.join(FIX, "trader-timemachine", "TSLA-60d5m.json.gz")


def tool_args(now):
    n = ["--now", now]
    return {"entry": ["--offline", TSLA_5M] + n, "exit": n,
            "timemachine": ["--offline", TSLA_60D] + n, "budget": n, "risk": n}


class FakeAlpaca:
    def __init__(self, ts="2026-10-19T10:15:05.0-04:00", is_open=True, equity=100000, last_equity=100000):
        self.ts, self.is_open = ts, is_open
        self.equity, self.last_equity = equity, last_equity
        self.submitted, self.closed, self.held, self.orders, self.lists = [], 0, [], [], []

    def clock(self):
        return {"timestamp": self.ts, "is_open": self.is_open, "next_open": "2026-10-20T09:30:00-04:00"}

    def account(self):
        return {"cash": "100000", "equity": str(self.equity), "last_equity": str(self.last_equity)}

    def positions(self):
        return [{"symbol": s, "qty": "8"} for s in self.held]

    def open_orders(self):
        return [o for o in self.orders if o["status"] == "new"]

    def orders_since(self, after):
        return self.orders + [{"id": "fake-%d" % i, "client_order_id": cid, "status": "new", "qty": o["qty"],
                               "filled_qty": "0", "submitted_at": self.ts}
                              for i, (o, cid) in enumerate(self.submitted, 1)]

    def submit_bracket(self, order, client_order_id):
        self.submitted.append((order, client_order_id))
        return {"id": "fake-%d" % len(self.submitted)}

    def watchlists(self):
        return self.lists

    def create_watchlist(self, name, symbols):
        self.lists.append({"id": "w%d" % len(self.lists), "name": name, "symbols": symbols})

    def update_watchlist(self, watchlist_id, name, symbols):
        for w in self.lists:
            if w["id"] == watchlist_id:
                w.update(name=name, symbols=symbols)

    def close_all(self):
        self.closed += 1
        return []


class BotTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = bot.load_config(os.path.join(BOT, "config.example.json"))
        self.cfg["bot"]["symbols"] = ["TSLA"]
        self.cfg["bot"]["replays"] = 500
        self.lines = []

    def tearDown(self):
        shutil.rmtree(self.dir)

    def make(self, broker, cfg=None, now="2026-10-19 10:15"):
        return bot.Bot(broker, cfg or self.cfg, workdir=self.dir, tool_args=tool_args(now), log=self.lines.append)

    def test_breakout_places_one_paper_bracket(self):
        b = FakeAlpaca()
        self.assertEqual(self.make(b).tick(), "traded")
        self.assertEqual(len(b.submitted), 1)
        order, cid = b.submitted[0]
        self.assertEqual((order["symbol"], order["qty"], order["side"]), ("TSLA", "8", "buy"))
        self.assertEqual(order["stop_loss_stop_price"], "358.32")
        self.assertEqual(order["take_profit_limit_price"], "370.04")
        self.assertEqual(cid, "bot-2026-10-19-TSLA-4688")
        state = bot.read_json(os.path.join(self.dir, bot.STATE))
        self.assertEqual(state["orders"][0]["status"], "placed")
        self.assertEqual(state["orders"][0]["max_loss"], 46.88)

    def test_second_tick_does_not_buy_again(self):
        b = FakeAlpaca()
        bt = self.make(b)
        bt.tick()
        b.held = ["TSLA"]
        self.assertEqual(bt.tick(), "watching")
        self.assertEqual(len(b.submitted), 1)

    def test_fresh_run_remembers_the_days_trades(self):
        # GitHub Actions: a new run on a clean machine, same broker
        b = FakeAlpaca()
        self.make(b).tick()
        shutil.rmtree(self.dir)
        os.makedirs(self.dir)
        self.assertEqual(self.make(b).tick(), "watching")
        self.assertEqual(len(b.submitted), 1)
        cfg = copy.deepcopy(self.cfg)
        cfg["max_trades_per_day"] = 1
        self.assertEqual(self.make(b, cfg).tick(), "max-trades")

    def test_cancelled_unfilled_orders_do_not_count(self):
        b = FakeAlpaca()
        b.orders = [{"id": "x", "client_order_id": "bot-2026-10-19-AAPL-12000", "status": "canceled",
                     "qty": "10", "filled_qty": "0", "submitted_at": b.ts}]
        self.assertEqual(self.make(b).tick(), "traded")

    def test_session_over(self):
        start = bot.parse_ts("2026-10-19T09:20:00-04:00")
        open_ = {"timestamp": "2026-10-19T12:00:00.5-04:00", "is_open": True,
                 "next_open": "2026-10-20T09:30:00-04:00"}
        self.assertIsNone(bot.session_over(open_, start, 5.8))
        late = dict(open_, timestamp="2026-10-19T15:09:00-04:00")
        self.assertIn("time limit", bot.session_over(late, start, 5.8))
        before_open = {"timestamp": "2026-10-19T08:20:00-05:00", "is_open": False,
                       "next_open": "2026-10-19T09:30:00-05:00"}
        self.assertIsNone(bot.session_over(before_open, bot.parse_ts(before_open["timestamp"]), 5.8))
        after_close = {"timestamp": "2026-10-19T16:01:00-04:00", "is_open": False,
                       "next_open": "2026-10-20T09:30:00-04:00"}
        self.assertIn("market closed", bot.session_over(after_close, start, None))

    def test_time_machine_filter_skips_weak_setup(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["bot"]["min_avg_r"] = 0.5
        b = FakeAlpaca()
        bt = self.make(b, cfg)
        self.assertEqual(bt.tick(), "watching")
        self.assertEqual(b.submitted, [])
        self.assertIn("TSLA", bt.skipped)
        self.assertTrue(any("under min_avg_r" in l for l in self.lines))

    def test_risk_block_stops_the_order(self):
        # an earlier run today already risked $120 of the $150 daily limit on AAPL
        b = FakeAlpaca()
        b.orders = [{"id": "x", "client_order_id": "bot-2026-10-19-AAPL-12000", "status": "filled",
                     "qty": "10", "filled_qty": "10", "submitted_at": b.ts}]
        self.assertEqual(self.make(b).tick(), "watching")
        self.assertEqual(b.submitted, [])
        self.assertTrue(any("risk BLOCK" in l and "daily" in l for l in self.lines), self.lines)

    def test_blocked_ticker_never_ordered(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["blocked"] = ["TSLA"]
        b = FakeAlpaca()
        self.assertEqual(self.make(b, cfg).tick(), "watching")
        self.assertEqual(b.submitted, [])

    def test_waiting_before_breakout(self):
        b = FakeAlpaca(ts="2026-10-19T09:50:05.0-04:00")
        self.assertEqual(self.make(b, now="2026-10-19 09:50").tick(), "watching")
        self.assertEqual(b.submitted, [])

    def test_flat_by_closes_everything_once(self):
        b = FakeAlpaca(ts="2026-10-19T15:56:00.0-04:00")
        bt = self.make(b)
        self.assertEqual(bt.tick(), "flat")
        self.assertEqual(bt.tick(), "flat")
        self.assertEqual(b.closed, 1)

    def test_daily_loss_limit_stops_entries(self):
        b = FakeAlpaca(equity=99800, last_equity=100000)
        self.assertEqual(self.make(b).tick(), "loss-limit")
        self.assertEqual(b.submitted, [])

    def test_watchlist_created_then_updated(self):
        b = FakeAlpaca()
        b.lists = [{"id": "other", "name": "Mine", "symbols": ["KO"]}]
        cfg = copy.deepcopy(self.cfg)
        cfg["bot"]["symbols"] = ["tsla", "NVDA"]
        self.make(b, cfg).sync_watchlist()
        self.assertEqual(b.lists[1]["name"], "Paper-Bot")
        self.assertEqual(b.lists[1]["symbols"], ["TSLA", "NVDA"])
        cfg["bot"]["symbols"] = ["AMD"]
        self.make(b, cfg).sync_watchlist()
        self.assertEqual(len(b.lists), 2)
        self.assertEqual(b.lists[1]["symbols"], ["AMD"])
        self.assertEqual(b.lists[0]["symbols"], ["KO"])

    def test_selftest_offline(self):
        b = FakeAlpaca()
        self.assertEqual(self.make(b).selftest(), 0)
        self.assertTrue(any("selftest time machine TSLA: ok" in l for l in self.lines), self.lines)
        self.assertEqual(b.submitted, [])

    def test_market_closed(self):
        b = FakeAlpaca(is_open=False)
        self.assertEqual(self.make(b).tick(), "closed")

    def test_refuses_live_account(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["paper"] = False
        with self.assertRaises(SystemExit):
            self.make(FakeAlpaca(), cfg)
        with self.assertRaises(alpaca.AlpacaError):
            alpaca.Alpaca("k", "s", base_url="https://api.alpaca.markets")


if __name__ == "__main__":
    unittest.main()
