# Bot Monitoring

Live health, orders and PnL of the bots, from what they write to InfluxDB. The page reads it through the
api-server's `/metrics` endpoints; it doesn't talk to InfluxDB or the bots itself. Times are IST.

## What it needs

- An api-server with bot monitoring on: run `make monitoring` in the api-server folder, add the lines it prints to
  its `.env`, and restart it. Until then the page says monitoring is off.
- Bots deployed by that api-server after the change. They get the InfluxDB settings in their environment and start
  writing a few seconds after they start.

## Tabs

Only the open tab asks the api-server for data. With **Live** on, it refreshes every 10 seconds. The time range
(15 minutes to 3 days) applies to every tab.

- **Bot health**: each bot's state now (running, hung, down or stopped), its uptime, a timeline of up and down
  periods, incidents, and what the api-server's health watcher noticed. A bot is *hung* when its strategy loop stops
  while its process keeps running, and *down* when both stop. Time a bot was stopped on purpose doesn't count against
  its uptime.
- **Orders vs price**: one bot's best bid and best ask (their own lines, with the spread shaded between them) and
  mid price, each order as a line from when it was placed to when it was filled or cancelled, its fills (hollow
  triangles are partial fills), and the grid reference for grid bots. Hover for details; click an order, or pick it
  in the box below the chart, for its full story. Under the chart, **Active orders**: the bot's open orders now
  (side, price, distance from mid, amount, filled, value, age, order id). On the right: best bid, best ask, spread,
  the open orders by price, and PnL right now. A bot that trades several markets gets a **Market** box: the chart
  shows one market at a time.
- **PnL**: global, realized and unrealized PnL and volume per bot and controller. Only V2 bots (with controllers)
  report PnL. Values are in each pair's quote currency.
- **Market data**: order book health per market (mid, spread, depth, seconds since the book last changed), from the
  market recorder. Empty until the recorder runs.

## Limits

- At most 3 days per window: InfluxDB 3 Core reads about 72 hours of a table in one query.
- PnL rows name a controller, not a market. With a market picked, the PnL on the right is that market's grid
  controller; other V2 bots on several markets show their latest controller's PnL.
