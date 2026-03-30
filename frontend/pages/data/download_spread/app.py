import pandas as pd
import streamlit as st

from frontend.st_utils import get_backend_api_client, initialize_st_page

# Initialize Streamlit page
initialize_st_page(title="Download Spread", icon="📊")
backend_api_client = get_backend_api_client()
c1, c2, c3 = st.columns([2, 2, 0.5])
with c1:
    connectors = st.multiselect(
        "Exchanges",
        options=["binance", "coinbase", "kraken", "kucoin", "bybit", "okx", "gate_io", "huobi", "coindcx", "wazirx"],
        default=["coindcx"]
    )
    trading_pairs = st.text_input("Trading Pairs", value="BTC-USDT")
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
    else:
        try:
            with st.spinner("Fetching spread data..."):
                spread_response = backend_api_client.market_data.get_spread_averages(
                    pairs=trading_pairs.split(","),
                    connectors=connectors,
                    window_hours=window_hours
                )
            if spread_response and spread_response.get("data"):
                spread_data = spread_response["data"]
                spread_df = pd.DataFrame(spread_data)

                if not spread_df.empty:
                    # Display detailed data table
                    st.subheader("Spread Data Details")
                    st.dataframe(spread_df, use_container_width=True)

                    # Generating CSV and download button
                    csv = spread_df.to_csv(index=False)
                    connectors_str = "_".join(connectors)
                    pairs_str = "_".join([p.replace("-", "") for p in trading_pairs.split(",")])
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
