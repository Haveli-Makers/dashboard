"""
Bot Monitoring: what the bots write to InfluxDB, read through the api-server's /metrics endpoints.

  Bot health       every bot now (running, hung, down, stopped), its uptime, a timeline, incidents and status changes
  Orders vs price  one bot: its bid/ask and mid, each order as a line from placed to filled or cancelled, its fills
                   (partial and final) and grid reference, and its open orders and PnL right now
  PnL              PnL and volume per bot and controller
  Market data      order book health per market, from the market recorder

Times are IST. Needs an api-server with bot monitoring on (INFLUXDB_ENABLED); see the api-server README.
"""
import asyncio
import math
from collections import Counter
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import aiohttp
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from frontend.st_utils import get_backend_api_client, initialize_st_page

TZ = "Asia/Kolkata"
REFRESH_S = 10
RANGES = {"15 min": 15, "1 hour": 60, "6 hours": 360, "24 hours": 1440, "3 days": 4320}
# Checked for colour-blind readers on the dark theme. Buys and sells also differ in shape (fills) and place (orders).
SIDE_COLORS = {"BUY": "#26a69a", "SELL": "#ef5350"}
STATE_COLORS = {"up": "#0ca30c", "down": "#d03b3b"}
SERIES_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#0ca30c", "#9085e9", "#e66767"]
SURFACE, MID_COLOR, BAND_COLOR, REFERENCE_COLOR = "#0e1117", "#c3c2b7", "rgba(195,194,183,0.14)", "#9085e9"
LEVEL_NAMES = {"strategy": "strategy loop", "process": "process"}
KIND_NAMES = {"hang": "Hang: process alive, strategy loop frozen",
              "crash": "Crash: the process stopped too",
              "no heartbeat": "Process heartbeat lost, strategy loop still running"}
OUTCOME_NAMES = {"open": "still open", "filled": "filled", "cancelled": "cancelled", "failed": "failed",
                 "expired": "expired", "gone": "gone (no end event)"}
CHANGE_ICONS = {"down": "🔴", "up": "🟢", "stopped": "⚪", "started": "▶️"}
NOW_LABELS = {"running": "🟢 running", "hung": "🟠 hung", "down": "🔴 down", "stopped": "⚪ stopped",
              "no process heartbeat": "🟡 running, no process heartbeat", "unknown": "❔ no recent data"}
PNL_METRICS = {"Global PnL": "global_pnl_quote", "Realized PnL": "realized_pnl_quote",
               "Unrealized PnL": "unrealized_pnl_quote", "Volume traded": "volume_traded"}
# The health watcher writes every few seconds; a bot it hasn't written about for this long is stopped or not watched.
FRESH_S = 30
# Hover points above this many go to WebGL, which stays fast with tens of thousands.
WEBGL_POINTS = 4000


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
        return "This api-server has no bot monitoring endpoints (/metrics). It needs the version with InfluxDB monitoring."
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


def fmt_quote(value, signed: bool = False, digits: int = 4) -> str:
    number = num(value)
    if number is None:
        return "–"
    return f"{number:+,.{digits}f}" if signed else f"{number:,.{digits}f}"


def legend_below(height: int) -> Dict[str, Any]:
    """A horizontal legend under the x axis: at the top it collides with the chart's toolbar."""
    return dict(orientation="h", yanchor="top", y=-70 / max(height - 100, 100), x=0, traceorder="normal", title_text="")


def short_message(bot: str, message: Any) -> str:
    """Watcher messages start with the bot's name; a table that already has a Bot column doesn't need it twice."""
    message = str(message or "")
    return message[len(bot) + 2:] if message.startswith(f"{bot}: ") else message


# ---------------------------------------------------------------------------------------------------- bot health

def bot_state(bot: str, timeline: pd.DataFrame, latest_change: Optional[pd.Series], now: pd.Timestamp) -> str:
    """
    running, hung, down, stopped, no process heartbeat or unknown, from the watcher's ongoing up/down periods. A clean
    stop newer than those periods wins: the watcher stops writing then, but its last period still looks fresh for a
    while.
    """
    stopped = latest_change is not None and latest_change.get("state") == "stopped"
    stopped_at = latest_change.get("time") if stopped else None
    if not timeline.empty:
        rows = timeline[(timeline["bot"] == bot) & timeline["ongoing"].astype(bool)]
        stopped_since = stopped_at is not None and not rows.empty and stopped_at >= rows["start"].max()
        if not rows.empty and rows["end"].max() >= now - pd.Timedelta(seconds=FRESH_S) and not stopped_since:
            states = dict(zip(rows["level"], rows["state"]))
            strategy, process = states.get("strategy"), states.get("process")
            if strategy == "down":
                return "hung" if process == "up" else "down"
            if process == "down":
                return "no process heartbeat" if strategy == "up" else "down"
            return "running"
    if latest_change is not None and latest_change.get("state") in ("stopped", "down"):
        return latest_change["state"]
    return "unknown"


