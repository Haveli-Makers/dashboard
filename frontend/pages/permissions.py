import streamlit as st


def main_page():
    return [st.Page("frontend/pages/landing.py", title="Dashboard", icon="📊", url_path="landing")]


def public_pages():
    return {
        "Data": [
            st.Page(
                "frontend/pages/data/download_candles/app.py",
                title="Download Candles",
                icon="💹",
                url_path="download_candles"
            ),
            st.Page(
                "frontend/pages/data/download_spread/app.py",
                title="Download Spread",
                icon="📊",
                url_path="download_spread"
            ),
        ],
        # "Community Pages": [
        #     st.Page("frontend/pages/data/tvl_vs_mcap/app.py", title="TVL vs Market Cap", icon="🦉", url_path="tvl_vs_mcap"),
        # ]
    }


def private_pages():
    return {
        "Bot Orchestration": [
            st.Page(
                "frontend/pages/orchestration/config_generator.py",
                title="Config Generator",
                icon="🧩",
                url_path="config_generator"
            ),
            st.Page(
                "frontend/pages/orchestration/instances/app.py",
                title="Instances",
                icon="🦅",
                url_path="instances"
            ),
            st.Page(
                "frontend/pages/orchestration/launch_bot_v2/app.py",
                title="Deploy V2",
                icon="🚀",
                url_path="launch_bot_v2"
            ),
            st.Page(
                "frontend/pages/orchestration/credentials/app.py",
                title="Accounts",
                icon="🔑",
                url_path="accounts"
            ),
            st.Page(
                "frontend/pages/orchestration/portfolio/app.py",
                title="Portfolio",
                icon="💰",
                url_path="portfolio"
            ),
            st.Page(
                "frontend/pages/orchestration/trading/app.py",
                title="Trading",
                icon="🪄",
                url_path="trading"
            ),
            st.Page(
                "frontend/pages/orchestration/archived_bots/app.py",
                title="Archived Bots",
                icon="🗃️",
                url_path="archived_bots"
            ),
        ]
    }
