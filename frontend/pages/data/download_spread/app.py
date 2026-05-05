import traceback

import pandas as pd
import streamlit as st

from frontend.st_utils import get_backend_api_client, initialize_st_page

# Initialize Streamlit page
initialize_st_page(title="Download Spread", icon="📊")
backend_api_client = get_backend_api_client()
c1, c2, c3 = st.columns([2, 2, 0.5])
with c1:
    connectors = st.multiselect(
        "Exchanges",
        options=["binance", "coinbase", "kraken", "kucoin", "bybit", "okx", "gate_io", "huobi", "coindcx", "wazirx"],
        default=["coindcx"]
    )
    trading_pairs = st.text_input("Trading Pairs", value="BTC-USDT")
with c2:
    window_hours = st.selectbox("Time Window (Hours)",
                                options=[1, 6, 12, 24, 48, 72, 168],  # 1h, 6h, 12h, 24h, 48h, 72h, 1 week
                                index=3)  # Default to 24 hours
with c3:
    get_data_button = st.button("Get Spread!")

if get_data_button:
    # Validate inputs
    if not connectors:
        st.error("Please select at least one exchange.")
    else:
        st.session_state.pop("download_spread__spread_df", None)
        try:
            pairs_list = [p.strip() for p in trading_pairs.split(",") if p.strip()]

            with st.spinner("Fetching spread data..."):
                spread_response = backend_api_client.market_data.get_spread_averages(
                    pairs=pairs_list,
                    connectors=connectors,
                    window_hours=window_hours
                )

            volume_pairs_list = pairs_list
            if not volume_pairs_list and spread_response and spread_response.get("data"):
                spread_data_temp = pd.DataFrame(spread_response["data"])
                if not spread_data_temp.empty:
                    volume_pairs_list = spread_data_temp["pair"].dropna().unique().tolist()

            volume_records = []
            failed_pairs = []
            if volume_pairs_list:
                with st.spinner("Fetching volume data..."):
                    for connector in connectors:
                        try:
                            vol_response = backend_api_client.market_data.get_24h_volume(
                                exchange=connector,
                                trading_pairs=volume_pairs_list
                            )
                            if vol_response:
                                if vol_response.get("data"):
                                    volume_records.extend(vol_response["data"])
                                if vol_response.get("errors"):
                                    for err in vol_response["errors"]:
                                        if "deprecated" in err.get("error", "").lower():
                                            continue
                                        failed_pairs.append(f"{err['pair']} on {connector}: {err['error']}")
                        except Exception:
                            failed_pairs.append(f"Failed to fetch volume for {connector}")

            if volume_records:
                volume_df = pd.DataFrame(volume_records)
                volume_df["quote_volume"] = volume_df["quote_volume"].replace(0, "-")
            else:
                volume_df = pd.DataFrame()

            if spread_response and spread_response.get("data"):
                spread_data = spread_response["data"]
                spread_df = pd.DataFrame(spread_data)

                if not spread_df.empty:
                    if not volume_df.empty:
                        spread_df["_merge_pair"] = spread_df["pair"].astype(str).str.strip().str.upper()
                        spread_df["_merge_connector"] = spread_df["connector"].astype(str).str.strip().str.lower()

                        vol_merge = volume_df.copy()
                        vol_merge["_merge_pair"] = vol_merge["trading_pair"].astype(str).str.strip().str.upper()
                        vol_merge["_merge_connector"] = vol_merge["exchange"].astype(str).str.strip().str.lower()
                        vol_merge.drop(columns=["exchange", "trading_pair"], inplace=True, errors="ignore")

                        spread_df = spread_df.merge(
                            vol_merge,
                            on=["_merge_connector", "_merge_pair"],
                            how="left"
                        )
                        spread_df.drop(columns=["_merge_connector", "_merge_pair"], inplace=True, errors="ignore")

                    # Persist in session state so row-selection reruns don't lose data
                    st.session_state["download_spread__spread_df"] = spread_df
                    st.session_state["download_spread__volume_df"] = volume_df
                    st.session_state["download_spread__failed_pairs"] = failed_pairs
                    st.session_state["download_spread__pairs_list"] = pairs_list
                    st.session_state["download_spread__connectors"] = connectors
                    st.session_state["download_spread__window_hours"] = window_hours
                else:
                    st.warning("No spread data available for the selected parameters.")
            else:
                st.warning("No spread data available for the selected parameters.")

        except Exception as e:
            st.error(f"Failed to fetch spread data: {str(e)}")
            st.code(traceback.format_exc(), language="python")

