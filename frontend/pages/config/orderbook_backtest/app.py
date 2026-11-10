import json
from datetime import datetime, timedelta

import streamlit as st

from frontend.st_utils import get_backend_api_client, initialize_st_page
from frontend.visualization.orderbook_backtest import create_equity_figure

initialize_st_page(title="Orderbook Backtest", icon="📒")
backend_api_client = get_backend_api_client()


_USE_DEFAULT = object()

_SCALAR_TYPES = ("str", "int", "float", "decimal", "bool", "optional", "none", "list", "dict")


_KNOWN_ENUMS = {
    "positionmode": [("HEDGE", "HEDGE"), ("ONEWAY", "ONEWAY")],
    "pricetype": [
        ("MidPrice", 1), ("BestBid", 2), ("BestAsk", 3),
        ("LastTrade", 4), ("LastOwnTrade", 5), ("InventoryCost", 6), ("Custom", 7),
    ],
    "simplegridentrymode": [
        ("LONG_ONLY", "long_only"), ("SHORT_ONLY", "short_only"), ("BOTH_OCO", "both_oco"),
    ],
    "tradetype": [("BUY", 1), ("SELL", 2)],
    "ordertype": [("LIMIT", 2), ("MARKET", 1), ("LIMIT_MAKER", 3)],
}

_CLOSE_TYPES = {
    1: "TIME_LIMIT", 2: "STOP_LOSS", 3: "TAKE_PROFIT", 4: "EXPIRED", 5: "EARLY_STOP",
    6: "TRAILING_STOP", 7: "INSUFFICIENT_BALANCE", 8: "FAILED", 9: "COMPLETED", 10: "POSITION_HOLD",
}


def _parse_enum_default(default_str):
    if default_str and isinstance(default_str, str) and "." in default_str:
        return default_str.split(".", 1)[1]
    return default_str


def _extract_class_name(ftype: str) -> str:
    import re
    m = re.match(r"<class '([^']+)'>", ftype)
    if m:
        return m.group(1).rsplit(".", 1)[-1]
    return ftype


def _is_nested_model(ftype: str) -> bool:
    """Detect nested Pydantic model fields (e.g. triple_barrier_config).
    """
    import re
    class_name = _extract_class_name(ftype).lower()
    ftype_low = ftype.lower()
    if any(e in class_name for e in _KNOWN_ENUMS):
        return False
    if class_name in ("str", "int", "float", "decimal", "bool"):
        return False
    for token in _SCALAR_TYPES:
        if re.search(rf"\b{token}\b", ftype_low):
            return False
    return True


def _is_structured(ftype: str) -> bool:
    """A dict, or a list of something other than numbers (e.g. the grids of a multi grid)."""
    import re
    if "dict[" in ftype:
        return True
    inner = re.search(r"list\[([^\]]+)\]", ftype)
    return bool(inner) and not re.search(r"\b(int|float|decimal|str)\b", inner.group(1))


def _render_structured_field(label: str, default):
    text = st.text_area(f"{label} (JSON)", value=json.dumps(default) if default not in (None, "") else "")
    if not text.strip():
        return _USE_DEFAULT
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        st.error(f"{label} is not valid JSON: {e}")
        return _USE_DEFAULT


def _type_default(ftype: str):
    if "int" in ftype:
        return 0
    if "float" in ftype or "decimal" in ftype:
        return 0.0
    if "bool" in ftype:
        return False
    return ""


