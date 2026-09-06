# Secrets — stored in macOS Keychain, not here

This file is a **directory of key names only** — no actual secret values live in
this file or in this repo. Every value below is stored in macOS Keychain
(encrypted at rest), retrievable with:

```sh
security find-generic-password -a "$USER" -s "<service-name>" -w
```

| Service name | What it is | Notes |
|---|---|---|
| `sarqyt-bot-token-current` | Live production bot token (@sarqytappbot) | Used in `.env` (local) and Render's `BOT_TOKEN` env var (production) |
| `sarqyt-bot-token-old` | Retired test bot token (@toogoodkzbot) | Kept only for reference/rollback; webhook deregistered |
| `sarqyt-2gis-api-key` | 2GIS MapGL JS key | Domain-restricted public key, not really secret, but kept here for consistency |
| `sarqyt-render-api-key` | Render API key | **Not stored long-term** — added here only while actively debugging a deploy, then deleted from Keychain once done (Render API keys are account-wide and high-privilege, so we don't keep one sitting around) |

To add a new one:

```sh
security add-generic-password -a "$USER" -s "<service-name>" -w "<value>" -U
```

`-U` updates in place if the name already exists, so re-running with a new value rotates it safely.

This file is committed to git (it contains no secrets), but each secret's *value*
never leaves Keychain except when actively needed for a specific operation.
