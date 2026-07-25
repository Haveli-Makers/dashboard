import time

import pandas as pd
import streamlit as st

from frontend.components.bot_stream import get_stream
from frontend.st_utils import get_backend_api_client, initialize_st_page
from frontend.visualization.live_bot_card import render_controller_live

initialize_st_page(icon="🦅", show_readme=False)

# Initialize backend client
backend_api_client = get_backend_api_client()

# Start the broker (MQTT-over-WebSocket) subscriber so bot cards can render live data.
# Singleton across reruns — reuses one socket. Broker is fixed via CONFIG (single broker);
# switching servers in the sidebar does NOT repoint the broker.
bot_stream = get_stream()

# Initialize session state for auto-refresh
if "auto_refresh_enabled" not in st.session_state:
    st.session_state.auto_refresh_enabled = True

# Fragment refresh interval. Kept short so the live broker data on each card updates in
# near real-time; structural REST calls re-run on the same beat (acceptable for a local backend).
REFRESH_INTERVAL = 2  # seconds


def stop_bot(bot_name):
    """Stop a running bot."""
    try:
        backend_api_client.bot_orchestration.stop_and_archive_bot(bot_name)
        st.success(f"Bot {bot_name} stopped and archived successfully")
        time.sleep(2)  # Give time for the backend to process
    except Exception as e:
        st.error(f"Failed to stop bot {bot_name}: {e}")


def archive_bot(bot_name):
    """Archive a stopped bot."""
    try:
        backend_api_client.docker.stop_container(bot_name)
        backend_api_client.docker.remove_container(bot_name)
        st.success(f"Bot {bot_name} archived successfully")
        time.sleep(1)
    except Exception as e:
        st.error(f"Failed to archive bot {bot_name}: {e}")


def stop_controllers(bot_name, controllers):
    """Stop selected controllers."""
    success_count = 0
    for controller in controllers:
        try:
            backend_api_client.controllers.update_bot_controller_config(
                bot_name,
                controller,
                {"manual_kill_switch": True}
            )
            success_count += 1
        except Exception as e:
            st.error(f"Failed to stop controller {controller}: {e}")

    if success_count > 0:
        st.success(f"Successfully stopped {success_count} controller(s)")
        # Temporarily disable auto-refresh to prevent immediate state reset
        st.session_state.auto_refresh_enabled = False

    return success_count > 0


def start_controllers(bot_name, controllers):
    """Start selected controllers."""
    success_count = 0
    for controller in controllers:
        try:
            backend_api_client.controllers.update_bot_controller_config(
                bot_name,
                controller,
                {"manual_kill_switch": False}
            )
            success_count += 1
        except Exception as e:
            st.error(f"Failed to start controller {controller}: {e}")

    if success_count > 0:
        st.success(f"Successfully started {success_count} controller(s)")
        # Temporarily disable auto-refresh to prevent immediate state reset
        st.session_state.auto_refresh_enabled = False

    return success_count > 0


