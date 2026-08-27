from datetime import datetime, time, timedelta, timezone

import aiohttp
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from frontend.st_utils import get_backend_api_client, initialize_st_page

# Initialize Streamlit page
initialize_st_page(title="Download Candles", icon="💾")
backend_api_client = get_backend_api_client()

c1, c2, c3, c4 = st.columns([2, 2, 2, 0.5])
with c1:
    connector = st.selectbox("Exchange",
                             ["binance_perpetual", "binance", "gate_io", "gate_io_perpetual", "kucoin", "kucoin_perpetual", "okx", "coindcx", "wazirx", "zebpay", "coinex", "coinex_perpetual", "csx", "coinswitch"],
                             index=0)
    trading_pair = st.text_input("Trading Pair", value="BTC-USDT")
with c2:
    interval = st.selectbox("Interval", options=["1m", "3m", "5m", "15m", "1h", "4h", "1d", "1s"])
with c3:
    coarse_interval = interval in ("1h", "4h", "1d")
    start_date = st.date_input("Start Date", value=datetime.now().date() - timedelta(days=1))
    if not coarse_interval:
        start_time_input = st.time_input("Start Time", value=time.min, key="start_time")
    end_date = st.date_input("End Date", value=datetime.now().date())
    if not coarse_interval:
        end_time_input = st.time_input("End Time", value=time.max.replace(second=0, microsecond=0), key="end_time")
with c4:
    get_data_button = st.button("Get Candles!")

if get_data_button:
    if coarse_interval:
        start_datetime = datetime.combine(start_date, time.min)
        end_datetime_full = datetime.combine(end_date, time.max)
    else:
        start_datetime = datetime.combine(start_date, start_time_input)
        end_datetime_full = datetime.combine(end_date, end_time_input)
    end_datetime = min(end_datetime_full, datetime.now())
    if end_datetime < start_datetime:
        st.error("End Date should be greater than Start Date.")
        st.stop()

    start_ts = int(start_datetime.timestamp())
    end_ts = int(end_datetime.timestamp())
    utc_start = datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
    utc_end = datetime.fromtimestamp(end_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')

    range_caption = (
        f"Requested UTC range: `{datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')}` → "
        f"`{datetime.fromtimestamp(end_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')}`"
    )
    try:
        candles = backend_api_client.market_data.get_historical_candles(
            connector_name=connector,
            trading_pair=trading_pair,
            interval=interval,
            start_time=start_ts,
            end_time=end_ts,
        )
    except aiohttp.ClientResponseError as e:
        st.error(
            f"Backend error for **{connector}** / **{trading_pair}** / **{interval}**: {e.message or e.status}\n\n"
            f"Requested UTC range: `{utc_start}` -> `{utc_end}`\n\n"
            "Tip: Try a shorter date range."
        )
        st.stop()
    except Exception as e:
        st.error(
            f"Failed to download candles for **{connector}** / **{trading_pair}** / **{interval}**: {e}\n\n"
            f"Requested UTC range: `{utc_start}` -> `{utc_end}`"
        )
        st.stop()

    def show_backend_error(err):
        st.error(
            f"Backend error for **{connector}** / **{trading_pair}** / **{interval}**: {err}\n\n"
            f"Requested UTC range: `{utc_start}` -> `{utc_end}`\n\n"
            "Tip: Try a shorter date range."
        )
        st.stop()

    try:
        candles = backend_api_client.market_data.get_historical_candles(
            connector_name=connector,
            trading_pair=trading_pair,
            interval=interval,
            start_time=start_ts,
            end_time=end_ts,
        )
    except aiohttp.ClientConnectorError:
        st.error(
            f"Can't reach the backend API for **{connector}** / **{trading_pair}** / **{interval}**.\n\n"
            "The backend server appears to be down or unreachable. Confirm it's running and retry."
        )
        st.stop()
    except TimeoutError:
        st.error(
            f"Backend request timed out for **{connector}** / **{trading_pair}** / **{interval}**.\n\n"
            f"{range_caption}\n\n"
            "Tip: Try a shorter date range or a coarser interval — large 1m/5m ranges take longer to fetch."
        )
        st.stop()
    except aiohttp.ClientResponseError as e:
        st.error(
            f"Backend returned HTTP {e.status} for **{connector}** / **{trading_pair}** / **{interval}**: {e.message}\n\n"
            f"{range_caption}"
        )
        st.stop()
    except Exception as e:
        st.error(
            f"Unexpected error fetching candles for **{connector}** / **{trading_pair}** / **{interval}**: "
            f"{type(e).__name__}: {e}\n\n"
            f"{range_caption}"
        )
        st.stop()

    if isinstance(candles, dict):
        if candles.get("status") == "success":
            candles = candles.get("data", [])
        elif "error" in candles:
            show_backend_error(str(candles["error"]))
        elif "data" in candles:
            candles = candles["data"]
        elif "error" in candles:
            err = str(candles["error"])
            st.error(
                f"Backend error for **{connector}** / **{trading_pair}** / **{interval}**: {err}\n\n"
                f"{range_caption}\n\n"
                "Tip: Try a shorter date range."
            )
            st.stop()
        else:
            st.error(f"Unexpected response from server: {candles}")
            st.stop()
    if not candles:
        st.warning("No candle data returned for the selected parameters.")
        st.stop()

    try:
        candles_df = pd.DataFrame(candles)
        candles_df.index = pd.to_datetime(candles_df["timestamp"], unit='s')
        missing_cols = [c for c in ("open", "high", "low", "close") if c not in candles_df.columns]
        if missing_cols:
            raise KeyError(f"response rows are missing expected column(s): {missing_cols}")
    except Exception as e:
        st.error(
            f"Backend returned candle data in an unexpected shape for **{connector}** / **{trading_pair}** / "
            f"**{interval}**: {type(e).__name__}: {e}\n\n"
            f"{range_caption}\n\n"
            f"First row received: `{candles[0] if candles else 'n/a'}`"
        )
        st.stop()

    # Plotting the candlestick chart
    fig = go.Figure(data=[go.Candlestick(
        x=candles_df.index,
        open=candles_df['open'],
        high=candles_df['high'],
        low=candles_df['low'],
        close=candles_df['close']
    )])
    fig.update_layout(
        height=1000,
        title="Candlesticks",
        xaxis_title="Time",
        yaxis_title="Price",
        template="plotly_dark",
        showlegend=False
    )
    fig.update_xaxes(rangeslider_visible=False)
    fig.update_yaxes(title_text="Price")
    st.plotly_chart(fig, use_container_width=True)

    # Generating CSV and download button
    csv = candles_df.to_csv(index=False)
    filename = f"{connector}_{trading_pair}_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.csv"
    st.download_button(
        label="Download Candles as CSV",
        data=csv,
        file_name=filename,
        mime='text/csv',
    )
