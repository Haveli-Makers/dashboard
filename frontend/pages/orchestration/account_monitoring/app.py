"""
Account Monitoring: one exchange account's balances, open orders, fills and market data, from its account monitor (a
hummingbot bot that never trades and holds the account's keys), read through the api-server's /metrics endpoints.

  Balances      what the account holds now per asset (total, available, in orders), and each asset over time
  Open orders   every open order on the account now, whoever placed it: any bot, or a person
  Fills         the account's trades in the time range
  Market data   the watched pairs' order books over time: best bid and ask, mid, spread, depth, book age

Times are IST. Needs an api-server with monitoring on (INFLUXDB_ENABLED) and an account monitor running.
"""
import asyncio
import math
from typing import Any, Callable, Dict, Iterable, List, Optional

import aiohttp
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from frontend.st_utils import get_backend_api_client, initialize_st_page

TZ = "Asia/Kolkata"
REFRESH_S = 10
RANGES = {"15 min": 15, "1 hour": 60, "6 hours": 360, "24 hours": 1440, "3 days": 4320}
# The monitor reads the account every 5 s by default; this long without an update means it isn't running.
STALE_S = 60
# Checked for colour-blind readers on the dark theme (the same colours as Bot Monitoring).
SIDE_COLORS = {"BUY": "#26a69a", "SELL": "#ef5350"}
SERIES_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#0ca30c", "#9085e9", "#e66767"]
MID_COLOR = "#c3c2b7"


class MonitoringError(Exception):
    """A /metrics call failed. The message says why, in plain words."""


def call(method: Callable, *args, **kwargs):
    """Calls a metrics endpoint. Any failure becomes a MonitoringError with a readable message."""
    try:
        return method(*args, **kwargs)
    except aiohttp.ClientResponseError as e:
        raise MonitoringError(explain(e.status, e.message)) from e
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
        raise MonitoringError(f"The api-server did not answer: {str(e) or type(e).__name__}") from e


def explain(status: int, message: str) -> str:
    if status == 401:
        return "The api-server refused the login. Check this server's username and password in servers.yml."
    if status == 404:
        return "This api-server has no account monitoring endpoints (/metrics/accounts). It needs a newer version."
    return f"The api-server refused the request ({status}): {message}"


# ------------------------------------------------------------------------------------------- formatting helpers

def frame(rows) -> pd.DataFrame:
    return pd.DataFrame(rows or [])


def local(values) -> pd.Series:
    """API times (UTC) in IST, without the zone, so plotly draws them as they are."""
    times = pd.to_datetime(pd.Series(values), utc=True, format="ISO8601")
    return times.dt.tz_convert(TZ).dt.tz_localize(None)


def now_local() -> pd.Timestamp:
    return pd.Timestamp.now(tz=TZ).tz_localize(None)


def clock(times: pd.Series) -> pd.Series:
    """IST times as text: the time of day, with the date when it isn't today."""
    today = now_local().normalize()
    return times.map(lambda t: "" if pd.isna(t) else t.strftime("%H:%M:%S" if t.normalize() == today else "%d %b %H:%M:%S"))


def num(value) -> Optional[float]:
    """A finite float, or None (InfluxDB leaves missing fields out as null)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def text(value) -> str:
    """A label, or "" when missing (pandas turns a missing string into NaN, which would print as "nan")."""
    return "" if value is None or (isinstance(value, float) and math.isnan(value)) else str(value)


def duration(seconds) -> str:
    seconds = int(max(num(seconds) or 0, 0))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours >= 24:
        return f"{hours // 24} d {hours % 24} h"
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min {secs} s" if minutes else f"{secs} s"


def price_digits(values: Iterable) -> int:
    """Decimals that show about five significant digits of a typical price: 2 for 3,000.00, 5 for 0.35000."""
    prices = sorted(abs(number) for number in map(num, values) if number)
    if not prices:
        return 2
    return min(10, max(2, 4 - math.floor(math.log10(prices[len(prices) // 2]))))


def fmt_price(value, digits: int) -> str:
    number = num(value)
    return "–" if number is None else f"{number:,.{digits}f}"


def fmt_amount(value) -> str:
    number = num(value)
    return "–" if number is None else (f"{number:,.8f}".rstrip("0").rstrip(".") or "0")


def fmt_quote(value, digits: int = 2) -> str:
    number = num(value)
    return "–" if number is None else f"{number:,.{digits}f}"


def legend_below(height: int) -> Dict[str, Any]:
    """A horizontal legend under the x axis: at the top it collides with the chart's toolbar."""
    return dict(orientation="h", yanchor="top", y=-70 / max(height - 100, 100), x=0, traceorder="normal", title_text="")


