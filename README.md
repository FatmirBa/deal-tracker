# Deal Tracker

Prices for washing machines, dishwashers, dryers, fridges, TVs and corner sofas across Bosnian shops
(Domod, Imtec, Technoshop, Tehnodepo, Topizbor, eKupi, Emmezeta, JYSK, Forma Ideale, OLX.ba), checked every 3 hours.
The app shows today's cheapest options, compares the same model across shops, and keeps a price history so you can
tell a real discount from a raised "was" price.

## On your phone

Open `https://<your-username>.github.io/deal-tracker/`, then:
- **Android (Chrome):** menu, then *Add to Home screen*
- **iPhone (Safari):** Share, then *Add to Home Screen*

## Phone alerts: ntfy or Telegram (use either, or both)

**ntfy (quickest):** install the free ntfy app, tap + and subscribe to your secret topic name. Then on GitHub open
**Settings → Secrets and variables → Actions → New repository secret**, name `NTFY_TOPIC`, value: that topic name.
Anyone who knows the topic name can read the alerts, so keep it long and random.

**Telegram:**

1. In Telegram, open **@BotFather**, send `/newbot`, follow the steps and copy the token.
2. Send `/start` to your new bot.
3. On GitHub, open this repo's **Settings → Secrets and variables → Actions → New repository secret**.
   Name: `TELEGRAM_TOKEN`, value: the token.

Either way, you get a message when a watched item drops to your target price (`max_price` in `watchlist.yaml`) or hits a real
30-day low. OLX listings show in the app but don't send alerts (change `alerts: false` in `shops.yaml`).

## Watching something new

Tap **Watch something new** in the app. It opens a short GitHub form; submit it and the tracker adds the product
and runs a check. To stop watching, open an issue titled `Unwatch: <name>`.

## What the badges mean

- **Lowest in 30 days**: today's price is at or below every price recorded in the previous 30 days.
- **"Was" price never seen here**: the shop shows an old price that this tracker never saw it charge in 30 days.
- **Tracking since …**: fewer than 3 days of history, so no verdict yet.

## Files

| File | What it does |
|---|---|
| `watchlist.yaml` | What to search for, accessory filters, your target prices |
| `shops.yaml` | Which shops to check; search pages are found automatically |
| `tracker/` | The Python code that fetches, extracts and analyses prices |
| `data/history.csv` | Every price ever recorded |
| `docs/` | The phone app (GitHub Pages) |
| `.github/workflows/` | The 3-hourly price check, shop mapping, and watch-from-issue jobs |
