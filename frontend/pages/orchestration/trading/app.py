import datetime
import html
import math

import nest_asyncio
import pandas as pd
import streamlit as st

from frontend.candles import is_valid_pair, market_data_error
from frontend.components.price_chart import show_price_chart_dialog
from frontend.st_utils import get_backend_api_client, get_currency_symbol, get_server_cache_key, initialize_st_page
from frontend.utils import price_precision

# Enable nested async
nest_asyncio.apply()

initialize_st_page(
    layout="wide",
    show_readme=False
)

# Initialize backend client
backend_api_client = get_backend_api_client()
CURRENCY = get_currency_symbol()

# Initialize session state
if "selected_account" not in st.session_state:
    st.session_state.selected_account = None
if "selected_connector" not in st.session_state:
    st.session_state.selected_connector = None
if "selected_market" not in st.session_state:
    st.session_state.selected_market = {"connector": "binance_perpetual", "trading_pair": "BTC-USDT"}
if "auto_refresh_enabled" not in st.session_state:
    st.session_state.auto_refresh_enabled = False  # Start with manual refresh

# Trading form session state
if "trade_price_set_by_user" not in st.session_state:
    st.session_state.trade_price_set_by_user = False  # Track if user set custom price
if "last_order_type" not in st.session_state:
    st.session_state.last_order_type = "market"  # Track order type changes

# Set refresh interval for real-time updates
REFRESH_INTERVAL = 30  # seconds
MARKET_DATA_TTL = 3  # seconds; lets form edits and clicks reuse the market data instead of re-fetching
ORDER_BOOK_ROWS = 22


@st.cache_data(ttl=MARKET_DATA_TTL, show_spinner=False)
def _fetch_order_book(server, connector, trading_pair, depth):
    return backend_api_client.market_data.get_order_book(
        connector_name=connector,
        trading_pair=trading_pair,
        depth=depth
    )


@st.cache_data(ttl=MARKET_DATA_TTL, show_spinner=False)
def _fetch_prices(server, connector, trading_pair):
    return backend_api_client.market_data.get_prices(
        connector_name=connector,
        trading_pairs=[trading_pair]
    )


@st.cache_data(ttl=MARKET_DATA_TTL, show_spinner=False)
def _fetch_quote_volume(server, connector, trading_pair, price, is_buy):
    return backend_api_client.market_data.get_quote_volume_for_price(
        connector_name=connector,
        trading_pair=trading_pair,
        price=price,
        is_buy=is_buy
    )


@st.cache_data(ttl=REFRESH_INTERVAL, show_spinner=False)
def _fetch_funding_info(server, connector, trading_pair):
    return backend_api_client.market_data.get_funding_info(
        connector_name=connector,
        trading_pair=trading_pair
    )


def clear_market_data_cache():
    for cached_fetch in (_fetch_order_book, _fetch_prices, _fetch_quote_volume, _fetch_funding_info):
        cached_fetch.clear()


def split_trading_pair(trading_pair):
    """Split a trading pair into base and quote without breaking dated pairs."""
    base_token, separator, quote_token = trading_pair.partition("-")
    return base_token, quote_token if separator else ""


def show_market_data_error(data, connector, trading_pair, error):
    """Show a readable message, with the raw backend error tucked away for debugging."""
    st.warning(market_data_error(trading_pair, connector, error, data=data))
    with st.expander("Error details"):
        st.code(str(error), language="text")


def get_price_map(connector, trading_pair, quiet=False):
    """Get the latest price response normalized to a trading_pair -> price mapping."""
    try:
        price_response = _fetch_prices(get_server_cache_key(), connector, trading_pair)
        if isinstance(price_response, dict):
            if price_response.get("status") == "success":
                return price_response.get("data", {})
            if "prices" in price_response:
                return price_response.get("prices", {})
            return price_response
        if isinstance(price_response, list):
            return {
                item.get("trading_pair", "unknown"): item.get("price", 0)
                for item in price_response
                if isinstance(item, dict)
            }
    except Exception as e:
        if not quiet:
            show_market_data_error("prices", connector, trading_pair, e)
    return {}


def get_current_price(prices, trading_pair, order_book):
    """Prefer ticker price, then fall back to the order book midpoint."""
    if prices and trading_pair in prices:
        try:
            return float(prices[trading_pair])
        except (TypeError, ValueError):
            pass

    bids = order_book.get("bids", []) if order_book else []
    asks = order_book.get("asks", []) if order_book else []
    if bids and asks:
        try:
            return (float(bids[0]["price"]) + float(asks[0]["price"])) / 2
        except (TypeError, ValueError, KeyError):
            pass
    return 0.0


def get_market_snapshot(connector, trading_pair):
    """Order book plus the best available current price for the pair. Fetch errors are left to the
    market header to report, so they show once."""
    order_book = get_order_book(connector, trading_pair, depth=ORDER_BOOK_ROWS, quiet=True)
    prices = get_price_map(connector, trading_pair, quiet=True)
    return order_book, get_current_price(prices, trading_pair, order_book)


def get_quote_volume(connector, trading_pair, price, is_buy):
    """Quote volume available up to `price`, or 0 when the backend has no usable value."""
    response = _fetch_quote_volume(get_server_cache_key(), connector, trading_pair, price, is_buy)
    volume = response.get("result_quote_volume") if isinstance(response, dict) else None
    try:
        volume = float(volume)
    except (TypeError, ValueError):
        return 0
    return 0 if math.isnan(volume) else volume


