import streamlit as st
from hummingbot.core.data_type.common import PositionMode


def _get(default_config: dict, key: str, fallback):
    value = default_config.get(key, fallback)
    return fallback if value is None else value


def user_inputs() -> dict:
    default_config = st.session_state.get("default_config", {})

    with st.expander("General Settings", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            connector_name = st.text_input(
                "Connector Name",
                value=_get(default_config, "connector_name", "coindcx_perpetual"),
            )
            leverage = st.number_input(
                "Leverage",
                min_value=1,
                value=int(_get(default_config, "leverage", 1)),
            )
        with c2:
            trading_pair = st.text_input(
                "Trading Pair",
                value=_get(default_config, "trading_pair", "BTC-USDT"),
            )
            raw_position_mode = default_config.get("position_mode", PositionMode.ONEWAY)
            position_mode_name = (
                raw_position_mode if isinstance(raw_position_mode, str) else raw_position_mode.name
            )
            position_mode = st.selectbox(
                "Position Mode",
                options=["ONEWAY", "HEDGE"],
                index=["ONEWAY", "HEDGE"].index(position_mode_name),
            )
        with c3:
            total_amount_quote = st.number_input(
                "Total Amount (Quote)",
                min_value=0.0,
                value=float(_get(default_config, "total_amount_quote", 100.0)),
                help="Caps the strategy — the reconciliation and risk guards halt new legs once "
                     "losses reach a share of this.",
            )
            order_amount_quote = st.number_input(
                "Order Amount per Leg (Quote)",
                min_value=0.0,
                value=float(_get(default_config, "order_amount_quote", 100.0)),
                help="Each leg risks this much quote, independent of total_amount_quote.",
            )
        initial_entry_mode = st.selectbox(
            "Initial Entry Mode",
            options=["BOTH_OCO", "LONG_ONLY", "SHORT_ONLY"],
            index=["BOTH_OCO", "LONG_ONLY", "SHORT_ONLY"].index(
                _get(default_config, "initial_entry_mode", "BOTH_OCO")
                if isinstance(default_config.get("initial_entry_mode"), str)
                else "BOTH_OCO"
            ),
            help="Which side(s) the very first leg offers on a perpetual. Once a leg fills, every "
                 "later leg follows that side (long-or-flat, or short-or-flat) for the rest of the "
                 "run. Spot connectors are always LONG_ONLY regardless of this setting.",
        )

    with st.expander("Grid Step", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            take_profit = st.number_input(
                "Take Profit",
                min_value=0.0,
                value=float(_get(default_config, "take_profit", 0.005)),
                format="%.4f",
                help="Distance from the fill price to the take-profit exit, as a fraction (0.005 = 0.5%).",
            )
        with c2:
            stop_loss = st.number_input(
                "Stop Loss",
                min_value=0.0,
                value=float(_get(default_config, "stop_loss", 0.005)),
                format="%.4f",
                help="Distance from the fill price to the stop-loss exit, and also the distance "
                     "from the reference price to the next entry trigger.",
            )
        with c3:
            time_limit_enabled = st.checkbox(
                "Enable Time Limit",
                value=default_config.get("time_limit") is not None,
            )
            time_limit = None
            if time_limit_enabled:
                time_limit = st.number_input(
                    "Time Limit (s)",
                    min_value=1,
                    value=int(_get(default_config, "time_limit", 300)),
                )

        c1, c2 = st.columns(2)
        with c1:
            entry_timeout_enabled = st.checkbox(
                "Enable Entry Timeout",
                value=default_config.get("entry_timeout", 300) is not None,
            )
            entry_timeout = None
            if entry_timeout_enabled:
                entry_timeout = st.number_input(
                    "Entry Timeout (s)",
                    min_value=1,
                    value=int(_get(default_config, "entry_timeout", 300)),
                    help="Cancels an unfilled entry leg if the price stays between the resting "
                         "order and the trigger for this long.",
                )
        with c2:
            close_slippage_ticks = st.number_input(
                "Close Slippage (ticks)",
                min_value=0,
                value=int(_get(default_config, "close_slippage_ticks", 20)),
                help="How far through the book an urgent exit crosses, in price ticks.",
            )

    with st.expander("Stop Loss Chase", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            stop_loss_chase = st.checkbox(
                "Chase Stop Loss",
                value=bool(_get(default_config, "stop_loss_chase", True)),
                help="Once triggered, requote the stop loss as a maker order that chases the "
                     "opposite touch instead of resting once.",
            )
        with c2:
            stop_loss_maker_offset_ticks = st.number_input(
                "Maker Offset (ticks)",
                min_value=0,
                value=int(_get(default_config, "stop_loss_maker_offset_ticks", 1)),
                help="Ticks inside the opposite touch for the chasing maker order.",
            )
        with c3:
            stop_loss_requote_pct = st.number_input(
                "Requote Threshold",
                min_value=0.0,
                value=float(_get(default_config, "stop_loss_requote_pct", 0.0005)),
                format="%.4f",
                help="Price move (fraction) needed before the chasing order is requoted.",
            )
        with c4:
            stop_loss_max_drift_pct = st.number_input(
                "Max Drift",
                min_value=0.0,
                value=float(_get(default_config, "stop_loss_max_drift_pct", 0.001)),
                format="%.4f",
                help="Max distance (fraction) the chasing order is allowed to drift from the touch.",
            )

    with st.expander("Order Execution & Retries", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            cancel_settle_delay = st.number_input(
                "Cancel Settle Delay (s)",
                min_value=0.0,
                value=float(_get(default_config, "cancel_settle_delay", 0.25)),
                help="Wait after a cancel acknowledgement before sending the exit that follows it, "
                     "for venues that hold collateral briefly after a cancel.",
            )
        with c2:
            exit_retry_max_delay = st.number_input(
                "Exit Retry Max Delay (s)",
                min_value=0.0,
                value=float(_get(default_config, "exit_retry_max_delay", 2.0)),
            )
        with c3:
            collateral_refusal_wait = st.number_input(
                "Collateral Refusal Wait (s)",
                min_value=0.0,
                value=float(_get(default_config, "collateral_refusal_wait", 3.0)),
                help="Wait time once the venue keeps refusing a reduce-only close as insufficient funds.",
            )
        with c4:
            collateral_refusals_before_waiting = st.number_input(
                "Refusals Before Waiting",
                min_value=1,
                value=int(_get(default_config, "collateral_refusals_before_waiting", 2)),
            )

    with st.expander("Cooldowns", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            cooldown_after_take_profit = st.number_input(
                "Cooldown After Take Profit (s)",
                min_value=0,
                value=int(_get(default_config, "cooldown_after_take_profit", 0)),
            )
        with c2:
            cooldown_after_stop_loss = st.number_input(
                "Cooldown After Stop Loss (s)",
                min_value=0,
                value=int(_get(default_config, "cooldown_after_stop_loss", 0)),
            )

    with st.expander("Risk Management", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            max_loss_quote_enabled = st.checkbox(
                "Enable Max Loss (Quote)",
                value=default_config.get("max_loss_quote") is not None,
            )
            max_loss_quote = None
            if max_loss_quote_enabled:
                max_loss_quote = st.number_input(
                    "Max Loss (Quote)",
                    min_value=0.0,
                    value=float(_get(default_config, "max_loss_quote", 10.0)),
                )
        with c2:
            max_loss_pct_enabled = st.checkbox(
                "Enable Max Loss (%)",
                value=default_config.get("max_loss_pct") is not None,
            )
            max_loss_pct = None
            if max_loss_pct_enabled:
                max_loss_pct = st.number_input(
                    "Max Loss (% of Total Amount)",
                    min_value=0.0,
                    value=float(_get(default_config, "max_loss_pct", 0.1)),
                    format="%.4f",
                )
        st.caption(
            "Both may be set — whichever loss threshold is reached first stops new legs from opening."
        )

        c1, c2, c3 = st.columns(3)
        with c1:
            max_consecutive_failed_legs = st.number_input(
                "Max Consecutive Failed Legs",
                min_value=1,
                value=int(_get(default_config, "max_consecutive_failed_legs", 5)),
                help="Halt after this many legs in a row are refused by the venue before trading.",
            )
        with c2:
            insufficient_balance_grace_seconds = st.number_input(
                "Insufficient Balance Grace (s)",
                min_value=0.0,
                value=float(_get(default_config, "insufficient_balance_grace_seconds", 180.0)),
                help="Halt if no leg has been affordable for this long — long enough to rule out a "
                     "stale balance cache.",
            )
        with c3:
            retry_after_insufficient_balance = st.number_input(
                "Retry After Insufficient Balance (s)",
                min_value=1,
                value=int(_get(default_config, "retry_after_insufficient_balance", 5)),
            )

        st.write("---")
        c1, c2, c3 = st.columns(3)
        with c1:
            reconcile_positions = st.checkbox(
                "Reconcile Positions",
                value=bool(_get(default_config, "reconcile_positions", True)),
                help="Compare the venue's actual position against what the controller's legs claim, "
                     "and halt if it finds one nothing is watching.",
            )
        with c2:
            orphan_grace_seconds = st.number_input(
                "Orphan Grace (s)",
                min_value=0.0,
                value=float(_get(default_config, "orphan_grace_seconds", 10.0)),
                help="How long the venue and our own records must disagree before treating a "
                     "position as orphaned.",
            )
        with c3:
            flatten_orphan_positions = st.checkbox(
                "Flatten Orphan Positions",
                value=bool(_get(default_config, "flatten_orphan_positions", True)),
                help="Close an orphaned position automatically (only one that appeared while this "
                     "controller was running and watching a flat account).",
            )

        st.write("---")
        c1, c2 = st.columns(2)
        with c1:
            stop_when_losses_outnumber_wins = st.checkbox(
                "Stop When Losses Outnumber Wins",
                value=bool(_get(default_config, "stop_when_losses_outnumber_wins", False)),
            )
        with c2:
            min_legs_before_count_check = st.number_input(
                "Min Legs Before Count Check",
                min_value=1,
                value=int(_get(default_config, "min_legs_before_count_check", 10)),
            )

    return {
        "controller_name": "simple_grid",
        "controller_type": "generic",
        "candles_config": [],
        "connector_name": connector_name.strip(),
        "trading_pair": trading_pair.strip(),
        "leverage": leverage,
        "position_mode": position_mode,
        "total_amount_quote": total_amount_quote,
        "order_amount_quote": order_amount_quote,
        "take_profit": take_profit,
        "stop_loss": stop_loss,
        "time_limit": time_limit,
        "entry_timeout": entry_timeout,
        "close_slippage_ticks": close_slippage_ticks,
        "cancel_settle_delay": cancel_settle_delay,
        "exit_retry_max_delay": exit_retry_max_delay,
        "collateral_refusal_wait": collateral_refusal_wait,
        "collateral_refusals_before_waiting": collateral_refusals_before_waiting,
        "stop_loss_chase": stop_loss_chase,
        "stop_loss_maker_offset_ticks": stop_loss_maker_offset_ticks,
        "stop_loss_requote_pct": stop_loss_requote_pct,
        "stop_loss_max_drift_pct": stop_loss_max_drift_pct,
        "initial_entry_mode": initial_entry_mode,
        "cooldown_after_take_profit": cooldown_after_take_profit,
        "cooldown_after_stop_loss": cooldown_after_stop_loss,
        "max_loss_quote": max_loss_quote,
        "max_loss_pct": max_loss_pct,
        "max_consecutive_failed_legs": max_consecutive_failed_legs,
        "insufficient_balance_grace_seconds": insufficient_balance_grace_seconds,
        "retry_after_insufficient_balance": retry_after_insufficient_balance,
        "reconcile_positions": reconcile_positions,
        "orphan_grace_seconds": orphan_grace_seconds,
        "flatten_orphan_positions": flatten_orphan_positions,
        "stop_when_losses_outnumber_wins": stop_when_losses_outnumber_wins,
        "min_legs_before_count_check": min_legs_before_count_check,
    }