def render_bot_card(bot_name):
    """Render a bot performance card using native Streamlit components."""
    try:
        # Get bot status first
        bot_status = backend_api_client.bot_orchestration.get_bot_status(bot_name)

        # Only try to get controller configs if bot exists and is running
        controller_configs = []
        if bot_status.get("status") == "success":
            bot_data = bot_status.get("data", {})
            is_running = bot_data.get("status") == "running"
            if is_running:
                try:
                    controller_configs = backend_api_client.controllers.get_bot_controller_configs(bot_name)
                    controller_configs = controller_configs if controller_configs else []
                except Exception as e:
                    # If controller configs fail, continue without them
                    st.warning(f"Could not fetch controller configs for {bot_name}: {e}")
                    controller_configs = []

        with st.container(border=True):

            if bot_status.get("status") == "error":
                # Error state
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.error(f"🤖 **{bot_name}** - Not Available")
                st.error(f"An error occurred while fetching bot status of {bot_name}. Please check the bot client.")
            else:
                bot_data = bot_status.get("data", {})
                is_running = bot_data.get("status") == "running"
                performance = bot_data.get("performance", {})
                error_logs = bot_data.get("error_logs", [])
                general_logs = bot_data.get("general_logs", [])

                # Bot header
                col1, col2, col3 = st.columns([2, 1, 1])
                with col1:
                    if is_running:
                        st.success(f"🤖 **{bot_name}** - Running")
                    else:
                        st.warning(f"🤖 **{bot_name}** - Stopped")

                with col3:
                    if is_running:
                        if st.button("⏹️ Stop", key=f"stop_{bot_name}", use_container_width=True):
                            stop_bot(bot_name)
                    else:
                        if st.button("📦 Archive", key=f"archive_{bot_name}", use_container_width=True):
                            archive_bot(bot_name)

                if is_running:
                    # Live data streamed from the broker, keyed by controller_id.
                    bot_stream_data = bot_stream.get_bot_data(bot_name)

                    # Classify controllers using REST config (structure / kill switch), but read
                    # all metrics from the live stream. Detect error controllers from REST status.
                    active_configs = []
                    stopped_configs = []
                    error_controllers = []

                    for controller, inner_dict in performance.items():
                        if inner_dict.get("status") == "error":
                            error_controllers.append({
                                "Controller": controller,
                                "Error": inner_dict.get("error", "Unknown error")
                            })

                    for controller_config in controller_configs:
                        controller = controller_config.get("id")
                        if any(e["Controller"] == controller for e in error_controllers):
                            continue
                        if controller_config.get("manual_kill_switch", False):
                            stopped_configs.append(controller_config)
                        else:
                            active_configs.append(controller_config)

                    # Aggregate bot-level metrics from the live stream.
                    total_pnl_quote = 0.0
                    total_unrealized_pnl_quote = 0.0
                    total_volume_traded = 0.0
                    for cdata in bot_stream_data.values():
                        perf = cdata.get("performance_data", {})
                        total_pnl_quote += perf.get("total_pnl_quote", 0) or 0
                        total_unrealized_pnl_quote += perf.get("unrealized_pnl_quote", 0) or 0
                        total_volume_traded += (perf.get("buy_volume_quote", 0) or 0) + \
                            (perf.get("sell_volume_quote", 0) or 0)

                    total_pnl_pct = total_pnl_quote / total_volume_traded if total_volume_traded > 0 else 0

                    # Display aggregate metrics
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("🏦 NET PNL", f"${total_pnl_quote:.2f}")
                    with col2:
                        st.metric("💹 Unrealized PNL", f"${total_unrealized_pnl_quote:.2f}")
                    with col3:
                        st.metric("📊 NET PNL (%)", f"{total_pnl_pct:.2%}")
                    with col4:
                        st.metric("💸 Volume Traded", f"${total_volume_traded:.2f}")

                    def _controller_meta(config):
                        return {
                            "controller_name": config.get("controller_name", config.get("id")),
                            "connector_name": config.get("connector_name", "N/A"),
                            "trading_pair": config.get("trading_pair", "N/A"),
                            "kill_switch": config.get("manual_kill_switch", False),
                        }

                    # Active Controllers — live panels + stop control
                    if active_configs:
                        st.success("🚀 **Active Controllers:** Controllers currently running and trading")
                        for config in active_configs:
                            with st.container(border=True):
                                render_controller_live(
                                    config.get("controller_type"),
                                    _controller_meta(config),
                                    bot_stream_data.get(config.get("id"), {}),
                                )

                        name_by_id = {c.get("id"): c.get("controller_name", c.get("id")) for c in active_configs}
                        selected_active = st.multiselect(
                            "Select controllers to stop",
                            options=list(name_by_id.keys()),
                            format_func=lambda cid: name_by_id.get(cid, cid),
                            key=f"stop_select_{bot_name}",
                        )
                        if selected_active and st.button(f"⏹️ Stop Selected ({len(selected_active)})",
                                                         key=f"stop_active_{bot_name}",
                                                         type="secondary"):
                            with st.spinner(f"Stopping {len(selected_active)} controller(s)..."):
                                stop_controllers(bot_name, selected_active)
                                time.sleep(1)

                    # Stopped Controllers — live panels + start control
                    if stopped_configs:
                        st.warning("💤 **Stopped Controllers:** Controllers that are paused or stopped")
                        for config in stopped_configs:
                            with st.container(border=True):
                                render_controller_live(
                                    config.get("controller_type"),
                                    _controller_meta(config),
                                    bot_stream_data.get(config.get("id"), {}),
                                )

                        name_by_id = {c.get("id"): c.get("controller_name", c.get("id")) for c in stopped_configs}
                        selected_stopped = st.multiselect(
                            "Select controllers to start",
                            options=list(name_by_id.keys()),
                            format_func=lambda cid: name_by_id.get(cid, cid),
                            key=f"start_select_{bot_name}",
                        )
                        if selected_stopped and st.button(f"▶️ Start Selected ({len(selected_stopped)})",
                                                          key=f"start_stopped_{bot_name}",
                                                          type="primary"):
                            with st.spinner(f"Starting {len(selected_stopped)} controller(s)..."):
                                start_controllers(bot_name, selected_stopped)
                                time.sleep(1)

                    # Error Controllers
                    if error_controllers:
                        st.error("💀 **Controllers with Errors:** Controllers that encountered errors")
                        error_df = pd.DataFrame(error_controllers)
                        st.dataframe(error_df, use_container_width=True, hide_index=True)

                # Logs sections (available for both running and stopped bots)
                with st.expander("📋 Error Logs"):
                    if error_logs:
                        for log in error_logs[:50]:
                            timestamp = log.get("timestamp", "")
                            message = log.get("msg", "")
                            logger_name = log.get("logger_name", "")
                            st.text(f"{timestamp} - {logger_name}: {message}")
                    else:
                        st.info("No error logs available.")

                with st.expander("📝 General Logs"):
                    if general_logs:
                        for log in general_logs[:50]:
                            timestamp = pd.to_datetime(int(log.get("timestamp", 0)), unit="s")
                            message = log.get("msg", "")
                            logger_name = log.get("logger_name", "")
                            st.text(f"{timestamp} - {logger_name}: {message}")
                    else:
                        st.info("No general logs available.")

    except Exception as e:
        with st.container(border=True):
            st.error(f"🤖 **{bot_name}** - Error")
            st.error(f"An error occurred while fetching bot status: {str(e)}")