# Quote assets priced in US dollars; converted to INR when the server displays in ₹
USD_QUOTES = {"USDT", "USD", "USDC"}
FX_PAIR = "USDT-INR"
USDT_INR_RATE = 1.0  # Resolved once the exchange is selected


def parse_prices(price_response):
    """Normalize the different get_prices response formats into {trading_pair: price}."""
    if isinstance(price_response, dict):
        if "status" in price_response and price_response.get("status") == "success":
            return price_response.get("data", {})
        elif "prices" in price_response:
            return price_response.get("prices", {})
        return price_response
    elif isinstance(price_response, list):
        return {item.get("trading_pair", "unknown"): item.get("price", 0) for item in price_response if
                isinstance(item, dict)}
    return {}


@st.cache_data(ttl=REFRESH_INTERVAL, show_spinner=False)
def fetch_usdt_inr_rate(connector_name):
    """Fetch the USDT-INR price from the exchange."""
    try:
        book = backend_api_client.market_data.get_order_book(
            connector_name=connector_name,
            trading_pair=FX_PAIR,
            depth=1
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

    response = backend_api_client.market_data.get_prices(
        connector_name=connector_name,
        trading_pairs=[FX_PAIR]
    )
    price = parse_prices(response).get(FX_PAIR)
    return float(price) if price and float(price) > 0 else None


def resolve_usdt_inr_rate(connector_name):
    """Rate for converting USD-quoted values to the display currency."""
    global CURRENCY
    if CURRENCY != "₹":
        return 1.0
    rate = None
    if connector_name:
        try:
            rate = fetch_usdt_inr_rate(connector_name)
        except Exception:
            rate = None
    if not rate:
        st.warning(f"Could not fetch {FX_PAIR} price; showing USD-quoted values in $.")
        CURRENCY = "$"
        return 1.0
    return rate


def quote_rate(trading_pair=None):
    if not trading_pair or "-" not in str(trading_pair):
        return USDT_INR_RATE
    quote = str(trading_pair).split("-")[-1].upper()
    return USDT_INR_RATE if quote in USD_QUOTES else 1.0


def convert_price_columns(df, columns):
    rates = df["trading_pair"].map(quote_rate) if "trading_pair" in df.columns else USDT_INR_RATE
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce") * rates
    return df


def convert_records(records, keys, rate):
    if rate == 1.0 or not records:
        return records
    converted = []
    for record in records:
        if isinstance(record, dict):
            record = {**record, **{k: float(record[k]) * rate for k in keys if record.get(k) is not None}}
        converted.append(record)
    return converted


def get_accounts_and_credentials():
    """Get available accounts and their credentials."""
    try:
        accounts_list = backend_api_client.accounts.list_accounts()
        credentials_list = {}
        for account in accounts_list:
            credentials = backend_api_client.accounts.list_account_credentials(account_name=account)
            credentials_list[account] = credentials
        return accounts_list, credentials_list
    except Exception as e:
        st.error(f"Failed to fetch accounts: {e}")
        return [], {}


def get_positions(account_name=None):
    """Get current positions."""
    try:
        kwargs = {"limit": 100}
        if account_name:
            kwargs["account_names"] = [account_name]
        response = backend_api_client.trading.get_positions(**kwargs)
        # Handle both response formats
        if isinstance(response, list):
            return response
        elif isinstance(response, dict) and response.get("status") == "success":
            return response.get("data", [])
        elif isinstance(response, dict) and "data" in response:
            return response.get("data", [])
        return []
    except Exception as e:
        st.error(f"Failed to fetch positions: {e}")
        return []


def get_active_orders(account_name=None):
    """Get active orders."""
    try:
        kwargs = {"limit": 100}
        if account_name:
            kwargs["account_names"] = [account_name]
        response = backend_api_client.trading.get_active_orders(**kwargs)
        if isinstance(response, list):
            return response
        elif isinstance(response, dict):
            if response.get("status") == "success":
                return response.get("data", [])
            elif "data" in response:
                return response.get("data", [])
        return []
    except Exception as e:
        st.error(f"Failed to fetch active orders: {e}")
        return []


def _extract_data(response):
    if isinstance(response, list):
        return response
    elif isinstance(response, dict):
        if response.get("status") == "success":
            return response.get("data", [])
        elif "data" in response:
            return response.get("data", [])
    return []


def get_order_history(start_date=None, end_date=None, tz=None):
    """Get order history for [start_date, end_date] (inclusive, local dates)."""
    start_ms = end_ms = None
    if start_date is not None and end_date is not None:
        tz = tz or datetime.datetime.now().astimezone().tzinfo
        start_ms = int(datetime.datetime.combine(start_date, datetime.time.min, tzinfo=tz).timestamp() * 1000)
        end_ms = int(datetime.datetime.combine(end_date, datetime.time.max, tzinfo=tz).timestamp() * 1000)

    db_orders = []
    try:
        response = backend_api_client.trading.search_orders(limit=200, start_time=start_ms, end_time=end_ms)
        db_orders = _extract_data(response)
    except Exception:
        pass

    exchange_orders = []
    if st.session_state.selected_account and st.session_state.selected_connector:
        try:
            selected_pair = st.session_state.selected_market.get("trading_pair")
            response = backend_api_client.trading.search_exchange_orders(
                account_names=[st.session_state.selected_account],
                connector_names=[st.session_state.selected_connector],
                trading_pairs=[selected_pair] if selected_pair else None,
                start_time=start_ms,
                end_time=end_ms,
                limit=200,
            )
            exchange_orders = _extract_data(response)
        except Exception:
            pass

    return db_orders + exchange_orders


def get_order_book(connector, trading_pair, depth=10, quiet=False):
    """Get order book data for the selected trading pair."""
    try:
        response = _fetch_order_book(get_server_cache_key(), connector, trading_pair, depth)

        if isinstance(response, dict):
            if "status" in response and response.get("status") == "success":
                return response.get("data", {})
            elif "bids" in response and "asks" in response:
                return response
        return {}
    except Exception as e:
        if not quiet:
            show_market_data_error("the order book", connector, trading_pair, e)
        return {}


def get_funding_rate(connector, trading_pair):
    """Get funding rate for perpetual contracts."""
    try:
        if "perpetual" in connector.lower():
            response = _fetch_funding_info(get_server_cache_key(), connector, trading_pair)
            if isinstance(response, dict):
                if "status" in response and response.get("status") == "success":
                    return response.get("data", {})
                elif "funding_rate" in response:
                    return response
            return {}
        return {}
    except Exception:
        return {}


def place_order(order_data):
    """Place a trading order."""
    try:
        response = backend_api_client.trading.place_order(**order_data)
        if response.get("status") == "submitted":
            st.success(f"Order placed successfully! Order ID: {response.get('order_id')}")
            return True
        else:
            st.error(f"Failed to place order: {response.get('message', 'Unknown error')}")
            return False
    except Exception as e:
        st.error(f"Failed to place order: {e}")
        return False


def cancel_order(account_name, connector_name, order_id):
    """Cancel an order."""
    try:
        response = backend_api_client.trading.cancel_order(
            account_name=account_name,
            connector_name=connector_name,
            client_order_id=order_id
        )
        if response.get("status") == "success":
            st.success(f"Order {order_id} cancelled successfully!")
            return True
        else:
            st.error(f"Failed to cancel order: {response.get('message', 'Unknown error')}")
            return False
    except Exception as e:
        st.error(f"Failed to cancel order: {e}")
        return False


def render_positions_table(positions_data):
    """Render positions table with enhanced metrics and hedging information."""
    if not positions_data:
        st.info("No open positions found.")
        return

    df = pd.DataFrame(positions_data)
    if df.empty:
        st.info("No open positions found.")
        return

    df = convert_price_columns(df, ["entry_price", "mark_price", "unrealized_pnl"])

    if 'amount' in df.columns and 'entry_price' in df.columns:
        df['original_value'] = df['amount'] * df['entry_price']

    st.subheader("🎯 Open Positions")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        total_unrealized_pnl = df['unrealized_pnl'].sum() if 'unrealized_pnl' in df.columns else 0
        st.metric(
            "Total Unrealized PnL",
            f"{CURRENCY}{total_unrealized_pnl:,.2f}",
            delta=None,
            delta_color="normal" if total_unrealized_pnl >= 0 else "inverse"
        )
    with col2:
        total_original_value = abs(df['original_value']).sum() if 'original_value' in df.columns else 0
        st.metric(
            "Total Position Amount",
            f"{CURRENCY}{abs(total_original_value):,.2f}"
        )
    long_positions = df[df['amount'] > 0] if 'amount' in df.columns else pd.DataFrame()
    short_positions = df[df['amount'] < 0] if 'amount' in df.columns else pd.DataFrame()
    with col3:
        long_value = (
            long_positions['original_value'].sum()
            if not long_positions.empty and 'original_value' in long_positions.columns
            else 0
        )
        st.metric("Long Exposure", f"{CURRENCY}{abs(long_value):,.2f}", help="Total value of long positions")

    with col4:
        short_value = (
            short_positions['original_value'].sum()
            if not short_positions.empty and 'original_value' in short_positions.columns
            else 0
        )
        st.metric(
            "Short Exposure", f"{CURRENCY}{abs(short_value):,.2f}", help="Total value of short positions")

    if long_value != 0 and short_value != 0:
        hedge_ratio = min(abs(short_value), abs(long_value)) / max(abs(short_value), abs(long_value)) * 100
        st.info(f"📊 **Hedge Ratio**: {hedge_ratio:.1f}% (Higher = More Hedged)")
    elif long_value > 0 and short_value == 0:
        st.warning("⚠️ **Portfolio is fully LONG** - No short hedging")
    elif short_value > 0 and long_value == 0:
        st.warning("⚠️ **Portfolio is fully SHORT** - No long hedging")

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "amount": st.column_config.NumberColumn(
                "Amount",
                format="%.6f",
                help="Positive = Long, Negative = Short"
            ),
            "entry_price": st.column_config.NumberColumn(
                "Entry Price",
                format=f"{CURRENCY}%.4f"
            ),
            "original_value": st.column_config.NumberColumn(
                "Original Value",
                format=f"{CURRENCY}%.2f",
                help="Amount × Entry Price"
            ),
            "mark_price": st.column_config.NumberColumn(
                "Mark Price",
                format=f"{CURRENCY}%.4f"
            ),
            "unrealized_pnl": st.column_config.NumberColumn(
                "Unrealized PnL",
                format=f"{CURRENCY}%.2f"
            )
        }
    )

    if not long_positions.empty and not short_positions.empty:
        st.divider()

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("🟢 Long Positions")
            if not long_positions.empty:
                long_pnl = long_positions['unrealized_pnl'].sum() if 'unrealized_pnl' in long_positions.columns else 0
                st.caption(f"PnL: {CURRENCY}{long_pnl:,.2f}")
                st.dataframe(
                    long_positions,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "amount": st.column_config.NumberColumn("Amount", format="%.6f"),
                        "entry_price": st.column_config.NumberColumn("Entry Price", format=f"{CURRENCY}%.4f"),
                        "unrealized_pnl": st.column_config.NumberColumn("PnL", format=f"{CURRENCY}%.2f")
                    }
                )

        with col2:
            st.subheader("🔴 Short Positions")
            if not short_positions.empty:
                short_pnl = short_positions['unrealized_pnl'].sum() if 'unrealized_pnl' in short_positions.columns else 0
                st.caption(f"PnL: {CURRENCY}{short_pnl:,.2f}")
                st.dataframe(
                    short_positions,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "amount": st.column_config.NumberColumn("Amount", format="%.6f"),
                        "entry_price": st.column_config.NumberColumn("Entry Price", format=f"{CURRENCY}%.4f"),
                        "unrealized_pnl": st.column_config.NumberColumn("PnL", format=f"{CURRENCY}%.2f")
                    }
                )
    elif not long_positions.empty:
        st.info("📈 All positions are LONG")
    elif not short_positions.empty:
        st.info("📉 All positions are SHORT")


