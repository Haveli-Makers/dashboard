# InfluxDB monitoring: dashboard

The dashboard shows what bots and account monitors write to InfluxDB 3. It never talks to InfluxDB or the bots
itself: it reads everything through the api-server's `/metrics` endpoints. The api-server repo's
`INFLUXDB_MONITORING.md` covers the server side, and hummingbot's `docs/INFLUXDB_MONITORING.md` covers what is
written.

## Why InfluxDB

Before, the api-server kept only each bot's latest values, so the dashboard couldn't show history: uptime, hangs and
crashes, orders against the price, or market data second by second. In November 2026 the team adopted InfluxDB 3
Core, after a proof of concept showed fast queries (23–65 ms over days of data) on little memory (about 0.5 GB).
Bots write to it, the api-server serves it, and this dashboard draws the charts, so no Grafana is needed. The team
chose to monitor exchange accounts first, so the account page is the one in the menu.

## Pages

- **Account Monitoring** (Trading Bots → Account Monitoring): one exchange account's balances, open orders, fills
  and market data. It doesn't matter which bot or person acts on the account.
- **Bot Monitoring** (hidden for now): per-bot health (running, hung, down, stopped), uptime and incidents, each order
  against the price, active orders, and PnL. Its code is in `frontend/pages/orchestration/bot_monitoring/`. To show it
  again, add its `st.Page` back to `frontend/pages/permissions.py`.

## What it needs

- An api-server with monitoring on (`INFLUXDB_ENABLED=true`), recent enough to have the account endpoints
  (`/metrics/accounts`).
- `servers.yml` (or `BACKEND_API_*` in `CONFIG.py`) pointing at that api-server.
- For Account Monitoring: hummingbot's `account_monitor` script running for each account. For Bot Monitoring: bots
  running with the `INFLUXDB_*` settings.
- **Streamlit 1.62 or newer.** The pages use lazy tabs (`tab.open`) and `persist_state`, and were tested on 1.62.0.
  The `streamlit>=1.42.0` floor in `requirements.txt` is too low for them.

## Using Account Monitoring

1. Pick the account at the top. Each account monitor shows up as `<account name> · <exchange>`.
2. Read the status line under it: when the monitor last wrote, and anything it couldn't read. A warning means the
   monitor stopped (nothing new for over a minute) or the exchange refused a read.
3. Pick the time range, from 15 minutes to 3 days. With **Live** on, the open tab refreshes every 10 seconds; turn it
   off to read a table without it moving.
4. The tabs:
   - **Balances**: per asset, total, available, and the part held by open orders; below, one asset over time.
   - **Open orders**: every open order on the account now, read from the exchange: pair, side, price, distance from
     mid, amount, filled, value, how long it has been open, and its order ids. The client order id hints at who
     placed it: on CoinDCX, our hummingbot bots' ids start with `haveli-`.
   - **Fills**: the account's trades in the range, newest first, with a summary per pair (bought, spent, sold,
     received, fees).
   - **Market data**: the watched pairs' best bid, best ask and mid over time, spread, depth within 1% of mid, and
     how long ago the order book last changed.

Times are IST. Values are in each pair's quote currency (INR, USDT, …).

## How it reads the data

- `api_client/routers/metrics.py` (`MetricsRouter`) has one method per `/metrics` endpoint. Every call only reads.
- Only the open tab calls the api-server, so the other tabs cost nothing.
- Each tab redraws on its own: one failing view shows its error without blanking the page.

## Limits

- **3 days per window**, the most InfluxDB 3 Core reads in one query.
- **Open orders need exchange support.** Only exchanges whose connector can list an account's open orders fill that
  tab; today that's CoinDCX. Balances, fills and market data have wider support.
- **Short-lived orders can be missed.** An order that lives shorter than the monitor's update interval (5 s by
  default) may never show under Open orders. Its fills still show.
- **Colours** were checked for colour-blind readers on the dark theme: buys teal, sells red.

## Files

- `frontend/pages/orchestration/account_monitoring/` (`app.py`, `README.md`): the Account Monitoring page.
- `frontend/pages/orchestration/bot_monitoring/` (`app.py`, `README.md`): the hidden Bot Monitoring page.
- `frontend/pages/permissions.py`: which pages are in the menu.
- `api_client/routers/metrics.py`: the API client for `/metrics`.

## Troubleshooting

| The page says | Why, and what to do |
|---|---|
| "Monitoring is off on this api-server" | Turn it on in the api-server (`make monitoring`, add the printed lines to `.env`, restart) |
| "The api-server can't reach InfluxDB" | InfluxDB is down or `INFLUXDB_URL` is wrong on the api-server |
| "No account monitor has written in the last day" | Start hummingbot's `account_monitor` script for the account |
| "This api-server has no account monitoring endpoints" | The api-server is older than the account endpoints; update it |
| "Reload this browser tab" | The browser session started before these pages existed; reload it |
| "The account monitor hasn't written for …" | The monitor stopped, or can't reach InfluxDB; check its terminal or `status` |
