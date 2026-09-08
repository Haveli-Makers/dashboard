import asyncio
import datetime
import re
import threading
import traceback

import pandas as pd
import streamlit as st

from api_client.client import HummingbotAPIClient

from frontend.email_utils import (
    SAMPLES_EMAIL_BODY_TEMPLATE,
    SAMPLES_EMAIL_SUBJECT_TEMPLATE,
    SPREAD_EMAIL_BODY_TEMPLATE,
    SPREAD_EMAIL_SUBJECT_TEMPLATE,
    build_samples_email_context,
    build_spread_email_context,
    dataframes_to_xlsx_bytes,
    is_smtp_configured,
    parse_recipients,
    render_template,
    send_email_with_xlsx,
)
from api_client.audit import audit_logged
from frontend.st_utils import (
    get_backend_api_client,
    get_selected_server_config,
    initialize_st_page,
)

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
    "coin_switch",
    "zebpay",
    "coinex",
    "valr",
]


def _safe_filename_part(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_") or "unknown"


def _format_timestamp_column(df):
    if "timestamp" not in df.columns:
        return df

    formatted_df = df.copy()
    local_tz = datetime.datetime.now().astimezone().tzinfo
    formatted_df["timestamp"] = (
        pd.to_datetime(formatted_df["timestamp"], unit="s", utc=True)
        .dt.tz_convert(local_tz)
        .dt.strftime("%Y-%m-%d %H:%M:%S")
    )
    return formatted_df


MAX_SAMPLE_LIMIT = 10000


def _sample_limit_for_row(sample_count_option):
    if sample_count_option != "All":
        return int(sample_count_option)
    return MAX_SAMPLE_LIMIT


def _fetch_spread_samples_bulk(requests, include_total_count=False):
    """Fetch raw spread samples for many (connector, pair) at once.
    """
    server = get_selected_server_config()
    host = str(server.get("host", "127.0.0.1"))
    port = server.get("port", 8000)
    if not host.startswith(("http://", "https://")):
        base_url = f"http://{host}:{port}"
    else:
        base_url = f"{host}:{port}"
    username = server.get("username", "admin")
    password = server.get("password", "admin")
    reqs = list(requests)
    box = {}

    def _worker():
        async def _run():
            api = HummingbotAPIClient(base_url, username, password)
            await api.init()
            try:
                async def _one(connector, pair, limit):
                    try:
                        resp = await api.market_data.get_spread_data(
                            pair=pair,
                            connector=connector,
                            limit=limit,
                            include_total_count=include_total_count,
                        )
                        return (connector, pair), resp
                    except Exception as exc:
                        return (connector, pair), exc

                pairs = await asyncio.gather(*(_one(c, p, lim) for c, p, lim in reqs))
                return dict(pairs)
            finally:
                await api.close()

        try:
            box["result"] = asyncio.run(_run())
        except Exception as exc:  # surfaced to the caller below
            box["error"] = exc

    worker = threading.Thread(target=_worker, name="spread-samples-fetch", daemon=True)
    worker.start()
    worker.join()

    if "error" in box:
        raise box["error"]
    return box["result"]


@st.cache_data(show_spinner=False, max_entries=8)
def _build_sample_downloads(samples_df, sheet_specs):
    """Build the CSV + XLSX bytes for the samples table.

    Cached so the (multi-second for tens of thousands of rows) XLSX build runs
    once per unique selection instead of on every rerun.
    """
    csv_bytes = samples_df.to_csv(index=False)
    sheets = {
        name: samples_df[
            (samples_df["connector"] == conn) & (samples_df["pair"] == pair)
        ].reset_index(drop=True)
        for name, conn, pair in sheet_specs
    }
    return csv_bytes, dataframes_to_xlsx_bytes(sheets)


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
with c2:
    trading_pairs = st.text_input("Trading Pairs (BTC-USDT, ETH-USDT)", value="")
with c3:
    st.write("")
    st.write("")
    get_data_button = st.button("Get Spread!")

if get_data_button:
    # Validate inputs
    if not connectors:
        st.error("Please select at least one exchange.")
    else:
        st.session_state.pop("download_spread__spread_df", None)
        try:
            pairs_list = [p.strip() for p in trading_pairs.split(",") if p.strip()]

            with st.spinner("Fetching spread data..."), audit_logged():
                spread_response = backend_api_client.market_data.get_spread_averages(
                    pairs=pairs_list,
                    connectors=connectors,
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
            with st.spinner("Fetching volume data..."), audit_logged():
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

    if failed_pairs:
        st.warning("Some pairs had errors:\n- " + "\n- ".join(failed_pairs))

    connectors_str = "_".join(connectors_used)
    pairs_str = "_".join([p.replace("-", "") for p in pairs_list]) if pairs_list else "all"
    display_df = spread_df.drop(columns=["sample_count"], errors="ignore")
    spread_xlsx_filename = f"spread_{connectors_str}_{pairs_str}.xlsx"

    header_col, download_col, email_col = st.columns([8, 1, 1])
    with header_col:
        st.subheader("Spread Data Details")

    st.caption("Select one or more rows to view all samples for those trading pairs in a single table.")

    # Render the table first so it paints immediately; the CSV/XLSX payloads
    # below are memoized so they are only rebuilt when the data changes.
    selection = st.dataframe(
        display_df,
        use_container_width=True,
        selection_mode="multi-row",
        on_select="rerun",
        key="spread_summary_table",
    )

    spread_csv = _cached_csv(display_df)

    spread_sheets = {}
    used_spread_sheet_names = set()
    if "connector" in display_df.columns:
        for connector_name in display_df["connector"].drop_duplicates():
            sheet_name = re.sub(r"[\[\]:*?/\\]", "_", str(connector_name))[:31]
            base_name, suffix = sheet_name, 2
            while sheet_name in used_spread_sheet_names:
                sheet_name = f"{base_name[:28]}_{suffix}"
                suffix += 1
            used_spread_sheet_names.add(sheet_name)
            spread_sheets[sheet_name] = display_df[display_df["connector"] == connector_name].reset_index(drop=True)
    else:
        spread_sheets["Spread Data"] = display_df
    if not spread_sheets:
        spread_sheets["Spread Data"] = display_df
    spread_xlsx = _cached_xlsx(spread_sheets)

    with download_col:
        with st.popover("⬇️", use_container_width=True):
            st.download_button(
                label="Download as CSV",
                data=spread_csv,
                file_name=f"spread_{connectors_str}_{pairs_str}.csv",
                mime="text/csv",
                key="dl_spread",
                use_container_width=True,
            )
            st.download_button(
                label="Download as XLSX",
                data=spread_xlsx,
                file_name=spread_xlsx_filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_spread_xlsx",
                use_container_width=True,
            )
    with email_col:
        with st.popover("📧", use_container_width=True):
            if not is_smtp_configured():
                st.info(
                    "SMTP is not configured. Set SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD "
                    "in the `.env` file to enable emailing."
                )
            recipients_raw = st.text_input(
                "Recipient email(s)",
                placeholder="alice@example.com, bob@example.com",
                key="spread_email_recipients",
            )
            if st.button("Send Email", key="send_spread_email", use_container_width=True):
                try:
                    recipients, invalid_recipients = parse_recipients(recipients_raw)
                    if invalid_recipients:
                        st.error(f"Invalid recipient email address(es): {', '.join(invalid_recipients)}")
                    elif not recipients:
                        st.error("Please enter at least one valid recipient email address.")
                    else:
                        email_context = build_spread_email_context(
                            connectors=connectors_used,
                            pairs=pairs_list,
                            row_count=len(display_df),
                            failed_count=len(failed_pairs),
                        )
                        email_subject = render_template(SPREAD_EMAIL_SUBJECT_TEMPLATE, email_context)
                        email_body = render_template(SPREAD_EMAIL_BODY_TEMPLATE, email_context)
                        with st.spinner("Sending email..."):
                            send_email_with_xlsx(
                                to_emails=recipients,
                                subject=email_subject,
                                body=email_body,
                                attachment_bytes=spread_xlsx,
                                attachment_filename=spread_xlsx_filename,
                            )
                        st.success(f"Email sent to {', '.join(recipients)}")
                except Exception as email_err:
                    st.error(f"Failed to send email: {str(email_err)}")

    st.caption("Tick one or more rows, choose how many spreads, then click **Fetch Samples**.")

    selection = st.dataframe(
        display_df,
        use_container_width=True,
        selection_mode="multi-row",
        on_select="rerun",
        key="spread_summary_table",
    )

    selected_rows = selection.selection.rows if selection.selection else []
    selected_rows = [row for row in selected_rows if row < len(spread_df)]
    if not selected_rows:
        st.session_state.pop("download_spread__samples", None)
    else:
        selected_pairs_df = spread_df.iloc[selected_rows].reset_index(drop=True)
        selected_keys = "_".join(
            f"{r['connector']}-{r['pair']}" for _, r in selected_pairs_df.iterrows()
        )

        col1, col2, col3 = st.columns([6, 1.3, 1.3], vertical_alignment="bottom")
        with col1:
            st.subheader("Samples for the selected Pairs")
        with col2:
            sample_count_option = st.selectbox(
                "Number of spreads",
                options=["All", "10", "100", "200", "500", "1000"],
                index=0,  # Default to All
                key="spread_sample_count",
                label_visibility="collapsed",
            )
        with col3:
            fetch_samples_clicked = st.button(
                "Fetch Samples", use_container_width=True, key="fetch_samples_btn"
            )

        if fetch_samples_clicked:
            sample_limit = _sample_limit_for_row(sample_count_option)
            want_total = sample_count_option == "All"
            fetch_requests = [
                (row["connector"], row["pair"], sample_limit)
                for _, row in selected_pairs_df.iterrows()
            ]

            with st.spinner("Fetching samples..."):
                try:
                    bulk_samples = _fetch_spread_samples_bulk(
                        fetch_requests, include_total_count=want_total
                    )
                except Exception as bulk_err:  # noqa: BLE001
                    bulk_samples = {(c, p): bulk_err for c, p, _lim in fetch_requests}

            fetched_frames = []
            fetch_errors = []
            fetched_total = 0
            for f_connector, f_pair, _lim in fetch_requests:
                resp = bulk_samples.get((f_connector, f_pair))
                if isinstance(resp, Exception):
                    fetch_errors.append(
                        f"Failed to fetch samples for {f_pair} on {f_connector}: {resp}"
                    )
                    continue
                fetched_total += int(resp.get("total_count") or 0) if resp else 0
                if resp and resp.get("data"):
                    pair_samples_df = pd.DataFrame(resp["data"])
                    pair_samples_df["connector"] = f_connector
                    pair_samples_df["pair"] = f_pair
                    other_cols = [c for c in pair_samples_df.columns if c not in ("connector", "pair")]
                    pair_samples_df = pair_samples_df[["connector", "pair"] + other_cols]
                    fetched_frames.append(_format_timestamp_column(pair_samples_df))
                else:
                    fetch_errors.append(f"No raw samples found for {f_pair} on {f_connector}.")

            sheet_specs = []
            used_sheet_names = set()
            for pair_samples_df in fetched_frames:
                pair_connector = pair_samples_df["connector"].iloc[0]
                pair_name = pair_samples_df["pair"].iloc[0]
                sheet_name = re.sub(r"[\[\]:*?/\\]", "_", f"{pair_connector}_{pair_name}")[:31]
                base_name, suffix = sheet_name, 2
                while sheet_name in used_sheet_names:
                    sheet_name = f"{base_name[:28]}_{suffix}"
                    suffix += 1
                used_sheet_names.add(sheet_name)
                sheet_specs.append((sheet_name, pair_connector, pair_name))

            st.session_state["download_spread__samples"] = {
                "keys": selected_keys,
                "sample_count_option": sample_count_option,
                "samples_df": (
                    pd.concat(fetched_frames, ignore_index=True) if fetched_frames else None
                ),
                "selected_pairs_df": selected_pairs_df,
                "total_available": fetched_total,
                "errors": fetch_errors,
                "sheet_specs": tuple(sheet_specs),
                "window_hours_used": window_hours_used,
            }

        cached_samples = st.session_state.get("download_spread__samples")
        selection_matches = (
            bool(cached_samples)
            and cached_samples.get("keys") == selected_keys
            and cached_samples.get("sample_count_option") == sample_count_option
        )
        if not selection_matches:
            st.info("Click ***Fetch Samples*** to load samples for the current selection.")

        samples_errors = cached_samples["errors"] if selection_matches else []
        if samples_errors:
            st.warning("\n\n".join(samples_errors))

        samples_df = cached_samples["samples_df"] if selection_matches else None

        if samples_df is not None and not samples_df.empty:
            selected_pairs_df = cached_samples["selected_pairs_df"]
            sample_count_option = cached_samples["sample_count_option"]
            total_available = cached_samples["total_available"]
            sheet_specs = cached_samples["sheet_specs"]
            window_hours_used = cached_samples["window_hours_used"]

            samples_header_col, samples_download_col, samples_email_col = st.columns([6, 1, 1])
            with samples_header_col:
                if sample_count_option == "All" and total_available:
                    st.caption(
                        f"Showing {len(samples_df)} of {total_available} samples across {len(selected_pairs_df)} pair(s)"
                    )
                else:
                    st.caption(f"Showing {len(samples_df)} samples across {len(selected_pairs_df)} pair(s)")

            st.dataframe(
                samples_df,
                use_container_width=True,
                key=f"spread_samples_table_{cached_samples['keys']}_{sample_count_option}",
            )

            selected_connectors_str = "_".join(
                _safe_filename_part(c) for c in sorted(selected_pairs_df["connector"].unique().tolist())
            )
            selected_pairs_str = "_".join(
                _safe_filename_part(p.replace("-", "")) for p in sorted(selected_pairs_df["pair"].unique().tolist())
            )
            samples_xlsx_filename = f"samples_{selected_connectors_str}_{selected_pairs_str}.xlsx"

            samples_csv = _cached_csv(samples_df)

            samples_csv, samples_xlsx = _build_sample_downloads(samples_df, sheet_specs)

            with samples_download_col:
                with st.popover("⬇️", use_container_width=True):
                    st.download_button(
                        label="Download as CSV",
                        data=samples_csv,
                        file_name=f"samples_{selected_connectors_str}_{selected_pairs_str}.csv",
                        mime="text/csv",
                        key="dl_samples_csv",
                        use_container_width=True,
                    )
                    st.download_button(
                        label="Download as XLSX",
                        data=samples_xlsx,
                        file_name=samples_xlsx_filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="dl_samples_xlsx",
                        use_container_width=True,
                    )
            with samples_email_col:
                with st.popover("📧", use_container_width=True):
                    if not is_smtp_configured():
                        st.info(
                            "SMTP is not configured. Set SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD "
                            "in the `.env` file to enable emailing."
                        )
                    samples_recipients_raw = st.text_input(
                        "Recipient email(s)",
                        placeholder="alice@example.com, bob@example.com",
                        key="samples_email_recipients",
                    )
                    if st.button("Send Email", key="send_samples_email", use_container_width=True):
                        try:
                            samples_recipients, invalid_samples_recipients = parse_recipients(samples_recipients_raw)
                            if invalid_samples_recipients:
                                st.error(f"Invalid recipient email address(es): {', '.join(invalid_samples_recipients)}")
                            elif not samples_recipients:
                                st.error("Please enter at least one valid recipient email address.")
                            else:
                                samples_email_context = build_samples_email_context(
                                    connectors=sorted(selected_pairs_df["connector"].unique().tolist()),
                                    pairs=sorted(selected_pairs_df["pair"].unique().tolist()),
                                    row_count=len(samples_df),
                                )
                                samples_email_subject = render_template(SAMPLES_EMAIL_SUBJECT_TEMPLATE, samples_email_context)
                                samples_email_body = render_template(SAMPLES_EMAIL_BODY_TEMPLATE, samples_email_context)
                                with st.spinner("Sending email..."):
                                    send_email_with_xlsx(
                                        to_emails=samples_recipients,
                                        subject=samples_email_subject,
                                        body=samples_email_body,
                                        attachment_bytes=samples_xlsx,
                                        attachment_filename=samples_xlsx_filename,
                                    )
                                st.success(f"Email sent to {', '.join(samples_recipients)}")
                        except Exception as samples_email_err:
                            st.error(f"Failed to send email: {str(samples_email_err)}")
