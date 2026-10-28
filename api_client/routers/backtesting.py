from typing import Any, Dict, List, Optional

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
        """Run a backtesting simulation with the provided configuration."""
        payload = {
            "start_time": start_time,
            "end_time": end_time,
            "backtesting_resolution": backtesting_resolution,
            "trade_cost": trade_cost,
            "config": config or {}
        }
        return await self._post("/backtesting/run-backtesting", json=payload)

    async def list_orderbook_strategies(self) -> List[Dict[str, str]]:
        """List available orderbook backtesting strategies."""
        return await self._get("/backtesting/orderbook-strategies")

    async def run_orderbook_backtest(
        self,
        strategy: str,
        connector: str,
        pair: str,
        start: str,
        end: Optional[str] = None,
        maker_fee: float = 0.001,
        taker_fee: float = 0.001,
        latency_ms: float = 100,
        fill_at_touch: bool = False,
        strategy_args: Optional[Dict[str, Any]] = None,
        config_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run an orderbook-based backtest on recorded market data."""
        payload = {
            "strategy": strategy,
            "connector": connector,
            "pair": pair,
            "start": start,
            "maker_fee": maker_fee,
            "taker_fee": taker_fee,
            "latency_ms": latency_ms,
            "fill_at_touch": fill_at_touch,
        }
        if end is not None:
            payload["end"] = end
        if strategy_args is not None:
            payload["strategy_args"] = strategy_args
        if config_path is not None:
            payload["config_path"] = config_path
        return await self._post("/backtesting/run-orderbook-backtest", json=payload)
