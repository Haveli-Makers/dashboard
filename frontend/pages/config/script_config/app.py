import streamlit as st

from frontend.st_utils import get_backend_api_client, initialize_st_page

initialize_st_page(title="Script Config", icon="📜", show_readme=False)

backend_api_client = get_backend_api_client()

NEW_CONFIG_LABEL = "+ New config"


def get_scripts():
    try:
        return backend_api_client.scripts.list_scripts()
    except Exception as exc:
        st.error(f"Failed to fetch scripts: {exc}")
        return []


def get_script_configs():
    try:
        return backend_api_client.scripts.list_script_configs()
    except Exception as exc:
        st.error(f"Failed to fetch script configs: {exc}")
        return []


def get_script_config_template(script_name):
    """Fetch the config template (field name -> default/annotation/prompt) for a script."""
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


def render_config_inputs(config_template, saved_values, prefix):
    config = {}
    for field_name, field_info in config_template.items():
        is_field_dict = isinstance(field_info, dict)
        default = saved_values.get(field_name, field_info.get("default") if is_field_dict else field_info)
        annotation = field_info.get("annotation", "") if is_field_dict else ""
        prompt = (field_info.get("prompt") or field_name) if is_field_dict else field_name

        if "bool" in annotation:
            config[field_name] = st.checkbox(prompt, value=bool(default) if default is not None else False, key=f"{prefix}_{field_name}")
        elif "int" in annotation:
            config[field_name] = st.number_input(prompt, value=int(default) if default is not None else 0, key=f"{prefix}_{field_name}")
        elif "float" in annotation:
            config[field_name] = st.number_input(prompt, value=float(default) if default is not None else 0.0, format="%.6f", key=f"{prefix}_{field_name}")
        else:
            if isinstance(default, (list, dict)) and not default:
                # Hummingbot's own config parsers expect an empty string for "no value" here
                # (e.g. candles_config/controllers_config), not the literal "[]"/"{}".
                default = ""
            config[field_name] = st.text_input(prompt, value=str(default) if default is not None else "", key=f"{prefix}_{field_name}")
    return config


def build_saved_config(script_name, config):
    saved_config = dict(config)
    saved_config.setdefault("script_file_name", f"{script_name}.py")
    return saved_config


st.text(
    "Create or edit a configuration for any Hummingbot script found in the scripts environment "
    "(including scripts nested in subfolders, e.g. utility/v2_pmm_single_level). "
    "Saved configs can be deployed from the Deploy V2 page in Script mode."
)

scripts = get_scripts()

if not scripts:
    st.warning("⚠️ No scripts are currently available from the API.")
    st.stop()

selected_script = st.selectbox("Script", scripts, key="script_config_script_select")

script_configs = get_script_configs()
matching_configs = [
    config for config in script_configs
    if config.get("script_file_name") == f"{selected_script}.py"
]
config_choice_options = [NEW_CONFIG_LABEL] + [c.get("config_name") for c in matching_configs]
config_choice = st.selectbox(
    "Configuration",
    config_choice_options,
    key=f"script_config_choice_{selected_script}",
    help="Pick an existing config for this script to edit it, or create a new one.",
)

editing_existing = config_choice != NEW_CONFIG_LABEL
saved_values = {}
if editing_existing:
    try:
        saved_values = backend_api_client.scripts.get_script_config(config_choice)
    except Exception as exc:
        st.error(f"Failed to load configuration '{config_choice}': {exc}")

config_template = get_script_config_template(selected_script)

config_name = st.text_input(
    "Config name",
    value=config_choice if editing_existing else "",
    placeholder=f"e.g. {selected_script.split('/')[-1]}_1",
    key=f"script_config_name_{selected_script}_{config_choice}",
)

if config_template:
    st.subheader("Config inputs")
    config_values = render_config_inputs(config_template, saved_values, prefix=f"script_config_{selected_script}_{config_choice}")
else:
    st.info("No config fields were returned for this script.")
    config_values = {}

save_col, delete_col = st.columns(2)
with save_col:
    if st.button("💾 Save configuration", type="primary", use_container_width=True):
        if not config_name.strip():
            st.warning("Please provide a config name.")
        else:
            try:
                backend_api_client.scripts.create_or_update_script_config(
                    config_name.strip(),
                    build_saved_config(selected_script, config_values),
                )
                st.success(f"Saved configuration '{config_name.strip()}' for script '{selected_script}'")
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to save configuration: {exc}")

with delete_col:
    if editing_existing and st.button("🗑️ Delete configuration", use_container_width=True):
        try:
            backend_api_client.scripts.delete_script_config(config_choice)
            st.success(f"Deleted configuration '{config_choice}'")
            st.rerun()
        except Exception as exc:
            st.error(f"Failed to delete configuration: {exc}")
