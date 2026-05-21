import copy

import nest_asyncio
import streamlit as st

from frontend.st_utils import get_backend_api_client
from frontend.utils import generate_random_name

nest_asyncio.apply()
backend_api_client = get_backend_api_client()


def get_default_config_loader(controller_name: str):
    """
    Load default configuration for a controller with proper session state isolation.
    Uses controller-specific session state keys to prevent cross-contamination.
    """
    # Use controller-specific session state key to prevent cross-contamination
    config_key = f"config_{controller_name}"

    try:
        all_configs = backend_api_client.controllers.list_controller_configs()
    except Exception as e:
        st.error(f"Failed to fetch controller configs: {e}")
        all_configs = []

    # Handle both old and new config format
    existing_configs = []
    for config in all_configs:
        config_name = config.get("id")
        if config_name:
            existing_configs.append(config_name.split("_")[0])

    # Create default configuration with unique ID
    default_dict = {
        "id": generate_random_name(existing_configs),
        "controller_name": controller_name
    }

    # Initialize controller-specific config if not exists
    if config_key not in st.session_state:
        st.session_state[config_key] = copy.deepcopy(default_dict)

    delete_message_key = f"config_delete_message_{controller_name}"

    with st.expander("Configurations", expanded=True):
        if delete_message_key in st.session_state:
            st.success(st.session_state.pop(delete_message_key))

        toggle_column, delete_column = st.columns([0.85, 0.15])

        with toggle_column:
            use_default_config = st.checkbox(
                "Use default config",
                value=st.session_state.get(f"use_default_{controller_name}", False),
                key=f"use_default_{controller_name}"
            )

        if not use_default_config:
            # Filter configs by controller name
            configs = []
            for config in all_configs:
                config_data = config.get("config", config)
                if config_data.get("controller_name") == controller_name:
                    configs.append(config)

            if len(configs) > 0:
                config_groups = {}
                current_config_id = st.session_state.get(config_key, {}).get("id")
                current_config_base = None
                current_config_tag = None

                if current_config_id and "_" in current_config_id:
                    current_config_base, current_config_tag = current_config_id.split("_", 1)

                for config in configs:
                    config_name = config.get("id")
                    if not config_name:
                        continue

                    config_base, _, config_tag = config_name.partition("_")
                    config_groups.setdefault(config_base, []).append((config_tag, config))

                config_bases = sorted(config_groups.keys())
                config_base_key = f"config_base_select_{controller_name}"
                config_tag_key = f"config_tag_select_{controller_name}"

                if st.session_state.get(config_base_key) not in config_bases:
                    st.session_state[config_base_key] = (
                        current_config_base if current_config_base in config_bases else config_bases[0]
                    )

                base_column, tag_column = st.columns(2)

                with base_column:
                    selected_config_base = st.selectbox(
                        "Select a config base",
                        config_bases,
                        key=config_base_key
                    )

                available_configs = sorted(
                    config_groups[selected_config_base],
                    key=lambda item: item[0]
                )
                config_tags = [config_tag for config_tag, _ in available_configs]

                if st.session_state.get(config_tag_key) not in config_tags:
                    st.session_state[config_tag_key] = (
                        current_config_tag if current_config_base == selected_config_base and current_config_tag in config_tags
                        else config_tags[0]
                    )

                with tag_column:
                    selected_config_tag = st.selectbox(
                        "Select a config tag",
                        config_tags,
                        key=config_tag_key
                    )

                selected_config = next(
                    config
                    for config_tag, config in available_configs
                    if config_tag == selected_config_tag
                )
                selected_config_name = selected_config.get("id")

                if selected_config:
                    # Use deep copy to prevent shared references
                    config_data = selected_config.get("config", selected_config)
                    st.session_state[config_key] = copy.deepcopy(config_data)
                    # Keep the original config ID
                    st.session_state[config_key]["id"] = selected_config_name
                    st.session_state[config_key]["controller_name"] = controller_name

                    with delete_column:
                        if st.button(
                            "Delete",
                            key=f"delete_config_{controller_name}",
                            use_container_width=True
                        ):
                            try:
                                backend_api_client.controllers.delete_controller_config(selected_config_name)
                                st.session_state[config_key] = copy.deepcopy(default_dict)
                                st.session_state.pop(config_base_key, None)
                                st.session_state.pop(config_tag_key, None)
                                st.session_state[delete_message_key] = f"Deleted {selected_config_name}"
                                st.rerun()
                            except Exception as e:
                                st.error(f"Failed to delete config {selected_config_name}: {e}")
            else:
                st.warning("No existing configs found for this controller.")

    # Set legacy key for backward compatibility (but with deep copy)
    st.session_state["default_config"] = copy.deepcopy(st.session_state[config_key])


def get_controller_config(controller_name: str) -> dict:
    """
    Get the current configuration for a controller with proper isolation.
    Returns a deep copy to prevent shared reference mutations.
    """
    config_key = f"config_{controller_name}"

    if config_key not in st.session_state:
        # Initialize with basic config if not found
        existing_configs = []
        try:
            all_configs = backend_api_client.controllers.list_controller_configs()
            for config in all_configs:
                config_name = config.get("id")
                if config_name:
                    existing_configs.append(config_name.split("_")[0])
        except Exception:
            pass

        default_dict = {
            "id": generate_random_name(existing_configs),
            "controller_name": controller_name
        }
        st.session_state[config_key] = copy.deepcopy(default_dict)

    # Always return a deep copy to prevent mutations
    return copy.deepcopy(st.session_state[config_key])


def update_controller_config(controller_name: str, config_updates: dict) -> None:
    """
    Update the configuration for a controller with proper isolation.
    Performs a deep copy of the updates to prevent shared references.
    """
    config_key = f"config_{controller_name}"

    # Get current config or initialize if not exists
    current_config = get_controller_config(controller_name)

    # Deep copy the updates to prevent shared references
    safe_updates = copy.deepcopy(config_updates)

    # Update the config
    current_config.update(safe_updates)

    # Store the updated config
    st.session_state[config_key] = current_config

    # Update legacy key for backward compatibility
    st.session_state["default_config"] = copy.deepcopy(current_config)


def reset_controller_config(controller_name: str) -> None:
    """
    Reset the configuration for a controller, clearing all session state.
    """
    config_key = f"config_{controller_name}"
    loader_key = f"config_loader_initialized_{controller_name}"

    # Clear controller-specific state
    st.session_state.pop(config_key, None)
    st.session_state.pop(loader_key, None)

    # Clear related UI state
    st.session_state.pop(f"use_default_{controller_name}", None)
    st.session_state.pop(f"config_select_{controller_name}", None)
    st.session_state.pop(f"config_base_select_{controller_name}", None)
    st.session_state.pop(f"config_tag_select_{controller_name}", None)

    # Clear legacy state if it matches this controller
    if st.session_state.get("default_config", {}).get("controller_name") == controller_name:
        st.session_state.pop("default_config", None)