def render_orders_table(orders_data):
    """Render active orders table."""
    if not orders_data:
        st.info("No active orders found.")
        return

    df = pd.DataFrame(orders_data)
    if df.empty:
        st.info("No active orders found.")
        return

    st.subheader("📋 Active Orders")

    df_with_cancel = convert_price_columns(df.copy(), ["price"])
    df_with_cancel["cancel"] = False

    column_config = {
        "cancel": st.column_config.CheckboxColumn(
            "Cancel",
            help="Select orders to cancel",
            default=False,
        ),
        "price": st.column_config.NumberColumn(
            "Price",
            format=f"{CURRENCY}%.4f"
        ),
        "amount": st.column_config.NumberColumn(
            "Amount",
            format="%.6f"
        ),
        "executed_amount_base": st.column_config.NumberColumn(
            "Executed (Base)",
            format="%.6f"
        ),
        "executed_amount_quote": st.column_config.NumberColumn(
            "Executed (Quote)",
            format="%.6f"
        ),
        "last_update_timestamp": st.column_config.DatetimeColumn(
            "Last Update",
            format="DD/MM/YYYY HH:mm:ss"
        )
    }

    edited_df = st.data_editor(
        df_with_cancel,
        column_config=column_config,
        disabled=[col for col in df_with_cancel.columns if col != "cancel"],
        hide_index=True,
        use_container_width=True,
        key="orders_editor"
    )

    if "cancel" in edited_df.columns:
        selected_orders = edited_df[edited_df["cancel"]]
        if not selected_orders.empty and st.button(f"❌ Cancel Selected ({len(selected_orders)}) Orders",
                                                   type="secondary"):
            with st.spinner("Cancelling orders..."):
                for _, order in selected_orders.iterrows():
                    cancel_order(
                        order.get("account_name", ""),
                        order.get("connector_name", ""),
                        order.get("client_order_id", "")
                    )
            st.rerun()


