"""Per-controller-type rendering of live streamed data on the Instances bot cards.

The payload shape published on the broker topics varies by ``controller_type``, so each type gets
its own render function. ``render_controller_live`` dispatches by type and falls back to a generic
renderer for unknown types.

``controller_meta`` carries the REST-sourced structural fields (name / connector / trading_pair /
kill_switch). ``stream`` is the per-controller snapshot from ``bot_stream.get_bot_data`` and looks
like ``{"account_data": {...}, "market_data": {...}, "performance_data": {...}, "_age": float}``.
"""

import pandas as pd
import streamlit as st


def _normalize_type(controller_type: str) -> str:
    """Lowercase and strip non-alphanumerics so 'Spread Killer'/'spread_killer' all match."""
    return "".join(ch for ch in (controller_type or "").lower() if ch.isalnum())


def render_controller_live(controller_type, controller_meta, stream):
    """Dispatch to the controller-type-specific live renderer."""
    if _normalize_type(controller_type) == "spreadkiller":
        render_spreadkiller(controller_meta, stream)
    else:
        render_generic(controller_meta, stream)


def _controller_header(controller_meta, stream):
    """Shared header line: controller name, pair, and a live/stale badge."""
    name = controller_meta.get("controller_name", "Controller")
    connector = controller_meta.get("connector_name", "N/A")
    pair = controller_meta.get("trading_pair", "N/A")
    age = stream.get("_age") if stream else None
    if age is None:
        badge = "🔴 no stream"
    elif age > 8.0:
        badge = f"🟡 stale ({age:.0f}s)"
    else:
        badge = "🟢 live"
    st.markdown(f"**{name}** · {connector} · {pair} — {badge}")


def render_spreadkiller(controller_meta, stream):
    """Live panel for the Spreadkiller controller type."""
    _controller_header(controller_meta, stream)

    if not stream:
        st.caption("Waiting for live data…")
        return

    market = stream.get("market_data", {})
    perf = stream.get("performance_data", {})
    account = stream.get("account_data", {})

    # Market data
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Mid Price", _fmt(market.get("mid_price")))
    c2.metric("Best Bid", _fmt(market.get("best_bid")))
    c3.metric("Best Ask", _fmt(market.get("best_ask")))
    c4.metric("Spread", _fmt(market.get("spread")))

    # Performance data
    buy_vol = perf.get("buy_volume_quote", 0) or 0
    sell_vol = perf.get("sell_volume_quote", 0) or 0
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Total PNL ($)", _fmt(perf.get("total_pnl_quote")))
    p2.metric("Unrealized PNL ($)", _fmt(perf.get("unrealized_pnl_quote")))
    p3.metric("Realized PNL ($)", _fmt(perf.get("realized_pnl_quote")))
    p4.metric("Return (%)", _fmt_pct(perf.get("return_pct")))

    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Trades", perf.get("num_trades", 0))
    q2.metric("Volume ($)", _fmt(buy_vol + sell_vol))
    q3.metric("Net Exposure", _fmt(account.get("net_exposure")))
    q4.metric("Current Price", _fmt(perf.get("current_price")))

    # Active orders
    active_orders = account.get("active_orders") or []
    if active_orders:
        st.caption("Active Orders")
        orders_df = pd.DataFrame([
            {
                "Side": o.get("side"),
                "Amount": o.get("amount"),
                "Price Diff": o.get("price_diff"),
                "Order ID": o.get("order_id"),
            }
            for o in active_orders
        ])
        st.dataframe(orders_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No active orders")


def render_generic(controller_meta, stream):
    """Fallback live panel for controller types without a dedicated layout."""
    _controller_header(controller_meta, stream)

    if not stream:
        st.caption("Waiting for live data…")
        return

    for kind in ("market_data", "performance_data", "account_data"):
        payload = stream.get(kind)
        if not payload:
            continue
        with st.expander(kind.replace("_", " ").title(), expanded=(kind == "performance_data")):
            st.json(payload)


def _fmt(value):
    """Format a numeric value to 2 decimals, passing through None/non-numerics."""
    if value is None:
        return "—"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_pct(value):
    if value is None:
        return "—"
    try:
        return f"{float(value):.2%}"
    except (TypeError, ValueError):
        return str(value)