def _render_field(name: str, field_info: dict):
    """Render a Streamlit input widget based on the field's type and default value."""
    default = field_info.get("default")
    if default == "PydanticUndefined":     
        default = None
    ftype = str(field_info.get("type", "str")).lower()
    label = name.replace("_", " ").title()

    if _is_structured(ftype):
        return _render_structured_field(label, default)

    if "list[" in ftype:
        if isinstance(default, list):
            default = ",".join(str(item) for item in default)
        text = st.text_input(label, value=str(default) if default is not None else "",
                             help="Comma separated, e.g. 0.01,0.02")
        return text if text.strip() else _USE_DEFAULT

    if _is_nested_model(ftype):
        st.caption(f"**{label}**: _using controller default (nested config)_")
        return _USE_DEFAULT

    for enum_key, enum_options in _KNOWN_ENUMS.items():
        if enum_key in ftype:
            labels = [opt[0] for opt in enum_options]
            values = [opt[1] for opt in enum_options]
            default_name = _parse_enum_default(str(default)) if default is not None else labels[0]
            try:
                default_idx = labels.index(default_name)
            except ValueError:
                default_idx = 0
            selected_label = st.selectbox(label, labels, index=default_idx)
            return values[labels.index(selected_label)]

    is_optional = "optional" in ftype or "none" in ftype

    if default is None and not is_optional:
        default = _type_default(ftype)

    if is_optional:
        if default is None and not st.checkbox(f"Set {label}", value=False):
            return None
        if "bool" in ftype:
            return st.checkbox(label, value=bool(default) if default is not None else False)
        if "decimal" in ftype or "float" in ftype:
            return st.number_input(label, value=float(default) if default is not None else 0.0,
                                   format="%.6f", step=0.001)
        if "int" in ftype:
            return st.number_input(label, value=int(default) if default is not None else 0, step=1)
        return st.text_input(label, value=str(default) if default is not None else "")

    if ftype == "bool" or isinstance(default, bool):
        return st.checkbox(label, value=bool(default) if default is not None else False)

    if ftype == "int" or (isinstance(default, int) and not isinstance(default, bool)):
        return st.number_input(label, value=int(default) if default is not None else 0, step=1)

    if ftype in ("float", "decimal") or "decimal" in ftype or isinstance(default, float):
        val = float(default) if default is not None else 0.0
        return st.number_input(label, value=val, format="%.6f", step=0.001)

    return st.text_input(label, value=str(default) if default is not None else "")


# ── Page content ───────────────────────────────────────────────────────
st.text("Run any strategy_v2 controller against recorded orderbook and public trades data.")

DURATION_PRESETS = {
    "6 Hours": timedelta(hours=6),
    "12 Hours": timedelta(hours=12),
    "1 Day": timedelta(days=1),
    "3 Days": timedelta(days=3),
    "1 Week": timedelta(weeks=1),
    "2 Weeks": timedelta(weeks=2),
    "1 Month": timedelta(days=30),
    "Custom": None,
}

_HIDDEN_FIELDS = {
    "id", "controller_name", "controller_type", "manual_kill_switch",
    "candles_config", "initial_positions", "type", "connector_name", "trading_pair",
}

_UNSUPPORTED_CONTROLLERS = {
    ("generic", "xemm_multiple_levels"): "quotes one venue and hedges on another",
    ("generic", "arbitrage_controller"): "trades two venues at once",
    ("generic", "stat_arb"): "trades two pairs at once",
    ("generic", "quantum_grid_allocator"): "allocates across several pairs and needs account balances",
    ("directional_trading", "ai_livestream"): "takes its signals from a live message stream",
}

# ── Controller selection ──────────────────────────────────────────────
st.write("### Controller Config")

config_mode = st.radio(
    "Config Source",
    ["Select Controller", "Upload YAML", "Paste JSON/Dict"],
    horizontal=True,
)

controller_config = None

if config_mode == "Select Controller":
    try:
        all_controllers = backend_api_client.controllers.list_controllers()
    except Exception as e:
        st.error(f"Failed to fetch controllers: {e}")
        st.stop()

    controller_options = []
    unavailable = []
    for ctype, names in sorted(all_controllers.items()):
        for name in sorted(names):
            if (ctype, name) in _UNSUPPORTED_CONTROLLERS:
                unavailable.append(f"`{name}` ({_UNSUPPORTED_CONTROLLERS[(ctype, name)]})")
            else:
                controller_options.append((ctype, name))

    if not controller_options:
        st.warning("No controllers found on the backend.")
        st.stop()

    if unavailable:
        st.caption("Not listed, because a replay serves one market: " + ", ".join(unavailable) + ".")

    display_labels = [f"{ctype} / {name}" for ctype, name in controller_options]
    selected_idx = st.selectbox(
        "Controller",
        range(len(display_labels)),
        format_func=lambda i: display_labels[i],
        help="Select a strategy_v2 controller to backtest",
    )
    selected_type, selected_name = controller_options[selected_idx]

    # Fetch config template
    try:
        template = backend_api_client.controllers.get_controller_config_template(
            selected_type, selected_name
        )
    except Exception as e:
        st.error(f"Failed to fetch config template: {e}")
        st.stop()

    # Render auto-generated form from template fields
    form_values = {}
    visible_fields = {
        k: v for k, v in template.items() if k not in _HIDDEN_FIELDS
    }

    with st.expander("Strategy Parameters", expanded=True):
        # Group sizing at top
        top_fields = ["leverage", "total_amount_quote"]
        top_visible = [f for f in top_fields if f in visible_fields]
        if top_visible:
            cols = st.columns(len(top_visible))
            for col, fname in zip(cols, top_visible):
                with col:
                    form_values[fname] = _render_field(fname, visible_fields[fname])

        remaining = [f for f in visible_fields if f not in top_fields]
        if remaining:
            for row_start in range(0, len(remaining), 3):
                row_fields = remaining[row_start:row_start + 3]
                cols = st.columns(3)
                for col, fname in zip(cols, row_fields):
                    with col:
                        form_values[fname] = _render_field(fname, visible_fields[fname])

    controller_config = {
        "controller_name": selected_name,
        "controller_type": selected_type,
        "candles_config": [],
    }
    controller_config.update({k: v for k, v in form_values.items() if v is not _USE_DEFAULT})