def bot_overview(uptime: pd.DataFrame, timeline: pd.DataFrame, incidents: pd.DataFrame, changes: pd.DataFrame,
                 now: pd.Timestamp) -> pd.DataFrame:
    bots = sorted({*uptime.get("bot", []), *timeline.get("bot", []), *changes.get("bot", [])})
    rows = []
    for bot in bots:
        pct = uptime[uptime["bot"] == bot].set_index("level")["uptime_pct"] if not uptime.empty else pd.Series(dtype=float)
        mine = changes[changes["bot"] == bot] if not changes.empty else changes
        latest = mine.iloc[0] if not mine.empty else None  # newest first
        rows.append({
            "Bot": bot,
            "Now": NOW_LABELS[bot_state(bot, timeline, latest, now)],
            "Strategy loop uptime": num(pct.get("strategy")),
            "Process uptime": num(pct.get("process")),
            "Incidents": int((incidents["bot"] == bot).sum()) if not incidents.empty else 0,
            "Last change": "" if latest is None else
            f"{clock(pd.Series([latest['time']])).iloc[0]} · {short_message(bot, latest.get('message'))}",
        })
    return pd.DataFrame(rows)


def timeline_chart(timeline: pd.DataFrame, minutes: int, now: pd.Timestamp) -> go.Figure:
    data = timeline.copy()
    data["series"] = data["bot"] + " · " + data["level"].map(lambda level: LEVEL_NAMES.get(level, level))
    data["lasted"] = data["duration_s"].map(duration)
    order = sorted(data["series"].unique())
    chart = px.timeline(data, x_start="start", x_end="end", y="series", color="state", color_discrete_map=STATE_COLORS,
                        category_orders={"series": order, "state": ["up", "down"]},
                        hover_data={"lasted": True, "series": False})
    chart.update_traces(offsetgroup="state", alignmentgroup="state")
    height = 120 + 34 * len(order)
    chart.update_layout(barmode="overlay", height=height, margin=dict(l=0, r=0, t=10, b=0), legend=legend_below(height),
                        xaxis_title="", yaxis_title="")
    chart.update_xaxes(range=[now - pd.Timedelta(minutes=minutes), now])
    return chart


def health_view(metrics: Any, minutes: int):
    try:
        uptime = frame(call(metrics.get_uptime, minutes=minutes))
        timeline = frame(call(metrics.get_uptime_timeline, minutes=minutes))
        incidents = frame(call(metrics.get_incidents, minutes=minutes))
        changes = frame(call(metrics.get_status_changes, minutes=minutes, limit=200))
    except MonitoringError as e:
        st.error(str(e))
        return
    if uptime.empty and timeline.empty and changes.empty:
        st.info("No bot health data in this window. The api-server's health watcher writes it every 5 seconds while a "
                "bot with monitoring on is running.")
        return
    now = now_local()
    for table, columns in ((timeline, ("start", "end")), (incidents, ("start", "end")), (changes, ("time",))):
        for column in columns if not table.empty else ():
            table[column] = local(table[column])

    st.caption("**strategy loop**: heartbeat from the bot's strategy loop, every second. **process**: heartbeat from a "
               "background thread, every 5 seconds. Loop silent while the process beats: hung. Both silent: down. "
               "A bot stopped on purpose counts as stopped, and that time is left out of its uptime.")
    # A neutral bar: uptime is an amount. The Now column and the incident count carry the alarm.
    uptime_column = st.column_config.ProgressColumn(format="%.2f%%", min_value=0, max_value=100, color=SERIES_COLORS[0])
    st.dataframe(bot_overview(uptime, timeline, incidents, changes, now), hide_index=True, width="stretch",
                 column_config={"Strategy loop uptime": uptime_column, "Process uptime": uptime_column,
                                "Incidents": st.column_config.NumberColumn(help="Down periods in this window")})
    if not timeline.empty:
        st.plotly_chart(timeline_chart(timeline, minutes, now), width="stretch", key="bm_timeline_chart")
        st.caption("Gaps: the bot was stopped, or not running yet.")

    st.subheader("Incidents")
    if incidents.empty:
        st.caption("None in this window.")
    else:
        st.dataframe(pd.DataFrame({
            "Started": clock(incidents["start"]),
            "Bot": incidents["bot"],
            "What happened": incidents["kind"].map(lambda kind: KIND_NAMES.get(kind, kind)),
            "Lasted": incidents["duration_s"].map(duration)
            + incidents["ongoing"].map(lambda ongoing: " (ongoing)" if ongoing else ""),
        }), hide_index=True, width="stretch")
    st.subheader("Status changes")
    if changes.empty:
        st.caption("None in this window.")
    else:
        st.dataframe(pd.DataFrame({
            "Time": clock(changes["time"]),
            "Bot": changes["bot"],
            "Change": [f"{CHANGE_ICONS.get(state, '')} {short_message(bot, message)}".strip()
                       for bot, state, message in zip(changes["bot"], changes["state"], changes["message"])],
        }), hide_index=True, width="stretch")


