import inspect
import os.path
from pathlib import Path
from typing import Optional, Union

import pandas as pd
import streamlit as st
import yaml
from streamlit.commands.page_config import InitialSideBarState, Layout
from yaml import SafeLoader

from CONFIG import AUTH_SYSTEM_ENABLED, GOOGLE_ALLOWED_DOMAIN, GOOGLE_SSO_ENABLED
from frontend.pages.permissions import main_page, private_pages, public_pages


def initialize_st_page(title: Optional[str] = None, icon: str = "🤖", layout: Layout = 'wide',
                       initial_sidebar_state: InitialSideBarState = "expanded",
                       show_readme: bool = True):
    # Ensure page configuration is only applied once per rerun to avoid Streamlit errors
    config_state_key = "_page_configured"
    if config_state_key not in st.session_state or not st.session_state[config_state_key]:
        st.set_page_config(
            page_title=title,
            page_icon=icon,
            layout=layout,
            initial_sidebar_state=initial_sidebar_state
        )
        st.session_state[config_state_key] = True

    # Add page title
    if title:
        st.title(title)

    # Get caller frame info safely
    frame: Optional[Union[inspect.FrameInfo, inspect.Traceback]] = None
    try:
        caller_frame = inspect.currentframe()
        if caller_frame is not None:
            caller_frame = caller_frame.f_back
            if caller_frame is not None:
                frame = inspect.getframeinfo(caller_frame)
    except Exception:
        pass

    if frame is not None and show_readme:
        current_directory = Path(os.path.dirname(frame.filename))
        readme_path = current_directory / "README.md"
        if readme_path.exists():
            with st.expander("About This Page"):
                st.write(readme_path.read_text())
        else:
            # Only show expander if README exists
            pass


def download_csv_button(df: pd.DataFrame, filename: str, key: str):
    csv = df.to_csv(index=False).encode('utf-8')
    return st.download_button(
        label="Download CSV",
        data=csv,
        file_name=f"{filename}.csv",
        mime="text/csv",
        key=key
    )


def style_metric_cards():
    # Removed custom metric styling to use default Streamlit styling
    pass


def _close_backend_api_client(client) -> None:
    try:
        client.__exit__(None, None, None)
    except Exception:
        pass

    
def load_servers() -> list[dict]:
    """Load server configurations from servers.yml."""
    servers_path = Path('servers.yml')
    if not servers_path.exists():
        from CONFIG import BACKEND_API_HOST, BACKEND_API_PASSWORD, BACKEND_API_PORT, BACKEND_API_USERNAME
        return [{
            'name': 'Local',
            'host': BACKEND_API_HOST,
            'port': int(BACKEND_API_PORT),
            'username': BACKEND_API_USERNAME,
            'password': BACKEND_API_PASSWORD,
        }]
    with open(servers_path) as f:
        data = yaml.load(f, Loader=SafeLoader)
    return data.get('servers', [])


def render_server_selector():
    """Render a server selector dropdown in the sidebar."""
    servers = load_servers()
    if not servers:
        return
    server_names = [s['name'] for s in servers]
    if 'selected_server_name' not in st.session_state:
        st.session_state.selected_server_name = server_names[0]

    def _on_server_change():
        if 'backend_api_client' in st.session_state:
            try:
                if st.session_state.backend_api_client is not None:
                    st.session_state.backend_api_client.__exit__(None, None, None)
            except Exception:
                pass
            st.session_state.backend_api_client = None
        st.session_state.selected_server_name = st.session_state._server_selector
        st.cache_data.clear()

    st.sidebar.selectbox(
        "Server",
        options=server_names,
        index=server_names.index(st.session_state.selected_server_name)
              if st.session_state.selected_server_name in server_names else 0,
        key='_server_selector',
        on_change=_on_server_change,
    )