# Page Header
st.title("💹 Trading Hub")
st.caption("Execute trades, monitor positions, and analyze markets")

# Get accounts and credentials
accounts_list, credentials_dict = get_accounts_and_credentials()

st.subheader("🏦 Account & Market")
acc_col, conn_col, pair_col = st.columns(3)

with acc_col:
    if accounts_list:
        if st.session_state.selected_account is None:
            st.session_state.selected_account = accounts_list[0]
        selected_account = st.selectbox(
            "📱 Account",
            accounts_list,
            index=accounts_list.index(
                st.session_state.selected_account) if st.session_state.selected_account in accounts_list else 0,
            key="account_selector"
        )
        st.session_state.selected_account = selected_account
    else:
        st.error("No accounts found")
        st.stop()

with conn_col:
    if selected_account and credentials_dict.get(selected_account):
        credentials = credentials_dict[selected_account]
        if isinstance(credentials, list) and credentials:
            if isinstance(credentials[0], str):
                credentials = [{"connector_name": cred} for cred in credentials]
            elif isinstance(credentials[0], dict):
                credentials = credentials
        elif isinstance(credentials, dict):
            credentials = [{"connector_name": k, **v} for k, v in credentials.items()]
        else:
            credentials = []
        default_cred = credentials[0] if credentials else None
        if default_cred and credentials:
            connector = st.selectbox(
                "📡 Exchange",
                [cred["connector_name"] for cred in credentials],
                index=0,
                key="connector_selector"
            )
            st.session_state.selected_connector = connector
        else:
            st.error("No credentials found for this account")
            connector = None
    else:
        st.error("No credentials available")
        connector = None
    if connector is None:
        st.session_state.selected_connector = None
        st.session_state.selected_market = {}

with pair_col:
    trading_pair = st.text_input(
        "💱 Trading Pair",
        value="BTC-USDT",
        key="trading_pair_input"
    )
    trading_pair = trading_pair.strip().upper()
    if trading_pair and not is_valid_pair(trading_pair):
        st.warning(market_data_error(trading_pair, connector, "invalid pair format"))
        trading_pair = ""