# ---------------------------------------------------------------------------------------------- orders vs price

def pick_order(order_id: Optional[str]):
    """Opens an order in the details below the chart. Runs before the "Inspect an order" box, or as a callback."""
    st.session_state["bm_inspect"] = order_id


def forget_order():
    """A different bot or market: close the order details and forget the last chart click."""
    pick_order(None)
    st.session_state.pop("bm_last_click", None)


def orders_figure(data: Dict, minutes: int, digits: int, revision: str) -> Tuple[go.Figure, Dict[int, List[str]]]:
    """The chart, plus {trace number: order id per point}, so a click can be traced back to its order."""
    figure = go.Figure()
    pick_map: Dict[int, List[str]] = {}
    price = frame(data.get("price"))
    mids = None
    if not price.empty:
        price["time"] = local(price["time"])
        figure.add_trace(go.Scatter(x=price["time"], y=price["best_ask"], mode="lines", line=dict(width=0),
                                    hoverinfo="skip", showlegend=False))
        figure.add_trace(go.Scatter(x=price["time"], y=price["best_bid"], mode="lines", line=dict(width=0),
                                    fill="tonexty", fillcolor=BAND_COLOR, name="bid/ask", hoverinfo="skip"))
        figure.add_trace(go.Scatter(x=price["time"], y=price["mid_price"], mode="lines", name="mid price",
                                    line=dict(color=MID_COLOR, width=1.5),
                                    hovertemplate=f"mid %{{y:,.{digits}f}}<extra></extra>"))
        mids = price[["time", "mid_price"]].dropna().sort_values("time")
        mids["time"] = mids["time"].astype("datetime64[ns]")  # merge_asof needs one time resolution on both sides
    reference = frame(data.get("reference"))
    if not reference.empty:
        figure.add_trace(go.Scatter(x=local(reference["time"]), y=reference["reference_price"], mode="lines",
                                    line=dict(color=REFERENCE_COLOR, width=1.5, dash="dash", shape="hv"),
                                    name="grid reference",
                                    hovertemplate=f"grid reference %{{y:,.{digits}f}}<extra></extra>"))

    segments = frame(data.get("segments"))
    if not segments.empty:
        segments = segments[segments["price"].notna()]  # market orders have no price
    if not segments.empty:
        segments["start"], segments["end"] = local(segments["start"]), local(segments["end"])
        step = pd.Timedelta(seconds=max(5.0, minutes * 60 / 90))
        for side, name in (("BUY", "buy orders"), ("SELL", "sell orders")):
            rows = segments[segments["side"] == side]
            if rows.empty:
                continue
            xs, ys, hover = [], [], []
            for row in rows.itertuples():
                xs += [row.start, row.end, None]
                ys += [row.price, row.price, None]
                amount, outcome = num(getattr(row, "amount", None)), text(getattr(row, "outcome", None))
                count = max(2, int((row.end - row.start) / step) + 1)
                for i in range(count):
                    hover.append({
                        "time": row.start + (row.end - row.start) * (i / (count - 1)), "order_id": row.order_id,
                        "level": text(getattr(row, "level", None)), "side": side, "price": row.price,
                        "amount_text": fmt_amount(amount), "value_text": fmt_quote(row.price * amount if amount else None),
                        "outcome": OUTCOME_NAMES.get(outcome, outcome), "placed": row.start.strftime("%H:%M:%S"),
                        "ended": "still open" if outcome == "open" else row.end.strftime("%H:%M:%S"),
                        "lasted": duration((row.end - row.start).total_seconds())})
            figure.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name=name, hoverinfo="skip",
                                        line=dict(color=SIDE_COLORS[side], width=3)))
            points = pd.DataFrame(hover).sort_values("time")
            points["time"] = points["time"].astype("datetime64[ns]")
            if mids is not None and not mids.empty:
                points = pd.merge_asof(points, mids, on="time", direction="nearest")
                points["from_mid"] = ((points["price"] / points["mid_price"] - 1) * 100).map(lambda d: f"{d:+.3f}%")
            else:
                points["from_mid"] = "?"
            points["price_text"] = points["price"].map(lambda p: fmt_price(p, digits))
            pick_map[len(figure.data)] = list(points["order_id"])
            # Nearly invisible markers along each order line carry its tooltip; the line itself can't be hovered.
            marker_trace = go.Scattergl if len(points) > WEBGL_POINTS else go.Scatter
            figure.add_trace(marker_trace(
                x=points["time"], y=points["price"], mode="markers", showlegend=False,
                marker=dict(size=10, color=SIDE_COLORS[side], opacity=0.01),
                customdata=points[["order_id", "level", "side", "price_text", "amount_text", "value_text", "outcome",
                                   "placed", "ended", "lasted", "from_mid"]].values,
                hovertemplate=("<b>%{customdata[2]} %{customdata[1]}</b> · %{customdata[6]}<br>"
                               "price %{customdata[3]} (%{customdata[10]} from mid)<br>"
                               "amount %{customdata[4]} ≈ %{customdata[5]} quote<br>"
                               "placed %{customdata[7]} · ended %{customdata[8]} · lasted %{customdata[9]}<br>"
                               "%{customdata[0]} · click for details<extra></extra>")))

    fills = frame(data.get("fills"))
    if not fills.empty:
        fills = fills[fills["price"].notna()]
    if not fills.empty:
        fills["time"] = local(fills["time"])
        partial = fills["partial"].fillna(False).astype(bool) if "partial" in fills else pd.Series(False, index=fills.index)
        for side, symbol in (("BUY", "triangle-up"), ("SELL", "triangle-down")):
            for is_partial in (False, True):
                rows = fills[(fills["side"] == side) & (partial == is_partial)]
                if rows.empty:
                    continue
                labels = pd.DataFrame({
                    "order_id": rows["order_id"], "level": rows.get("level", pd.Series(index=rows.index)).map(text),
                    "price": rows["price"].map(lambda p: fmt_price(p, digits)), "amount": rows["amount"].map(fmt_amount),
                    "pnl": rows.get("realized_pnl", pd.Series(index=rows.index)).map(lambda v: fmt_quote(v, signed=True)),
                })
                pick_map[len(figure.data)] = list(rows["order_id"])
                figure.add_trace(go.Scatter(
                    x=rows["time"], y=rows["price"], mode="markers",
                    name=f"{side.lower()} {'partial fills' if is_partial else 'fills'}",
                    marker=dict(symbol=f"{symbol}-open" if is_partial else symbol, size=13, color=SIDE_COLORS[side],
                                line=dict(color=SIDE_COLORS[side] if is_partial else SURFACE, width=2 if is_partial else 1.5)),
                    customdata=labels.values,
                    hovertemplate=(f"<b>{'partial fill' if is_partial else 'filled'}: {side} %{{customdata[1]}}</b><br>"
                                   "price %{customdata[2]}<br>amount %{customdata[3]}<br>"
                                   "realized PnL %{customdata[4]}<br>%{customdata[0]} · click for details<extra></extra>")))
    figure.update_layout(height=560, margin=dict(l=0, r=0, t=10, b=0), hovermode="closest", uirevision=revision,
                         legend=legend_below(560), yaxis_title="", xaxis_title="")
    figure.update_yaxes(tickformat=f",.{digits}f")
    return figure, pick_map


