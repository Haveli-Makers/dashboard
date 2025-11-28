import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from frontend.st_utils import get_backend_api_client, initialize_st_page

# Initialize Streamlit page
initialize_st_page(title="Download Spread", icon="📊")
backend_api_client = get_backend_api_client()
c1, c2, c3 = st.columns([2, 2, 0.5])
with c1:
    connectors = st.multiselect(
        "Exchanges",
        options=["binance", "coinbase", "kraken", "kucoin", "bybit", "okx", "gate_io", "huobi"],
        default=["binance"]
    )
    trading_pairs = st.multiselect(
        "Trading Pairs",
        options=["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT", "ADA-USDT", "DOGE-USDT", "MATIC-USDT"],
        default=["BTC-USDT"]
    )
with c2:
    window_hours = st.selectbox("Time Window (Hours)", 
                                options=[1, 6, 12, 24, 48, 72, 168],  # 1h, 6h, 12h, 24h, 48h, 72h, 1 week
                                index=3)  # Default to 24 hours
with c3:
    get_data_button = st.button("Get Spread!")

if get_data_button:
    # Validate inputs
    if not connectors:
        st.error("Please select at least one exchange.")
    elif not trading_pairs:
        st.error("Please select at least one trading pair.")
    else:
        try:
            with st.spinner("Fetching spread data..."):
                spread_response = backend_api_client.market_data.get_spread_averages(
                    pairs=trading_pairs,
                    connectors=connectors,
                    window_hours=window_hours
                )
            if spread_response and spread_response.get("data"):
                spread_data = spread_response["data"]
                spread_df = pd.DataFrame(spread_data)
                
                if not spread_df.empty:
                    # Plotting the spread data as separate lines per connector
                    fig = go.Figure()
                    
                    # Define colors for different connectors
                    colors = ['cyan', 'orange', 'green', 'red', 'purple', 'yellow', 'pink', 'blue']
                    
                    for idx, connector in enumerate(spread_df['connector'].unique()):
                        connector_data = spread_df[spread_df['connector'] == connector]
                        
                        fig.add_trace(go.Scatter(
                            x=connector_data['pair'],
                            y=connector_data['avg_spread'].astype(float),
                            mode='lines+markers',
                            name=connector.title(),
                            line=dict(color=colors[idx % len(colors)], width=2),
                            marker=dict(size=8)
                        ))
                    
                    fig.update_layout(
                        height=600,
                        title=f"Spread Averages by Exchange ({window_hours}h window)",
                        xaxis_title="Trading Pair",
                        yaxis_title="Spread (%)",
                        template="plotly_dark",
                        showlegend=True,
                        yaxis=dict(tickformat=".4f", ticksuffix="%")
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # Display detailed data table
                    st.subheader("Spread Data Details")
                    st.dataframe(spread_df, use_container_width=True)
                    
                    # Generating CSV and download button
                    csv = spread_df.to_csv(index=False)
                    connectors_str = "_".join(connectors)
                    pairs_str = "_".join([p.replace("-", "") for p in trading_pairs])
                    filename = f"spread_{connectors_str}_{pairs_str}_{window_hours}h.csv"
                    st.download_button(
                        label="Download Spread Data as CSV",
                        data=csv,
                        file_name=filename,
                        mime='text/csv',
                    )
                else:
                    st.warning("No spread data available for the selected parameters.")
            else:
                st.warning("No spread data available for the selected parameters.")
                
        except Exception as e:
            st.error(f"Failed to fetch spread data: {str(e)}")
            st.info("Please make sure the backend server is running and try again.")