def line_chart(data: pd.DataFrame, y: str, title: str, **kwargs) -> go.Figure:
    chart = px.line(data, x="time", y=y, title=title, **kwargs)
    chart.update_traces(line=dict(width=2))
    chart.update_layout(height=260, margin=dict(l=0, r=0, t=40, b=0), xaxis_title="", yaxis_title="",
                        legend=legend_below(260), hovermode="x unified")
    return chart


# ------------------------------------------------------------------------------------------------------ views

def status_line(metrics: Any, account: str, exchange: str):
    """When the account monitor last wrote, what it could read, and its last error."""
    try:
        rows = call(metrics.get_accounts)
    except MonitoringError as e:
        st.error(str(e))
        return
    row = next((row for row in rows if row.get("account") == account and row.get("exchange") == exchange), None)
    if row is None:
        st.warning("This account's monitor hasn't written in the last day.")
        return
    age = num(row.get("age_s"))
    if age is not None and age > STALE_S:
        st.warning(f"The account monitor hasn't written for {duration(age)}: is it running?")
    if text(row.get("error")):
        st.warning(f"Its last update had a problem: {row['error']}")
    unread = [what for what, key in (("balances", "balances_ok"), ("open orders", "orders_ok"), ("fills", "fills_ok"))
              if row.get(key) is False]
    st.caption(f"Account monitor: updated {duration(age)} ago · {int(num(row.get('assets')) or 0)} assets with a balance"
               + (f" · {int(num(row.get('open_orders')) or 0)} open orders" if row.get("orders_ok") else "")
               + (f" · couldn't read {', '.join(unread)}" if unread else ""))


def balances_view(metrics: Any, account: str, exchange: str, minutes: int):
    try:
        data = call(metrics.get_balances, account=account, exchange=exchange, minutes=minutes)
    except MonitoringError as e:
        st.error(str(e))
        return
    latest, history = frame(data.get("latest")), frame(data.get("history"))
    if latest.empty and history.empty:
        st.info("No balances in this window.")
        return
    if not latest.empty:
        total = latest["total"].map(num)
        available = latest["available"].map(num)
        st.dataframe(pd.DataFrame({
            "Asset": latest["asset"],
            "Total": total.map(fmt_amount),
            "Available": available.map(fmt_amount),
            "In orders": (total - available).map(lambda value: fmt_amount(max(value, 0)) if num(value) is not None else "–"),
        }), hide_index=True, width="stretch")
        st.caption(f"As of {clock(local(latest['time'])).max()}. Assets at zero are left out. \"In orders\" is the part "
                   "held by open orders.")
    if history.empty:
        return
    assets = sorted(history["asset"].unique())
    asset = st.selectbox("Asset over time", assets, key="am_balance_asset", persist_state="page")
    series = history[history["asset"] == asset].copy()
    series["time"] = local(series["time"])
    lines = series.melt(id_vars="time", value_vars=["total", "available"], var_name="balance", value_name="amount")
    lines["balance"] = lines["balance"].map({"total": "Total", "available": "Available"})
    st.plotly_chart(line_chart(lines, "amount", f"{asset} balance", color="balance",
                               color_discrete_sequence=SERIES_COLORS[:2]), width="stretch", key="am_balance_chart")


