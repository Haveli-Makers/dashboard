import pandas as pd
import streamlit as st

from frontend.st_utils import get_backend_api_client, initialize_st_page


initialize_st_page(
    title="Scripts",
    layout="wide",
    show_readme=False,
)

backend_api_client = get_backend_api_client()

if "scripts_history_expanded" not in st.session_state:
    st.session_state.scripts_history_expanded = False


def get_scripts():
    try:
        return backend_api_client.scripts.list_scripts()
    except Exception as exc:
        st.error(f"Failed to fetch scripts: {exc}")
        return []


def get_configs():
    try:
        return backend_api_client.scripts.list_script_configs()
    except Exception as exc:
        st.error(f"Failed to fetch script configs: {exc}")
        return []


def get_config_names(configs):
    return [config.get("config_name") for config in configs if config.get("config_name")]


def render_output(result):
    status = result.get("status", "unknown")
    if status == "success":
        st.success("Script completed successfully")
    else:
        st.error("Script failed")
    st.caption(
        f"Run ID: {result.get('run_id')} | "
        f"Started: {result.get('started_at')} | "
        f"Completed: {result.get('completed_at')} | "
        f"Return code: {result.get('return_code')}"
    )
    st.code(result.get("output") or "", language="text")


def build_run_payload(prefix, scripts, config_names):
    strategy_name = st.selectbox("Strategy", scripts, key=f"{prefix}_strategy")
    config_name = st.selectbox("Config", config_names, key=f"{prefix}_config")
    account_name = st.text_input("Account", key=f"{prefix}_account", placeholder="Optional")
    verbose = st.checkbox("Verbose output", key=f"{prefix}_verbose")
    extra_args_text = st.text_input("Extra args", key=f"{prefix}_extra_args", placeholder="Optional, space separated")
    return {
        "strategy_name": strategy_name,
        "config_name": config_name,
        "account_name": account_name or None,
        "verbose": verbose,
        "extra_args": [arg for arg in extra_args_text.split(" ") if arg],
    }


def schedules_to_overview_df(schedules):
    rows = []
    for item in schedules:
        cadence = (
            f"Every {item.get('interval_value')} {item.get('interval_unit')}"
            if item.get("interval_value") is not None and item.get("interval_unit")
            else "—"
        )
        enabled = item.get("enabled", True)
        status = "Active" if enabled else "Paused"
        rows.append(
            {
                "Name": item.get("name"),
                "Strategy": item.get("strategy_name"),
                "Config": item.get("config_name"),
                "Account": item.get("account_name") or "—",
                "Cadence": cadence,
                "Next run": item.get("next_run_at"),
                "Last run": item.get("last_run_at") or "—",
                "Status": status,
            }
        )
    df = pd.DataFrame(rows)
    for col in ("Next run", "Last run"):
        if col in df.columns and not df.empty:
            df[col] = pd.to_datetime(df[col], errors="coerce")
            df[col] = df[col].dt.strftime("%Y-%m-%d %H:%M:%S").where(df[col].notna(), "—")
    return df


scripts = get_scripts()
configs = get_configs()
config_names = get_config_names(configs)

scheduled_tab, instant_tab = st.tabs(["Scheduled Workflows", "Instant Run"])

with scheduled_tab:
    st.caption("Recurring strategy runs managed by the API. Create workflows, run on demand, and review past output.")

    try:
        schedules = backend_api_client.scripts.list_script_schedules()
    except Exception as exc:
        st.error(f"Failed to fetch schedules: {exc}")
        schedules = []

    if schedules:
        st.subheader("All scheduled workflows")
        st.dataframe(schedules_to_overview_df(schedules), use_container_width=True, hide_index=True)

        schedule_labels = {f"{item['name']} ({item['id'][:8]})": item["id"] for item in schedules}
        selected_label = st.selectbox("Workflow", list(schedule_labels.keys()))
        selected_schedule_id = schedule_labels[selected_label]
        selected_name = next(s["name"] for s in schedules if s["id"] == selected_schedule_id)

        run_col, history_col, delete_col = st.columns(3)
        with run_col:
            if st.button("Run now", type="primary", use_container_width=True):
                try:
                    result = backend_api_client.scripts.run_script_schedule_now(selected_schedule_id)
                    render_output(result)
                except Exception as exc:
                    st.error(f"Scheduled run failed: {exc}")
        with history_col:
            if st.button("View history", use_container_width=True):
                st.session_state.scripts_history_expanded = True
                st.rerun()
        with delete_col:
            if st.button("Delete", use_container_width=True):
                try:
                    backend_api_client.scripts.delete_script_schedule(selected_schedule_id)
                    st.session_state.scripts_history_expanded = False
                    st.success("Schedule deleted")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed to delete schedule: {exc}")

        with st.expander(
            f"Run history: {selected_name} (up to 50 outputs)",
            expanded=st.session_state.scripts_history_expanded,
        ):
            try:
                history = backend_api_client.scripts.get_script_schedule_history(selected_schedule_id, limit=50)
                runs = history.get("runs", [])
            except Exception as exc:
                st.error(f"Failed to fetch history: {exc}")
                runs = []

            if runs:
                for run in runs:
                    with st.expander(
                        f"{run.get('completed_at')} | {run.get('status')} | {run.get('run_id')}",
                        expanded=False,
                    ):
                        render_output(run)
            else:
                st.info("No stored outputs for this workflow yet.")
    else:
        st.info("No scheduled workflows yet. Create one below once scripts and configs are available from the API.")

    st.divider()
    with st.expander("Create scheduled workflow"):
        if not scripts:
            st.info("No scripts are currently available from the API.")
        elif not config_names:
            st.info("No script configs are currently available from the API.")
        else:
            name = st.text_input("Schedule name", placeholder="e.g. update hourly balance")
            payload = build_run_payload("schedule", scripts, config_names)
            interval_value = st.number_input("Every", min_value=1, value=60, step=1)
            interval_unit = st.selectbox("Unit", ["minutes", "hours", "weeks"])
            if st.button("Create schedule", type="primary"):
                try:
                    schedule = backend_api_client.scripts.create_script_schedule(
                        {
                            **payload,
                            "name": name or f"{payload['strategy_name']} schedule",
                            "interval_value": int(interval_value),
                            "interval_unit": interval_unit,
                        }
                    )
                    st.success(f"Created schedule: {schedule.get('name')}")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed to create schedule: {exc}")

with instant_tab:
    st.caption("One-off run. Output is shown here and is not stored in schedule history.")
    if not scripts:
        st.info("No scripts are currently available from the API.")
    elif not config_names:
        st.info("No script configs are currently available from the API.")
    else:
        st.subheader("Run once")
        payload = build_run_payload("instant", scripts, config_names)
        if st.button("Run now", type="primary"):
            try:
                result = backend_api_client.scripts.run_script_instant(payload)
                render_output(result)
            except Exception as exc:
                st.error(f"Script run failed: {exc}")