def handle_click(event: Any, pick_map: Dict[int, List[str]]):
    """
    A click on an order line or a fill opens that order below the chart. Only a new click counts: the chart keeps its
    selection across refreshes, and replaying it would undo a choice made in the "Inspect an order" box.
    """
    points = list(((event or {}).get("selection") or {}).get("points") or [])
    clicked = [(point.get("curve_number"), point.get("point_index", point.get("point_number"))) for point in points]
    if not clicked or clicked == st.session_state.get("bm_last_click"):
        return
    st.session_state["bm_last_click"] = clicked
    for point, (curve, index) in zip(points, clicked):
        order_id = (point.get("customdata") or [None])[0]
        if not order_id:
            ids = pick_map.get(curve, [])
            order_id = ids[index] if index is not None and index < len(ids) else None
        if order_id:
            pick_order(order_id)
            return


def order_details(data: Dict, digits: int):
    segments, fills = data.get("segments") or [], data.get("fills") or []
    if not segments:
        return
    recent = sorted(segments, key=lambda segment: segment["start"], reverse=True)[:80]
    placed = clock(local([segment["start"] for segment in recent]))
    labels = {segment["order_id"]: f"{at} · {segment['side']} {segment.get('level') or ''} @ "
                                   f"{fmt_price(segment['price'], digits)} · "
                                   f"{OUTCOME_NAMES.get(segment['outcome'], segment['outcome'])}"
              for segment, at in zip(recent, placed)}
    current = st.session_state.get("bm_inspect")
    options = [None] + list(labels) + ([current] if current and current not in labels else [])
    picked = st.selectbox("Inspect an order (or click one on the chart)", options, key="bm_inspect", persist_state="page",
                          format_func=lambda order_id: "Pick an order…" if order_id is None else labels.get(order_id, order_id))
    if not picked:
        st.caption("Hover an order line or a fill for a quick look. Pause Live while inspecting, so the chart stays put.")
        return
    segment = next((segment for segment in segments if segment["order_id"] == picked), None)
    header, close = st.columns([6, 1])
    header.markdown(f"**Order `{picked}`**")
    close.button("Close", key="bm_close_details", on_click=pick_order, args=(None,))
    if segment is None:
        st.caption("This order is outside the selected time range.")
        return
    start, end = local([segment["start"], segment["end"]])
    amount = num(segment.get("amount"))
    st.dataframe(pd.DataFrame([{
        "Level": segment.get("level") or "", "Side": segment["side"],
        "Price": "market" if segment["price"] is None else fmt_price(segment["price"], digits),
        "Amount": fmt_amount(amount),
        "Value (quote)": fmt_quote(num(segment["price"]) * amount if amount and num(segment["price"]) else None),
        "Placed": start.strftime("%d %b %H:%M:%S"),
        "Ended": "still open" if segment["outcome"] == "open" else end.strftime("%d %b %H:%M:%S"),
        "Outcome": OUTCOME_NAMES.get(segment["outcome"], segment["outcome"]),
        "Open for": duration((end - start).total_seconds()),
        "Realized PnL": fmt_quote(segment.get("realized_pnl"), signed=True),
    }]), hide_index=True, width="stretch")
    mine = frame([fill for fill in fills if fill["order_id"] == picked])
    if not mine.empty:
        st.dataframe(pd.DataFrame({
            "Fill time": clock(local(mine["time"])),
            "Fill": mine.get("partial", pd.Series(False, index=mine.index)).map(lambda p: "partial" if p else "final"),
            "Price": mine["price"].map(lambda p: fmt_price(p, digits)),
            "Amount": mine["amount"].map(fmt_amount),
            "Realized PnL": mine.get("realized_pnl", pd.Series(index=mine.index)).map(lambda v: fmt_quote(v, signed=True)),
        }), hide_index=True, width="stretch")


