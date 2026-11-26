from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from .base import BaseRouter

End = Optional[Union[str, datetime]]


class MetricsRouter(BaseRouter):
    """
    Monitoring: what bots, account monitors, the market recorder and the API's bot health watcher store in InfluxDB.
    Windows are in minutes (5 to 4320, the most InfluxDB 3 Core reads in one query) and end at `end` (UTC) or now.
    Every endpoint except get_health answers 503 while monitoring is off on the API (INFLUXDB_ENABLED).
    """

    @staticmethod
    def _params(**params: Any) -> Dict[str, Any]:
        """Leaves out unset parameters, so the API uses its own defaults for them."""
        return {key: value.isoformat() if isinstance(value, datetime) else value
                for key, value in params.items() if value is not None}

    async def get_health(self) -> Dict[str, Any]:
        """Whether monitoring is on, whether InfluxDB answers, and the bot health watcher's last check."""
        return await self._get("/metrics/health")

    async def get_uptime(self, minutes: int = 360, end: End = None) -> List[Dict[str, Any]]:
        """Uptime % per bot and level (process, strategy). Time a bot was stopped on purpose is left out."""
        return await self._get("/metrics/uptime", params=self._params(minutes=minutes, end=end))

    async def get_uptime_timeline(self, minutes: int = 360, end: End = None) -> List[Dict[str, Any]]:
        """Up and down periods per bot and level: bot, level, state, start, end, ongoing, duration_s."""
        return await self._get("/metrics/uptime/timeline", params=self._params(minutes=minutes, end=end))

    async def get_incidents(self, minutes: int = 1440, end: End = None) -> List[Dict[str, Any]]:
        """Down periods, newest first, each a "hang", "crash" or "no heartbeat"."""
        return await self._get("/metrics/incidents", params=self._params(minutes=minutes, end=end))

    async def get_status_changes(self, minutes: int = 1440, end: End = None, bot: Optional[str] = None,
                                 limit: int = 50) -> List[Dict[str, Any]]:
        """What the bot health watcher noticed, newest first: down, up again, stopped, started."""
        return await self._get("/metrics/status-changes",
                               params=self._params(minutes=minutes, end=end, bot=bot, limit=limit))

    async def get_bots(self) -> List[Dict[str, Any]]:
        """Bots that reported a price in the last day: one row per bot, exchange and pair."""
        return await self._get("/metrics/bots")

    async def get_pnl(self, minutes: int = 360, end: End = None, bot: Optional[str] = None) -> List[Dict[str, Any]]:
        """PnL and volume per bot and controller over time."""
        return await self._get("/metrics/pnl", params=self._params(minutes=minutes, end=end, bot=bot))

    async def get_orders(self, bot: str, minutes: int = 60, end: End = None, exchange: Optional[str] = None,
                         pair: Optional[str] = None) -> Dict[str, Any]:
        """
        One bot's price, orders (placed until filled, cancelled or now), fills and grid reference price.
        exchange and pair narrow it to one market, for a bot that trades several.
        """
        params = self._params(bot=bot, minutes=minutes, end=end, exchange=exchange, pair=pair)
        return await self._get("/metrics/orders", params=params)

    async def get_ladder(self, bot: str, exchange: Optional[str] = None, pair: Optional[str] = None) -> Dict[str, Any]:
        """One bot right now: its open orders, price, grid state and PnL, optionally for one of its markets."""
        return await self._get("/metrics/ladder", params=self._params(bot=bot, exchange=exchange, pair=pair))

    async def get_markets(self) -> List[Dict[str, Any]]:
        """Markets the market recorder sampled in the last day."""
        return await self._get("/metrics/markets")

    async def get_feeds(self) -> List[Dict[str, Any]]:
        """Per market, the latest sample and the seconds since its order book last changed."""
        return await self._get("/metrics/feeds")

    async def get_market(self, exchange: str, pair: str, minutes: int = 60, end: End = None) -> List[Dict[str, Any]]:
        """One market over time: best bid and ask, mid price, spread %, depth within 1% of mid, order book age."""
        return await self._get("/metrics/market",
                               params=self._params(exchange=exchange, pair=pair, minutes=minutes, end=end))

    async def get_accounts(self) -> List[Dict[str, Any]]:
        """Accounts an account monitor wrote about in the last day, each with its latest update (age_s, errors)."""
        return await self._get("/metrics/accounts")

    async def get_balances(self, account: str, exchange: str, minutes: int = 360, end: End = None) -> Dict[str, Any]:
        """One account's balances: `latest` per asset, and `history` (total and available per asset over time)."""
        return await self._get("/metrics/balances",
                               params=self._params(account=account, exchange=exchange, minutes=minutes, end=end))

    async def get_account_orders(self, account: str, exchange: str) -> Dict[str, Any]:
        """One account's open orders now, whoever placed them, with snapshot_age_s and the latest error."""
        return await self._get("/metrics/account-orders", params=self._params(account=account, exchange=exchange))

    async def get_fills(self, account: str, exchange: str, minutes: int = 1440, end: End = None,
                        pair: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
        """One account's fills in the window, newest first."""
        params = self._params(account=account, exchange=exchange, minutes=minutes, end=end, pair=pair, limit=limit)
        return await self._get("/metrics/fills", params=params)