def latest_mids(metrics: Any, exchange: str) -> Dict[str, float]:
    """The latest mid price per pair of this exchange, from the market samples; empty if there are none."""
    try:
        feeds = call(metrics.get_feeds)
    except MonitoringError:
        return {}
    return {row["pair"]: num(row.get("mid_price")) for row in feeds or []
            if row.get("exchange") == exchange and num(row.get("mid_price"))}


def orders_view(metrics: Any, account: str, exchange: str, minutes: int):
    try:
        data = call(metrics.get_account_orders, account=account, exchange=exchange)
    except MonitoringError as e:
        st.error(str(e))
        return
    age, orders = data.get("snapshot_age_s"), frame(data.get("orders"))
    if age is None:
        st.info("The account monitor hasn't read the open orders yet."
                + (f" Its last update said: {data['error']}" if data.get("error") else ""))
        return
    read = f"read from the exchange {duration(age)} ago"
    if orders.empty:
        st.markdown("**Open orders:** none right now.")
        st.caption(f"The account's open orders, {read}.")
        return
    mids = latest_mids(metrics, exchange)
    digits = price_digits(orders["price"])
    now_ms = pd.Timestamp.now(tz="UTC").timestamp() * 1000
    created = orders["created_ms"] if "created_ms" in orders else pd.Series([None] * len(orders))
    st.markdown(f"**Open orders ({len(orders)})**")
    st.dataframe(pd.DataFrame({
        "Pair": orders["pair"],
        "Side": orders["side"],
        "Price": orders["price"].map(lambda price: fmt_price(price, digits)),
        "From mid": [f"{(num(price) / mids[pair] - 1) * 100:+.3f}%" if pair in mids and num(price) else "–"
                     for price, pair in zip(orders["price"], orders["pair"])],
        "Amount": orders["amount"].map(fmt_amount),
        "Filled": orders["filled"].map(fmt_amount) if "filled" in orders else "–",
        "Value (quote)": [fmt_quote((num(price) or 0) * (num(amount) or 0)) for price, amount
                          in zip(orders["price"], orders["amount"])],
        "Open for": [duration((now_ms - num(ms)) / 1000) if num(ms) else "–" for ms in created],
        "Order id": orders["order_id"].map(text),
        "Client order id": orders["client_order_id"].map(text) if "client_order_id" in orders else "",
    }), hide_index=True, width="stretch")
    st.caption(f"Every open order on the account, {read}, whoever placed it: any bot, or a person. Highest price "
               "first. An order that lives shorter than the monitor's update interval may never show here; its fills "
               "do show under Fills.")


def fills_view(metrics: Any, account: str, exchange: str, minutes: int):
    try:
        fills = frame(call(metrics.get_fills, account=account, exchange=exchange, minutes=minutes))
    except MonitoringError as e:
        st.error(str(e))
        return
    if fills.empty:
        st.info("No fills in this window.")
        return
    fills["time"] = local(fills["time"])
    for column in ("price", "amount", "quote_amount", "fee"):
        fills[column] = fills[column].map(num) if column in fills else None
    summary = []
    for pair, rows in fills.groupby("pair"):
        buys, sells = rows[rows["side"] == "BUY"], rows[rows["side"] == "SELL"]
        summary.append({"Pair": pair, "Fills": len(rows), "Bought": fmt_amount(buys["amount"].sum()),
                        "Spent (quote)": fmt_quote(buys["quote_amount"].sum()), "Sold": fmt_amount(sells["amount"].sum()),
                        "Received (quote)": fmt_quote(sells["quote_amount"].sum()),
                        "Fees": fmt_amount(rows["fee"].sum())})
    st.dataframe(pd.DataFrame(summary), hide_index=True, width="stretch")
    digits = price_digits(fills["price"])
    st.dataframe(pd.DataFrame({
        "Time": clock(fills["time"]),
        "Pair": fills["pair"],
        "Side": fills["side"],
        "Price": fills["price"].map(lambda price: fmt_price(price, digits)),
        "Amount": fills["amount"].map(fmt_amount),
        "Value (quote)": fills["quote_amount"].map(fmt_quote),
        "Fee": fills["fee"].map(fmt_amount),
        "Order id": fills["order_id"].map(text) if "order_id" in fills else "",
        "Trade id": fills["trade_id"].map(text),
    }), hide_index=True, width="stretch")
    st.caption(f"{len(fills)} fills in this window, newest first, from the exchange's trade history. Values and fees "
               "are in each pair's quote currency.")