elif config_mode == "Upload YAML":
    uploaded = st.file_uploader("Controller YAML config", type=["yml", "yaml"])
    if uploaded is not None:
        controller_config = uploaded.getvalue().decode("utf-8")

else:  
    config_text = st.text_area(
        "Controller config (JSON dict)",
        height=200,
        placeholder='{"controller_type": "generic", "controller_name": "simple_grid", "connector_name": "coindcx", ...}',
    )
    if config_text.strip():
        try:
            controller_config = json.loads(config_text)
        except json.JSONDecodeError:
            st.error("Invalid JSON. Please enter a valid controller config dict.")

# ── Market data ────────────────────────────────────────────────────────
st.write("### Market Data")
mc1, mc2, mc3 = st.columns(3)
with mc1:
    connector = st.text_input("Connector", value="coindcx")
with mc2:
    pair = st.text_input("Pair", value="BTC-USDT")
with mc3:
    duration_label = st.selectbox(
        "Backtest Duration",
        options=list(DURATION_PRESETS.keys()),
        index=2,
        help="How far back from now to backtest",
    )

preset_delta = DURATION_PRESETS[duration_label]
if preset_delta is None:
    dd1, dd2 = st.columns(2)
    with dd1:
        start_date = st.date_input("Start Date")
    with dd2:
        end_date = st.date_input("End Date", help="Inclusive.")
else:
    end_date = datetime.utcnow().date()
    start_date = (datetime.utcnow() - preset_delta).date()

# ── Engine settings ────────────────────────────────────────────────────
st.write("### Engine Settings")
fc1, fc2, fc3, fc4 = st.columns(4)
with fc1:
    maker_fee = st.number_input("Maker Fee (%)", min_value=0.0, value=0.1, step=0.01, format="%.3f")
with fc2:
    taker_fee = st.number_input("Taker Fee (%)", min_value=0.0, value=0.1, step=0.01, format="%.3f")
with fc3:
    latency_ms = st.number_input("Latency (ms)", min_value=0.0, value=100.0, step=10.0)
with fc4:
    fill_at_touch = st.checkbox("Fill at touch", value=False,
                                help="Optimistic: fill resting orders when a trade prints AT the price")

