import html
import time

import nest_asyncio
import pandas as pd
import streamlit as st

from frontend.st_utils import get_backend_api_client, initialize_st_page

# Enable nested async
nest_asyncio.apply()

initialize_st_page(
    layout="wide",
    show_readme=False
)

# Initialize backend client
backend_api_client = get_backend_api_client()

# Initialize session state
if "selected_account" not in st.session_state:
    st.session_state.selected_account = None
if "selected_connector" not in st.session_state:
    st.session_state.selected_connector = None
if "selected_market" not in st.session_state:
    st.session_state.selected_market = {"connector": "binance_perpetual", "trading_pair": "BTC-USDT"}
if "auto_refresh_enabled" not in st.session_state:
    st.session_state.auto_refresh_enabled = False  # Start with manual refresh
if "last_api_request" not in st.session_state:
    st.session_state.last_api_request = 0  # Track last API request time
if "last_refresh_time" not in st.session_state:
    st.session_state.last_refresh_time = 0  # Track last refresh time

# Trading form session state
if "trade_custom_price" not in st.session_state:
    st.session_state.trade_custom_price = None  # User's custom price input
if "trade_price_set_by_user" not in st.session_state:
    st.session_state.trade_price_set_by_user = False  # Track if user set custom price
if "last_order_type" not in st.session_state:
    st.session_state.last_order_type = "market"  # Track order type changes

# Set refresh interval for real-time updates
REFRESH_INTERVAL = 30  # seconds
ORDER_BOOK_ROWS = 22


def split_trading_pair(trading_pair):
    """Split a trading pair into base and quote without breaking dated pairs."""
    base_token, separator, quote_token = trading_pair.partition("-")
    return base_token, quote_token if separator else ""


def get_price_map(connector, trading_pair):
    """Get the latest price response normalized to a trading_pair -> price mapping."""
    try:
        price_response = backend_api_client.market_data.get_prices(
            connector_name=connector,
            trading_pairs=[trading_pair]
        )
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
        st.warning(f"Could not fetch prices: {e}")
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
            # Handle the actual API response format
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
        # Handle both response formats
        if isinstance(response, list):
            return response
        elif isinstance(response, dict):
            # Check for different response formats
            if response.get("status") == "success":
                return response.get("data", [])
            elif "data" in response:
                # Handle response format like {"data": [...], "pagination": {...}}
                return response.get("data", [])
        return []
    except Exception as e:
        st.error(f"Failed to fetch active orders: {e}")
        return []


def get_order_history(account_name=None):
    """Get recent order history."""
    try:
        # Try to get orders instead of order_history since that method doesn't exist
        kwargs = {"limit": 50}
        if account_name:
            kwargs["account_names"] = [account_name]
        response = backend_api_client.trading.search_orders(**kwargs)
        # Handle both response formats
        if isinstance(response, list):
            return response
        elif isinstance(response, dict):
            # Check for different response formats
            if response.get("status") == "success":
                return response.get("data", [])
            elif "data" in response:
                # Handle response format like {"data": [...], "pagination": {...}}
                return response.get("data", [])
        return []
    except Exception:
        # If get_orders doesn't exist either, just return empty list without warning
        return []


def get_order_book(connector, trading_pair, depth=10):
    """Get order book data for the selected trading pair."""
    try:
        response = backend_api_client.market_data.get_order_book(
            connector_name=connector,
            trading_pair=trading_pair,
            depth=depth
        )

        # Handle both response formats
        if isinstance(response, dict):
            if "status" in response and response.get("status") == "success":
                return response.get("data", {})
            elif "bids" in response and "asks" in response:
                return response
        return {}
    except Exception as e:
        st.warning(f"Could not fetch order book: {e}")
        return {}


