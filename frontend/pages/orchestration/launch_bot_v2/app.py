import time

import pandas as pd
import streamlit as st

from frontend.st_utils import get_backend_api_client, initialize_st_page

initialize_st_page(icon="🙌", show_readme=False)

# Initialize backend client
backend_api_client = get_backend_api_client()

DRAWDOWN_QUOTE_OPTIONS = ["INR", "USDT"]


def get_controller_configs():
    """Get all controller configurations using the new API."""
    try:
        return backend_api_client.controllers.list_controller_configs()
    except Exception as e:
        st.error(f"Failed to fetch controller configs: {e}")
        return []


def filter_hummingbot_images(images):
    """Filter images to only show Havelimakers-related ones."""
    from CONFIG import IMAGE_FILTER_KEYWORD
    filtered_images = []

    for image in images:
        try:
            if image.startswith(f'{IMAGE_FILTER_KEYWORD}:'):
                filtered_images.append(image)
        except Exception:
            continue

    return filtered_images


def launch_new_bot(bot_name, image_name, credentials, selected_controllers, max_global_drawdown,
                   max_controller_drawdown):
    """Launch a new bot with the selected configuration."""
    if not bot_name:
        st.warning("You need to define the bot name.")
        return False
    if not image_name:
        st.warning("You need to select the havelimakers image.")
        return False
    if not selected_controllers:
        st.warning("You need to select the controllers configs. Please select at least one controller "
                   "config by clicking on the checkbox.")
        return False
    st.info(f"🚀 Launching new bot with name: {bot_name}, image: {image_name}")

    start_time_str = time.strftime("%Y%m%d-%H%M")
    full_bot_name = f"{bot_name}-{start_time_str}"

    try:
        # Use the new deploy_v2_controllers method
        deploy_config = {
            "instance_name": full_bot_name,
            "credentials_profile": credentials,
            "controllers_config": selected_controllers,
            "image": image_name,
        }

        # Add optional drawdown parameters if set.
        # These fields already represent amounts in the selected quote asset.
        if max_global_drawdown is not None and max_global_drawdown > 0:
            deploy_config["max_global_drawdown_quote"] = max_global_drawdown
        if max_controller_drawdown is not None and max_controller_drawdown > 0:
            deploy_config["max_controller_drawdown_quote"] = max_controller_drawdown

        backend_api_client.bot_orchestration.deploy_v2_controllers(**deploy_config)
        st.success(f"Successfully deployed bot: {full_bot_name} with drawdown limits in {drawdown_quote}")
        time.sleep(3)
        return True

    except Exception as e:
        st.error(f"Failed to deploy bot: {e}")
        return False


def get_scripts():
    """Get all available scripts from the imported Hummingbot environment."""
    try:
        return backend_api_client.scripts.list_scripts()
    except Exception as e:
        st.error(f"Failed to fetch scripts: {e}")
        return []


def get_script_configs():
    """Get all script configurations with metadata."""
    try:
        return backend_api_client.scripts.list_script_configs()
    except Exception as e:
        st.error(f"Failed to fetch script configs: {e}")
        return []


def launch_new_script_bot(bot_name, image_name, credentials, script_name, script_config_name):
    """Launch a new bot running a standalone script with the selected configuration."""
    if not bot_name:
        st.warning("You need to define the bot name.")
        return False
    if not image_name:
        st.warning("You need to select the havelimakers image.")
        return False
    if not script_name:
        st.warning("You need to select a script to deploy.")
        return False
    if not script_config_name:
        st.warning("You need to select the script configuration to deploy.")
        return False

    start_time_str = time.strftime("%Y%m%d-%H%M")
    full_bot_name = f"{bot_name}-{start_time_str}"

    try:
        response = backend_api_client.bot_orchestration.deploy_v2_script(
            instance_name=full_bot_name,
            credentials_profile=credentials,
            script=f"{script_name}.py",
            script_config=f"{script_config_name}.yml",
            image=image_name,
        )
        if response.get("success") is False:
            st.error(f"Failed to deploy bot: {response.get('message')}")
            return False
        st.success(f"Successfully deployed bot: {full_bot_name}")
        time.sleep(3)
        return True
    except Exception as e:
        st.error(f"Failed to deploy bot: {e}")
        return False


