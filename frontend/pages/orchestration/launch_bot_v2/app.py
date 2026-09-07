import time

import pandas as pd
import streamlit as st

from frontend.st_utils import get_backend_api_client, initialize_st_page

initialize_st_page(icon="🙌", show_readme=False)

# Initialize backend client
backend_api_client = get_backend_api_client()

DRAWDOWN_QUOTE_OPTIONS = ["INR", "USDT"]
DEPLOYMENT_TYPE_CONTROLLERS = "Controllers"
DEPLOYMENT_TYPE_SCRIPT = "Script"


def get_controller_configs():
    """Get all controller configurations using the new API."""
    try:
        return backend_api_client.controllers.list_controller_configs()
    except Exception as e:
        st.error(f"Failed to fetch controller configs: {e}")
        return []


def get_scripts():
    """Get all available scripts."""
    try:
        return backend_api_client.scripts.list_community_scripts()
    except Exception as e:
        st.error(f"Failed to fetch scripts: {e}")
        return []


def get_script_configs():
    """Get all available script configs."""
    try:
        return backend_api_client.scripts.list_script_configs()
    except Exception as e:
        st.error(f"Failed to fetch script configs: {e}")
        return []


def normalize_file_stem(value):
    """Return a deployable file stem for script/config selections."""
    if not value:
        return None

    file_name = value.replace("\\", "/").split("/")[-1]
    for extension in (".py", ".yml", ".yaml"):
        if file_name.endswith(extension):
            return file_name[:-len(extension)]
    return file_name


def get_config_name(config):
    """Extract the config id from old and new script config API formats."""
    if isinstance(config, str):
        return normalize_file_stem(config)
    if isinstance(config, dict):
        for key in ("id", "name", "config_name", "file_name", "filename"):
            if config.get(key):
                return normalize_file_stem(config[key])
    return None


def get_config_script_name(config):
    """Extract the script name attached to a script config."""
    if isinstance(config, dict):
        return normalize_file_stem(config.get("script_file_name"))
    return None


def normalize_image_options(images):
    """Normalize Docker image API responses into a list of tags."""
    if isinstance(images, list):
        return [image for image in images if image]
    if isinstance(images, dict):
        image_values = images.get("images", images.get("data", []))
        normalized_images = []
        for image in image_values:
            if isinstance(image, str):
                normalized_images.append(image)
            elif isinstance(image, dict):
                tags = image.get("tags", [])
                normalized_images.extend(tags)
        return [image for image in normalized_images if image]
    return []


def filter_hummingbot_images(images):
    """Filter images to only show Havelimakers-related ones."""
    from CONFIG import IMAGE_FILTER_KEYWORD

    filtered_images = []
    for image in images:
        try:
            if image.startswith(f"{IMAGE_FILTER_KEYWORD}:"):
                filtered_images.append(image)
        except Exception:
            continue

    return filtered_images


def get_available_bot_images():
    """Return preferred bot images and fall back to all images when the filter has no matches."""
    all_images = normalize_image_options(backend_api_client.docker.get_available_images(""))
    filtered_images = filter_hummingbot_images(all_images)
    return filtered_images or all_images


