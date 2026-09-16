import asyncio
import datetime
import io
import re
import threading
import traceback
import uuid
import zipfile

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
from frontend.st_utils import get_backend_api_client, initialize_st_page


def _fragment(run_every=None):
    real_fragment = getattr(st, "fragment", None) or getattr(st, "experimental_fragment", None)
    if real_fragment is None:
        def _identity(func):
            return func
        return _identity
    try:
        return real_fragment(run_every=run_every)
    except TypeError:
        return real_fragment


def _rerun_app():
    try:
        st.rerun(scope="app")
    except TypeError:
        st.rerun()


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


def _build_sheet_specs(frames_by_pair):
    specs = []
    used_names = set()
    for pair_connector, pair_name in frames_by_pair:
        sheet_name = re.sub(r"[\[\]:*?/\\]", "_", f"{pair_connector}_{pair_name}")[:31]
        base_name, suffix = sheet_name, 2
        while sheet_name in used_names:
            sheet_name = f"{base_name[:28]}_{suffix}"
            suffix += 1
        used_names.add(sheet_name)
        specs.append((sheet_name, pair_connector, pair_name))
    return specs


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


BACKEND_MAX_PAGE_LIMIT = 10000


def _sample_limit_for_row(sample_count_option):
    if sample_count_option != "All":
        return int(sample_count_option)
    return BACKEND_MAX_PAGE_LIMIT


DB_REQUEST_CONCURRENCY = 8


def _fetch_spread_samples_bulk(client, requests, include_total_count=False, on_progress=None):
    """Fetch raw spread samples for many (connector, pair, offset) pages at once."""
    base_url = getattr(client, "_base_url", "http://localhost:8000")
    username = getattr(client, "_username", "admin")
    password = getattr(client, "_password", "admin")
    reqs = [(req[0], req[1], req[2], req[3] if len(req) > 3 else 0) for req in requests]
    total_requests = len(reqs)
    progress_state = {"completed": 0}
    box = {}

    def _worker():
        async def _run():
            api = HummingbotAPIClient(base_url, username, password)
            await api.init()
            semaphore = asyncio.Semaphore(DB_REQUEST_CONCURRENCY)
            try:
                async def _one(connector, pair, limit, offset):
                    async with semaphore:
                        try:
                            resp = await api.market_data.get_spread_data(
                                pair=pair,
                                connector=connector,
                                limit=limit,
                                offset=offset,
                                include_total_count=include_total_count,
                            )
                            return (connector, pair, offset), resp
                        except Exception as exc:
                            return (connector, pair, offset), exc
                        finally:
                            progress_state["completed"] += 1

                results = await asyncio.gather(*(_one(c, p, lim, off) for c, p, lim, off in reqs))
                return dict(results)
            finally:
                await api.close()

        try:
            box["result"] = asyncio.run(_run())
        except Exception as exc:  # surfaced to the caller below
            box["error"] = exc

    worker = threading.Thread(target=_worker, name="spread-samples-fetch", daemon=True)
    worker.start()
    while worker.is_alive():
        if on_progress is not None:
            on_progress(progress_state["completed"], total_requests)
        worker.join(timeout=0.2)

    if on_progress is not None:
        on_progress(total_requests, total_requests)

    if "error" in box:
        raise box["error"]
    return box["result"]


def _fetch_all_spread_samples(client, pair_totals, first_page_frames, on_progress=None):
    page_requests = []
    for connector, pair, total_count in pair_totals:
        remaining_offsets = range(BACKEND_MAX_PAGE_LIMIT, int(total_count or 0), BACKEND_MAX_PAGE_LIMIT)
        for offset in remaining_offsets:
            page_limit = min(BACKEND_MAX_PAGE_LIMIT, int(total_count) - offset)
            page_requests.append((connector, pair, page_limit, offset))

    if not page_requests:
        return {}

    bulk_pages = _fetch_spread_samples_bulk(
        client, page_requests, include_total_count=False, on_progress=on_progress
    )

    full_frames = {}
    for connector, pair, total_count in pair_totals:
        pages = [
            (offset, bulk_pages[(connector, pair, offset)])
            for offset in range(BACKEND_MAX_PAGE_LIMIT, int(total_count or 0), BACKEND_MAX_PAGE_LIMIT)
            if (connector, pair, offset) in bulk_pages
        ]
        errored = [resp for _off, resp in pages if isinstance(resp, Exception)]
        if errored:
            raise errored[0]
        if not pages:
            continue

        pages.sort(key=lambda item: item[0])
        frames = [first_page_frames[(connector, pair)]]
        for _offset, resp in pages:
            if resp and resp.get("data"):
                page_df = pd.DataFrame(resp["data"])
                page_df["connector"] = connector
                page_df["pair"] = pair
                other_cols = [c for c in page_df.columns if c not in ("connector", "pair")]
                frames.append(_format_timestamp_column(page_df[["connector", "pair"] + other_cols]))
        full_frames[(connector, pair)] = pd.concat(frames, ignore_index=True)

    return full_frames