# ── Run ────────────────────────────────────────────────────────────────
run_disabled = controller_config is None
if st.button("Run Backtest", type="primary", disabled=run_disabled):
    start_str = start_date.isoformat()
    end_str = end_date.isoformat() if end_date != start_date else None

    if config_mode == "Select Controller":
        controller_config["connector_name"] = connector
        controller_config["trading_pair"] = pair

    with st.spinner("Running controller orderbook backtest..."):
        try:
            results = backend_api_client.backtesting.run_controller_orderbook_backtest(
                connector=connector,
                pair=pair,
                start=start_str,
                end=end_str,
                maker_fee=maker_fee / 100,
                taker_fee=taker_fee / 100,
                latency_ms=latency_ms,
                fill_at_touch=fill_at_touch,
                config=controller_config,
            )
        except Exception as e:
            st.error(f"Backtest failed: {e}")
            st.stop()

    if "error" in results:
        st.error(f"Backtest error: {results['error']}")
        st.stop()

    # ── Results ────────────────────────────────────────────────────────
    st.write("### Results")
    r_results = results.get("results", {})

    def _num(key, spec, default=0):
        """Metrics the engine reports as undefined come back as None, not as zero."""
        value = r_results.get(key, default)
        if value is None:
            return "n/a"
        return format(value, spec)

    rm1, rm2, rm3, rm4 = st.columns(4)
    rm1.metric("Net PnL (Quote)", _num("net_pnl_quote", "+,.4f"))
    rm2.metric("Total Executors", r_results.get("total_executors", 0))
    rm3.metric("Total Fees", f"{results.get('fees', 0):,.4f}")
    rm4.metric("Sharpe Ratio", _num("sharpe_ratio", ".2f"),
               help=f"Annualised from {r_results.get('sharpe_samples', 0)} one-minute buckets. "
                    "A short window makes this arithmetically correct but statistically weak.")

    rm5, rm6, rm7, rm8 = st.columns(4)
    rm5.metric("Accuracy", _num("accuracy", ".1%"))
    rm6.metric("Max Drawdown", _num("max_drawdown_pct", ".2%"))
    rm7.metric("Profit Factor", _num("profit_factor", ".2f"),
               help="Gross wins / gross losses. 'n/a' means no losing executor, so the "
                    "ratio is undefined rather than break-even.")
    rm8.metric("Final Position", f"{results.get('final_position', 0):+.8g}")

    recon = results.get("reconciliation") or {}
    if recon and not recon.get("ok", True):
        st.error(
            f"PnL reconciliation failed: executors sum to "
            f"{recon.get('executor_pnl_quote', 0):+,.6f} but the engine's books say "
            f"{recon.get('engine_pnl_quote', 0):+,.6f} "
            f"(residual {recon.get('residual', 0):+,.6f}). These results are not trustworthy.")

    strategy = results.get("strategy") or {}
    st.write("### Strategy Report")
    status_lines = strategy.get("status") or []
    if status_lines:
        st.code("\n".join(status_lines), language=None)
    else:
        st.caption("This controller has no status display of its own. Its results are below.")
    for problem in strategy.get("errors") or []:
        st.warning(f"The controller's report could not be fully produced: {problem}")

    positions = strategy.get("positions") or []
    if positions:
        import pandas as pd
        st.write("**Positions held at the end of the run**")
        st.dataframe(pd.DataFrame(positions), use_container_width=True)

    processed = strategy.get("processed_data") or {}
    if processed:
        with st.expander("Strategy state at the end of the run"):
            for key, value in processed.items():
                if isinstance(value, dict) and value.get("_type") == "DataFrame":
                    st.write(f"**{key}**: {value.get('rows', 0)} rows. Latest values:")
                    st.json(value.get("latest") or {})
                else:
                    st.write(f"**{key}**: {value}")

    candles = results.get("candles") or []
    if candles:
        st.caption("Indicators computed from the venue's candles: " + ", ".join(
            f"{c['feed']} {c['interval']} ({c['rows']} bars)" for c in candles))

    # ── Close types breakdown ──────────────────────────────────────────
    close_types = r_results.get("close_types", {})
    if close_types:
        rm9, rm10, rm11, rm12 = st.columns(4)
        rm9.metric("Long Accuracy", f"{r_results.get('accuracy_long', 0):.1%}")
        rm10.metric("Short Accuracy", f"{r_results.get('accuracy_short', 0):.1%}")
        rm11.metric("Win / Loss", f"{r_results.get('win_signals', 0)} / {r_results.get('loss_signals', 0)}")
        close_str = " | ".join(f"{k}: {v}" for k, v in close_types.items())
        rm12.metric("Close Types", close_str)

    # ── Equity curve ───────────────────────────────────────────────────
    equity = results.get("equity", [])
    fills = results.get("fills", [])
    fig = create_equity_figure(equity, fills)
    if fig:
        st.plotly_chart(fig, use_container_width=True)

    # ── Executors table ────────────────────────────────────────────────
    executors = results.get("executors", [])
    if executors:
        with st.expander("Executors", expanded=True):
            import pandas as pd
            ex_df = pd.DataFrame(executors)
            ex_df["close_type"] = ex_df["close_type"].map(_CLOSE_TYPES)
            ex_df["side"] = ex_df["side"].map({1: "BUY", 2: "SELL"})
            ex_df["level_id"] = [(row or {}).get("level_id") for row in ex_df["custom_info"]]
            for column in ("timestamp", "close_timestamp"):
                ex_df[column] = pd.to_datetime(ex_df[column], unit="s", utc=True)
            columns = ["id", "type", "level_id", "side", "timestamp", "close_timestamp", "close_type",
                       "net_pnl_quote", "net_pnl_pct", "cum_fees_quote", "filled_amount_quote"]
            st.dataframe(ex_df[columns], use_container_width=True)

    # ── Fills table ────────────────────────────────────────────────────
    if fills:
        with st.expander("Fills Table"):
            import pandas as pd
            fills_df = pd.DataFrame(fills)
            if "ts" in fills_df.columns:
                fills_df["time"] = pd.to_datetime(fills_df["ts"], unit="s", utc=True)
                fills_df = fills_df.drop(columns=["ts"])
            st.dataframe(fills_df, use_container_width=True)
