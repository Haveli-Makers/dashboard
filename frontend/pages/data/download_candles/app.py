import io
import re
import zipfile
from datetime import datetime, time
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from frontend.email_utils import dataframes_to_xlsx_bytes
from frontend.st_utils import get_backend_api_client, initialize_st_page

FALLBACK_CONNECTORS = ["binance_perpetual", "binance", "gate_io", "gate_io_perpetual", "kucoin", "kucoin_perpetual", "okx"]
FALLBACK_INTERVALS = ["1m", "3m", "5m", "15m", "1h", "4h", "1d", "1s"]
UNAVAILABLE_CONNECTORS = {"ascend_ex"}

PAIR_FORMAT = re.compile(r"^[A-Z0-9]+-[A-Z0-9]+$")


def _is_valid_pair(pair):
    """Hummingbot candle feeds split pairs on '-', so only BASE-QUOTE is accepted."""
    return bool(PAIR_FORMAT.match(pair))


def _candles_error(trading_pair, connector, raw_error):
    """Translate raw exchange/API errors into a message a user can act on."""
    error = str(raw_error).lower()
    if "not enough values to unpack" in error or "invalid pair format" in error:
        return f"{trading_pair} is not in BASE-QUOTE format. Enter it like USDT-INR or BTC-USDT."
    if "invalid symbol" in error or "-1121" in error or "not found" in error or "unknown symbol" in error:
        return f"{trading_pair} is not available on {connector}. Check the pair name or pick another exchange."
    if "no historical data" in error:
        return f"No candles found for {trading_pair} in the selected date range."
    if "429" in error or "too many requests" in error or "rate limit" in error:
        return f"{connector} is rate limiting requests. Please wait a minute and try again."
    if "timeout" in error or "timed out" in error:
        return f"The request for {trading_pair} timed out. Try a shorter date range or try again later."
    if "connect" in error or "503" in error or "502" in error or "unavailable" in error:
        return f"Could not reach {connector} right now. Please try again later."
    return f"Could not fetch candles for {trading_pair} on {connector}."


