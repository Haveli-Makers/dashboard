import streamlit as st

from frontend.st_utils import get_backend_api_client, initialize_st_page
from frontend.visualization.orderbook_backtest import create_equity_figure, create_strategy_report_table

initialize_st_page(title="Orderbook Backtest", icon="📒")
backend_api_client = get_backend_api_client()

st.text("Backtest strategies on recorded orderbook and public trades data.")

# ── Strategy selection ──────────────────────────────────────────────────
strategies = backend_api_client.backtesting.list_orderbook_strategies()
if not strategies:
    st.warning("No orderbook strategies available. Make sure the API server has backtest_strategies loaded.")
    st.stop()

strategy_names = [s["name"] for s in strategies]
strategy_map = {s["name"]: s for s in strategies}

c1, c2 = st.columns([0.3, 0.7])
with c1:
    selected_strategy = st.selectbox(
        "Strategy", strategy_names,
        format_func=lambda n: f"{n} — {strategy_map[n]['description']}" if strategy_map[n].get("description") else n,
    )

# ── Common parameters ───────────────────────────────────────────────────
st.write("### Market Data")
cc1, cc2, cc3, cc4 = st.columns(4)
with cc1:
    connector = st.text_input("Connector", value="coindcx")
with cc2:
    pair = st.text_input("Pair", value="BTC-USDT")
with cc3:
    start_date = st.date_input("Start Date")
with cc4:
    end_date = st.date_input("End Date", help="Inclusive. Leave same as start for a single day.")

st.write("### Engine Settings")
ec1, ec2, ec3, ec4 = st.columns(4)
with ec1:
    maker_fee = st.number_input("Maker Fee (%)", min_value=0.0, value=0.1, step=0.01, format="%.3f")
with ec2:
    taker_fee = st.number_input("Taker Fee (%)", min_value=0.0, value=0.1, step=0.01, format="%.3f")
with ec3:
    latency_ms = st.number_input("Latency (ms)", min_value=0.0, value=100.0, step=10.0)
with ec4:
    fill_at_touch = st.checkbox("Fill at touch", value=False,
                                help="Optimistic: fill resting orders when a trade prints AT the price")


# ── Auto-generated strategy parameters from config schema ──────────────

def _render_param(key: str, prop: dict, cols_per_row: int = 4):
    """Render a Streamlit input widget from a JSON schema property."""
    title = key.replace("_", " ").title()
    description = prop.get("description", "")
    default = prop.get("default")
    param_type = prop.get("type", "number")

    if key in ("strategy_name", "tick_size"):
        return None

    if param_type == "boolean":
        return st.checkbox(title, value=bool(default) if default is not None else False, help=description)
    elif param_type == "string":
        if "enum" in prop:
            return st.selectbox(title, options=prop["enum"],
                                index=prop["enum"].index(default) if default in prop.get("enum", []) else 0,
                                help=description)
        return st.text_input(title, value=default or "", help=description)
    elif param_type == "integer":
        return int(st.number_input(title, value=int(default) if default is not None else 0,
                                   step=1, help=description))
    else:
        if default is None:
            val = st.number_input(title, value=0.0, step=0.001, format="%.6f",
                                  help=f"{description} (0 = disabled/None)")
            return val if val != 0.0 else None
        return st.number_input(title, value=float(default), step=0.001, format="%.6f", help=description)


st.write("### Strategy Parameters")
strategy_args = {}

params = strategy_map[selected_strategy].get("parameters", {})
if params:
    param_keys = [k for k in params if k not in ("strategy_name", "tick_size")]
    cols = st.columns(min(4, max(1, len(param_keys))))
    for i, key in enumerate(param_keys):
        with cols[i % len(cols)]:
            val = _render_param(key, params[key])
            if val is not None:
                strategy_args[key] = val

# ── Tick size (common to all strategies) ────────────────────────────────
tick_size = st.number_input("Tick Size", min_value=0.0001, value=0.01, step=0.01, format="%.4f")
strategy_args["tick_size"] = tick_size

# ── Run ─────────────────────────────────────────────────────────────────
run_bt = st.button("Run Backtest", type="primary")

if run_bt:
    start_str = start_date.isoformat()
    end_str = end_date.isoformat() if end_date != start_date else None

    with st.spinner("Running orderbook backtest..."):
        try:
            results = backend_api_client.backtesting.run_orderbook_backtest(
                strategy=selected_strategy,
                connector=connector,
                pair=pair,
                start=start_str,
                end=end_str,
                maker_fee=maker_fee / 100,
                taker_fee=taker_fee / 100,
                latency_ms=latency_ms,
                fill_at_touch=fill_at_touch,
                strategy_args=strategy_args,
            )
        except Exception as e:
            st.error(f"Backtest failed: {e}")
            st.stop()

    if "error" in results:
        st.error(f"Backtest error: {results['error']}")
        st.stop()

    # ── Summary metrics ─────────────────────────────────────────────────
    st.write("### Results")
    m1, m2, m3, m4 = st.columns(4)
    equity = results.get("equity", [])
    fills = results.get("fills", [])
    final_pnl = equity[-1]["pnl"] if equity else 0
    m1.metric("Final PnL (Quote)", f"{final_pnl:+,.4f}")
    m2.metric("Total Fills", len(fills))
    m3.metric("Total Fees", f"{results.get('fees', 0):,.4f}")
    m4.metric("Final Position", f"{results.get('final_position', 0):+.8g}")

    # ── Engine summary ──────────────────────────────────────────────────
    with st.expander("Engine Summary", expanded=True):
        st.code(results.get("summary", ""), language=None)

    # ── Strategy summary ────────────────────────────────────────────────
    strategy_summary = results.get("strategy_summary", "")
    if strategy_summary:
        with st.expander("Strategy Summary", expanded=True):
            st.code(strategy_summary, language=None)

    # ── Equity & fills chart ────────────────────────────────────────────
    fig = create_equity_figure(equity, fills)
    if fig:
        st.plotly_chart(fig, use_container_width=True)

    # ── Strategy report table ───────────────────────────────────────────
    report_df = create_strategy_report_table(results.get("strategy_report", []), selected_strategy)
    if report_df is not None and not report_df.empty:
        st.write("### Strategy Report")
        st.dataframe(report_df, use_container_width=True)

    # ── Fills table ─────────────────────────────────────────────────────
    if fills:
        with st.expander("Fills Table"):
            import pandas as pd
            fills_df = pd.DataFrame(fills)
            if "ts" in fills_df.columns:
                fills_df["time"] = pd.to_datetime(fills_df["ts"], unit="s", utc=True)
                fills_df = fills_df.drop(columns=["ts"])
            st.dataframe(fills_df, use_container_width=True)
