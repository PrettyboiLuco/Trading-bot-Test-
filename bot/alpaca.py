"""A small Alpaca client for the paper account only. Standard library, no SDK.

Keys come from the environment (APCA_API_KEY_ID, APCA_API_SECRET_KEY), never
from a file in the repo. The base URL is fixed to the paper endpoint: this
module refuses to talk to a live account.
"""

import json
import os
import urllib.error
import urllib.request

PAPER_URL = "https://paper-api.alpaca.markets"


class AlpacaError(Exception):
    pass


class Alpaca:
    def __init__(self, key=None, secret=None, base_url=PAPER_URL, timeout=20):
        self.key = key or os.environ.get("APCA_API_KEY_ID", "")
        self.secret = secret or os.environ.get("APCA_API_SECRET_KEY", "")
        if not self.key or not self.secret:
            raise AlpacaError("set APCA_API_KEY_ID and APCA_API_SECRET_KEY (your Alpaca paper keys)")
        if "paper-api." not in base_url:
            raise AlpacaError("refusing %s: this bot only trades the paper account" % base_url)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers={
            "APCA-API-KEY-ID": self.key,
            "APCA-API-SECRET-KEY": self.secret,
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                text = r.read().decode()
        except urllib.error.HTTPError as e:
            raise AlpacaError("%s %s -> %s %s" % (method, path, e.code, e.read().decode(errors="replace")[:300]))
        except urllib.error.URLError as e:
            raise AlpacaError("%s %s -> %s" % (method, path, e.reason))
        return json.loads(text) if text.strip() else None

    def clock(self):
        return self._call("GET", "/v2/clock")

    def account(self):
        return self._call("GET", "/v2/account")

    def positions(self):
        return self._call("GET", "/v2/positions")

    def open_orders(self):
        return self._call("GET", "/v2/orders?status=open&nested=true&limit=500")

    def orders_since(self, after):
        """Every order (any status) submitted after the ISO time `after`."""
        return self._call("GET", "/v2/orders?status=all&limit=500&direction=asc&after=" + after)

    def submit_bracket(self, order, client_order_id):
        """order: one entry from trader/orders.json (trader-budget's shape)."""
        body = {
            "symbol": order["symbol"],
            "qty": str(order["qty"]),
            "side": order["side"],
            "type": order["type"],
            "time_in_force": order.get("time_in_force", "day"),
            "order_class": "bracket",
            "take_profit": {"limit_price": str(order["take_profit_limit_price"])},
            "stop_loss": {"stop_price": str(order["stop_loss_stop_price"])},
            "client_order_id": client_order_id,
        }
        if order["type"] == "limit":
            body["limit_price"] = str(order["limit_price"])
        return self._call("POST", "/v2/orders", body)

    def watchlists(self):
        return self._call("GET", "/v2/watchlists")

    def create_watchlist(self, name, symbols):
        return self._call("POST", "/v2/watchlists", {"name": name, "symbols": symbols})

    def update_watchlist(self, watchlist_id, name, symbols):
        return self._call("PUT", "/v2/watchlists/" + watchlist_id, {"name": name, "symbols": symbols})

    def cancel_all_orders(self):
        return self._call("DELETE", "/v2/orders")

    def close_position(self, symbol):
        return self._call("DELETE", "/v2/positions/" + symbol)