def ladder_chart(orders: pd.DataFrame, mid: Optional[float], digits: int) -> go.Figure:
    orders = orders.sort_values("price")
    away = ((orders["price"] / mid - 1) * 100).map(lambda d: f"  {d:+.3f}%") if mid else ""
    bars = pd.DataFrame({
        "side": orders["side"],
        "price": orders["price"].map(lambda p: fmt_price(p, digits)) + away,
        "value": orders["price"] * orders["amount"].fillna(0) * orders["side"].map({"BUY": -1, "SELL": 1}).fillna(1),
        "level": orders.get("level", pd.Series(index=orders.index)).map(text),
        "amount": orders["amount"].map(fmt_amount),
    })
    chart = px.bar(bars, x="value", y="price", color="side", orientation="h", color_discrete_map=SIDE_COLORS,
                   hover_data={"level": True, "amount": True, "value": ":,.2f"})
    chart.update_layout(height=40 + 36 * len(bars), margin=dict(l=0, r=0, t=0, b=0), showlegend=False,
                        xaxis_title="", yaxis_title="", bargap=0.3)
    # Exact prices as rows, highest on top (sells above buys), not a numeric scale.
    chart.update_yaxes(type="category", categoryorder="array", categoryarray=list(dict.fromkeys(bars["price"])))
    return chart


