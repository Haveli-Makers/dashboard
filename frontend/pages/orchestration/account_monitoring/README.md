# Account Monitoring

One exchange account's balances, open orders, fills and market data. They come from the account's **account
monitor**: hummingbot's `account_monitor` script, a bot that never places or cancels an order and holds the account's
API keys. So the page shows the whole account, whatever acts on it: any bot on that account, or a person. The page
reads everything through the api-server's `/metrics` endpoints. Times are IST.

## What it needs

- An api-server with monitoring on: `make monitoring` in the api-server folder, add the lines it prints to its
  `.env`, and restart it.
- An account monitor per account, run like any bot with the account's keys (`connect <exchange>`) and the
  `INFLUXDB_*` settings. Its config names the account, the exchange and the pairs to watch, and how often it reads the
  account (`update_interval`, default 5 seconds).

## Tabs

Pick the account at the top. The line under it says when its monitor last wrote and what it couldn't read. With
**Live** on, the open tab refreshes every 10 seconds; the time range (15 minutes to 3 days) applies to every tab.

- **Balances**: what the account holds now per asset (total, available, and the part held by open orders), and one
  asset's total and available over time.
- **Open orders**: every open order on the account now, read from the exchange: pair, side, price, distance from
  mid, amount, filled, value, how long it has been open, and its order ids.
- **Fills**: the account's trades in the time range, newest first, with a summary per pair (bought, sold, fees).
- **Market data**: the watched pairs' order books over time: best bid, best ask and mid, spread, depth within 1% of
  mid, and how long ago the book last changed.

## Limits

- An order that lives shorter than the monitor's update interval may never show under Open orders; its fills still
  show under Fills.
- Open orders need the exchange's "list open orders" call in the connector. CoinDCX has it; other exchanges show the
  tab empty until theirs is added.
- At most 3 days per window: InfluxDB 3 Core reads about 72 hours of a table in one query.

The Bot Monitoring page (bot health, orders per bot, PnL) is hidden from the menu for now; its code stays in
`bot_monitoring/`, and adding it back to `frontend/pages/permissions.py` brings it back.