if connector and trading_pair:
    st.session_state.selected_market = {"connector": connector, "trading_pair": trading_pair}
else:
    st.session_state.selected_market = {}

USDT_INR_RATE = resolve_usdt_inr_rate(st.session_state.selected_connector)

st.divider()
market_title_col, refresh_toggle_col, refresh_btn_col = st.columns([4, 1, 1])
with market_title_col:
    st.subheader("📊 Market Data")
with refresh_toggle_col:
    auto_refresh = st.toggle(
        "🔄 Auto-refresh",
        value=st.session_state.auto_refresh_enabled,
        help=f"Refresh data every {REFRESH_INTERVAL} seconds"
    )
    st.session_state.auto_refresh_enabled = auto_refresh
with refresh_btn_col:
    if st.button("🔄 Refresh Now", use_container_width=True, type="primary"):
        clear_market_data_cache()
        st.rerun()

# Market sections refresh as fragments, so auto-refresh never reruns (and resets) the trade form
MARKET_RUN_EVERY = REFRESH_INTERVAL if st.session_state.auto_refresh_enabled else None


def render_market_header(connector, trading_pair):
    order_book = get_order_book(connector, trading_pair, depth=ORDER_BOOK_ROWS)

    bid_price = 0
    ask_price = 0
    if order_book and "bids" in order_book and "asks" in order_book:
        bid_price = float(order_book["bids"][0]["price"]) if order_book["bids"] else 0
        ask_price = float(order_book["asks"][0]["price"]) if order_book["asks"] else 0
    precision = price_precision(bid_price or ask_price)

    display_rate = quote_rate(trading_pair)

    is_perpetual = "perpetual" in connector.lower()
    header_cols = st.columns(7 if is_perpetual else 6)
    bid_col, ask_col, spread_col, depth_pct_col, buy_depth_col, sell_depth_col = header_cols[:6]

    with bid_col:
        st.metric("📈 Bid Price", f"{CURRENCY}{bid_price * display_rate:,.{precision}f}" if bid_price else "N/A")

    with ask_col:
        st.metric("📉 Ask Price", f"{CURRENCY}{ask_price * display_rate:,.{precision}f}" if ask_price else "N/A")

    with spread_col:
        if bid_price > 0 and ask_price > 0:
            spread = ask_price - bid_price
            spread_pct = (spread / bid_price) * 100
            st.metric("↔️ Spread", f"{CURRENCY}{spread * display_rate:,.{precision}f}", delta=f"{spread_pct:.4f}%")
        else:
            st.metric("↔️ Spread", "N/A")

    with depth_pct_col:
        depth_percentage = st.number_input(
            "📊 Depth ±%",
            min_value=0.1,
            max_value=10.0,
            value=1.0,
            step=0.1,
            format="%.1f",
            key="depth_percentage"
        )

    with buy_depth_col:
        if order_book and "bids" in order_book and "asks" in order_book and bid_price > 0 and ask_price > 0:
            depth_factor = depth_percentage / 100
            sell_price_depth = ask_price * (1 + depth_factor)
            try:
                buy_vol = get_quote_volume(connector, trading_pair, sell_price_depth, is_buy=True)
                st.metric(
                    f"📊 Buy Depth ({CURRENCY})",
                    f"{CURRENCY}{buy_vol * display_rate:,.0f}" if buy_vol != 0 else "N/A",
                    help="Volume available when buying (hitting asks)"
                )
            except Exception:
                total_ask_volume = sum(float(ask["amount"]) * float(ask["price"]) for ask in order_book["asks"]) * display_rate
                st.metric(f"📊 Buy Depth ({CURRENCY})", f"{CURRENCY}{total_ask_volume:,.0f}", help="Total ask volume (for buying)")
        else:
            st.metric(f"📊 Buy Depth ({CURRENCY})", "N/A")

    with sell_depth_col:
        if order_book and "bids" in order_book and "asks" in order_book and bid_price > 0 and ask_price > 0:
            depth_factor = depth_percentage / 100
            buy_price_depth = bid_price * (1 - depth_factor)
            try:
                sell_vol = get_quote_volume(connector, trading_pair, buy_price_depth, is_buy=False)
                st.metric(
                    f"📊 Sell Depth ({CURRENCY})",
                    f"{CURRENCY}{sell_vol * display_rate:,.0f}" if sell_vol != 0 else "N/A",
                    help="Volume available when selling (hitting bids)"
                )
            except Exception:
                total_bid_volume = sum(float(bid["amount"]) * float(bid["price"]) for bid in order_book["bids"]) * display_rate
                st.metric(f"📊 Sell Depth ({CURRENCY})", f"{CURRENCY}{total_bid_volume:,.0f}", help="Total bid volume (for selling)")
        else:
            st.metric(f"📊 Sell Depth ({CURRENCY})", "N/A")

    if is_perpetual:
        with header_cols[6]:
            funding_data = get_funding_rate(connector, trading_pair)
            if funding_data and "funding_rate" in funding_data:
                funding_rate = float(funding_data["funding_rate"]) * 100
                st.metric("💸 Funding Rate", f"{funding_rate:.4f}%")
            else:
                st.metric("💸 Funding Rate", "N/A")


if st.session_state.selected_market.get("connector") and st.session_state.selected_market.get("trading_pair"):
    st.fragment(render_market_header, run_every=MARKET_RUN_EVERY)(
        st.session_state.selected_market["connector"],
        st.session_state.selected_market["trading_pair"],
    )
