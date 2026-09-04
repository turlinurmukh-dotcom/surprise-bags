# Surprise Bags

Telegram bot + Mini App for a TooGoodToGo-style surplus food marketplace,
aimed at university cafes in Almaty. Deployed on Render: https://surprise-bags.onrender.com

## Local development (polling mode)

```sh
cd surprise-bags
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # then fill in BOT_TOKEN
.venv/bin/python -m app.db.init_db   # creates local SQLite tables
.venv/bin/python main.py             # runs the bot via long polling
```

No `DATABASE_URL` needed locally — `app/db/session.py` falls back to a
SQLite file when it's unset.

**You can't run local polling while the production webhook is registered**
— Telegram rejects `getUpdates` calls while a webhook is active
(`TelegramConflictError`). To develop locally against the real bot, either
delete the webhook temporarily (`deleteWebhook` via the Bot API) and
re-register it when done, or use a second bot token from @BotFather for
local testing.

To test the Mini App locally you also need `web.py` running plus a public
tunnel (e.g. `cloudflared tunnel --url http://localhost:8000`) pointed at
it, since Telegram Mini Apps require HTTPS.

## Production (webhook mode, Render)

Render deploys `web.py` as a single FastAPI process that serves both the
Mini App API and the bot (`USE_WEBHOOK=1` merges the bot into the same
process — see `app/bot_setup.py`). Config lives in `render.yaml`
(Blueprint) plus secrets set directly in Render's dashboard:

- `BOT_TOKEN`, `TWOGIS_API_KEY` — as usual
- `USE_WEBHOOK=1`, `WEBHOOK_URL` — the deployed URL, points Telegram's
  webhook at `$WEBHOOK_URL/webhook/telegram`
- `TELEGRAM_WEBHOOK_SECRET` — random string, verified against Telegram's
  `X-Telegram-Bot-Api-Secret-Token` header so nobody can POST fake
  updates to the public webhook endpoint
- `DATABASE_URL` — Render's managed Postgres, auto-injected via
  `render.yaml`'s `fromDatabase` link

**Database**: production uses Postgres, not SQLite — Render's free web
service tier has an ephemeral filesystem, so a SQLite file would be wiped
on every restart/redeploy/sleep-wake cycle. `app/db/session.py` picks
Postgres automatically whenever `DATABASE_URL` is set.

Render's free Postgres instance expires 90 days after creation and needs
recreating or upgrading — it is not a permanent free database.

**Cold starts**: the free web service tier sleeps after ~15 min of no
traffic; the next request (including an incoming Telegram message, since
webhook mode means Telegram calls us) takes 30-60s to wake it. This is
accepted as fine for the current pilot scale — no UptimeRobot-style
keep-alive ping is configured.

After first deploy (or after `render.yaml` changes, which don't auto-sync
to an already-created service — re-apply via Render's dashboard or API):

```sh
# One-time: create tables in the new Postgres instance
DATABASE_URL="<external connection string from Render>" \
  .venv/bin/python -m app.db.init_db
```

## Register a merchant (manual for now)

There's no registration flow yet — see the TODO in `app/db/seed_merchant.py`.
Add a cafe by hand:

```sh
.venv/bin/python -m app.db.seed_merchant "Cafe Aroma" "Al-Farabi Ave 71, Almaty" "+77011234567" <telegram_id> [latitude longitude]
```

Get the owner's numeric Telegram ID by having them message `@userinfobot`.
For demo/test data across several merchants and listings, use
`app/db/seed_demo.py` instead (idempotent, safe to re-run).

## Commands

- Merchant: `/post_listing` (category → prices → quantity → pickup window → confirm), `/my_listings`, `/pickup <code>` (confirm a consumer's pickup)
- Consumer: `/start`, `/app` (opens the Mini App), `/browse` (chat-based listing, older path), `/my_orders`

## Known limits (fine for a trial, not for real users)

- No merchant registration/auth flow — manual DB insert only.
- No payment integration — orders are created with `payment_status=pending`.
  A per-user active-reservation cap (2) and no-show tracking/soft-block
  exist as a stopgap, but don't fully solve hoarding until Kaspi Pay
  prepayment is wired in.
- Reserving a listing isn't wrapped in a transaction-safe decrement, so two
  people tapping "Reserve" on the last bag at the same instant could both win it.
- Mini App language switcher (EN/RU/KZ) covers the Mini App UI only —
  bot chat messages and backend error strings are still English-only.