def launch_new_bot(
        bot_name,
        image_name,
        credentials,
        deployment_type,
        selected_controllers=None,
        selected_script=None,
        selected_script_config=None,
        max_global_drawdown=None,
        max_controller_drawdown=None,
        drawdown_quote="INR",
):
    """Launch a new bot with the selected configuration."""
    if not bot_name:
        st.warning("You need to define the bot name.")
        return False
    if not image_name:
        st.warning("You need to select the havelimakers image.")
        return False
    if deployment_type == DEPLOYMENT_TYPE_CONTROLLERS and not selected_controllers:
        st.warning("You need to select at least one controller config.")
        return False
    if deployment_type == DEPLOYMENT_TYPE_SCRIPT and not selected_script:
        st.warning("You need to select the script to deploy.")
        return False
    st.info(f"🚀 Launching new bot with name: {bot_name}, image: {image_name}")

    start_time_str = time.strftime("%Y%m%d-%H%M")
    full_bot_name = f"{bot_name}-{start_time_str}"

    try:
        if deployment_type == DEPLOYMENT_TYPE_SCRIPT:
            backend_api_client.scripts.import_community_script(selected_script, override=True)
            deploy_config = {
                "instance_name": full_bot_name,
                "credentials_profile": credentials,
                "script": selected_script,
                "image": image_name,
            }
            if selected_script_config:
                deploy_config["script_config"] = selected_script_config

            backend_api_client.bot_orchestration.deploy_script(**deploy_config)
            st.success(f"Successfully deployed script bot: {full_bot_name}")
        else:
            deploy_config = {
                "instance_name": full_bot_name,
                "credentials_profile": credentials,
                "controllers_config": selected_controllers,
                "image": image_name,
            }

            if max_global_drawdown is not None and max_global_drawdown > 0:
                deploy_config["max_global_drawdown_quote"] = max_global_drawdown
            if max_controller_drawdown is not None and max_controller_drawdown > 0:
                deploy_config["max_controller_drawdown_quote"] = max_controller_drawdown

            backend_api_client.bot_orchestration.deploy_v2_controllers(**deploy_config)
            st.success(
                f"Successfully deployed controller bot: {full_bot_name} with drawdown limits in {drawdown_quote}"
            )

        time.sleep(3)
        return True
    except Exception as e:
        st.error(f"Failed to deploy bot: {e}")
        return False


# Page Header
st.title("🚀 Deploy Trading Bot")
st.subheader("Configure and deploy your automated trading strategy")

# Bot Configuration Section
with st.container(border=True):
    st.info("🤖 **Bot Configuration:** Set up your bot instance with basic configuration")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        bot_name = st.text_input(
            "Instance Name",
            placeholder="Enter a unique name for your bot instance",
            key="bot_name_input",
        )

    with col2:
        try:
            available_credentials = backend_api_client.accounts.list_accounts()
            credentials = st.selectbox(
                "Credentials Profile",
                options=available_credentials,
                index=0,
                key="credentials_select",
            )
        except Exception as e:
            st.error(f"Failed to fetch credentials: {e}")
            credentials = st.text_input(
                "Credentials Profile",
                value="master_account",
                key="credentials_input",
            )

    with col3:
        try:
            available_images = get_available_bot_images()
            if available_images:
                image_name = st.selectbox(
                    "Bot Image",
                    options=available_images,
                    index=0,
                    key="image_select",
                )
                st.write(f"Selected Image: {image_name}")
            else:
                st.warning("No Docker images returned by the API. Enter an image manually.")
                image_name = st.text_input(
                    "Bot Image",
                    value="hummingbot/hummingbot:latest",
                    key="image_input_manual",
                )
        except Exception as e:
            st.error(f"Failed to fetch available images: {e}")
            image_name = st.text_input(
                "Bot Image",
                value="havelimakers:latest",
                key="image_input",
            )

    with col4:
        deployment_type = st.selectbox(
            "Deployment Type",
            options=[DEPLOYMENT_TYPE_CONTROLLERS, DEPLOYMENT_TYPE_SCRIPT],
            index=0,
            help="Choose whether to deploy controller configs or a script.",
            key="deployment_type_select",
        )

