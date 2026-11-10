from typing import Any, Dict, Optional

from .base import BaseRouter


class BacktestingRouter(BaseRouter):
    """Backtesting router for running backtesting simulations."""

    async def run_backtesting(
        self,
        start_time: int,
        end_time: int,
        backtesting_resolution: str = "1m",
        trade_cost: float = 0.0006,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Run a candle-based backtesting simulation."""
        payload = {
            "start_time": start_time,
            "end_time": end_time,
            "backtesting_resolution": backtesting_resolution,
            "trade_cost": trade_cost,
            "config": config or {}
        }
        return await self._post("/backtesting/run-backtesting", json=payload)

    async def run_controller_orderbook_backtest(
        self,
        connector: str,
        pair: str,
        start: str,
        end: Optional[str] = None,
        maker_fee: float = 0.001,
        taker_fee: float = 0.001,
        latency_ms: float = 100,
        fill_at_touch: bool = False,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run any strategy_v2 controller against recorded orderbook + trade data."""
        payload = {
            "connector": connector,
            "pair": pair,
            "start": start,
            "maker_fee": maker_fee,
            "taker_fee": taker_fee,
            "latency_ms": latency_ms,
            "fill_at_touch": fill_at_touch,
            "config": config or {},
        }
        if end is not None:
            payload["end"] = end
        return await self._post("/backtesting/run-controller-orderbook-backtest", json=payload)