def ladder_panel(ladder: Dict, digits: int):
    price, performance, state = ladder.get("price") or {}, ladder.get("performance") or {}, ladder.get("state") or {}
    st.markdown("**Right now**")
    mid = num(price.get("mid_price"))
    if mid is not None:
        st.metric("Mid price", fmt_price(mid, digits),
                  help=f"bid {fmt_price(price.get('best_bid'), digits)} · ask {fmt_price(price.get('best_ask'), digits)}")
    orders = frame(ladder.get("orders"))
    if not orders.empty:
        orders = orders[orders["price"].notna()]
    if orders.empty:
        age = num(ladder.get("snapshot_age_s"))
        st.caption("No open orders right now." + (f" The last open order was seen {duration(age)} ago." if age else ""))
    else:
        st.plotly_chart(ladder_chart(orders, mid, digits), width="stretch", key="bm_ladder_chart",
                        config={"displayModeBar": False})
        st.caption("Open orders by price and distance from mid, as quote value: buys left, sells right.")
    rows = []
    if performance:
        rows += [("Realized PnL", fmt_quote(performance.get("realized_pnl_quote"), signed=True)),
                 ("Unrealized PnL", fmt_quote(performance.get("unrealized_pnl_quote"), signed=True)),
                 ("Global PnL", fmt_quote(performance.get("global_pnl_quote"), signed=True)),
                 ("Volume traded", fmt_quote(performance.get("volume_traded"), digits=2))]
    if state:
        rows.append(("Grid reference", fmt_price(state.get("reference_price"), digits)))
        placed, total = num(state.get("levels_placed")), num(state.get("levels_total"))
        if total is not None:
            rows.append(("Levels placed", f"{int(placed or 0)} / {int(total)}"))
    if rows:
        st.table(pd.DataFrame(rows, columns=["What", "Value"]), hide_index=True, hide_header=True)
    if performance:
        st.caption(f"PnL of controller {performance.get('controller') or '?'}, in its quote currency.")
    else:
        st.caption("No PnL: only V2 bots (with controllers) report it.")


def orders_view(metrics: Any, minutes: int):
    try:
        bots = call(metrics.get_bots)
    except MonitoringError as e:
        st.error(str(e))
        return
    if not bots:
        st.info("No bot has reported a price in the last day. Bots show up here a few seconds after they start with "
                "monitoring on.")
        return
    markets: Dict[str, List[Tuple[str, str]]] = {}
    for row in bots:
        markets.setdefault(row["bot"], []).append((text(row.get("exchange")), text(row.get("pair"))))
    bot = st.selectbox("Bot", sorted(markets), key="bm_bot", persist_state="page", on_change=forget_order,
                       format_func=lambda name: f"{name} · {', '.join(f'{e} {p}' for e, p in markets.get(name, []))}")
    exchange = pair = None
    if len(markets[bot]) > 1:  # one market at a time: their prices can be far apart
        names = [f"{e} {p}" for e, p in markets[bot]]
        picked = st.selectbox(f"Market ({len(names)} for this bot)", names, key="bm_bot_market", persist_state="page",
                              on_change=forget_order)
        exchange, pair = markets[bot][names.index(picked)]
    view = bot if exchange is None else f"{bot} {exchange} {pair}"
    try:
        data = call(metrics.get_orders, bot=bot, minutes=minutes, exchange=exchange, pair=pair)
        ladder = call(metrics.get_ladder, bot=bot, exchange=exchange, pair=pair)
    except MonitoringError as e:
        st.error(str(e))
        return
    segments, fills = data.get("segments") or [], data.get("fills") or []
    if not segments and not data.get("price"):
        st.info("No prices or orders from this bot in this window.")
        return
    outcomes = Counter(OUTCOME_NAMES.get(segment.get("outcome"), segment.get("outcome")) for segment in segments)
    partial = sum(1 for fill in fills if fill.get("partial"))
    st.caption(f"{len(segments)} orders in this window"
               + (": " + ", ".join(f"{count} {outcome}" for outcome, count in outcomes.most_common()) if segments else "")
               + f" · {len(fills)} fills ({partial} partial)")
    digits = price_digits([row.get("mid_price") for row in data.get("price") or []]
                          + [segment.get("price") for segment in segments]
                          + [(ladder.get("price") or {}).get("mid_price")])
    left, right = st.columns([5, 2])
    with left:
        figure, pick_map = orders_figure(data, minutes, digits, revision=view)
        event = st.plotly_chart(figure, width="stretch", on_select="rerun", selection_mode="points",
                                key=f"bm_orders_chart_{view}")
        handle_click(event, pick_map)
        order_details(data, digits)
    with right:
        ladder_panel(ladder, digits)


# ----------------------------------------------------------------------------------------------------------- PnL