def _get_selected_server() -> dict:
    """Return the server config dict for the currently selected server."""
    servers = load_servers()
    selected_name = st.session_state.get('selected_server_name')
    for s in servers:
        if s['name'] == selected_name:
            return s
    return servers[0] if servers else {}


def get_selected_server_config() -> dict:
    """Public helper: returns host, port, username, password for the active server."""
    return _get_selected_server()


def start_google_login():
    st.session_state.pop("google_access_denied_email", None)
    st.login("google")


def _sync_google_login() -> bool:
    """
    Returns True once the session is authenticated via Google.
    """
    if not GOOGLE_SSO_ENABLED:
        return False
    try:
        user = st.user
    except Exception:
        return False

    if not getattr(user, "is_logged_in", False):
        st.session_state.pop("google_access_denied_email", None)
        return False

    email = (user.email or "").lower()
    if GOOGLE_ALLOWED_DOMAIN and not email.endswith(f"@{GOOGLE_ALLOWED_DOMAIN.lower()}"):
        already_seen = st.session_state.get("google_access_denied_email") == email
        st.session_state.google_access_denied_email = email
        if already_seen:
            st.logout()
        return False

    st.session_state.pop("google_access_denied_email", None)
    st.session_state.authentication_status = True
    st.session_state.login_method = "google"
    st.session_state.username = email
    st.session_state.name = user.name or email
    return True


def get_backend_api_client():
    import atexit

    from api_client.sync_client import SyncHummingbotAPIClient

    server = _get_selected_server()
    host = server.get('host', '127.0.0.1')
    port = server.get('port', 8000)
    username = server.get('username', 'admin')
    password = server.get('password', 'admin')

    # Use Streamlit session state to store singleton instance
    if 'backend_api_client' not in st.session_state or st.session_state.backend_api_client is None:
        try:
            # Create and enter the client context
            # Ensure URL has proper protocol
            if not str(host).startswith(('http://', 'https://')):
                base_url = f"http://{host}:{port}"
            else:
                base_url = f"{host}:{port}"

            client = SyncHummingbotAPIClient(
                base_url=base_url,
                username=username,
                password=password
            )
            # Initialize the client using context manager
            client.__enter__()

            # Register cleanup function to properly exit the context manager
            def cleanup_client():
                _close_backend_api_client(client)
                if st.session_state.get('backend_api_client') is client:
                    st.session_state.backend_api_client = None

            # Register cleanup with atexit and session state
            atexit.register(_close_backend_api_client, client)
            if 'cleanup_registered' not in st.session_state:
                st.session_state.cleanup_registered = True
                # Also register cleanup for session state changes
                st.session_state.backend_api_client_cleanup = cleanup_client

            # Check Docker after initialization
            if not client.docker.is_running():
                st.error("Docker is not running. Please make sure Docker is running.")
                cleanup_client()  # Clean up before stopping
                st.stop()

            st.session_state.backend_api_client = client
        except Exception as e:
            st.error(f"Failed to initialize API client: {str(e)}")
            st.stop()

    return st.session_state.backend_api_client


def _clear_google_auth_state():
    for key in ("authentication_status", "login_method", "username", "name"):
        st.session_state.pop(key, None)


def auth_system():
    render_server_selector()
    visible_sections = _get_selected_server().get('visible_sections')
    if not AUTH_SYSTEM_ENABLED:
        render_server_selector()
        return {
            "Main": main_page(),
            **private_pages(visible_sections),
            **public_pages(),
        }

    _sync_google_login()

    if st.session_state.get("authentication_status", False):
        render_server_selector()
        if st.sidebar.button("Logout"):
            _clear_google_auth_state()
            st.logout()
            st.rerun()

        st.sidebar.write(f'Welcome *{st.session_state.get("name", st.session_state.get("username", "User"))}*')
        return {
            "Main": main_page(),
            **private_pages(),
            **public_pages(),
        }

    return {
        "Login": [st.Page("frontend/pages/login.py", title="Sign in", icon="🔒", url_path="login")],
    }
