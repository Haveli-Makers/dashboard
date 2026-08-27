import inspect
import json
import os.path
from pathlib import Path
from typing import Optional, Union
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st
import yaml
from streamlit.commands.page_config import InitialSideBarState, Layout
from yaml import SafeLoader

from CONFIG import AUTH_SYSTEM_ENABLED
from frontend.pages.permissions import main_page, pages_for_role, private_pages, public_pages


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
        clear_backend_auth_state()
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


def _build_base_url(server: dict) -> str:
    host = server.get('host', '127.0.0.1')
    port = server.get('port', 8000)
    if not str(host).startswith(('http://', 'https://')):
        return f"http://{host}:{port}"
    return f"{host}:{port}"


def clear_backend_auth_state():
    for key in (
        "authentication_status",
        "backend_access_token",
        "backend_token_type",
        "backend_token_expires_in",
        "user_role",
        "username",
        "name",
    ):
        st.session_state.pop(key, None)


def login_with_backend(username: str, password: str) -> dict:
    server = _get_selected_server()
    login_url = f"{_build_base_url(server)}/auth/token"
    payload = json.dumps({"username": username, "password": password}).encode("utf-8")
    request = Request(
        login_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 401:
            raise ValueError("Username/password is incorrect") from exc
        raise ValueError(f"Backend login failed with status {exc.code}") from exc
    except URLError as exc:
        raise ValueError(f"Could not connect to backend: {exc.reason}") from exc


def get_backend_api_client():
    import atexit

    from api_client.sync_client import SyncHummingbotAPIClient

    server = _get_selected_server()
    username = server.get('username', 'admin')
    password = server.get('password', 'admin')
    access_token = st.session_state.get("backend_access_token")

    # Use Streamlit session state to store singleton instance
    if 'backend_api_client' not in st.session_state or st.session_state.backend_api_client is None:
        try:
            # Create and enter the client context
            # Ensure URL has proper protocol
            base_url = _build_base_url(server)

            client = SyncHummingbotAPIClient(
                base_url=base_url,
                username=username,
                password=password,
                access_token=access_token,
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


def auth_system():
    render_server_selector()
    if not AUTH_SYSTEM_ENABLED:
        return {
            "Main": main_page(),
            **private_pages(),
            **public_pages(),
        }

    if st.session_state.get("authentication_status", False):
        if st.sidebar.button("Logout"):
            if st.session_state.get("backend_api_client") is not None:
                try:
                    st.session_state.backend_api_client.__exit__(None, None, None)
                except Exception:
                    pass
                st.session_state.backend_api_client = None
            clear_backend_auth_state()
            st.rerun()

        role = st.session_state.get("user_role", "USER")
        st.sidebar.write(f'Welcome *{st.session_state.get("name", st.session_state.get("username", "User"))}*')
        st.sidebar.caption(f"Role: {role}")
        return {
            "Main": main_page(),
            **pages_for_role(role),
            **public_pages(),
        }

    with st.form("backend_login_form"):
        st.subheader("Login")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

    if submitted:
        try:
            token_response = login_with_backend(username, password)
            role = token_response.get("role", "USER")
            st.session_state.authentication_status = True
            st.session_state.backend_access_token = token_response["access_token"]
            st.session_state.backend_token_type = token_response.get("token_type", "bearer")
            st.session_state.backend_token_expires_in = token_response.get("expires_in")
            st.session_state.user_role = role
            st.session_state.username = username
            st.session_state.name = username
            st.rerun()
        except ValueError as exc:
            st.session_state.authentication_status = False
            st.error(str(exc))

    return {
        "Main": main_page(),
        **public_pages()
    }
