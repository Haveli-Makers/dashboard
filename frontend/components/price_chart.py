import bisect
import json

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from frontend.candles import (
    candles_error,
    clear_candles_cache,
    default_candle_source,
    fetch_recent_candles,
    get_candle_connectors,
    get_candle_intervals,
    interval_to_seconds,
    is_valid_pair,
)
from frontend.st_utils import get_server_cache_key
from frontend.utils import price_precision

LIGHTWEIGHT_CHARTS_JS = "https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js"

CANDLE_COUNT_OPTIONS = [100, 300, 500, 1000]
CHART_HEIGHT = 520
TRADES_LIMIT = 500


@st.cache_data(ttl=15, show_spinner=False)
def _fetch_trades(_client, server, account_name, connector, trading_pair, start_time, end_time):
    response = _client.trading.get_trades(
        account_names=[account_name],
        connector_names=[connector],
        trading_pairs=[trading_pair],
        start_time=start_time,
        end_time=end_time,
        limit=TRADES_LIMIT,
    )
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        return response.get("data", [])
    return []


def get_trades(client, account_name, connector, trading_pair, start_time, end_time):
    """The account's fills for the pair in [start_time, end_time]; empty if they can't be fetched."""
    if not account_name:
        return []
    try:
        return _fetch_trades(client, get_server_cache_key(), account_name, connector, trading_pair,
                             int(start_time), int(end_time))
    except Exception:
        return []