else:
    st.info("Select account and pair to view extended market data")


def render_coindcx_orderbook(order_book, current_price, trading_pair):
    """Render a CoinDCX-style order book."""
    raw_base_token, raw_quote_token = split_trading_pair(trading_pair)
    base_token = html.escape(raw_base_token)
    quote_token = html.escape(raw_quote_token)

    view = st.segmented_control(
        "Order book view",
        ["All", "Asks", "Bids"],
        default="All",
        key="ob_view_filter",
        label_visibility="collapsed",
    ) or "All"
    num_rows = 11 if view == "All" else ORDER_BOOK_ROWS

    css = """
    <style>
    .ob-wrap { font-family: 'Roboto Mono', monospace; font-size: 12.5px; user-select: none; }
    .ob-header-row {
        display: flex; color: #888; font-size: 11px;
        padding: 4px 0 6px 0; border-bottom: 1px solid #2a2a2a; margin-bottom: 2px;
    }
    .ob-header-row span { flex: 1; text-align: right; }
    .ob-header-row span:first-child { flex: 1.3; text-align: left; }
    .ob-row {
        display: flex; padding: 2px 0; line-height: 1.6;
        position: relative; cursor: pointer; overflow: hidden;
    }
    .ob-row:hover { background: rgba(255,255,255,0.04); }
    .ob-row span { flex: 1; text-align: right; color: #ccc; font-size: 12px; position: relative; z-index: 1; }
    .ob-row span:first-child { flex: 1.3; text-align: left; font-weight: 600; }
    .ob-ask span:first-child { color: #f03b3b; }
    .ob-bid span:first-child { color: #22c55e; }
    .ob-depth-bar {
        position: absolute; right: 0; top: 0; bottom: 0;
        opacity: 0.15; pointer-events: none; z-index: 0;
    }
    .ob-ask .ob-depth-bar { background: #f03b3b; }
    .ob-bid .ob-depth-bar { background: #22c55e; }
    .ob-mid {
        text-align: center; padding: 8px 0; font-size: 18px; font-weight: 700;
        border-top: 1px solid #333; border-bottom: 1px solid #333; margin: 5px 0;
        letter-spacing: 0.5px;
    }
    .ob-mid-sub { font-size: 11px; color: #888; font-weight: 400; margin-top: 1px; }
    </style>
    """

    if not order_book or not order_book.get("bids") or not order_book.get("asks"):
        st.markdown(css, unsafe_allow_html=True)
        st.info("No order book data available")
        return

    bids_raw = order_book.get("bids", [])
    asks_raw = order_book.get("asks", [])

    bids = bids_raw[:num_rows]
    asks_display = asks_raw[:num_rows]
    asks_reversed = list(reversed(asks_display))

    max_ask_vol = max((float(a["amount"]) for a in asks_display), default=1)
    max_bid_vol = max((float(b["amount"]) for b in bids), default=1)
    best_bid = float(bids_raw[0]["price"]) if bids_raw else 0.0
    best_ask = float(asks_raw[0]["price"]) if asks_raw else 0.0
    ob_mid_price = (best_bid + best_ask) / 2 if best_bid and best_ask else (best_bid or best_ask)
    display_price = current_price if current_price and current_price > 0 else ob_mid_price

    previous_price_key = f"previous_orderbook_price:{trading_pair}"
    previous_price = st.session_state.get(previous_price_key)
    direction = "UP" if previous_price is None or display_price >= previous_price else "DOWN"
    st.session_state[previous_price_key] = display_price
    price_color = "#f03b3b" if direction == "DOWN" else "#22c55e"
    spread = best_ask - best_bid if best_bid and best_ask else 0

    precision = price_precision(display_price)

    def fmt_price(v):
        return f"{float(v):,.{precision}f}"

    def fmt_total(v):
        v = float(v)
        return f"{v:,.4f}" if v < 10000 else f"{v:,.2f}"

    def fmt_qty(v):
        v = float(v)
        return f"{v:,.4f}" if v < 1000 else f"{v:,.2f}"

    def ask_row(item):
        price = float(item["price"])
        qty = float(item["amount"])
        total = price * qty
        bar_pct = int((qty / max_ask_vol) * 100)
        return (
            f'<div class="ob-row ob-ask">'
            f'<div class="ob-depth-bar" style="width:{bar_pct}%"></div>'
            f'<span>{fmt_price(price)}</span>'
            f'<span>{fmt_qty(qty)}</span>'
            f'<span>{fmt_total(total)}</span>'
            f'</div>'
        )

    def bid_row(item):
        price = float(item["price"])
        qty = float(item["amount"])
        total = price * qty
        bar_pct = int((qty / max_bid_vol) * 100)
        return (
            f'<div class="ob-row ob-bid">'
            f'<div class="ob-depth-bar" style="width:{bar_pct}%"></div>'
            f'<span>{fmt_price(price)}</span>'
            f'<span>{fmt_qty(qty)}</span>'
            f'<span>{fmt_total(total)}</span>'
            f'</div>'
        )

    header_html = (
        f'<div class="ob-header-row">'
        f'<span>Price ({quote_token})</span>'
        f'<span>Qty ({base_token})</span>'
        f'<span>Total ({quote_token})</span>'
        f'</div>'
    )

    spread_pct = (spread / best_bid * 100) if best_bid else 0
    mid_html = (
        f'<div class="ob-mid" style="color:{price_color}">'
        f'{fmt_price(display_price)} {direction}'
        f'</div>'
        f'<div class="ob-mid-sub">'
        f'Spread: {fmt_price(spread)} ({spread_pct:.4f}%)'
        f'</div>'
    )

    if view == "All":
        rows_html = "".join(ask_row(a) for a in asks_reversed) + mid_html + "".join(bid_row(b) for b in bids)
    elif view == "Asks":
        rows_html = mid_html + "".join(ask_row(a) for a in asks_display)
    else:
        rows_html = "".join(bid_row(b) for b in bids) + mid_html

    full_html = css + f'<div class="ob-wrap">{header_html}{rows_html}</div>'
    st.markdown(full_html, unsafe_allow_html=True)