# Page Header
st.title("🚀 Deploy Trading Bot")
st.subheader("Configure and deploy your automated trading strategy")

deployment_type = st.radio(
    "Deployment Type",
    options=["Controllers", "Script"],
    horizontal=True,
    key="deployment_type_select",
    help="Controllers deploy the v2_with_controllers strategy with one or more controller configs. "
         "Script deploys a standalone Hummingbot script (e.g. from scripts/utility) with a script config.",
)

# Bot Configuration Section
with st.container(border=True):
    st.info("🤖 **Bot Configuration:** Set up your bot instance with basic configuration")

    # Create three columns for the configuration inputs
    col1, col2, col3 = st.columns(3)

    with col1:
        bot_name = st.text_input(
            "Instance Name",
            placeholder="Enter a unique name for your bot instance",
            key="bot_name_input"
        )

    with col2:
        try:
            available_credentials = backend_api_client.accounts.list_accounts()
            credentials = st.selectbox(
                "Credentials Profile",
                options=available_credentials,
                index=0,
                key="credentials_select"
            )
        except Exception as e:
            st.error(f"Failed to fetch credentials: {e}")
            credentials = st.text_input(
                "Credentials Profile",
                value="master_account",
                key="credentials_input"
            )

    with col3:
        try:
            all_images = backend_api_client.docker.get_available_images("")
            available_images = filter_hummingbot_images(all_images)

            image_name = st.selectbox(
                "Bot Image",
                options=available_images,
                index=0,
                key="image_select"
            )

            if not available_images:
                st.error("No images available")
            else:
                st.write(f"Selected Image: {image_name}")
        except Exception as e:
            st.error(f"Failed to fetch available images: {e}")
            image_name = st.text_input(
                "Bot Image",
                value="havelimakers:latest",
                key="image_input"
            )

if deployment_type == "Script":
    with st.container(border=True):
        st.success("📜 **Script Selection:** Pick a script and the config you created for it in the Config Generator")

        scripts = get_scripts()
        script_configs = get_script_configs()

        if not scripts:
            st.warning("⚠️ No scripts available from the API.")
            selected_script = None
            selected_config_name = None
        else:
            selected_script = st.selectbox(
                "Script",
                options=scripts,
                key="script_select",
                help="Scripts are discovered from the Hummingbot scripts environment, including subfolders like utility/.",
            )

            matching_configs = [
                config for config in script_configs
                if config.get("script_file_name") in (f"{selected_script}.py", selected_script)
            ]
            config_options = matching_configs or script_configs

            if not config_options:
                st.warning("⚠️ No script configurations available. Create one in the Config Generator first.")
                selected_config_name = None
            else:
                if not matching_configs:
                    st.info("No configs are tagged for this script yet, showing all script configs.")
                config_names = [config.get("config_name") for config in config_options]
                selected_config_name = st.selectbox(
                    "Script Config",
                    options=config_names,
                    key="script_config_select",
                )

        st.divider()
        if st.button("🚀 Deploy Bot", type="primary" if (scripts and selected_config_name) else "secondary",
                     use_container_width=True, key="deploy_script_button"):
            if selected_script and selected_config_name:
                with st.spinner("🚀 Starting Bot... This process may take a few seconds"):
                    if launch_new_script_bot(bot_name, image_name, credentials, selected_script, selected_config_name):
                        st.rerun()
            else:
                st.warning("Please select a script and a script config to deploy")

