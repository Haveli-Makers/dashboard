import inspect
import os.path
from pathlib import Path
from typing import Optional, Union

import pandas as pd
import streamlit as st
import yaml
from streamlit.commands.page_config import InitialSideBarState, Layout
from streamlit.errors import StreamlitAuthError
from yaml import SafeLoader

from CONFIG import AUTH_SYSTEM_ENABLED, GOOGLE_ALLOWED_DOMAIN, GOOGLE_SSO_ENABLED
from frontend.pages.permissions import filter_sections, main_page, private_pages, public_pages


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
    with open(servers_path, encoding='utf-8') as f:
        data = yaml.load(f, Loader=SafeLoader)
    return data.get('servers', [])


SERVER_QUERY_PARAM = "server"


def _init_selected_server_name(server_names: list[str]) -> None:
    """Restore the selected server from the URL (survives page refresh), else default to the first one."""
    if 'selected_server_name' in st.session_state or not server_names:
        return
    requested = st.query_params.get(SERVER_QUERY_PARAM)
    st.session_state.selected_server_name = requested if requested in server_names else server_names[0]


def sync_server_query_param() -> None:
    """Keep the selected server in the URL so a refresh reloads the same server.
    Must run after st.navigation(), since switching pages clears query params."""
    selected_name = st.session_state.get('selected_server_name')
    if selected_name and st.query_params.get(SERVER_QUERY_PARAM) != selected_name:
        st.query_params[SERVER_QUERY_PARAM] = selected_name


def render_server_selector():
    """Render a server selector dropdown in the sidebar."""
    servers = load_servers()
    if not servers:
        return
    server_names = [s['name'] for s in servers]
    _init_selected_server_name(server_names)

    def _on_server_change():
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
    if servers:
        _init_selected_server_name([s['name'] for s in servers])
    selected_name = st.session_state.get('selected_server_name')
    for s in servers:
        if s['name'] == selected_name:
            return s
    return servers[0] if servers else {}


def get_selected_server_config() -> dict:
    """Public helper: returns host, port, username, password for the active server."""
    return _get_selected_server()


_CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$"}


def get_currency_symbol() -> str:
    """Currency symbol for the active server (set via `currency` in servers.yml, defaults to $)."""
    code = (_get_selected_server().get('currency') or 'USD').upper()
    return _CURRENCY_SYMBOLS.get(code, '$')


def get_server_cache_key() -> str:
    """Hashable id of the active server. st.cache_data is shared across sessions, so cached
    backend data must be keyed by it."""
    server = _get_selected_server()
    return f"{server.get('name')}@{server.get('host')}:{server.get('port')}"


USD_QUOTES = {"USDT", "USD", "USDC", "FDUSD", "BUSD", "TUSD", "DAI", "USDE"}
INR_QUOTES = {"INR"}
_DEFAULT_FX_PAIR = "USDT-INR"


@st.cache_data(ttl=30, show_spinner=False)
def _fetch_fx_rate(server_key: str, connector_name: str, fx_pair: str):
    """Fetch an FX mid-price from the exchange order book, falling back to the ticker."""
    client = get_backend_api_client()
    try:
        book = client.market_data.get_order_book(
            connector_name=connector_name,
            trading_pair=fx_pair,
            depth=1,
        )
        if isinstance(book, dict) and "data" in book:
            book = book.get("data", {})
        bids, asks = book.get("bids") or [], book.get("asks") or []
        best_bid = float(bids[0]["price"]) if bids else 0
        best_ask = float(asks[0]["price"]) if asks else 0
        if best_bid > 0 and best_ask > 0:
            return (best_bid + best_ask) / 2
        if best_bid > 0 or best_ask > 0:
            return best_bid or best_ask
    except Exception:
        pass

    try:
        price_response = client.market_data.get_prices(
            connector_name=connector_name,
            trading_pairs=[fx_pair],
        )
        if isinstance(price_response, dict):
            data = (
                price_response.get("data", {})
                if price_response.get("status") == "success"
                else price_response
            )
        else:
            data = {}
        price = data.get(fx_pair)
        if price and float(price) > 0:
            return float(price)
    except Exception:
        pass

    return None


def resolve_currency_and_rate(connector_name: Optional[str] = None):
    """Resolve the display currency and quote -> display-currency rate."""
    server = _get_selected_server()
    currency_code = (server.get('currency') or 'USD').upper()

    if currency_code != 'INR':
        return '$', 1.0

    fx_pair = _DEFAULT_FX_PAIR

    rate = None
    if connector_name:
        try:
            rate = _fetch_fx_rate(get_server_cache_key(), connector_name, fx_pair)
        except Exception:
            rate = None

    if not rate:
        if connector_name:
            st.warning(f"Could not fetch {fx_pair} rate from {connector_name}; USD-quoted values are not converted.")
        return '$', 1.0
    return '₹', rate


def start_google_login():
    st.session_state.pop("google_access_denied_email", None)
    try:
        st.login("google")
    except StreamlitAuthError:
        st.session_state["google_auth_not_configured"] = True


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
        return False

    email = (user.email or "").lower()
    if GOOGLE_ALLOWED_DOMAIN and not email.endswith(f"@{GOOGLE_ALLOWED_DOMAIN.lower()}"):
        st.session_state.google_access_denied_email = email
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

    clients = st.session_state.setdefault('backend_api_clients', {})
    client_key = server.get('name', f"{host}:{port}")
    if clients.get(client_key) is None:
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

            # Check Docker after initialization
            if not client.docker.is_running():
                st.error("Docker is not running. Please make sure Docker is running.")
                _close_backend_api_client(client)  # Clean up before stopping
                st.stop()

            atexit.register(_close_backend_api_client, client)
            clients[client_key] = client
        except Exception as e:
            st.error(f"Failed to initialize API client: {str(e)}")
            st.stop()

    return clients[client_key]


def _clear_google_auth_state():
    for key in ("authentication_status", "login_method", "username", "name"):
        st.session_state.pop(key, None)


def sign_out():
    _clear_google_auth_state()
    st.session_state.pop("google_access_denied_email", None)
    st.logout()


def auth_system():
    visible_sections = _get_selected_server().get('visible_sections')
    if not AUTH_SYSTEM_ENABLED:
        render_server_selector()
        return filter_sections({
            "Main": main_page(),
            **private_pages(),
            **public_pages(),
        }, visible_sections)

    _sync_google_login()

    if st.session_state.get("authentication_status", False):
        render_server_selector()
        if st.sidebar.button("Logout"):
            sign_out()

        st.sidebar.write(f'Welcome *{st.session_state.get("name", st.session_state.get("username", "User"))}*')
        return filter_sections({
            "Main": main_page(),
            **private_pages(),
            **public_pages(),
        }, visible_sections)

    return {
        "Login": [st.Page("frontend/pages/login.py", title="Sign in", icon="🔒", url_path="login")],
    }