def render_orderbook_section(connector, trading_pair):
    order_book, current_price = get_market_snapshot(connector, trading_pair)
    render_coindcx_orderbook(order_book, current_price, trading_pair)


def render_trade_panel(connector, trading_pair, current_price):
    """Render the Execute Trade panel."""
    base_token, quote_token = split_trading_pair(trading_pair)

    if not (st.session_state.selected_account and st.session_state.selected_connector):
        st.warning("Please select an account and exchange to execute trades")
        return

    # Order type selection
    order_type = st.selectbox(
        "Order Type",
        ["market", "limit"],
        key="trade_order_type"
    )

    # Side selection
    side = st.selectbox(
        "Side",
        ["buy", "sell"],
        key="trade_side"
    )

    # Position mode selection
    position_action = st.selectbox(
        "Position Mode",
        ["OPEN", "CLOSE"],
        index=0,
        key="trade_position_action",
        help="OPEN creates new positions, CLOSE reduces existing positions"
    )

    # Amount input
    amount = st.number_input(
        "Amount",
        min_value=0.0,
        value=0.001,
        format="%.6f",
        key="trade_amount"
    )

    # Base/Quote toggle switch
    is_quote = st.toggle(
        f"Amount in {quote_token}",
        value=False,
        help=f"Toggle to enter amount in {quote_token} instead of {base_token}",
        key="trade_is_quote"
    )

    # Show conversion line
    if current_price > 0 and amount > 0:
        if is_quote:
            base_equivalent = amount / current_price
            st.caption(f"≈ {base_equivalent:.6f} {base_token}")
        else:
            quote_equivalent = amount * current_price
            st.caption(f"≈ {quote_equivalent:.2f} {quote_token}")

    # Price input for limit orders
    price = None
    if order_type == "limit":
        price_market = (connector, trading_pair)
        if (st.session_state.last_order_type != order_type or
                st.session_state.get("trade_price_market") != price_market or
                not st.session_state.trade_price_set_by_user):
            st.session_state.trade_price = float(current_price) if current_price > 0 else 0.0
            st.session_state.trade_price_set_by_user = False
            st.session_state.trade_price_market = price_market

        st.session_state.last_order_type = order_type

        precision = price_precision(current_price or st.session_state.trade_price)
        price = st.number_input(
            "Price",
            min_value=0.0,
            step=10 ** -precision,
            format=f"%.{precision}f",
            key="trade_price",
            on_change=lambda: setattr(st.session_state, 'trade_price_set_by_user', True)
        )

        display_rate = quote_rate(trading_pair)
        if price > 0 and display_rate != 1.0:
            st.caption(f"≈ {CURRENCY}{price * display_rate:,.2f}")

        if price > 0 and amount > 0:
            if is_quote:
                st.caption(f"At limit price: ≈ {amount / price:.6f} {base_token}")
            else:
                st.caption(f"At limit price: ≈ {amount * price:.2f} {quote_token}")
    else:
        st.session_state.last_order_type = order_type

    st.write("")
    clicked_side = side.upper()
    place_clicked = st.button(
        f"{clicked_side} {base_token}",
        type="primary",
        use_container_width=True,
        key="place_order_btn"
    )

    if place_clicked:
        conversion_price = price if order_type == "limit" and price else current_price
        if amount <= 0:
            st.error("Please enter a valid amount")
        elif order_type == "limit" and not price:
            st.error("Please enter a limit price")
        elif is_quote and conversion_price <= 0:
            st.error(
                f"Can't convert {quote_token} to {base_token}: no price is available for {trading_pair}. "
                f"Enter the amount in {base_token} or try again."
            )
        else:
            final_amount = amount
            if is_quote:
                final_amount = amount / conversion_price
                st.success(f"Converting {amount} {quote_token} → {final_amount:.6f} {base_token}")

            order_data = {
                "account_name": st.session_state.selected_account,
                "connector_name": st.session_state.selected_connector,
                "trading_pair": st.session_state.selected_market["trading_pair"],
                "order_type": order_type.upper(),
                "trade_type": clicked_side,
                "amount": final_amount,
                "position_action": position_action
            }
            if order_type == "limit" and price:
                order_data["price"] = price

            with st.spinner("Placing order..."):
                place_order(order_data)

    st.write("")
    st.info(f"🎯 {st.session_state.selected_connector}\n{st.session_state.selected_market['trading_pair']}")