@st.cache_resource
def _full_download_registry():
    return {"lock": threading.Lock(), "jobs": {}}


def _get_full_download_job(job_id):
    if not job_id:
        return None
    registry = _full_download_registry()
    with registry["lock"]:
        job = registry["jobs"].get(job_id)
        return dict(job) if job is not None else None


def _discard_full_download_job(job_id):
    registry = _full_download_registry()
    with registry["lock"]:
        registry["jobs"].pop(job_id, None)


def _start_full_download_job(client, truncated_pairs, first_page_frames):
    registry = _full_download_registry()
    job_id = uuid.uuid4().hex
    with registry["lock"]:
        registry["jobs"][job_id] = {
            "status": "running",
            "phase": "fetching",
            "completed": 0,
            "total": 0,
            "result": None,
            "error": None,
        }

    def _on_progress(completed, total):
        with registry["lock"]:
            job = registry["jobs"].get(job_id)
            if job is not None:
                job["completed"] = completed
                job["total"] = total

    def _run_job():
        try:
            full_frames = dict(first_page_frames)
            full_frames.update(
                _fetch_all_spread_samples(client, truncated_pairs, first_page_frames, on_progress=_on_progress)
            )

            with registry["lock"]:
                job = registry["jobs"].get(job_id)
                if job is not None:
                    job["phase"] = "preparing_files"

            samples_df_full = pd.concat(full_frames.values(), ignore_index=True)
            sheet_specs_full = tuple(_build_sheet_specs(full_frames))
            csv_bytes, csv_is_zip, xlsx_bytes = _build_download_bytes(samples_df_full, sheet_specs_full)

            result = {
                "samples_df": samples_df_full,
                "sheet_specs": sheet_specs_full,
                "csv_bytes": csv_bytes,
                "csv_is_zip": csv_is_zip,
                "xlsx_bytes": xlsx_bytes,
            }
            with registry["lock"]:
                job = registry["jobs"].get(job_id)
                if job is not None:
                    job["status"] = "done"
                    job["result"] = result
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI via job["error"]
            with registry["lock"]:
                job = registry["jobs"].get(job_id)
                if job is not None:
                    job["status"] = "error"
                    job["error"] = str(exc)

    threading.Thread(target=_run_job, name=f"full-samples-download-{job_id}", daemon=True).start()
    return job_id


def _build_download_bytes(samples_df, sheet_specs):
    sheets = {
        name: samples_df[
            (samples_df["connector"] == conn) & (samples_df["pair"] == pair)
        ].reset_index(drop=True)
        for name, conn, pair in sheet_specs
    }

    if len(sheets) > 1:
        # CSV has no concept of "sheets" - the closest true equivalent is one
        # CSV file per pair, bundled into a single ZIP the user downloads.
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for name, df in sheets.items():
                zip_file.writestr(f"{name}.csv", df.to_csv(index=False))
        csv_bytes = zip_buffer.getvalue()
        csv_is_zip = True
    else:
        csv_bytes = samples_df.to_csv(index=False)
        csv_is_zip = False

    return csv_bytes, csv_is_zip, dataframes_to_xlsx_bytes(sheets)