def feed_status(book_age: Any, sample_age: Any) -> str:
    book_age, sample_age = num(book_age), num(sample_age)
    if sample_age is not None and sample_age >= 10:
        return f"🔴 no new samples for {duration(sample_age)}"
    if book_age is not None and book_age >= 30:
        return f"🟠 order book unchanged for {duration(book_age)}"
    return "🟢 OK"


def price_chart(series: pd.DataFrame, digits: int) -> go.Figure:
    figure = go.Figure()
    for column, name, color, dash in (("best_bid", "best bid", SIDE_COLORS["BUY"], None),
                                      ("best_ask", "best ask", SIDE_COLORS["SELL"], None),
                                      ("mid_price", "mid", MID_COLOR, "dot")):
        if column in series and series[column].notna().any():
            figure.add_trace(go.Scatter(x=series["time"], y=series[column], mode="lines", name=name,
                                        line=dict(color=color, width=1.5, dash=dash)))
    figure.update_layout(title="Best bid, best ask and mid", height=300, margin=dict(l=0, r=0, t=40, b=0),
                         legend=legend_below(300), hovermode="x unified")
    figure.update_yaxes(tickformat=f",.{digits}f")
    return figure


def market_view(metrics: Any, account: str, exchange: str, minutes: int):
    try:
        feeds = frame(call(metrics.get_feeds))
        markets = [market for market in call(metrics.get_markets) or [] if market.get("exchange") == exchange]
    except MonitoringError as e:
        st.error(str(e))
        return
    if not markets:
        st.info(f"No market data from {exchange} in the last day. The account monitor samples the order books of the "
                "pairs in its config every second.")
        return
    feeds = feeds[feeds["exchange"] == exchange] if not feeds.empty else feeds
    if not feeds.empty:
        feeds = feeds.sort_values("pair")
        sample_ages = feeds["sample_age_s"] if "sample_age_s" in feeds else [None] * len(feeds)
        st.dataframe(pd.DataFrame({
            "Pair": feeds["pair"],
            "Mid": [fmt_price(value, price_digits([value])) for value in feeds["mid_price"]],
            "Spread": feeds["spread_pct"].map(lambda value: "–" if num(value) is None else f"{num(value):.4f}%"),
            "Order book last changed": feeds["book_age_s"].map(lambda age: f"{duration(age)} ago"),
            "Feed": [feed_status(book, sample) for book, sample in zip(feeds["book_age_s"], sample_ages)],
        }), hide_index=True, width="stretch")
    pairs = [market["pair"] for market in markets]
    pair = st.selectbox("Pair", pairs, key="am_market_pair", persist_state="page")
    try:
        series = frame(call(metrics.get_market, exchange=exchange, pair=pair, minutes=minutes))
    except MonitoringError as e:
        st.error(str(e))
        return
    if series.empty:
        st.caption("No samples of this pair in this window.")
        return
    series["time"] = local(series["time"])
    digits = price_digits(series["mid_price"])
    st.plotly_chart(price_chart(series, digits), width="stretch", key="am_price_chart")
    left, right = st.columns(2)
    with left:
        chart = line_chart(series, "spread_pct", "Spread %", color_discrete_sequence=SERIES_COLORS[:1])
        chart.update_yaxes(tickformat=".4f")
        st.plotly_chart(chart, width="stretch", key="am_spread_chart")
        st.plotly_chart(line_chart(series, "book_age_s", "Seconds since the order book last changed",
                                   color_discrete_sequence=[MID_COLOR]), width="stretch", key="am_age_chart")
    with right:
        depth = series.melt(id_vars="time", value_vars=["bid_depth_1pct", "ask_depth_1pct"], var_name="side",
                            value_name="quote")
        depth["side"] = depth["side"].map({"bid_depth_1pct": "bids within 1%", "ask_depth_1pct": "asks within 1%"})
        st.plotly_chart(line_chart(depth, "quote", "Depth within 1% of mid (quote)", color="side",
                                   color_discrete_map={"bids within 1%": SIDE_COLORS["BUY"],
                                                       "asks within 1%": SIDE_COLORS["SELL"]}),
                        width="stretch", key="am_depth_chart")
    st.caption("Sampled every second from the live order book that the account monitor keeps for each watched pair.")