def show_trading_data():
    connector = st.session_state.selected_market.get("connector")
    trading_pair = st.session_state.selected_market.get("trading_pair")

    if not connector or not trading_pair:
        return  # the market header already asks for an account and pair

    st.divider()

    _, current_price = get_market_snapshot(connector, trading_pair)

    ob_col, trade_col = st.columns([1, 1])

    with ob_col:
        ob_title_col, chart_btn_col = st.columns([3, 1], vertical_alignment="bottom")
        with ob_title_col:
            st.subheader("📊 Order Book")
        with chart_btn_col:
            if st.button("📈 Price Chart", use_container_width=True, key="open_price_chart"):
                show_price_chart_dialog(backend_api_client, connector, trading_pair,
                                        account_name=st.session_state.selected_account)
        st.fragment(render_orderbook_section, run_every=MARKET_RUN_EVERY)(connector, trading_pair)

    with trade_col:
        st.subheader("💸 Execute Trade")
        render_trade_panel(connector, trading_pair, current_price)

    # Data tables section
    st.divider()

    # Get positions and orders
    positions = get_positions(st.session_state.selected_account)
    orders = get_active_orders(st.session_state.selected_account)

    # Display in tabs - Balances first
    tab1, tab2, tab3, tab4 = st.tabs(["💰 Balances", "📊 Positions", "📋 Active Orders", "📜 Order History"])

    with tab1:
        render_balances_table()
    with tab2:
        render_positions_table(positions)
    with tab3:
        render_orders_table(orders)
    with tab4:
        render_order_history_table()


def _parse_mixed_timestamp(value):
    if value is None or value == "":
        return pd.NaT
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1_000_000_000_000 else value
        return pd.to_datetime(seconds, unit="s", utc=True, errors="coerce")
    return pd.to_datetime(value, utc=True, errors="coerce")


def render_order_history_table():
    """Render order history with a freely configurable date filter (local time)."""
    st.subheader("📜 Order History")

    local_tz = datetime.datetime.now().astimezone().tzinfo
    today = datetime.datetime.now(local_tz).date()
    week_ago = today - datetime.timedelta(days=7)
    picker_min = today - datetime.timedelta(days=730)
    picker_max = today

    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        start_date = st.date_input(
            "From",
            value=week_ago,
            min_value=picker_min,
            max_value=picker_max,
            key="order_history_start_date",
        )
    with filter_col2:
        end_date = st.date_input(
            "To",
            value=today,
            min_value=picker_min,
            max_value=picker_max,
            key="order_history_end_date",
        )
    if start_date > end_date:
        st.warning("'From' date is after 'To' date - showing no results.")
        return

    order_history = get_order_history(start_date=start_date, end_date=end_date, tz=local_tz)
    if not order_history:
        st.info("No orders found for the selected date range.")
        return

    df = pd.DataFrame(order_history)
    if df.empty:
        st.info("No orders found for the selected date range.")
        return

    time_columns = [col for col in ("created_at", "updated_at", "timestamp") if col in df.columns]
    for col in time_columns:
        df[col] = df[col].apply(_parse_mixed_timestamp)
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.tz_convert(local_tz)

    date_col = "created_at" if "created_at" in time_columns else ("timestamp" if "timestamp" in time_columns else None)
    if date_col:
        df = df.sort_values(date_col, ascending=False, na_position="last")

    if df.empty:
        st.info("No orders found for the selected date range.")
        return

    for col in time_columns:
        df[col] = df[col].dt.strftime("%Y-%m-%d %H:%M:%S").where(df[col].notna(), "—")

    with filter_col3:
        st.markdown("<div style='height:1.8rem'></div>", unsafe_allow_html=True)
        st.download_button(
            "⬇️ Download CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name=f"order_history_{start_date}_{end_date}.csv",
            mime="text/csv",
            key="order_history_csv_download",
        )

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "price": st.column_config.NumberColumn(
                "Price",
                format=f"{CURRENCY}%.4f"
            ),
            "amount": st.column_config.NumberColumn(
                "Amount",
                format="%.6f"
            ),
        }
    )


def get_balances():
    """Get account balances."""
    try:
        if not st.session_state.selected_account:
            return []

        portfolio_state = backend_api_client.portfolio.get_state(
            account_names=[st.session_state.selected_account]
        )

        balances = []
        if st.session_state.selected_account in portfolio_state:
            for exchange, tokens in portfolio_state[st.session_state.selected_account].items():
                for token_info in tokens:
                    balances.append({
                        "exchange": exchange,
                        "token": token_info["token"],
                        "total": token_info["units"],
                        "available": token_info["available_units"],
                        "price": token_info["price"],
                        "value": token_info["value"]
                    })
        return balances
    except Exception as e:
        st.error(f"Failed to fetch balances: {e}")
        return []


def render_balances_table():
    """Render balances table."""
    balances = get_balances()

    if not balances:
        st.info("No balances found.")
        return

    df = pd.DataFrame(balances)
    if df.empty:
        st.info("No balances found.")
        return

    st.subheader(f"💰 Account Balances - {st.session_state.selected_account}")

    df = convert_price_columns(df, ["price", "value"])

    total_value = df['value'].sum()
    st.metric("Total Portfolio Value", f"{CURRENCY}{total_value:,.2f}")

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "total": st.column_config.NumberColumn(
                "Total Balance",
                format="%.6f"
            ),
            "available": st.column_config.NumberColumn(
                "Available",
                format="%.6f"
            ),
            "price": st.column_config.NumberColumn(
                "Price",
                format=f"{CURRENCY}%.4f"
            ),
            "value": st.column_config.NumberColumn(
                f"Value ({CURRENCY})",
                format=f"{CURRENCY}%.2f"
            )
        }
    )


# Display trading data
show_trading_data()