@_fragment(run_every="2s")
def _render_full_download_progress(job_id, full_cache_key):
    job = _get_full_download_job(job_id)
    if job is None:
        return

    if job["status"] == "running":
        if job.get("phase") == "preparing_files":
            st.progress(1.0, text="Fetching complete - preparing CSV/XLSX files...")
        else:
            completed, total = job["completed"], job["total"]
            pct = (completed / total) if total else 0.0
            st.progress(
                pct,
                text=f"Fetching all samples... {int(pct * 100)}% ({completed}/{total} pages)",
            )
        st.caption(
            "This keeps fetching in the background even if you switch pages - "
            "come back here once it's done."
        )
    elif job["status"] == "error":
        st.error(f"Failed to fetch full history: {job['error']}")
        if st.button("Retry", key="retry_full_samples_download", use_container_width=True):
            _discard_full_download_job(job_id)
            st.session_state.pop("download_spread__job_id", None)
            _rerun_app()  
    elif job["status"] == "done":
        st.session_state["download_spread__prepared_full"] = {
            "key": full_cache_key,
            "samples_df": job["result"]["samples_df"],
            "sheet_specs": job["result"]["sheet_specs"],
            "csv_bytes": job["result"]["csv_bytes"],
            "csv_is_zip": job["result"]["csv_is_zip"],
            "xlsx_bytes": job["result"]["xlsx_bytes"],
        }
        _discard_full_download_job(job_id)
        st.session_state.pop("download_spread__job_id", None)
        _rerun_app()


@st.cache_data(show_spinner=False, max_entries=8)
def _build_sample_downloads(samples_df, sheet_specs):
    return _build_download_bytes(samples_df, sheet_specs)