def get_funding_rate(connector, trading_pair):
    """Get funding rate for perpetual contracts."""
    try:
        # Only try to get funding rate for perpetual connectors
        if "perpetual" in connector.lower():
            response = backend_api_client.market_data.get_funding_info(
                connector_name=connector,
                trading_pair=trading_pair
            )
            # Handle both response formats
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

    # Convert to DataFrame for better display
    df = pd.DataFrame(positions_data)
    if df.empty:
        st.info("No open positions found.")
        return

    # Calculate original value (amount * entry_price)
    if 'amount' in df.columns and 'entry_price' in df.columns:
        df['original_value'] = df['amount'] * df['entry_price']

    st.subheader("🎯 Open Positions")

    # Calculate and display summary metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        total_unrealized_pnl = df['unrealized_pnl'].sum() if 'unrealized_pnl' in df.columns else 0
        st.metric(
            "Total Unrealized PnL",
            f"${total_unrealized_pnl:,.2f}",
            delta=None,
            delta_color="normal" if total_unrealized_pnl >= 0 else "inverse"
        )
    with col2:
        total_original_value = abs(df['original_value']).sum() if 'original_value' in df.columns else 0
        st.metric(
            "Total Position Amount",
            f"${abs(total_original_value):,.2f}"
        )
    # Separate long and short positions for hedging analysis
    long_positions = df[df['amount'] > 0] if 'amount' in df.columns else pd.DataFrame()
    short_positions = df[df['amount'] < 0] if 'amount' in df.columns else pd.DataFrame()
    with col3:
        long_value = (
            long_positions['original_value'].sum()
            if not long_positions.empty and 'original_value' in long_positions.columns
            else 0
        )
        st.metric("Long Exposure", f"${abs(long_value):,.2f}", help="Total value of long positions")

    with col4:
        short_value = (
            short_positions['original_value'].sum()
            if not short_positions.empty and 'original_value' in short_positions.columns
            else 0
        )
        st.metric(
            "Short Exposure", f"${abs(short_value):,.2f}", help="Total value of short positions")

    # Calculate hedge ratio if we have both long and short positions
    if long_value != 0 and short_value != 0:
        hedge_ratio = min(abs(short_value), abs(long_value)) / max(abs(short_value), abs(long_value)) * 100
        st.info(f"📊 **Hedge Ratio**: {hedge_ratio:.1f}% (Higher = More Hedged)")
    elif long_value > 0 and short_value == 0:
        st.warning("⚠️ **Portfolio is fully LONG** - No short hedging")
    elif short_value > 0 and long_value == 0:
        st.warning("⚠️ **Portfolio is fully SHORT** - No long hedging")

    # Display positions table with enhanced formatting
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
                format="$%.4f"
            ),
            "original_value": st.column_config.NumberColumn(
                "Original Value",
                format="$%.2f",
                help="Amount × Entry Price"
            ),
            "mark_price": st.column_config.NumberColumn(
                "Mark Price",
                format="$%.4f"
            ),
            "unrealized_pnl": st.column_config.NumberColumn(
                "Unrealized PnL",
                format="$%.2f"
            )
        }
    )

    # Show separate long/short breakdown if there are both types
    if not long_positions.empty and not short_positions.empty:
        st.divider()

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("🟢 Long Positions")
            if not long_positions.empty:
                long_pnl = long_positions['unrealized_pnl'].sum() if 'unrealized_pnl' in long_positions.columns else 0
                st.caption(f"PnL: ${long_pnl:,.2f}")
                st.dataframe(
                    long_positions,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "amount": st.column_config.NumberColumn("Amount", format="%.6f"),
                        "entry_price": st.column_config.NumberColumn("Entry Price", format="$%.4f"),
                        "unrealized_pnl": st.column_config.NumberColumn("PnL", format="$%.2f")
                    }
                )

        with col2:
            st.subheader("🔴 Short Positions")
            if not short_positions.empty:
                short_pnl = short_positions['unrealized_pnl'].sum() if 'unrealized_pnl' in short_positions.columns else 0
                st.caption(f"PnL: ${short_pnl:,.2f}")
                st.dataframe(
                    short_positions,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "amount": st.column_config.NumberColumn("Amount", format="%.6f"),
                        "entry_price": st.column_config.NumberColumn("Entry Price", format="$%.4f"),
                        "unrealized_pnl": st.column_config.NumberColumn("PnL", format="$%.2f")
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

    # Convert to DataFrame
    df = pd.DataFrame(orders_data)
    if df.empty:
        st.info("No active orders found.")
        return

    st.subheader("📋 Active Orders")

    # Add cancel column to dataframe
    df_with_cancel = df.copy()
    df_with_cancel["cancel"] = False

    # Create column configurations based on what's available in the data
    column_config = {
        "cancel": st.column_config.CheckboxColumn(
            "Cancel",
            help="Select orders to cancel",
            default=False,
        ),
        "price": st.column_config.NumberColumn(
            "Price",
            format="$%.4f"
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

    # Add cancel button functionality
    edited_df = st.data_editor(
        df_with_cancel,
        column_config=column_config,
        disabled=[col for col in df_with_cancel.columns if col != "cancel"],
        hide_index=True,
        use_container_width=True,
        key="orders_editor"
    )

    # Handle order cancellation
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

with pair_col:
    trading_pair = st.text_input(
        "💱 Trading Pair",
        value="BTC-USDT",
        key="trading_pair_input"
    )

if connector and trading_pair:
    st.session_state.selected_market = {"connector": connector, "trading_pair": trading_pair}

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
        st.session_state.last_refresh_time = time.time()
        st.rerun()

if st.session_state.selected_market.get("connector") and st.session_state.selected_market.get("trading_pair"):
    connector = st.session_state.selected_market["connector"]
    trading_pair = st.session_state.selected_market["trading_pair"]
    fetch_start = time.time()
    order_book = get_order_book(connector, trading_pair, depth=ORDER_BOOK_ROWS)
    prices = get_price_map(connector, trading_pair)
    current_price = get_current_price(prices, trading_pair, order_book)
    st.session_state["last_fetch_time"] = (time.time() - fetch_start) * 1000
    st.session_state["market_snapshot"] = {
        "connector": connector,
        "trading_pair": trading_pair,
        "order_book": order_book,
        "prices": prices,
        "current_price": current_price,
    }

    if "last_fetch_time" in st.session_state:
        st.caption(f"⚡ Fetch: {st.session_state['last_fetch_time']:.0f}ms")

    bid_price = 0
    ask_price = 0
    if order_book and "bids" in order_book and "asks" in order_book:
        bid_price = float(order_book["bids"][0]["price"]) if order_book["bids"] else 0
        ask_price = float(order_book["asks"][0]["price"]) if order_book["asks"] else 0

    bid_col, ask_col, spread_col, depth_pct_col, buy_depth_col, sell_depth_col = st.columns(6)

    with bid_col:
        st.metric("📈 Bid Price", f"${bid_price:.4f}" if bid_price else "N/A")

    with ask_col:
        st.metric("📉 Ask Price", f"${ask_price:.4f}" if ask_price else "N/A")

    with spread_col:
        if bid_price > 0 and ask_price > 0:
            spread = ask_price - bid_price
            spread_pct = (spread / bid_price) * 100
            st.metric("↔️ Spread", f"${spread:.4f}", delta=f"{spread_pct:.4f}%")
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
                buy_response = backend_api_client.market_data.get_quote_volume_for_price(
                    connector_name=connector,
                    trading_pair=trading_pair,
                    price=sell_price_depth,
                    is_buy=True
                )
                buy_vol = 0
                if isinstance(buy_response, dict) and "result_quote_volume" in buy_response:
                    buy_vol = buy_response["result_quote_volume"]
                    import math
                    if buy_vol is None or (isinstance(buy_vol, float) and math.isnan(buy_vol)) or str(buy_vol).lower() == 'nan':
                        buy_vol = 0
                st.metric(
                    "📊 Buy Depth",
                    f"${float(buy_vol):,.0f}" if buy_vol != 0 else "N/A",
                    help="Volume available when buying (hitting asks)"
                )
            except Exception:
                total_ask_volume = sum(float(ask["amount"]) * float(ask["price"]) for ask in order_book["asks"])
                st.metric("📊 Buy Depth", f"${total_ask_volume:,.0f}", help="Total ask volume (for buying)")
        else:
            st.metric("📊 Buy Depth", "N/A")

    with sell_depth_col:
        if order_book and "bids" in order_book and "asks" in order_book and bid_price > 0 and ask_price > 0:
            depth_factor = depth_percentage / 100
            buy_price_depth = bid_price * (1 - depth_factor)
            try:
                sell_response = backend_api_client.market_data.get_quote_volume_for_price(
                    connector_name=connector,
                    trading_pair=trading_pair,
                    price=buy_price_depth,
                    is_buy=False
                )
                sell_vol = 0
                if isinstance(sell_response, dict) and "result_quote_volume" in sell_response:
                    sell_vol = sell_response["result_quote_volume"]
                    import math
                    if (
                        sell_vol is None
                        or (isinstance(sell_vol, float) and math.isnan(sell_vol))
                        or str(sell_vol).lower() == "nan"
                    ):
                        sell_vol = 0
                st.metric(
                    "📊 Sell Depth",
                    f"${float(sell_vol):,.0f}" if sell_vol != 0 else "N/A",
                    help="Volume available when selling (hitting bids)"
                )
            except Exception:
                total_bid_volume = sum(float(bid["amount"]) * float(bid["price"]) for bid in order_book["bids"])
                st.metric("📊 Sell Depth", f"${total_bid_volume:,.0f}", help="Total bid volume (for selling)")
        else:
            st.metric("📊 Sell Depth", "N/A")
else:
    st.info("Select account and pair to view extended market data")


def render_coindcx_orderbook(order_book, current_price, trading_pair):
    """Render a CoinDCX-style order book."""
    raw_base_token, raw_quote_token = split_trading_pair(trading_pair)
    base_token = html.escape(raw_base_token)
    quote_token = html.escape(raw_quote_token)

    view = st.session_state.get("ob_view_filter", "All")
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

    def fmt_price(v):
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
            f'<span>{fmt_price(total)}</span>'
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
            f'<span>{fmt_price(total)}</span>'
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
        if (st.session_state.last_order_type != order_type or
                not st.session_state.trade_price_set_by_user or
                st.session_state.trade_custom_price is None):
            st.session_state.trade_custom_price = current_price if current_price > 0 else 0.0
            st.session_state.trade_price_set_by_user = False

        st.session_state.last_order_type = order_type

        price = st.number_input(
            "Price",
            min_value=0.0,
            value=st.session_state.trade_custom_price,
            format="%.4f",
            key="trade_price",
            on_change=lambda: setattr(st.session_state, 'trade_price_set_by_user', True)
        )

        if price != st.session_state.trade_custom_price:
            st.session_state.trade_custom_price = price
            st.session_state.trade_price_set_by_user = True

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
        if amount > 0:
            final_amount = amount
            conversion_price = price if order_type == "limit" and price else current_price
            if is_quote and conversion_price > 0:
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
        else:
            st.error("Please enter a valid amount")

    st.write("")
    st.info(f"🎯 {st.session_state.selected_connector}\n{st.session_state.selected_market['trading_pair']}")


def show_trading_data():
    connector = st.session_state.selected_market.get("connector")
    trading_pair = st.session_state.selected_market.get("trading_pair")

    if not connector or not trading_pair:
        st.warning("Please select an account and trading pair")
        return

    st.divider()

    snapshot = st.session_state.get("market_snapshot", {})
    if snapshot.get("connector") == connector and snapshot.get("trading_pair") == trading_pair:
        order_book = snapshot.get("order_book", {})
        current_price = snapshot.get("current_price", 0.0)
    else:
        order_book = get_order_book(connector, trading_pair, depth=ORDER_BOOK_ROWS)
        prices = get_price_map(connector, trading_pair)
        current_price = get_current_price(prices, trading_pair, order_book)

    ob_col, trade_col = st.columns([1, 1])

    with ob_col:
        st.subheader("📊 Order Book")
        render_coindcx_orderbook(order_book, current_price, trading_pair)

    with trade_col:
        st.subheader("💸 Execute Trade")
        render_trade_panel(connector, trading_pair, current_price)

    # Data tables section
    st.divider()

    # Get positions, orders, and history filtered by selected account
    selected_account = st.session_state.selected_account
    positions = get_positions(account_name=selected_account)
    orders = get_active_orders(account_name=selected_account)
    order_history = get_order_history(account_name=selected_account)

    # Display in tabs - Balances first
    tab1, tab2, tab3, tab4 = st.tabs(["💰 Balances", "📊 Positions", "📋 Active Orders", "📜 Order History"])

    with tab1:
        render_balances_table()
    with tab2:
        render_positions_table(positions)
    with tab3:
        render_orders_table(orders)
    with tab4:
        render_order_history_table(order_history)


def render_order_history_table(order_history):
    """Render order history table."""
    if not order_history:
        st.info("No order history found.")
        return

    # Convert to DataFrame
    df = pd.DataFrame(order_history)
    if df.empty:
        st.info("No order history found.")
        return

    st.subheader("📜 Order History")
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "price": st.column_config.NumberColumn(
                "Price",
                format="$%.4f"
            ),
            "amount": st.column_config.NumberColumn(
                "Amount",
                format="%.6f"
            ),
            "timestamp": st.column_config.DatetimeColumn(
                "Time",
                format="DD/MM/YYYY HH:mm:ss"
            )
        }
    )


def get_balances():
    """Get account balances."""
    try:
        if not st.session_state.selected_account:
            return []

        # Get portfolio state for the selected account
        portfolio_state = backend_api_client.portfolio.get_state(
            account_names=[st.session_state.selected_account]
        )

        # Extract balances
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

    # Convert to DataFrame
    df = pd.DataFrame(balances)
    if df.empty:
        st.info("No balances found.")
        return

    st.subheader(f"💰 Account Balances - {st.session_state.selected_account}")

    # Calculate total value
    total_value = df['value'].sum()
    st.metric("Total Portfolio Value", f"${total_value:,.2f}")

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
                format="$%.4f"
            ),
            "value": st.column_config.NumberColumn(
                "Value (USD)",
                format="$%.2f"
            )
        }
    )


# Auto-refresh logic - only if user is not actively trading
if st.session_state.auto_refresh_enabled and not st.session_state.trade_price_set_by_user:
    # Check if it's time to refresh
    current_time = time.time()
    time_since_last_refresh = current_time - st.session_state.last_refresh_time

    if time_since_last_refresh >= REFRESH_INTERVAL:
        # Update last refresh time and rerun
        st.session_state.last_refresh_time = current_time
        time.sleep(0.1)  # Small delay to prevent rapid refreshes
        st.rerun()

# Display trading data
show_trading_data()