import json
import re
from datetime import datetime

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


def get_script_config_template(script_name):
    try:
        template_response = backend_api_client.scripts.run_script({"script_name": script_name, "config": {}})
        if isinstance(template_response, dict) and template_response.get("status") == "requires_config":
            return template_response.get("config", {})
    except Exception as exc:
        st.warning(f"Failed to fetch config template from /scripts/run for {script_name}: {exc}")

    try:
        template = backend_api_client.scripts.get_script_config_template(script_name)
        if isinstance(template, dict) and template.get("status") == "requires_config":
            return template.get("config", {})
        return template if isinstance(template, dict) else {}
    except Exception as exc:
        st.warning(f"Failed to fetch config template for {script_name}: {exc}")
        return {}


def build_config_from_template(template):
    config = {}
    for field_name, field_info in template.items():
        if isinstance(field_info, dict) and "default" in field_info:
            config[field_name] = field_info.get("default")
        else:
            config[field_name] = field_info
    return config


def build_script_run_body(script_name):
    template = get_script_config_template(script_name)
    return {
        "script_name": script_name,
        "config": build_config_from_template(template),
    }, template


def make_script_config_name(schedule_name, script_name):
    name_source = schedule_name or script_name
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", name_source.strip().lower()).strip("_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{slug or script_name}_schedule_{timestamp}"


def build_saved_script_config(script_name, config):
    saved_config = dict(config)
    saved_config.setdefault("script_file_name", f"{script_name}.py")
    return saved_config


def render_config_inputs(config_template, prefix="config"):
    config = {}
    for field_name, field_info in config_template.items():
        default = field_info.get("default")
        annotation = field_info.get("annotation", "")
        prompt = field_info.get("prompt", field_name)

        if "int" in annotation:
            config[field_name] = st.number_input(
                prompt,
                value=int(default) if default is not None else 0,
                key=f"{prefix}_{field_name}"
            )
        elif "str" in annotation:
            config[field_name] = st.text_input(
                prompt,
                value=str(default) if default is not None else "",
                key=f"{prefix}_{field_name}"
            )
        else:
            # fallback for unknown types
            config[field_name] = st.text_input(
                prompt,
                value=str(default) if default is not None else "",
                key=f"{prefix}_{field_name}"
            )
    return config

import json

def render_output(result):
    status = result.get("status", "unknown")
    if status == "success":
        st.success("Script completed successfully")
    else:
        st.error("Script failed")

    rows = result.get("data")
    if isinstance(rows, list) and rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    result_payload = result.get("result")
    if result_payload is not None:
        if isinstance(result_payload, str):
            try:
                result_payload = json.loads(result_payload)
            except json.JSONDecodeError:
                st.warning("Result payload is not valid JSON.")
                st.text(result_payload)
                result_payload = None

        if isinstance(result_payload, list):
            st.dataframe(pd.DataFrame(result_payload), use_container_width=True, hide_index=True)
        elif isinstance(result_payload, dict):
            st.dataframe(pd.DataFrame([result_payload]), use_container_width=True, hide_index=True)
        elif result_payload is not None:
            st.json(result_payload)

    output = result.get("output")
    if output is not None:
        try:
            parsed_output = json.loads(output)
            if isinstance(parsed_output, list):
                st.dataframe(pd.DataFrame(parsed_output), use_container_width=True, hide_index=True)
            elif isinstance(parsed_output, dict):
                st.dataframe(pd.DataFrame([parsed_output]), use_container_width=True, hide_index=True)
            else:
                st.text(output)
        except json.JSONDecodeError:
            st.code(output or "", language="text")

        st.caption(
            f"Run ID: {result.get('run_id')} | "
            f"Started: {result.get('started_at')} | "
            f"Completed: {result.get('completed_at')} | "
            f"Return code: {result.get('return_code')}"
        )