# Page Header
st.title("🦅 Hummingbot Instances")

# Auto-refresh controls
col1, col2, col3 = st.columns([3, 1, 1])

# Create placeholder for status message
status_placeholder = col1.empty()

with col2:
    if st.button("▶️ Start Auto-refresh" if not st.session_state.auto_refresh_enabled else "⏸️ Stop Auto-refresh",
                 use_container_width=True):
        st.session_state.auto_refresh_enabled = not st.session_state.auto_refresh_enabled

with col3:
    if st.button("🔄 Refresh Now", use_container_width=True):
        # Re-enable auto-refresh if it was temporarily disabled
        if not st.session_state.auto_refresh_enabled:
            st.session_state.auto_refresh_enabled = True
        pass


@st.fragment(run_every=REFRESH_INTERVAL if st.session_state.auto_refresh_enabled else None)
def show_bot_instances():
    """Fragment to display bot instances with auto-refresh."""
    try:
        active_bots_response = backend_api_client.bot_orchestration.get_active_bots_status()

        if active_bots_response.get("status") == "success":
            active_bots = active_bots_response.get("data", {})

            # Filter out any bots that might be in transitional state
            truly_active_bots = {}
            for bot_name, bot_info in active_bots.items():
                try:
                    bot_status = backend_api_client.bot_orchestration.get_bot_status(bot_name)
                    if bot_status.get("status") == "success":
                        bot_data = bot_status.get("data", {})
                        if bot_data.get("status") in ["running", "stopped"]:
                            truly_active_bots[bot_name] = bot_info
                except Exception:
                    continue

            if truly_active_bots:
                # Show refresh status
                if st.session_state.auto_refresh_enabled:
                    status_placeholder.info(f"🔄 Auto-refreshing every {REFRESH_INTERVAL} seconds")
                else:
                    status_placeholder.warning("⏸️ Auto-refresh paused. Click 'Refresh Now' to resume.")

                # Render each bot
                for bot_name in truly_active_bots.keys():
                    render_bot_card(bot_name)
            else:
                status_placeholder.info("No active bot instances found. Deploy a bot to see it here.")
        else:
            st.error("Failed to fetch active bots status.")

    except Exception as e:
        st.error(f"Failed to connect to backend: {e}")
        st.info("Please make sure the backend is running and accessible.")


# Call the fragment
show_bot_instances()