# Initialize Streamlit page
initialize_st_page(title="Download Spread", icon="📊")
backend_api_client = get_backend_api_client()
window_hours = 24
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

    connectors_str = "_".join(connectors_used)
    pairs_str = "_".join([p.replace("-", "") for p in pairs_list]) if pairs_list else "all"
    display_df = spread_df.drop(columns=["sample_count"], errors="ignore")
    spread_csv = display_df.to_csv(index=False)
    spread_xlsx_filename = f"spread_{connectors_str}_{pairs_str}_{window_hours_used}h.xlsx"

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
    spread_xlsx = dataframes_to_xlsx_bytes(spread_sheets)

    header_col, download_col, email_col = st.columns([8, 1, 1])
    with header_col:
        st.subheader("Spread Data Details")
    with download_col:
        with st.popover("⬇️", use_container_width=True):
            st.download_button(
                label="Download as CSV",
                data=spread_csv,
                file_name=f"spread_{connectors_str}_{pairs_str}_{window_hours_used}h.csv",
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
                            window_hours=window_hours_used,
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

    if selected_rows:
        selected_pairs_df = spread_df.iloc[selected_rows].reset_index(drop=True)
    else:
        _cached_for_fallback = st.session_state.get("download_spread__samples")
        selected_pairs_df = _cached_for_fallback["selected_pairs_df"] if _cached_for_fallback else None

    if selected_pairs_df is None or selected_pairs_df.empty:
        st.session_state.pop("download_spread__samples", None)
    else:
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
                        backend_api_client, fetch_requests, include_total_count=want_total
                    )
                except Exception as bulk_err:  # noqa: BLE001
                    bulk_samples = {(c, p, 0): bulk_err for c, p, _lim in fetch_requests}

            fetched_frames = {}
            fetch_errors = []
            fetched_total = 0
            pair_totals = []
            for f_connector, f_pair, _lim in fetch_requests:
                resp = bulk_samples.get((f_connector, f_pair, 0))
                if isinstance(resp, Exception):
                    fetch_errors.append(
                        f"Failed to fetch samples for {f_pair} on {f_connector}: {resp}"
                    )
                    continue
                pair_total_count = int(resp.get("total_count") or 0) if resp else 0
                fetched_total += pair_total_count
                if resp and resp.get("data"):
                    pair_samples_df = pd.DataFrame(resp["data"])
                    pair_samples_df["connector"] = f_connector
                    pair_samples_df["pair"] = f_pair
                    other_cols = [c for c in pair_samples_df.columns if c not in ("connector", "pair")]
                    pair_samples_df = pair_samples_df[["connector", "pair"] + other_cols]
                    pair_samples_df = _format_timestamp_column(pair_samples_df)
                    fetched_frames[(f_connector, f_pair)] = pair_samples_df
                    if want_total and pair_total_count > len(pair_samples_df):
                        pair_totals.append((f_connector, f_pair, pair_total_count))
                else:
                    fetch_errors.append(f"No raw samples found for {f_pair} on {f_connector}.")

            st.session_state["download_spread__samples"] = {
                "keys": selected_keys,
                "sample_count_option": sample_count_option,
                "samples_df": (
                    pd.concat(fetched_frames.values(), ignore_index=True) if fetched_frames else None
                ),
                "sheet_specs": tuple(_build_sheet_specs(fetched_frames)),
                "truncated_pairs": tuple(pair_totals),
                "selected_pairs_df": selected_pairs_df,
                "total_available": fetched_total,
                "errors": fetch_errors,
                "window_hours_used": window_hours_used,
            }
            st.session_state.pop("download_spread__prepared_full", None)
            _discard_full_download_job(st.session_state.pop("download_spread__job_id", None))
            st.session_state.pop("download_spread__job_key", None)

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
            truncated_pairs = cached_samples.get("truncated_pairs") or ()
            window_hours_used = cached_samples["window_hours_used"]

            samples_header_col, samples_download_col, samples_email_col = st.columns([6, 1, 1])
            with samples_header_col:
                if sample_count_option == "All" and total_available:
                    caption = f"Showing {len(samples_df)} of {total_available} samples across {len(selected_pairs_df)} pair(s)"
                    if truncated_pairs:
                        caption += " (preview capped at 10,000/pair - use Download to fetch everything)"
                    st.caption(caption)
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
            samples_xlsx_filename = f"samples_{selected_connectors_str}_{selected_pairs_str}_{window_hours_used}h.xlsx"

            full_cache_key = (cached_samples["keys"], sample_count_option)
            prepared_full = st.session_state.get("download_spread__prepared_full")
            if prepared_full and prepared_full.get("key") != full_cache_key:
                prepared_full = None
            needs_full_fetch = bool(truncated_pairs) and prepared_full is None

            with samples_download_col:
                with st.popover("⬇️", use_container_width=True):
                    if needs_full_fetch:
                        job_id = st.session_state.get("download_spread__job_id")
                        job_key_matches = st.session_state.get("download_spread__job_key") == full_cache_key
                        active_job = job_id if (job_id and job_key_matches and _get_full_download_job(job_id)) else None

                        if active_job is None:
                            st.caption(
                                f"Only the {len(samples_df)}-row preview has been fetched "
                                f"({total_available} total). Fetch everything to download it all."
                            )
                            if st.button(
                                "Fetch all & prepare download",
                                key="prepare_full_samples_download",
                                use_container_width=True,
                            ):
                                first_page_frames = {
                                    (conn, pair): samples_df[
                                        (samples_df["connector"] == conn) & (samples_df["pair"] == pair)
                                    ].reset_index(drop=True)
                                    for _name, conn, pair in sheet_specs
                                }
                                new_job_id = _start_full_download_job(
                                    backend_api_client, truncated_pairs, first_page_frames
                                )
                                st.session_state["download_spread__job_id"] = new_job_id
                                st.session_state["download_spread__job_key"] = full_cache_key
                                st.rerun()
                        else:
                            _render_full_download_progress(active_job, full_cache_key)

                    if not needs_full_fetch:
                        if prepared_full:
                            download_samples_df = prepared_full["samples_df"]
                            samples_csv = prepared_full["csv_bytes"]
                            samples_csv_is_zip = prepared_full["csv_is_zip"]
                            samples_xlsx = prepared_full["xlsx_bytes"]
                        else:
                            download_samples_df = samples_df
                            samples_csv, samples_csv_is_zip, samples_xlsx = _build_sample_downloads(
                                samples_df, sheet_specs
                            )

                        csv_extension = "zip" if samples_csv_is_zip else "csv"
                        csv_mime = "application/zip" if samples_csv_is_zip else "text/csv"
                        csv_label = "Download CSVs as ZIP" if samples_csv_is_zip else "Download as CSV"

                        st.download_button(
                            label=csv_label,
                            data=samples_csv,
                            file_name=(
                                f"samples_{selected_connectors_str}_{selected_pairs_str}"
                                f"_{window_hours_used}h.{csv_extension}"
                            ),
                            mime=csv_mime,
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
                    if needs_full_fetch:
                        st.info("Fetch the full data from the ⬇️ download popover first, then come back to email it.")
                    else:
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
                                        row_count=len(download_samples_df),
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