def build_run_payload(prefix, scripts):
    strategy_name = st.selectbox("Strategy", scripts, key=f"{prefix}_strategy")
    config_name = st.text_input(
        "Config name",
        key=f"{prefix}_config",
        placeholder="Optional, for scripts that require a config",
    )
    account_name = st.text_input("Account", key=f"{prefix}_account", placeholder="Optional")
    verbose = st.checkbox("Verbose output", key=f"{prefix}_verbose")
    extra_args_text = st.text_input("Extra args", key=f"{prefix}_extra_args", placeholder="Optional arguments appended to the command")
    return {
        "strategy_name": strategy_name,
        "config_name": config_name.strip() or None,
        "account_name": account_name or None,
        "verbose": verbose,
        "extra_args": f" {extra_args_text}" if extra_args_text else "",
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

st.subheader("Available Scripts")
if scripts:
    st.write(", ".join(scripts))
else:
    st.info("No scripts are currently available from the API.")

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
        st.info("No scheduled workflows yet. Create one below.")

    st.divider()
    with st.expander("Create scheduled workflow"):
        if not scripts:
            st.info("No scripts are currently available from the API.")
        else:
            name = st.text_input("Schedule name", placeholder="e.g. update hourly balance")
            default_index = scripts.index("spread_capture_standalone") if "spread_capture_standalone" in scripts else 0
            selected_script = st.selectbox("Script", scripts, index=default_index, key="schedule_script_name")
            default_body, config_template = build_script_run_body(selected_script)

            if config_template:
                with st.expander("Config template", expanded=False):
                    st.json(config_template)
            else:
                st.info("No config template was returned for this script. You can still edit and submit the JSON body.")

            default_body, config_template = build_script_run_body(selected_script)

            if config_template:
                st.subheader("Config inputs")
                config = render_config_inputs(config_template, prefix=f"schedule_{selected_script}")
            else:
                st.info("No config template was returned for this script.")
                config = {}
            account_name = st.text_input("Account", key="schedule_account", placeholder="Optional")
            verbose = st.checkbox("Verbose output", key="schedule_verbose")
            extra_args_text = st.text_input(
                "Extra args",
                key="schedule_extra_args",
                placeholder="Optional, space separated",
            )
            interval_value = st.number_input("Every", min_value=1, value=60, step=1)
            interval_unit = st.selectbox("Unit", ["minutes", "hours", "weeks"])
            if st.button("Create schedule", type="primary"):
                try:
                    run_body = {"script_name": selected_script,"config": config,}

                    if not isinstance(run_body, dict):
                        raise ValueError("Request JSON must be an object.")

                    run_body["script_name"] = selected_script
                    config = run_body.get("config") or {}
                    if not isinstance(config, dict):
                        raise ValueError("Request JSON config must be an object.")

                    config_name = make_script_config_name(name, selected_script)
                    backend_api_client.scripts.create_or_update_script_config(
                        config_name,
                        build_saved_script_config(selected_script, config),
                    )

                    schedule = backend_api_client.scripts.create_script_schedule(
                        {
                            "strategy_name": selected_script,
                            "script_name": selected_script,
                            "config_name": config_name,
                            "config": config,
                            "run_request": run_body,
                            "account_name": account_name or None,
                            "verbose": verbose,
                            "extra_args": [arg for arg in extra_args_text.split(" ") if arg],
                            "name": name or f"{selected_script} schedule",
                            "interval_value": int(interval_value),
                            "interval_unit": interval_unit,
                        }
                    )
                    st.success(f"Created schedule: {schedule.get('name')} using config {config_name}")
                    st.rerun()
                except json.JSONDecodeError as exc:
                    st.error(f"Invalid JSON: {exc}")
                except Exception as exc:
                    st.error(f"Failed to create schedule: {exc}")

with instant_tab:
    st.caption("One-off run. Output is shown here and is not stored in schedule history.")
    st.subheader("Run once")

    if not scripts:
        st.info("No scripts are currently available from the API.")
    else:
        instant_default_index = scripts.index("spread_capture_standalone") if "spread_capture_standalone" in scripts else 0
        selected_script = st.selectbox(
            "Script",
            scripts,
            index=instant_default_index,
            key="instant_script_name"
        )

        default_body, config_template = build_script_run_body(selected_script)

        if config_template:
            with st.expander("Config template"):
                st.json(config_template)
        else:
            st.info("No config template was returned for this script. You can still edit and submit the JSON body.")

        if config_template:
            st.subheader("Config inputs")
            config = render_config_inputs(config_template, prefix=f"instant_{selected_script}")
        else:
            st.info("No config template was returned for this script.")
            config = {}
        if st.button("Run now", type="primary"):
            try:
                payload = {"script_name": selected_script,"config": config}
                if not isinstance(payload, dict):
                    raise ValueError("Request JSON must be an object.")
                payload["script_name"] = selected_script
                payload.setdefault("config", {})
                result = backend_api_client.scripts.run_script(payload)
                render_output(result)
            except json.JSONDecodeError as exc:
                st.error(f"Invalid JSON: {exc}")
            except Exception as exc:
                st.error(f"Script run failed: {exc}")
