import os

from dotenv import load_dotenv

load_dotenv()

MINER_COINS = ["Algorand", "Avalanche", "DAO Maker", "Faith Tribe", "Fear", "Frontier",
               "Harmony", "Hot Cross", "HUMAN Protocol", "Oddz", "Shera", "Firo",
               "Vesper Finance", "Youclout", "Nimiq"]
MINER_EXCHANGES = ["Binance", "FTX", "Coinbase Exchange", "Huobi Global", "OKX", "KuCoin",
                   "Kraken", "Bybit (Spot)", "FTX.US", "Crypto.com Exchange", "Binance US",
                   "MEXC Global", "Gate.io", "BitMart", "Bitfinex", "AscendEX (BitMax)",
                   "Bittrex", "CoinFLEX", "Digifinex", "HitBTC", "Kraken", "Liquid", ]

DEFAULT_MINER_COINS = ["Avalanche"]

CERTIFIED_EXCHANGES = ["ascendex", "binance", "bybit", "gate.io", "hitbtc", "huobi", "kucoin", "okx", "gateway"]
CERTIFIED_STRATEGIES = ["xemm", "cross exchange market making", "pmm", "pure market making"]

AUTH_SYSTEM_ENABLED = os.getenv("AUTH_SYSTEM_ENABLED", "True").lower() in ("true", "1", "t")

GOOGLE_SSO_ENABLED = os.getenv("GOOGLE_SSO_ENABLED", "True").lower() in ("true", "1", "t")
GOOGLE_ALLOWED_DOMAIN = os.getenv("GOOGLE_ALLOWED_DOMAIN", "havelimakers.com")

IMAGE_FILTER_KEYWORD = os.getenv("IMAGE_FILTER_KEYWORD", "haveli")

BACKEND_API_HOST = os.getenv("BACKEND_API_HOST", "127.0.0.1")
BACKEND_API_PORT = os.getenv("BACKEND_API_PORT", 8000)
BACKEND_API_USERNAME = os.getenv("BACKEND_API_USERNAME", "admin")
BACKEND_API_PASSWORD = os.getenv("BACKEND_API_PASSWORD", "admin")

# SMTP settings used to email exported data (e.g. spread reports) as attachments
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "True").lower() in ("true", "1", "t")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", SMTP_USERNAME)

SPREAD_EMAIL_SUBJECT_TEMPLATE = os.getenv(
    "SPREAD_EMAIL_SUBJECT_TEMPLATE",
    "Spread Report - {connectors} - {pairs} - {date}",
).replace("\\n", "\n")
SPREAD_EMAIL_BODY_TEMPLATE = os.getenv(
    "SPREAD_EMAIL_BODY_TEMPLATE",
    "Hi,\n\n"
    "Please find attached the spread data report generated on {date} at {time}.\n\n"
    "Exchanges: {connectors}\n"
    "Trading Pairs: {pairs}\n"
    "Time Window: {window_hours} hours\n"
    "Rows: {row_count}\n"
    "Failed/Missing Pairs: {failed_count}\n\n"
    "Regards,\n"
    "HM Dashboard\n",
).replace("\\n", "\n")

SAMPLES_EMAIL_SUBJECT_TEMPLATE = os.getenv(
    "SAMPLES_EMAIL_SUBJECT_TEMPLATE",
    "Spread Samples - {connectors} - {pairs} - {date}",
).replace("\\n", "\n")
SAMPLES_EMAIL_BODY_TEMPLATE = os.getenv(
    "SAMPLES_EMAIL_BODY_TEMPLATE",
    "Hi,\n\n"
    "Please find attached the raw spread samples generated on {date} at {time}.\n\n"
    "Exchanges: {connectors}\n"
    "Trading Pairs: {pairs}\n"
    "Rows: {row_count}\n\n"
    "Regards,\n"
    "HM Dashboard\n",
).replace("\\n", "\n")