def _to_unix_seconds(value):
    """Parse a seconds/milliseconds epoch or an ISO datetime string; None if unparseable."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value / 1000 if value > 1_000_000_000_000 else value)
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    return None if pd.isna(parsed) else int(parsed.timestamp())


def to_chart_series(candles):
    """Convert backend candle records into Lightweight Charts candle and volume series."""
    by_time = {}
    for c in candles:
        try:
            by_time[int(float(c["timestamp"]))] = c
        except (KeyError, TypeError, ValueError):
            continue

    ohlc, volume = [], []
    for ts in sorted(by_time):
        c = by_time[ts]
        try:
            o, h, l, cl = (float(c[k]) for k in ("open", "high", "low", "close"))
        except (KeyError, TypeError, ValueError):
            continue
        ohlc.append({"time": ts, "open": o, "high": h, "low": l, "close": cl})
        volume.append({
            "time": ts,
            "value": float(c.get("volume") or 0),
            "color": "rgba(34,197,94,0.45)" if cl >= o else "rgba(240,59,59,0.45)",
        })
    return ohlc, volume


def to_trade_markers(trades, ohlc, interval):
    """Buy/sell markers for fills inside the charted range, snapped to the candle they happened in."""
    if not trades or not ohlc:
        return []
    bar_times = [bar["time"] for bar in ohlc]
    range_end = bar_times[-1] + interval_to_seconds(interval)
    markers = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        ts = _to_unix_seconds(trade.get("timestamp") or trade.get("created_at") or trade.get("execution_time"))
        side = str(trade.get("trade_type") or trade.get("side") or "").upper()
        if ts is None or not bar_times[0] <= ts < range_end or side not in ("BUY", "SELL"):
            continue
        is_buy = side == "BUY"
        markers.append({
            "time": bar_times[bisect.bisect_right(bar_times, ts) - 1],
            "position": "belowBar" if is_buy else "aboveBar",
            "color": "#22c55e" if is_buy else "#f03b3b",
            "shape": "arrowUp" if is_buy else "arrowDown",
            "text": "B" if is_buy else "S",
        })
    return sorted(markers, key=lambda m: m["time"])


def render_lightweight_chart(ohlc, volume, markers=(), height=CHART_HEIGHT):
    last_price = ohlc[-1]["close"] if ohlc else 0
    precision = price_precision(last_price)
    chart_html = f"""
    <div id="chart" style="width:100%;height:{height - 10}px;"></div>
    <script src="{LIGHTWEIGHT_CHARTS_JS}"></script>
    <script>
      // Data stays in UTC; only the labels are formatted in the viewer's timezone, so DST is handled per bar.
      const fmt = (opts) => new Intl.DateTimeFormat(undefined, {{ hourCycle: "h23", ...opts }});
      const crosshairFmt = fmt({{ year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }});
      // Indexed by LightweightCharts.TickMarkType: Year, Month, DayOfMonth, Time, TimeWithSeconds
      const tickFmts = [
        fmt({{ year: "numeric" }}),
        fmt({{ month: "short" }}),
        fmt({{ day: "numeric", month: "short" }}),
        fmt({{ hour: "2-digit", minute: "2-digit" }}),
        fmt({{ hour: "2-digit", minute: "2-digit", second: "2-digit" }}),
      ];
      const toDate = (t) => new Date(t * 1000);
      const el = document.getElementById("chart");
      const chart = LightweightCharts.createChart(el, {{
        autoSize: true,
        layout: {{ background: {{ type: "solid", color: "rgba(0,0,0,0)" }}, textColor: "#aaa",
                   fontFamily: "monospace" }},
        grid: {{ vertLines: {{ color: "rgba(128,128,128,0.12)" }},
                 horzLines: {{ color: "rgba(128,128,128,0.12)" }} }},
        crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
        rightPriceScale: {{ borderColor: "rgba(128,128,128,0.3)" }},
        localization: {{ timeFormatter: (t) => crosshairFmt.format(toDate(t)) }},
        timeScale: {{
          borderColor: "rgba(128,128,128,0.3)", timeVisible: true, secondsVisible: false,
          tickMarkFormatter: (t, type) => (tickFmts[type] || tickFmts[3]).format(toDate(t)),
        }},
      }});
      const candles = chart.addCandlestickSeries({{
        upColor: "#22c55e", downColor: "#f03b3b", borderVisible: false,
        wickUpColor: "#22c55e", wickDownColor: "#f03b3b",
        priceFormat: {{ type: "price", precision: {precision}, minMove: {10 ** -precision} }},
      }});
      candles.setData({json.dumps(ohlc)});
      candles.setMarkers({json.dumps(list(markers))});
      const vol = chart.addHistogramSeries({{
        priceFormat: {{ type: "volume" }}, priceScaleId: "", lastValueVisible: false, priceLineVisible: false,
      }});
      vol.priceScale().applyOptions({{ scaleMargins: {{ top: 0.8, bottom: 0 }} }});
      vol.setData({json.dumps(volume)});
      chart.timeScale().fitContent();
    </script>
    """
    components.html(chart_html, height=height)


@st.dialog("📈 Price Chart", width="large")
def show_price_chart_dialog(backend_api_client, connector, trading_pair, account_name=None):
    trading_pair = trading_pair.strip().upper()
    if not is_valid_pair(trading_pair):
        st.warning(candles_error(trading_pair, connector, "invalid pair format"))
        return

    candle_connectors = get_candle_connectors(backend_api_client)
    default_source = default_candle_source(connector, candle_connectors)
    last_interval = st.session_state.get("price_chart_last_interval", "1m")
    last_count = st.session_state.get("price_chart_last_count", 300)

    source_col, interval_col, count_col, refresh_col = st.columns([2, 2, 2, 1], vertical_alignment="bottom")
    with source_col:
        source = st.selectbox(
            "Candles source",
            candle_connectors,
            index=candle_connectors.index(default_source) if default_source else None,
            placeholder="Pick a feed",
            help="Some exchanges don't provide candles. Select an alternative source.",
            key=f"price_chart_source_{connector}",
        )
    if source is None:
        st.info(f"{connector} has no candle feed. Pick another exchange to chart {trading_pair}.")
        return

    intervals = get_candle_intervals(backend_api_client, source)
    with interval_col:
        interval = st.selectbox(
            "Interval",
            intervals,
            index=intervals.index(last_interval) if last_interval in intervals else 0,
        )
    with count_col:
        count = st.selectbox("Candles", CANDLE_COUNT_OPTIONS, index=CANDLE_COUNT_OPTIONS.index(last_count))
    st.session_state.price_chart_last_interval = interval
    st.session_state.price_chart_last_count = count
    with refresh_col:
        if st.button("🔄", help="Refresh chart", use_container_width=True, key="price_chart_refresh"):
            clear_candles_cache()
            _fetch_trades.clear()

    with st.spinner(f"Loading {interval} candles for {trading_pair}…"):
        candles, error = fetch_recent_candles(backend_api_client, source, trading_pair, interval, count)

    if error:
        st.warning(candles_error(trading_pair, source, error))
        with st.expander("Error details"):
            st.code(error, language="text")
        return

    ohlc, volume = to_chart_series(candles)
    if not ohlc:
        st.info(f"No candles found for {trading_pair} on {source} at {interval}.")
        return

    # Fills come from the trading connector, even when the candles come from another feed
    trades = get_trades(backend_api_client, account_name, connector, trading_pair,
                        ohlc[0]["time"], ohlc[-1]["time"] + interval_to_seconds(interval))
    markers = to_trade_markers(trades, ohlc, interval)

    caption = f"{source} · {trading_pair} · {interval} · {len(ohlc)} candles"
    if source != connector:
        caption += f" · trading on {connector}"
    if markers:
        caption += f" · {len(markers)} of your trades"
    st.caption(caption)
    render_lightweight_chart(ohlc, volume, markers)