def pnl_view(metrics: Any, minutes: int):
    try:
        pnl = frame(call(metrics.get_pnl, minutes=minutes))
    except MonitoringError as e:
        st.error(str(e))
        return
    if pnl.empty:
        st.info("No PnL in this window. V2 bots (with controllers) report it every 5 seconds; plain scripts don't.")
        return
    pnl["time"] = local(pnl["time"])
    pnl["controller"] = pnl["controller"].fillna("") if "controller" in pnl else ""
    pnl["series"] = pnl["bot"] + " · " + pnl["controller"]
    for column in PNL_METRICS.values():
        pnl[column] = pd.to_numeric(pnl[column], errors="coerce") if column in pnl else float("nan")
    names = sorted(pnl["series"].unique())
    latest = pnl.sort_values("time").groupby("series").tail(1).sort_values("series")
    st.dataframe(pd.DataFrame({
        "Bot": latest["bot"], "Controller": latest["controller"],
        **{label: latest[column] for label, column in PNL_METRICS.items()},
        "As of": clock(latest["time"]),
    }), hide_index=True, width="stretch",
        column_config={label: st.column_config.NumberColumn(format="%.2f" if label == "Volume traded" else "%.4f")
                       for label in PNL_METRICS})

    label = st.segmented_control("Chart", list(PNL_METRICS), default="Global PnL", required=True, key="bm_pnl_metric",
                                 persist_state="page")
    shown = names
    if len(names) > len(SERIES_COLORS):
        shown = st.multiselect(f"On the chart (up to {len(SERIES_COLORS)})", names, default=names[:len(SERIES_COLORS)],
                               max_selections=len(SERIES_COLORS), key="bm_pnl_series", persist_state="page")
        if not shown:
            return
    colors = {name: SERIES_COLORS[i] for i, name in enumerate(shown)}
    chart = px.line(pnl[pnl["series"].isin(shown)], x="time", y=PNL_METRICS[label], color="series",
                    color_discrete_map=colors, category_orders={"series": shown})
    if label != "Volume traded":
        chart.add_hline(y=0, line_width=1, line_color="#383835")
    chart.update_traces(line=dict(width=2))
    chart.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="", yaxis_title="quote",
                        legend=legend_below(380), hovermode="x unified", uirevision="pnl")
    st.plotly_chart(chart, width="stretch", key="bm_pnl_chart")
    st.caption("Each controller reports in its own pair's quote currency (USDT, INR…), so values from different quotes "
               "don't add up. Points are averages per time bucket; volume is the bucket's highest.")


# --------------------------------------------------------------------------------------------------- market data

def feed_status(book_age: Any, sample_age: Any) -> str:
    book_age, sample_age = num(book_age), num(sample_age)
    if sample_age is not None and sample_age >= 10:
        return f"🔴 no new samples for {duration(sample_age)}"
    if book_age is not None and book_age >= 30:
        return f"🟠 order book unchanged for {duration(book_age)}"
    return "🟢 OK"


def line_chart(data: pd.DataFrame, y: str, title: str, **kwargs) -> go.Figure:
    chart = px.line(data, x="time", y=y, title=title, **kwargs)
    chart.update_traces(line=dict(width=2))
    chart.update_layout(height=260, margin=dict(l=0, r=0, t=40, b=0), xaxis_title="", yaxis_title="",
                        legend=legend_below(260), hovermode="x unified")
    return chart


def market_view(metrics: Any, minutes: int):
    try:
        feeds = frame(call(metrics.get_feeds))
        markets = call(metrics.get_markets)
    except MonitoringError as e:
        st.error(str(e))
        return
    if not markets and feeds.empty:
        st.info("No market data in the last day. It comes from the market recorder, which samples live public order "
                "books every second, with no bot involved. It isn't running on this server.")
        return
    st.caption("Sampled every second from live public order books by the market recorder, with no bot involved.")
    if not feeds.empty:
        feeds = feeds.sort_values(["exchange", "pair"])
        sample_ages = feeds["sample_age_s"] if "sample_age_s" in feeds else [None] * len(feeds)
        st.dataframe(pd.DataFrame({
            "Market": feeds["exchange"] + " " + feeds["pair"],
            "Mid": [fmt_price(value, price_digits([value])) for value in feeds["mid_price"]],
            "Spread": feeds["spread_pct"].map(lambda value: "–" if num(value) is None else f"{num(value):.4f}%"),
            "Order book last changed": feeds["book_age_s"].map(lambda age: f"{duration(age)} ago"),
            "Feed": [feed_status(book, sample) for book, sample in zip(feeds["book_age_s"], sample_ages)],
        }), hide_index=True, width="stretch")
    if not markets:
        return
    names = [f"{market['exchange']} {market['pair']}" for market in markets]
    picked = st.selectbox("Market", names, key="bm_market", persist_state="page")
    exchange, pair = markets[names.index(picked)]["exchange"], markets[names.index(picked)]["pair"]
    try:
        series = frame(call(metrics.get_market, exchange=exchange, pair=pair, minutes=minutes))
    except MonitoringError as e:
        st.error(str(e))
        return
    if series.empty:
        st.caption("No samples of this market in this window.")
        return
    series["time"] = local(series["time"])
    digits = price_digits(series["mid_price"])
    left, right = st.columns(2)
    with left:
        chart = line_chart(series, "mid_price", "Mid price", color_discrete_sequence=SERIES_COLORS[:1])
        chart.update_yaxes(tickformat=f",.{digits}f")
        st.plotly_chart(chart, width="stretch", key="bm_mid_chart")
        chart = line_chart(series, "spread_pct", "Spread %", color_discrete_sequence=SERIES_COLORS[:1])
        chart.update_yaxes(tickformat=".4f")
        st.plotly_chart(chart, width="stretch", key="bm_spread_chart")
    with right:
        depth = series.melt(id_vars="time", value_vars=["bid_depth_1pct", "ask_depth_1pct"], var_name="side",
                            value_name="quote")
        depth["side"] = depth["side"].map({"bid_depth_1pct": "bids within 1%", "ask_depth_1pct": "asks within 1%"})
        st.plotly_chart(line_chart(depth, "quote", "Depth within 1% of mid (quote)", color="side",
                                   color_discrete_map={"bids within 1%": SIDE_COLORS["BUY"],
                                                       "asks within 1%": SIDE_COLORS["SELL"]}),
                        width="stretch", key="bm_depth_chart")
        st.plotly_chart(line_chart(series, "book_age_s", "Seconds since the order book last changed",
                                   color_discrete_sequence=[MID_COLOR]), width="stretch", key="bm_age_chart")