# ---------------------------------------------------------------------------------------------------------- page

def monitoring_ready(metrics: Any) -> bool:
    """False, after saying why on the page, when this api-server can't serve monitoring."""
    try:
        health = call(metrics.get_health)
    except MonitoringError as e:
        st.error(str(e))
        return False
    if not health.get("enabled"):
        st.warning("Monitoring is off on this api-server. In the api-server folder run `make monitoring`, add the lines "
                   "it prints to `.env`, and restart the API.")
        return False
    if not health.get("influxdb_reachable"):
        st.error(f"The api-server can't reach InfluxDB: {health.get('influxdb_error')}")
        return False
    return True


def load_accounts(metrics: Any) -> Optional[List[Dict[str, Any]]]:
    try:
        return call(metrics.get_accounts) or []
    except MonitoringError as e:
        st.error(str(e))
        return None


initialize_st_page(icon="🏦", show_readme=False)
backend_api_client = get_backend_api_client()

st.title("🏦 Account Monitoring")
st.caption("Balances, open orders, fills and market data of an exchange account, from its account monitor: a bot that "
           "never trades, holding the account's keys. Times are IST.")

metrics_router = getattr(backend_api_client, "metrics", None)
if metrics_router is None:  # a client made before this page existed; a new browser session makes a new one
    st.error("Reload this browser tab: the API client in this session was made before account monitoring was added.")
    st.stop()
if not monitoring_ready(metrics_router):
    st.button("Try again")
    st.stop()
accounts = load_accounts(metrics_router)
if accounts is None:
    st.stop()
if not accounts:
    st.info("No account monitor has written in the last day. Start hummingbot's `account_monitor` script with the "
            "account's keys and the INFLUXDB_* settings; the account shows up here a few seconds later.")
    st.button("Check again")
    st.stop()

names = [f"{account['account']} · {account['exchange']}" for account in accounts]
picked = st.selectbox("Account", names, key="am_account")
account = accounts[names.index(picked)]
range_column, live_column = st.columns([4, 1])
range_label = range_column.segmented_control("Time range", list(RANGES), default="1 hour", required=True,
                                             key="am_range")
live = live_column.toggle(f"Live, every {REFRESH_S} s", value=True, key="am_live",
                          help="Pause it to read the tables without them moving.")
window = RANGES[range_label]
refresh = REFRESH_S if live else None
st.fragment(status_line, run_every=refresh)(metrics_router, account["account"], account["exchange"])

tabs = st.tabs(["Balances", "Open orders", "Fills", "Market data"], key="am_tab", on_change="rerun")
for tab, view in zip(tabs, (balances_view, orders_view, fills_view, market_view)):
    if tab.open is False:  # only the open tab runs, so only it polls the api-server
        continue
    with tab:
        try:  # one broken view must not blank the page
            st.fragment(view, run_every=refresh)(metrics_router, account["account"], account["exchange"], window)
        except Exception as e:
            st.exception(e)