def _safe_filename_part(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_") or "unknown"


def _build_sheet_names(pairs):
    """Map each pair to a unique name. Excel sheet names have a 31-character limit and cannot contain certain characters."""
    names = {}
    used_names = set()
    for pair in pairs:
        sheet_name = re.sub(r"[\[\]:*?/\\]", "_", pair)[:31]
        base_name, suffix = sheet_name, 2
        while sheet_name in used_names:
            sheet_name = f"{base_name[:28]}_{suffix}"
            suffix += 1
        used_names.add(sheet_name)
        names[pair] = sheet_name
    return names


def _build_all_pairs_downloads(candles_by_pair, connector, date_range):
    """Build (zip_bytes, xlsx_bytes)."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for pair, df in candles_by_pair.items():
            file_name = f"{_safe_filename_part(connector)}_{_safe_filename_part(pair)}_{date_range}.csv"
            zip_file.writestr(file_name, df.to_csv(index=False))

    sheet_names = _build_sheet_names(candles_by_pair)
    xlsx_bytes = dataframes_to_xlsx_bytes({
        sheet_names[pair]: df.reset_index(drop=True) for pair, df in candles_by_pair.items()
    })
    return zip_buffer.getvalue(), xlsx_bytes


# Initialize Streamlit page
initialize_st_page(title="Download Candles", icon="💾")
backend_api_client = get_backend_api_client()

if "download_candles__connectors" not in st.session_state:
    try:
        available_connectors = backend_api_client.market_data.get_available_candle_connectors()
        connectors = sorted(available_connectors) if available_connectors else FALLBACK_CONNECTORS
    except Exception:
        connectors = FALLBACK_CONNECTORS
    st.session_state["download_candles__connectors"] = [c for c in connectors if c not in UNAVAILABLE_CONNECTORS]
available_connectors = st.session_state["download_candles__connectors"]

st.markdown(
    """
    <style>
    div[data-testid="stButton"] button p,
    div[data-testid="stPopover"] button p {
        white-space: nowrap;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
with c1:
    connector = st.selectbox("Exchange", available_connectors, index=0)
    trading_pairs = st.text_input("Trading Pairs (BTC-USDT, ETH-USDT)", value="BTC-USDT")
with c2:
    intervals_cache = st.session_state.setdefault("download_candles__intervals_by_connector", {})
    if connector not in intervals_cache:
        try:
            connector_intervals = backend_api_client.market_data.get_candle_intervals(connector)
            intervals_cache[connector] = connector_intervals if connector_intervals else FALLBACK_INTERVALS
        except Exception:
            intervals_cache[connector] = FALLBACK_INTERVALS
    interval_options = intervals_cache[connector]
    interval = st.selectbox("Interval", options=interval_options)
with c3:
    coarse_interval = interval in ("1h", "4h", "1d")
    start_date = st.date_input("Start Date", value=datetime.now().date() - timedelta(days=1))
    if not coarse_interval:
        start_time_input = st.time_input("Start Time", value=time.min, key="start_time")
    end_date = st.date_input("End Date", value=datetime.now().date())
    if not coarse_interval:
        end_time_input = st.time_input("End Time", value=time.max.replace(second=0, microsecond=0), key="end_time")
with c4:
    get_data_button = st.button("Get Candles", use_container_width=True)

if get_data_button:
    if coarse_interval:
        start_datetime = datetime.combine(start_date, time.min)
        end_datetime = datetime.combine(end_date, time.max)
    else:
        start_datetime = datetime.combine(start_date, start_time_input)
        end_datetime = datetime.combine(end_date, end_time_input)
    typed_pairs = [p.strip().upper() for p in trading_pairs.split(",") if p.strip()]

    def _pair_key(pair):
        return re.sub(r"[^A-Z0-9]", "", pair)

    valid_by_key = {}
    for typed_pair in typed_pairs:
        if _is_valid_pair(typed_pair):
            valid_by_key.setdefault(_pair_key(typed_pair), typed_pair)

    pairs_list = []
    duplicate_messages = []
    format_errors = []
    handled = set()
    for typed_pair in typed_pairs:
        key = _pair_key(typed_pair)
        canonical = valid_by_key.get(key)
        if canonical is None:
            # No valid spelling of this pair anywhere in the input
            if typed_pair not in handled:
                format_errors.append((typed_pair, "invalid pair format"))
                handled.add(typed_pair)
            continue
        if typed_pair == canonical and canonical not in pairs_list:
            pairs_list.append(canonical)
            continue
        if typed_pair in handled:
            continue
        handled.add(typed_pair)
        if typed_pair == canonical:
            duplicate_messages.append(f"{typed_pair} was entered more than once.")
        else:
            duplicate_messages.append(f"{typed_pair} is the same as {canonical}.")

    if end_datetime <= start_datetime:
        st.error("End date and time should be after the start date and time.")
        st.stop()
    if not pairs_list:
        if format_errors:
            st.error("Please enter trading pairs in BASE-QUOTE format, e.g. USDT-INR, BTC-USDT.")
        else:
            st.error("Please enter at least one trading pair.")
        st.stop()

    candles_by_pair = {}
    errors = list(format_errors)
    progress = st.progress(0.0, text="Fetching candles...")
    for i, trading_pair in enumerate(pairs_list):
        progress.progress(i / len(pairs_list), text=f"Fetching candles for {trading_pair}...")
        try:
            candles = backend_api_client.market_data.get_historical_candles(
                connector_name=connector,
                trading_pair=trading_pair,
                interval=interval,
                start_time=int(start_datetime.timestamp()),
                end_time=int(end_datetime.timestamp())
            )
        except Exception as e:
            errors.append((trading_pair, str(e)))
            continue

        if isinstance(candles, dict) and "error" in candles:
            errors.append((trading_pair, str(candles["error"])))
            continue
        if not candles:
            errors.append((trading_pair, "No historical data available"))
            continue

        candles_df = pd.DataFrame(candles)
        candles_df.index = pd.to_datetime(candles_df["timestamp"], unit='s')
        candles_by_pair[trading_pair] = candles_df
    progress.empty()

    st.session_state["download_candles__result"] = {
        "connector": connector,
        "start_date": start_date,
        "end_date": end_date,
        "candles_by_pair": candles_by_pair,
        "errors": errors,
        "duplicate_messages": duplicate_messages,
    }

result = st.session_state.get("download_candles__result")
if result:
    candles_by_pair = result["candles_by_pair"]
    date_range = f"{result['start_date'].strftime('%Y%m%d')}_{result['end_date'].strftime('%Y%m%d')}"

    if result.get("duplicate_messages"):
        st.info("Duplicate pairs found:\n- " + "\n- ".join(result["duplicate_messages"]))

    if result["errors"]:
        st.warning("Some pairs could not be fetched:\n- " + "\n- ".join(
            _candles_error(pair, result["connector"], raw) for pair, raw in result["errors"]
        ))
        with st.expander("More error details"):
            st.code("\n".join(f"{pair}: {raw}" for pair, raw in result["errors"]), language="text")

    if candles_by_pair:
        pairs_str = "_".join(_safe_filename_part(p.replace("-", "")) for p in candles_by_pair)
        all_pairs_filename = f"candles_{_safe_filename_part(result['connector'])}_{pairs_str}_{date_range}"
        zip_bytes, xlsx_bytes = _build_all_pairs_downloads(candles_by_pair, result["connector"], date_range)

        header_col, download_col = st.columns([3, 1], vertical_alignment="bottom")
        with header_col:
            st.subheader("Candles")
        with download_col:
            with st.popover("⬇️ Download All", use_container_width=True):
                st.download_button(
                    label="Download CSVs as ZIP",
                    data=zip_bytes,
                    file_name=f"{all_pairs_filename}.zip",
                    mime="application/zip",
                    key="dl_candles_zip",
                    use_container_width=True,
                )
                st.download_button(
                    label="Download as XLSX",
                    data=xlsx_bytes,
                    file_name=f"{all_pairs_filename}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_candles_xlsx",
                    use_container_width=True,
                )

        tabs = st.tabs(list(candles_by_pair.keys()))
        for tab, (trading_pair, candles_df) in zip(tabs, candles_by_pair.items()):
            with tab:
                fig = go.Figure(data=[go.Candlestick(
                    x=candles_df.index,
                    open=candles_df['open'],
                    high=candles_df['high'],
                    low=candles_df['low'],
                    close=candles_df['close']
                )])
                fig.update_layout(
                    height=1000,
                    title=f"{trading_pair} Candlesticks",
                    xaxis_title="Time",
                    yaxis_title="Price",
                    template="plotly_dark",
                    showlegend=False
                )
                fig.update_xaxes(rangeslider_visible=False)
                fig.update_yaxes(title_text="Price")
                st.plotly_chart(fig, use_container_width=True)

                # Generating CSV and download button
                st.download_button(
                    label=f"Download {trading_pair} Candles as CSV",
                    data=candles_df.to_csv(index=False),
                    file_name=f"{result['connector']}_{trading_pair}_{date_range}.csv",
                    mime='text/csv',
                    key=f"dl_candles_{trading_pair}",
                )
