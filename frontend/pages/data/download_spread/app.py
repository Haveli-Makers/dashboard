import datetime
import traceback

import pandas as pd
import streamlit as st

from frontend.st_utils import get_backend_api_client, initialize_st_page

SUPPORTED_EXCHANGES = [
    "binance",
    "coinbase",
    "kraken",
    "kucoin",
    "bybit",
    "okx",
    "gate_io",
    "huobi",
    "coindcx",
    "wazirx",
    "coinswitch",
    "zebpay",
    "coinex",
    "valr",
]

# Initialize Streamlit page
initialize_st_page(title="Download Spread", icon="📊")
backend_api_client = get_backend_api_client()
c1, c2, c3 = st.columns([2, 2, 0.5])
with c1:
    connectors = st.multiselect(
        "Exchanges",
        options=SUPPORTED_EXCHANGES,
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

            volume_pairs_by_connector = {}
            if not pairs_list and spread_response and spread_response.get("data"):
                spread_data_temp = pd.DataFrame(spread_response["data"])
                if not spread_data_temp.empty and "connector" in spread_data_temp.columns:
                    for _conn in connectors:
                        conn_pairs = (
                            spread_data_temp[
                                spread_data_temp["connector"].str.lower() == _conn.lower()
                            ]["pair"].dropna().unique().tolist()
                        )
                        volume_pairs_by_connector[_conn] = conn_pairs

            volume_records = []
            failed_pairs = []
            with st.spinner("Fetching volume data..."):
                for connector in connectors:
                    volume_pairs_list = pairs_list if pairs_list else volume_pairs_by_connector.get(connector, [])
                    if not volume_pairs_list:
                        continue
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
                volume_df = volume_df.drop_duplicates(subset=["exchange", "trading_pair"])
            else:
                volume_df = pd.DataFrame()

            vol_data_cols = ["base_volume", "last_price", "quote_volume"]

            def _build_vol_merge(vdf):
                vm = vdf.copy()
                vm["_mk"] = vm["exchange"].astype(str).str.lower() + "||" + vm["trading_pair"].astype(str).str.strip().str.upper()
                vm.drop(columns=["exchange", "trading_pair"], inplace=True, errors="ignore")
                return vm

            if pairs_list:
                skeleton = pd.DataFrame(
                    [(c, p) for c in connectors for p in pairs_list],
                    columns=["connector", "pair"]
                )
                skeleton["_mk"] = skeleton["connector"].str.lower() + "||" + skeleton["pair"].str.strip().str.upper()

                spread_rows = pd.DataFrame(spread_response.get("data", []) if spread_response else [])
                if not spread_rows.empty:
                    spread_rows["_mk"] = (
                        spread_rows["connector"].astype(str).str.lower()
                        + "||"
                        + spread_rows["pair"].astype(str).str.strip().str.upper()
                    )
                    spread_df = skeleton.merge(
                        spread_rows.drop(columns=["connector", "pair"], errors="ignore"),
                        on="_mk", how="left"
                    )
                else:
                    spread_df = skeleton.copy()
                spread_df.drop(columns=["_mk"], inplace=True, errors="ignore")

                if not volume_df.empty:
                    vm = _build_vol_merge(volume_df)
                    spread_df["_mk"] = spread_df["connector"].str.lower() + "||" + spread_df["pair"].str.strip().str.upper()
                    spread_df = spread_df.merge(vm, on="_mk", how="left")
                    spread_df.drop(columns=["_mk"], inplace=True, errors="ignore")

                identity_cols = {"connector", "pair", "sample_count"}
                spread_data_cols = [c for c in spread_df.columns if c not in identity_cols and c not in vol_data_cols]
                rows_to_keep = []
                for idx, row in spread_df.iterrows():
                    spread_missing = not spread_data_cols or all(pd.isna(row.get(c)) for c in spread_data_cols)
                    vol_missing = all(pd.isna(row.get(c)) for c in vol_data_cols if c in spread_df.columns)
                    if spread_missing and vol_missing:
                        already_logged = any(
                            row["pair"] in fp and row["connector"] in fp
                            for fp in failed_pairs
                        )
                        if not already_logged:
                            failed_pairs.append(f"No spread or volume data found for {row['pair']} on {row['connector']}")
                    else:
                        rows_to_keep.append(idx)
                spread_df = spread_df.loc[rows_to_keep].reset_index(drop=True)

                spread_df = spread_df.fillna("-")
                if "quote_volume" in spread_df.columns:
                    spread_df["quote_volume"] = spread_df["quote_volume"].replace(0, "-")

                st.session_state["download_spread__spread_df"] = spread_df
                st.session_state["download_spread__failed_pairs"] = failed_pairs
                st.session_state["download_spread__pairs_list"] = pairs_list
                st.session_state["download_spread__connectors"] = connectors
                st.session_state["download_spread__window_hours"] = window_hours

            else:
                if spread_response and spread_response.get("data"):
                    spread_df = pd.DataFrame(spread_response["data"])

                    if not spread_df.empty:
                        if not volume_df.empty:
                            vm = _build_vol_merge(volume_df)
                            spread_df["_mk"] = (
                                spread_df["connector"].astype(str).str.lower()
                                + "||"
                                + spread_df["pair"].astype(str).str.strip().str.upper()
                            )
                            spread_df = spread_df.merge(vm, on="_mk", how="left")
                            spread_df.drop(columns=["_mk"], inplace=True, errors="ignore")
                            spread_df = spread_df.fillna("-")
                            if "quote_volume" in spread_df.columns:
                                spread_df["quote_volume"] = spread_df["quote_volume"].replace(0, "-")

                        st.session_state["download_spread__spread_df"] = spread_df
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

if "download_spread__spread_df" in st.session_state:
    spread_df = st.session_state["download_spread__spread_df"]
    failed_pairs = st.session_state.get("download_spread__failed_pairs", [])
    pairs_list = st.session_state.get("download_spread__pairs_list", [])
    connectors_used = st.session_state.get("download_spread__connectors", connectors)
    window_hours_used = st.session_state.get("download_spread__window_hours", window_hours)

    if failed_pairs:
        st.warning("Some pairs had errors:\n- " + "\n- ".join(failed_pairs))

    st.subheader("Spread Data Details")
    st.caption("Select a row to expand and view all samples for that trading pair.")

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

    # Expand raw samples when a row is selected
    selected_rows = selection.selection.rows if selection.selection else []
    if selected_rows:
        selected_idx = selected_rows[0]
        row = spread_df.iloc[selected_idx]
        selected_pair = row["pair"]
        selected_connector = row["connector"]

        col1, col2 = st.columns([8, 1])

        with col1:
            st.subheader(f"Samples — {selected_connector} / {selected_pair}")

        with col2:
            sample_count_option = st.selectbox(
                "Number of spreads",
                options=["10", "100", "200","500", "1000", "All"],
                index=1,
                key=f"spread_sample_count_{selected_connector}_{selected_pair}",
                label_visibility="collapsed"
            )
        if sample_count_option == "All":
            selected_sample_count = pd.to_numeric(row.get("sample_count"), errors="coerce")
            sample_limit = int(selected_sample_count) if pd.notna(selected_sample_count) else 100000
        else:
            sample_limit = int(sample_count_option)

        with st.spinner(f"Fetching samples for {selected_pair} on {selected_connector}..."):
            try:
                samples_response = backend_api_client.market_data.get_spread_data(
                    pair=selected_pair,
                    connector=selected_connector,
                    limit=sample_limit,
                )
                if samples_response and samples_response.get("data"):
                    samples_df = pd.DataFrame(samples_response["data"])
                    if "timestamp" in samples_df.columns:
                        local_tz = datetime.datetime.now().astimezone().tzinfo
                        samples_df["timestamp"] = pd.to_datetime(
                            samples_df["timestamp"], unit="s", utc=True).dt.tz_convert(local_tz).dt.strftime("%Y-%m-%d %H:%M:%S")
                    total_samples = samples_response.get("count", len(samples_df))
                    if sample_count_option == "All":
                        display_samples_df = samples_df
                    else:
                        display_samples_df = samples_df.head(int(sample_count_option))

                    st.dataframe(
                        display_samples_df,
                        use_container_width=True,
                        key=f"spread_samples_table_{selected_connector}_{selected_pair}_{sample_count_option}",
                    )
                    st.caption(f"Showing {len(display_samples_df)} of {total_samples} samples retrieved")
                    samples_csv = display_samples_df.to_csv(index=False)
                    st.download_button(
                        label="Download Samples as CSV",
                        data=samples_csv,
                        file_name=f"samples_{selected_connector}_{selected_pair.replace('-', '')}_{window_hours_used}h.csv",
                        mime="text/csv",
                        key="dl_samples",
                    )
                else:
                    st.info("No raw samples found for this trading pair.")
            except Exception as samples_err:
                st.error(f"Failed to fetch samples: {str(samples_err)}")