if deployment_type == "Controllers":
    # Risk Management Section
    with st.container(border=True):
        st.warning("⚠️ **Risk Management:** Choose the quote asset and set maximum drawdown limits in that "
                   "quote to protect your capital")

        col1, col2, col3 = st.columns([1, 3, 3])

        with col1:
            drawdown_quote = st.selectbox(
                "Drawdown Quote",
                options=DRAWDOWN_QUOTE_OPTIONS,
                index=DRAWDOWN_QUOTE_OPTIONS.index("INR"),
                help="Choose the quote asset used for the drawdown limits",
                key="drawdown_quote_select"
            )

        with col2:
            max_global_drawdown = st.number_input(
                f"Max Global Drawdown ({drawdown_quote})",
                min_value=0.0,
                value=0.0,
                step=100.0,
                format="%.2f",
                help=f"Maximum allowed drawdown across all controllers in {drawdown_quote}",
                key="global_drawdown_input"
            )

        with col3:
            max_controller_drawdown = st.number_input(
                f"Max Controller Drawdown ({drawdown_quote})",
                min_value=0.0,
                value=0.0,
                step=100.0,
                format="%.2f",
                help=f"Maximum allowed drawdown per controller in {drawdown_quote}",
                key="controller_drawdown_input"
            )

    # Controllers Section
    with st.container(border=True):
        st.success("🎛️ **Controller Selection:** Select the trading controllers you want to deploy with this bot instance")

        # Get controller configs
        all_controllers_config = get_controller_configs()

        # Prepare data for the table
        data = []
        for config in all_controllers_config:
            # Handle case where config might be a string instead of dict
            if isinstance(config, str):
                st.warning(f"Unexpected config format: {config}. Expected a dictionary.")
                continue

            # Handle both old and new config format
            config_name = config.get("id")
            if not config_name:
                # Skip configs without an ID
                st.warning(f"Config missing 'id' field: {config}")
                continue

            config_data = config.get("config", config)  # New format has config nested

            connector_name = config_data.get("connector_name", "Unknown")
            trading_pair = config_data.get("trading_pair", "Unknown")
            total_amount_quote = float(config_data.get("total_amount_quote", 0))

            # Extract controller info
            controller_name = config_data.get("controller_name", config_name)
            controller_type = config_data.get("controller_type", "generic")

            # Fix config base and version splitting
            config_parts = config_name.split("_")
            if len(config_parts) > 1:
                version = config_parts[-1]
                config_base = "_".join(config_parts[:-1])
            else:
                config_base = config_name
                version = "NaN"

            data.append({
                "Select": False,  # Checkbox column
                "Config Base": config_base,
                "Version": version,
                "Controller Name": controller_name,
                "Controller Type": controller_type,
                "Connector": connector_name,
                "Trading Pair": trading_pair,
                "Amount ": f"{total_amount_quote:,.2f}",
                "_config_name": config_name  # Hidden column for reference
            })

        # Display info and action buttons
        if data:
            # Create DataFrame
            df = pd.DataFrame(data)

            # Use data_editor with checkbox column for selection
            edited_df = st.data_editor(
                df,
                column_config={
                    "Select": st.column_config.CheckboxColumn(
                        "Select",
                        help="Select controllers to deploy",
                        default=False,
                    ),
                    "_config_name": None,  # Hide this column
                },
                disabled=[col for col in df.columns if col != "Select"],  # Only allow editing the Select column
                hide_index=True,
                use_container_width=True,
                key="controller_table"
            )

            # Get selected controllers from the edited dataframe
            selected_controllers = [
                row["_config_name"]
                for _, row in edited_df.iterrows()
                if row["Select"]
            ]

            # Display selected count
            if selected_controllers:
                st.success(f"✅ {len(selected_controllers)} controller(s) selected for deployment")

            # Display action buttons
            st.divider()
            deploy_button_style = "primary" if selected_controllers else "secondary"
            if st.button("🚀 Deploy Bot", type=deploy_button_style, use_container_width=True):
                if selected_controllers:
                    with st.spinner('🚀 Starting Bot... This process may take a few seconds'):
                        st.info(f"🚀 Launching new bot with name: {bot_name}, image: {image_name}")
                        if launch_new_bot(bot_name, image_name, credentials, selected_controllers,
                                          max_global_drawdown, max_controller_drawdown):
                            st.rerun()
                else:
                    st.warning("Please select at least one controller to deploy")

        else:
            st.warning("⚠️ No controller configurations available. Please create some configurations first.")
