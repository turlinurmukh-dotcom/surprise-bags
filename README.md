# Surprise Bags — trial bot

Telegram bot MVP for a TooGoodToGo-style surplus food marketplace, aimed at
university cafes in Almaty.

## Setup

```sh
cd surprise-bags
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # then fill in BOT_TOKEN
.venv/bin/python -m app.db.init_db
```

## Register a merchant (manual for now)

There's no registration flow yet — see the TODO in `app/db/seed_merchant.py`.
Add a cafe by hand:

```sh
.venv/bin/python -m app.db.seed_merchant "Cafe Aroma" "Al-Farabi Ave 71, Almaty" "+77011234567" <telegram_id>
```

Get the owner's numeric Telegram ID by having them message `@userinfobot`.

## Run

```sh
.venv/bin/python main.py
```

Runs with long polling — no public HTTPS URL needed for this trial.

## Commands

- Merchant: `/post_listing` (photo → description → prices → quantity → pickup window → confirm), `/my_listings`
- Consumer: `/start`, `/browse`, `/my_orders`

## Known limits (fine for a trial, not for real users)

- No merchant registration/auth flow — manual DB insert only.
- No payment integration — orders are created with `payment_status=pending`.
- Reserving a listing isn't wrapped in a transaction-safe decrement, so two
  people tapping "Reserve" on the last bag at the same instant could both win it.
- Pickup windows assume "today" in UTC — no date picker, no timezone handling
  for Almaty (UTC+5) yet.
