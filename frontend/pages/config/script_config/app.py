import streamlit as st

from frontend.st_utils import get_backend_api_client, initialize_st_page

initialize_st_page(title="Script Config", icon="📜", show_readme=False)

backend_api_client = get_backend_api_client()

NEW_CONFIG_LABEL = "+ New config"


def get_scripts():
    """List the deployable scripts, same source as the Deploy V2 page's Script dropdown."""
    try:
        return backend_api_client.scripts.list_community_scripts()
    except Exception as e:
        st.error(f"Failed to fetch scripts: {e}")
        return []


def get_script_configs():
    """List all saved script configurations with their metadata."""
    try:
        return backend_api_client.scripts.list_script_configs()
    except Exception as e:
        st.error(f"Failed to fetch script configs: {e}")
        return []


def script_stem(value):
    """Return the deployable stem for a script/config file reference."""
    if not value:
        return None
    file_name = str(value).replace("\\", "/").split("/")[-1]
    for extension in (".py", ".yml", ".yaml"):
        if file_name.endswith(extension):
            return file_name[:-len(extension)]
    return file_name


def get_config_id(config):
    """Extract the identifier of a saved script config from the list API payload."""
    if isinstance(config, str):
        return script_stem(config)
    if isinstance(config, dict):
        for key in ("config_name", "id", "name", "file_name", "filename"):
            if config.get(key):
                return script_stem(config[key])
    return None


def get_config_script_stem(config):
    """Extract the script a saved config is bound to, if any."""
    if isinstance(config, dict):
        return script_stem(config.get("script_file_name"))
    return None


st.text(
    "Register a named config for a Hummingbot script so it can be picked on the "
    "Deploy V2 page in Script mode. Parameters are taken from the script file itself "
    "(hardcoded in the .py), so there is nothing to fill in here."
)

scripts = sorted(script_stem(script) for script in get_scripts() if script)
if not scripts:
    st.warning("⚠️ No scripts are currently available from the API.")
    st.stop()

selected_script = st.selectbox("Script", options=scripts, key="script_config_script_select")

script_configs = get_script_configs()
matching_configs = [
    config
    for config in script_configs
    if get_config_script_stem(config) in (None, selected_script)
]

config_choice_options = [NEW_CONFIG_LABEL] + sorted(
    config_id for config_id in (get_config_id(config) for config in matching_configs) if config_id
)
config_choice = st.selectbox(
    "Configuration",
    options=config_choice_options,
    key=f"script_config_choice_{selected_script}",
    help="Existing configs for this script, or create a new one.",
)
editing_existing = config_choice != NEW_CONFIG_LABEL

config_name = st.text_input(
    "Config name",
    value=config_choice if editing_existing else "",
    placeholder=f"e.g. {selected_script.split('/')[-1]}_1",
    key=f"script_config_name_{selected_script}",
)

save_col, delete_col = st.columns(2)

with save_col:
    if st.button("💾 Save configuration", type="primary", use_container_width=True):
        if not config_name.strip():
            st.warning("Please provide a config name.")
        else:
            try:
                backend_api_client.scripts.create_or_update_script_config(
                    config_name.strip(), {"script_file_name": f"{selected_script}.py"}
                )
                st.success(
                    f"Saved configuration '{config_name.strip()}' for script '{selected_script}'"
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to save configuration: {exc}")

with delete_col:
    if editing_existing:
        if st.button("🗑️ Delete configuration", use_container_width=True):
            try:
                backend_api_client.scripts.delete_script_config(config_choice)
                st.success(f"Deleted configuration '{config_choice}'")
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to delete configuration: {exc}")
