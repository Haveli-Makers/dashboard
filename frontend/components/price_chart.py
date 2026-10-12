import json
import re
import time

import streamlit as st
import streamlit.components.v1 as components

LIGHTWEIGHT_CHARTS_JS = "https://unpkg.com/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js"

FALLBACK_INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"]
CANDLE_COUNT_OPTIONS = [100, 300, 500, 1000]
CHART_HEIGHT = 520

INTERVAL_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "M": 2592000}
INTERVAL_PATTERN = re.compile(r"^(\d+)([smhdwM])$")


def interval_to_seconds(interval):
    """Convert an interval like '15m' or '4h' into seconds; None if unrecognised."""
    match = INTERVAL_PATTERN.match(interval)
    if not match:
        return None
    return int(match.group(1)) * INTERVAL_SECONDS[match.group(2)]


@st.cache_data(ttl=600, show_spinner=False)
def get_candle_connectors(_backend_api_client):
    try:
        return set(_backend_api_client.market_data.get_available_candle_connectors() or [])
    except Exception:
        return set()


@st.cache_data(ttl=600, show_spinner=False)
def get_intervals(_backend_api_client, connector):
    try:
        intervals = _backend_api_client.market_data.get_candle_intervals(connector)
    except Exception:
        intervals = None
    usable = [i for i in (intervals or FALLBACK_INTERVALS) if interval_to_seconds(i)]
    return usable or FALLBACK_INTERVALS


@st.cache_data(ttl=15, show_spinner=False)
def fetch_candles(_backend_api_client, connector, trading_pair, interval, count):
    """Fetch the last `count` candles; returns (records, error)."""
    end_time = int(time.time())
    start_time = end_time - interval_to_seconds(interval) * count
    try:
        candles = _backend_api_client.market_data.get_historical_candles(
            connector_name=connector,
            trading_pair=trading_pair,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
        )
    except Exception as e:
        return [], str(e)
    if isinstance(candles, dict):
        return [], str(candles.get("error", "Unexpected response from backend"))
    return (candles or [])[-count:], None


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
        o, h, l, cl = (float(c[k]) for k in ("open", "high", "low", "close"))
        ohlc.append({"time": ts, "open": o, "high": h, "low": l, "close": cl})
        volume.append({
            "time": ts,
            "value": float(c.get("volume") or 0),
            "color": "rgba(34,197,94,0.45)" if cl >= o else "rgba(240,59,59,0.45)",
        })
    return ohlc, volume


def render_lightweight_chart(ohlc, volume, height=CHART_HEIGHT):
    last_price = ohlc[-1]["close"] if ohlc else 0
    precision = 2 if last_price >= 1000 else 4 if last_price >= 1 else 8
    chart_html = f"""
    <div id="chart" style="width:100%;height:{height - 10}px;"></div>
    <script src="{LIGHTWEIGHT_CHARTS_JS}"></script>
    <script>
      // Lightweight Charts renders timestamps as UTC; shift them so the axis shows the viewer's local time.
      const tzOffset = -new Date().getTimezoneOffset() * 60;
      const toLocal = (rows) => rows.map((r) => ({{ ...r, time: r.time + tzOffset }}));
      const el = document.getElementById("chart");
      const chart = LightweightCharts.createChart(el, {{
        autoSize: true,
        layout: {{ background: {{ type: "solid", color: "rgba(0,0,0,0)" }}, textColor: "#aaa",
                   fontFamily: "monospace" }},
        grid: {{ vertLines: {{ color: "rgba(128,128,128,0.12)" }},
                 horzLines: {{ color: "rgba(128,128,128,0.12)" }} }},
        crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
        rightPriceScale: {{ borderColor: "rgba(128,128,128,0.3)" }},
        timeScale: {{ borderColor: "rgba(128,128,128,0.3)", timeVisible: true, secondsVisible: false }},
      }});
      const candles = chart.addCandlestickSeries({{
        upColor: "#22c55e", downColor: "#f03b3b", borderVisible: false,
        wickUpColor: "#22c55e", wickDownColor: "#f03b3b",
        priceFormat: {{ type: "price", precision: {precision}, minMove: {10 ** -precision} }},
      }});
      candles.setData(toLocal({json.dumps(ohlc)}));
      const vol = chart.addHistogramSeries({{
        priceFormat: {{ type: "volume" }}, priceScaleId: "", lastValueVisible: false, priceLineVisible: false,
      }});
      vol.priceScale().applyOptions({{ scaleMargins: {{ top: 0.8, bottom: 0 }} }});
      vol.setData(toLocal({json.dumps(volume)}));
      chart.timeScale().fitContent();
    </script>
    """
    components.html(chart_html, height=height)


@st.dialog("📈 Price Chart", width="large")
def show_price_chart_dialog(backend_api_client, connector, trading_pair):
    candle_connectors = get_candle_connectors(backend_api_client)
    if candle_connectors and connector not in candle_connectors:
        st.info(f"Candles are not available for {connector}.")
        return

    intervals = get_intervals(backend_api_client, connector)
    last_interval = st.session_state.get("price_chart_last_interval", "1m")
    last_count = st.session_state.get("price_chart_last_count", 300)

    interval_col, count_col, refresh_col = st.columns([2, 2, 1], vertical_alignment="bottom")
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
            fetch_candles.clear()

    with st.spinner(f"Loading {interval} candles for {trading_pair}…"):
        candles, error = fetch_candles(backend_api_client, connector, trading_pair, interval, count)

    if error:
        st.warning(f"Could not load candles for {trading_pair} on {connector}.")
        with st.expander("Error details"):
            st.code(error, language="text")
        return

    ohlc, volume = to_chart_series(candles)
    if not ohlc:
        st.info(f"No candles found for {trading_pair} on {connector} at {interval}.")
        return

    st.caption(f"{connector} · {trading_pair} · {interval} · {len(ohlc)} candles")
    render_lightweight_chart(ohlc, volume)