if deployment_type == DEPLOYMENT_TYPE_CONTROLLERS:
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
                key="drawdown_quote_select",
            )

        with col2:
            max_global_drawdown = st.number_input(
                f"Max Global Drawdown ({drawdown_quote})",
                min_value=0.0,
                value=0.0,
                step=100.0,
                format="%.2f",
                help=f"Maximum allowed drawdown across all controllers in {drawdown_quote}",
                key="global_drawdown_input",
            )

        with col3:
            max_controller_drawdown = st.number_input(
                f"Max Controller Drawdown ({drawdown_quote})",
                min_value=0.0,
                value=0.0,
                step=100.0,
                format="%.2f",
                help=f"Maximum allowed drawdown per controller in {drawdown_quote}",
                key="controller_drawdown_input",
            )

    with st.container(border=True):
        st.success("🎛️ **Controller Selection:** Select the trading controllers you want to deploy")

        all_controllers_config = get_controller_configs()
        data = []
        for config in all_controllers_config:
            if isinstance(config, str):
                st.warning(f"Unexpected config format: {config}. Expected a dictionary.")
                continue

            config_name = config.get("id")
            if not config_name:
                st.warning(f"Config missing 'id' field: {config}")
                continue

            config_data = config.get("config", config)
            connector_name = config_data.get("connector_name", "Unknown")
            trading_pair = config_data.get("trading_pair", "Unknown")
            total_amount_quote = float(config_data.get("total_amount_quote", 0))
            controller_name = config_data.get("controller_name", config_name)
            controller_type = config_data.get("controller_type", "generic")

            config_parts = config_name.split("_")
            if len(config_parts) > 1:
                version = config_parts[-1]
                config_base = "_".join(config_parts[:-1])
            else:
                config_base = config_name
                version = "NaN"

            data.append({
                "Select": False,
                "Config Base": config_base,
                "Version": version,
                "Controller Name": controller_name,
                "Controller Type": controller_type,
                "Connector": connector_name,
                "Trading Pair": trading_pair,
                "Amount ": f"{total_amount_quote:,.2f}",
                "_config_name": config_name,
            })

        if data:
            df = pd.DataFrame(data)
            edited_df = st.data_editor(
                df,
                column_config={
                    "Select": st.column_config.CheckboxColumn(
                        "Select",
                        help="Select controllers to deploy",
                        default=False,
                    ),
                    "_config_name": None,
                },
                disabled=[col for col in df.columns if col != "Select"],
                hide_index=True,
                use_container_width=True,
                key="controller_table",
            )

            selected_controllers = [
                row["_config_name"]
                for _, row in edited_df.iterrows()
                if row["Select"]
            ]

            if selected_controllers:
                st.success(f"✅ {len(selected_controllers)} controller(s) selected for deployment")

            st.divider()
            deploy_button_style = "primary" if selected_controllers else "secondary"
            if st.button("Deploy Bot", type=deploy_button_style, use_container_width=True):
                if selected_controllers:
                    with st.spinner('🚀 Starting Bot... This process may take a few seconds'):
                        if launch_new_bot(
                                bot_name,
                                image_name,
                                credentials,
                                deployment_type,
                                selected_controllers=selected_controllers,
                                max_global_drawdown=max_global_drawdown,
                                max_controller_drawdown=max_controller_drawdown,
                                drawdown_quote=drawdown_quote,
                        ):
                            st.rerun()
                else:
                    st.warning("Please select at least one controller to deploy")
        else:
            st.warning("No controller configurations available. Please create some configurations first.")
else:
    with st.container(border=True):
        st.success("Script Selection: Select the script you want to deploy")

        scripts = [normalize_file_stem(script) for script in get_scripts()]
        scripts = sorted(script for script in scripts if script)
        all_script_configs = get_script_configs()

        if scripts:
            selected_script = st.selectbox(
                "Script",
                options=scripts,
                index=scripts.index("fixed_grid") if "fixed_grid" in scripts else 0,
                help="Select a script file from the scripts folder.",
                key="script_select",
            )

            matching_script_configs = [
                config
                for config in all_script_configs
                if get_config_script_name(config) in (None, selected_script)
            ]
            script_config_names = [get_config_name(config) for config in matching_script_configs]
            script_config_names = sorted(config for config in script_config_names if config)
            script_config_options = ["No config"] + script_config_names

            selected_script_config_option = st.selectbox(
                "Script Config",
                options=script_config_options,
                index=0,
                help="Optional YAML config for scripts that support external config.",
                key="script_config_select",
            )
            selected_script_config = (
                None if selected_script_config_option == "No config" else selected_script_config_option
            )
            selected_config_data = next(
                (
                    config for config in matching_script_configs
                    if get_config_name(config) == selected_script_config
                ),
                None,
            )
            if isinstance(selected_config_data, dict) and selected_config_data.get("controllers_config"):
                controllers = ", ".join(selected_config_data["controllers_config"])
                st.info(f"Controllers in selected script config: {controllers}")

            st.divider()
            if st.button("Deploy Bot", type="primary", use_container_width=True):
                with st.spinner('🚀 Starting Bot... This process may take a few seconds'):
                    if launch_new_bot(
                            bot_name,
                            image_name,
                            credentials,
                            deployment_type,
                            selected_script=selected_script,
                            selected_script_config=selected_script_config,
                    ):
                        st.rerun()
        else:
            st.warning("⚠️ No scripts available. Please upload or create a script first.")
