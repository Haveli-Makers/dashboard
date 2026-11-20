import pandas as pd
from plotly.subplots import make_subplots
import plotly.graph_objects as go

from frontend.visualization.theme import get_default_layout


def create_equity_figure(equity_data, fills_data):
    """Create a figure with equity curve and position, plus fill markers."""
    if not equity_data:
        return None

    eq_df = pd.DataFrame(equity_data)
    eq_df["time"] = pd.to_datetime(eq_df["ts"], unit="s", utc=True)

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.02,
        subplot_titles=("PnL (Quote)", "Position (Base)"),
        row_heights=[0.6, 0.4],
    )

    fig.add_trace(go.Scatter(
        x=eq_df["time"], y=eq_df["pnl"],
        mode="lines", name="PnL",
        line=dict(color="#32CD32", width=1.5),
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=eq_df["time"], y=eq_df["position"],
        mode="lines", name="Position",
        line=dict(color="#1E90FF", width=1),
        fill="tozeroy", fillcolor="rgba(30, 144, 255, 0.15)",
    ), row=2, col=1)

    if fills_data:
        fills_df = pd.DataFrame(fills_data)
        fills_df["time"] = pd.to_datetime(fills_df["ts"], unit="s", utc=True)
        buys = fills_df[fills_df["side"] == "buy"]
        sells = fills_df[fills_df["side"] == "sell"]

        for df_side, color, name in [(buys, "#32CD32", "Buy"), (sells, "#FF6347", "Sell")]:
            if not df_side.empty:
                fig.add_trace(go.Scatter(
                    x=df_side["time"], y=df_side["price"],
                    mode="markers", name=name,
                    marker=dict(color=color, size=5, symbol="triangle-up" if name == "Buy" else "triangle-down"),
                    text=[f"{row['qty']:.6g} @ {row['price']:.4f}" for _, row in df_side.iterrows()],
                    hoverinfo="text+x",
                ), row=1, col=1)

    layout = get_default_layout("Orderbook Backtest Results")
    layout["showlegend"] = True
    layout["legend"] = dict(x=0, y=1.12, orientation="h")
    fig.update_layout(**layout)
    fig.update_yaxes(title_text="PnL (Quote)", row=1, col=1)
    fig.update_yaxes(title_text="Position (Base)", row=2, col=1)
    return fig


def create_strategy_report_table(strategy_report, strategy_name):
    """Create a formatted DataFrame from the strategy report for display."""
    if not strategy_report:
        return None
    df = pd.DataFrame(strategy_report)
    if "start_ts" in df.columns:
        df["start"] = pd.to_datetime(df["start_ts"], unit="s", utc=True)
    if "end_ts" in df.columns:
        df["end"] = pd.to_datetime(df["end_ts"], unit="s", utc=True)
    drop_cols = [c for c in ["start_ts", "end_ts"] if c in df.columns]
    if drop_cols:
        df = df.drop(columns=drop_cols)
    return df