# Render results from session state (persists across row-selection reruns)
if "download_spread__spread_df" in st.session_state:
    spread_df = st.session_state["download_spread__spread_df"]
    volume_df = st.session_state["download_spread__volume_df"]
    failed_pairs = st.session_state.get("download_spread__failed_pairs", [])
    pairs_list = st.session_state.get("download_spread__pairs_list", [])
    connectors_used = st.session_state.get("download_spread__connectors", connectors)
    window_hours_used = st.session_state.get("download_spread__window_hours", window_hours)

    if failed_pairs:
        st.warning("Some pairs had errors:\n- " + "\n- ".join(failed_pairs))

    st.subheader("Spread Data Details")
    st.caption("Select a row to expand and view all raw samples for that trading pair.")

    display_df = spread_df.drop(columns=["sample_count"], errors="ignore")
    selection = st.dataframe(
        display_df,
        use_container_width=True,
        selection_mode="single-row",
        on_select="rerun",
        key="spread_summary_table",
    )

    connectors_str = "_".join(connectors_used)
    pairs_str = "_".join([p.replace("-", "") for p in pairs_list]) if pairs_list else "all"
    spread_csv = display_df.to_csv(index=False)
    st.download_button(
        label="Download Spread Data as CSV",
        data=spread_csv,
        file_name=f"spread_{connectors_str}_{pairs_str}_{window_hours_used}h.csv",
        mime="text/csv",
        key="dl_spread",
    )

    vol_cols = ["base_volume", "last_price", "quote_volume"]
    vol_cols_present = [c for c in vol_cols if c in spread_df.columns]
    merge_failed = (
        not vol_cols_present
        or spread_df[vol_cols_present].dropna(how="all").empty
    )
    if not volume_df.empty and merge_failed:
        st.subheader("Volume Data")
        st.dataframe(volume_df, use_container_width=True)

    # Expand raw samples when a row is selected
    selected_rows = selection.selection.rows if selection.selection else []
    if selected_rows:
        selected_idx = selected_rows[0]
        row = spread_df.iloc[selected_idx]
        selected_pair = row["pair"]
        selected_connector = row["connector"]

        st.subheader(f"Raw Samples — {selected_connector} / {selected_pair}")
        with st.spinner(f"Fetching samples for {selected_pair} on {selected_connector}..."):
            try:
                samples_response = backend_api_client.market_data.get_spread_data(
                    pair=selected_pair,
                    connector=selected_connector,
                )
                if samples_response and samples_response.get("data"):
                    samples_df = pd.DataFrame(samples_response["data"])
                    st.dataframe(samples_df, use_container_width=True)
                    st.caption(f"{samples_response.get('count', len(samples_df))} samples retrieved")
                    samples_csv = samples_df.to_csv(index=False)
                    st.download_button(
                        label="Download Raw Samples as CSV",
                        data=samples_csv,
                        file_name=f"samples_{selected_connector}_{selected_pair.replace('-', '')}_{window_hours_used}h.csv",
                        mime="text/csv",
                        key="dl_samples",
                    )
                else:
                    st.info("No raw samples found for this trading pair.")
            except Exception as samples_err:
                st.error(f"Failed to fetch samples: {str(samples_err)}")
