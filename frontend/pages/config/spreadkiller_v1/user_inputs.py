import streamlit as st

DEFAULT_CONNECTOR = "mexc"
DEFAULT_TRADING_PAIR = "ETH-USDT"
DEFAULT_AMOUNT_QUOTE = "100"
DEFAULT_MAX_SPREAD = "1.5"
DEFAULT_MIN_SPREAD = "1.1"


def user_inputs() -> dict:
    default_config = st.session_state.get("default_config", {})

    connector_name = default_config.get("connector_name", DEFAULT_CONNECTOR)
    trading_pair = default_config.get("trading_pair", DEFAULT_TRADING_PAIR)
    amount_quote = default_config.get("amount_quote", DEFAULT_AMOUNT_QUOTE)
    max_spread = default_config.get("max_spread", DEFAULT_MAX_SPREAD)
    min_spread = default_config.get("min_spread", DEFAULT_MIN_SPREAD)

    with st.expander("General Settings", expanded=True):
        connector_name = st.text_input("Connector Name", value=connector_name)
        trading_pair = st.text_input("Trading Pair", value=trading_pair)

        amount_quote = st.number_input(
            "Quote Amount",
            min_value=0.0,
            value=float(amount_quote),
            step=1.0,
            help="Total quote amount allocated to the strategy."
        )
        max_spread = st.number_input(
            "Maximum Spread (%)",
            min_value=0.0,
            value=float(max_spread),
            step=0.1,
            help="Upper bound for the spread used by the strategy."
        )
        min_spread = st.number_input(
            "Minimum Spread (%)",
            min_value=0.0,
            value=float(min_spread),
            step=0.1,
            help="Lower bound for the spread used by the strategy."
        )

    if min_spread > max_spread:
        st.warning("Minimum spread is greater than maximum spread. Please adjust the values.")

    return {
        "controller_name": "spreadkiller",
        "controller_type": "havelimakers",
        "connector_name": connector_name.strip(),
        "trading_pair": trading_pair.strip(),
        "amount_quote": amount_quote,
        "max_spread": max_spread,
        "min_spread": min_spread,
    }