# ---------------------------------------------------------------------------------------------------------- page

def monitoring_ready(metrics: Any) -> bool:
    """False, after saying why on the page, when this api-server can't serve bot monitoring."""
    try:
        health = call(metrics.get_health)
    except MonitoringError as e:
        st.error(str(e))
        return False
    if not health.get("enabled"):
        st.warning("Bot monitoring is off on this api-server. In the api-server folder run `make monitoring`, add the "
                   "lines it prints to `.env`, and restart the API. Bots deployed after that show up here.")
        return False
    if not health.get("influxdb_reachable"):
        st.error(f"The api-server can't reach InfluxDB: {health.get('influxdb_error')}")
        return False
    return True


def status_bar(metrics: Any):
    """InfluxDB and the bot health watcher, as the api-server sees them."""
    try:
        health = call(metrics.get_health)
    except MonitoringError as e:
        st.error(str(e))
        return
    if not health.get("influxdb_reachable"):
        st.error(f"The api-server can't reach InfluxDB: {health.get('influxdb_error')}")
        return
    watcher = health.get("watcher") or {}
    last_check = pd.to_datetime(watcher.get("last_check"), utc=True) if watcher.get("last_check") else None
    age = (pd.Timestamp.now(tz="UTC") - last_check).total_seconds() if last_check is not None else None
    if not watcher.get("running"):
        st.warning("The api-server's bot health watcher isn't running, so bot states, uptime and incidents aren't "
                   "updated. Restart the API.")
    elif watcher.get("last_error"):
        st.warning(f"The bot health watcher's last check failed: {watcher['last_error']}")
    elif age is None or age > FRESH_S:
        st.warning("The bot health watcher hasn't checked the bots "
                   + ("yet." if age is None else f"for {duration(age)}."))
    checked = "" if last_check is None else (f", last check {clock(local([watcher['last_check']])).iloc[0]}"
                                             f" ({duration(age)} ago)")
    st.caption(f"InfluxDB reachable · database `{health.get('database')}` · health watcher: "
               f"{watcher.get('bots_watched', 0)} bots watched{checked}")


initialize_st_page(icon="📈", show_readme=False)
backend_api_client = get_backend_api_client()

st.title("📈 Bot Monitoring")
st.caption("Heartbeats, prices, orders and PnL that the bots write to InfluxDB, read through the api-server. "
           "Times are IST.")

metrics_router = getattr(backend_api_client, "metrics", None)
if metrics_router is None:  # a client made before this page existed; a new browser session makes a new one
    st.error("Reload this browser tab: the API client in this session was made before bot monitoring was added.")
    st.stop()
if not monitoring_ready(metrics_router):
    st.button("Try again")
    st.stop()

status_area = st.container()
range_column, live_column = st.columns([4, 1])
range_label = range_column.segmented_control("Time range", list(RANGES), default="1 hour", required=True,
                                             key="bm_range")
live = live_column.toggle(f"Live, every {REFRESH_S} s", value=True, key="bm_live",
                          help="Pause it to inspect an order without the chart moving.")
window = RANGES[range_label]
refresh = REFRESH_S if live else None

with status_area:
    st.fragment(status_bar, run_every=refresh)(metrics_router)

tabs = st.tabs(["Bot health", "Orders vs price", "PnL", "Market data"], key="bm_tab", on_change="rerun")
for tab, view in zip(tabs, (health_view, orders_view, pnl_view, market_view)):
    if tab.open is False:  # only the open tab runs, so only it polls the api-server
        continue
    with tab:
        try:  # one broken view must not blank the page
            st.fragment(view, run_every=refresh)(metrics_router, window)
        except Exception as e:
            st.exception(e)
