# Claude Code Proxy

A self-hosted proxy that lets a team share a **pool of Claude subscription accounts** through one endpoint — with **automatic, quota-aware rotation**, **transparent failover**, **per-user/per-key usage tracking**, and a web dashboard.

Each person points their Claude Code at your server with a personal `usr_…` key. The proxy authenticates the key, picks the highest-priority eligible pooled account for every request (accounts are never pinned to a user), keeps each account's OAuth token fresh, rotates away from accounts nearing their 5h/7d limits, fails over on provider capacity and rate limits, and records exactly how many tokens each user and key consumed.

```
Claude Code ──Bearer usr_…──►  Traefik proxy ─►  Backend (FastAPI)  ──Bearer <rotated OAuth>──►  api.anthropic.com
 ANTHROPIC_BASE_URL=              /api → backend    1. authenticate key → user
   http://localhost:8080/api      /    → dashboard  2. per-key rate-limit + token budget
 ANTHROPIC_AUTH_TOKEN=usr_…                         3. pick highest-priority pooled account
                                                    4. refresh token, inject OAuth bearer
 Admin ─► Dashboard (Next.js) ◄── same origin       5. capacity → 60s cooldown; 429 → failover
                                                    6. capture tokens → per-user / per-key ledger
```

> ⚠️ **Legal / Terms of Service.** Claude Pro/Max subscriptions are intended for individual use. Sharing or rotating personal subscription accounts across multiple people may violate Anthropic's terms and can get accounts banned. This project is provided for educational and self-hosting purposes — **run it only with accounts you control and with that risk understood.** A banned account can be disabled with one click and rotation continues. "Claude" and "Anthropic" are trademarks of Anthropic; this is an independent, unaffiliated project.

## Features

- **Account pooling + automatic rotation** — priority-ordered selection on every request, lowest-load tie-breaking, and transparent failover on model capacity and `429`s.
- **Per-user, multi-key access** — a user can hold several `usr_…` keys (laptop, CI, …); the plaintext is shown once.
- **Per-user policy controls** — allow selected thinking levels, enforce monthly/lifetime token and API-equivalent USD caps, and rewrite requested model IDs to upstream Claude models.
- **Per-key rate limits and monthly token budgets** — contain a noisy or leaked key.
- **Anthropic API fallbacks** — connect multiple encrypted Anthropic-compatible API keys with custom base URLs, independent priorities, optional monthly USD spend caps, health checks, cooldowns, and enable/disable lifecycle controls. Subscription accounts are always attempted first; fallbacks are used only when no subscription account can serve the request.
- **Usage analytics** — per-user/per-key token and request tracking, API-equivalent USD value, daily activity, peak-hour distribution, and a full request log. Subscription spend is an API-price equivalent, not an amount billed by Anthropic.
- **Subscription tier + live quota** — each account's tier and provider-reported 5h/7d/monthly utilization, refreshed every minute by a sidecar. The dashboard only renders windows returned by Anthropic.
- **Self-service status line** — `GET /v1/me/usage` + a drop-in Claude Code status line showing your usage and average available-pool headroom, with explicit unknown-window counts and reset timing.
- **Encrypted at rest** — OAuth tokens are Fernet-encrypted; API keys are stored only as SHA-256 hashes.
- **Composable Docker deploy** — main app services in one file, with bundled Postgres and a bundled Traefik (local HTTP or production HTTPS via Let's Encrypt) as opt-in overlays.

## How the Compose files fit together

The deployment is split into one main file plus two opt-in overlays, so you can mix the bundled services with your own:

| File | Provides | When to include |
| --- | --- | --- |
| `docker-compose.yaml` | The main app services: DB migration, backend, quota refresher, notification dispatcher, and dashboard. | Always. |
| `docker-compose.postgres.yml` | A bundled PostgreSQL with a persistent volume. | Unless you point `POSTGRES_*` at your own database. |
| `docker-compose.traefik.yml` | A bundled Traefik that fronts the dashboard and API on **one origin** (local HTTP, or production HTTPS via Let's Encrypt). | Always — it's how the services are reached. |

The app services never publish host ports; everything is reached through Traefik. Stack the files with repeated `-f` flags (each `up`/`down`/`logs` command needs the same set).

## Quickstart (local, all-in-one)

Prerequisites: Docker + Docker Compose.

```bash
cp .env.example .env
```

Generate the required secrets and put them in `.env`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # FERNET_KEY
python -c "import secrets; print(secrets.token_urlsafe(48))"                                  # JWT_SECRET
```

Set `FERNET_KEY`, `JWT_SECRET`, `ADMIN_PASSWORD`, and `POSTGRES_PASSWORD` (the backend refuses to start with empty/placeholder/weak admin secrets). Then:

```bash
docker compose -f docker-compose.yaml -f docker-compose.postgres.yml -f docker-compose.traefik.yml up -d --build
```

This brings up Postgres (with a persistent volume), runs the database migration, and starts the backend, the quota-refresher sidecar, the dashboard, and a Traefik proxy that serves everything on one origin:

- Dashboard: `http://localhost:8080`
- API base URL for Claude Code: `http://localhost:8080/api`

(Change the port with `HTTP_PORT` in `.env`.) Log in to the dashboard with `ADMIN_USERNAME` / `ADMIN_PASSWORD`. To tear it down, repeat the same `-f` flags with `down` (add `-v` to also drop the database volume):

```bash
docker compose -f docker-compose.yaml -f docker-compose.postgres.yml -f docker-compose.traefik.yml down
```

## Add a Claude account to the pool

Accounts → *Add account* → open the authorize link → approve → paste the resulting `code#state` back. The proxy exchanges it for tokens and refreshes them automatically thereafter.

## Add an Anthropic API fallback

Open **API fallbacks** in the dashboard and add a label, an Anthropic-compatible
API origin (the default is `https://api.anthropic.com`), and an API key. The key
is encrypted with `FERNET_KEY` and is write-only: after saving, the dashboard
shows only a masked suffix and the API never returns the credential. Each entry
can have its own priority, optional monthly USD spend cap, custom base URL, and
enable/disable state. The proxy probes `/v1/models`, routes only after the
subscription pool cannot serve a request, cools down transient failures, and
records API-equivalent spend using the local pricing table. A request that
crosses a cap may overshoot it because the cap is checked before dispatch; a
model with no known local price contributes zero to the spend ledger until its
pricing is added.

## Onboard a user and point Claude Code at the proxy

1. Dashboard → **Users → Create user**, then expand the user and **add a key**. Copy the one-time `usr_…` secret (shown only once). You can set optional per-user monthly/lifetime token caps, monthly/lifetime API-equivalent USD caps, exact model rewrite rules, and per-key rate/token limits.
   The Users and Accounts pages show all-time and current-month spend alongside token usage. A request that crosses a cap may overshoot it because actual response usage is known only after completion; subsequent requests are rejected.
2. Run the setup command shown with the new key. It updates only the proxy
   values in `~/.claude/settings.json`, preserving every unrelated setting and
   keeping the previous file as `settings.json.bak`. The resulting config is:

   ```json
   {
     "env": {
       "ANTHROPIC_BASE_URL": "http://localhost:8080/api",
       "ANTHROPIC_AUTH_TOKEN": "usr_their_key_here"
     }
   }
   ```

   (Or export `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` in your shell.) Run `claude` — it now routes through the proxy, and the usage appears on the dashboard.

### Optional: usage in your Claude Code status line

Because Claude Code runs in API-key mode against the proxy, it doesn't show subscription limits. `clients/claude-code-statusline.sh` restores that, in the style of [claude-code-usage-bar](https://github.com/leeguooooo/claude-code-usage-bar): a two-line bar showing the available pool's average 5h/7d usage with the earliest upcoming reset timers (from `GET /v1/me/usage`), plus the model, context window, and prompt-cache countdown that Claude Code reports locally on stdin. The endpoint also exposes every available account's reset timestamp and counts windows whose provider value is unknown; the status line intentionally uses only the earliest upcoming reset.

```
5h[██░░░░░░] 38% ⏰3h12m │ 7d[███████░] 93% ⏰2d3h │ Opus 4.8 (64.6k/1.0M) │ cache 4m23s
⤷ claude-code-proxy ⎇ main● · +182 -47 · ⏱ 12m
```

The `5h`/`7d` bars are the **average usage of currently available accounts**, not a personal Anthropic window — through a relay, Anthropic's own per-user rate-limit headers never reach Claude Code, so the proxy fills them in. Unknown provider values are excluded from the arithmetic average and reported explicitly in the API rather than treated as zero. Requires `jq`, `curl`, and GNU `date` (coreutils). Copy the script somewhere on disk, make it executable, and point Claude Code at it in `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "/absolute/path/to/claude-code-statusline.sh",
    "refreshInterval": 1
  }
}
```

`refreshInterval: 1` lets the `cache` countdown tick every second; the call to the proxy is disk-cached for 30s regardless, so CPU stays low. If the proxy is unreachable the bar drops the 5h/7d segments and keeps the local ones — it never blocks Claude Code.

## API compatibility

The Claude proxy exposes Anthropic Messages operations for Claude Code:

- `POST /api/v1/messages` for streaming and non-streaming messages.
- `POST /api/v1/messages/count_tokens` for Anthropic token counting.

It does not expose OpenAI `POST /v1/chat/completions` or `POST /v1/responses`.
Those are OpenAI Platform API operations and are not provided by Claude
subscription credentials. Use the Anthropic endpoint above with a proxy API
key; the proxy forwards requests to Anthropic using the selected Claude
subscription account.

When configured, `/api/v1/fallbacks` manages Anthropic-compatible API
credentials for the same Messages operations. Fallback requests use the
configured origin plus `/v1/messages` (or `/v1/messages/count_tokens`) and
`x-api-key` authentication; OAuth-only subscription headers are not added.

### Optional: prompt cache duration (1 hour vs 5 minutes)

Anthropic's prompt cache keeps your context warm so repeat turns consume far less of your rate-limit quota. Because Claude Code talks to the proxy in API-key mode, it defaults to the **5-minute** cache TTL — so if you pause for more than 5 minutes, the next turn pays full price again. You can opt into the **1-hour** TTL instead; the proxy forwards the cache-TTL request untouched and the pooled subscription honours it.

This is a Claude Code client setting, so each user chooses their own. Add to the `env` block of `~/.claude/settings.json`:

```json
{
  "env": {
    "ENABLE_PROMPT_CACHING_1H": "1"
  }
}
```

| Want | Set in the `env` block |
| --- | --- |
| 1-hour cache | `"ENABLE_PROMPT_CACHING_1H": "1"` |
| 5-minute cache (default) | omit the above, or force it with `"FORCE_PROMPT_CACHING_5M": "1"` |
| No caching at all | `"DISABLE_PROMPT_CACHING": "1"` |

Restart Claude Code after changing it. The status line's `cache` segment auto-detects whichever TTL is actually in effect (it reads the per-turn `cache_creation` bucket from the transcript), so the countdown will start showing `~59m` instead of `~4m` once 1-hour caching is active. Trade-off: 1-hour cache *writes* cost a bit more, but *reads* stay at ~10% of the input rate — so it's worth enabling whenever you have gaps longer than 5 minutes between turns.

## Production deployment (HTTPS)

The bundled Traefik can serve real HTTPS with automatic Let's Encrypt certificates. In `.env`, set `DOMAIN` to your host, set `ACME_EMAIL`, switch the routers to TLS with `TRAEFIK_ENTRYPOINT=websecure`, and bind the standard ports with `HTTP_PORT=80` and `HTTPS_PORT=443`. Make sure the DNS for `DOMAIN` points at the host and ports 80/443 are open (the TLS challenge needs 443). Then bring it up with the same files:

```bash
docker compose -f docker-compose.yaml -f docker-compose.postgres.yml -f docker-compose.traefik.yml up -d --build
```

Traefik obtains a certificate on first request and routes `https://${DOMAIN}/` to the dashboard and `https://${DOMAIN}/api` to the backend (the cert is persisted in a named volume). To use an external Postgres instead of the bundled one, point `POSTGRES_*` at it and drop `-f docker-compose.postgres.yml` from the command.

## Zero-downtime Blue-Green deployment

Use `scripts/blue-green.sh` (or `make deploy-blue-green`) for production
updates when one Traefik instance already fronts the shared Docker network. The
script builds the next generation in a separate Compose project
(`claude-code-proxy-blue` or `claude-code-proxy-green`), waits for healthchecks,
promotes its routers, continuously probes `/api/health` in the background, and
drains the old generation. The API router has a higher priority than the
dashboard router, and every promotion raises the slot priority to avoid ties.

```bash
BG_COMPOSE_FILES=docker-compose.yaml:docker-compose.live.yml \
BG_URL=https://claude-proxy.example.com \
make deploy-blue-green

scripts/blue-green.sh status
```

The first run treats the existing `claude-code-proxy` Compose project as the
legacy generation and creates blue; subsequent runs alternate slots. The state
file is ignored by git. If a run is interrupted, its cleanup trap removes the
target project so stale Traefik routers are not left behind. Set
`BG_KEEP_OLD=1` to retain the old slot for rollback; otherwise HTTP services and
singleton workers are stopped after `BG_DRAIN_SECONDS`.

Routing uses Docker labels only. The deployment never writes Traefik rule files
or hardcoded container IPs; Docker/Traefik discovers each slot from its Compose
labels, with the API priority above the dashboard priority. The background probe
reports any handoff failures and interrupted runs remove the target project.
The backend is promoted and verified first, followed by the frontend. Both
public routes must return the new slot in `X-Deployment-Slot` before the old
slot is drained, preventing the frontend from intercepting API requests during
the handoff.

For a bundled gateway, start Traefik once and exclude it from slot services.
Blue-green slots must use an external/shared PostgreSQL instance; do not start
the fixed-name bundled Postgres in both slots:

```bash
docker compose -p claude-code-proxy-gateway \
  -f docker-compose.yaml -f docker-compose.traefik.yml \
  up -d traefik
BG_COMPOSE_FILES=docker-compose.yaml:docker-compose.traefik.yml \
BG_SERVICES='backend-init-db backend quota-refresher notification-dispatcher frontend' \
BG_URL=http://localhost:8080 make deploy-blue-green
```

Do not run two Traefik gateways on the same published ports. Render and inspect
labels before an update with:

```bash
BG_SLOT=blue BG_PRIORITY=1 BG_API_PRIORITY=2 \
  docker compose -f docker-compose.yaml -f docker-compose.live.yml config --quiet
```

## Telegram notifications

Open **Notifications** in the dashboard to connect a Telegram bot. The bot
token is encrypted with `FERNET_KEY` and is never returned to the browser after
it is saved. Configure the destination group/chat ID and, for forum groups, an
optional topic ID. Set the **Timezone** field to the IANA timezone that should
define report boundaries and delivery timing (the default is `Asia/Kolkata`,
Indian Standard Time), then use **Send test** to verify delivery.

Every account, pool, user, and API-key event can be enabled independently. Its
plain-text message template and repeat cooldown are editable in the same page.
Messages are written to a persistent outbox and delivered by the
`notification-dispatcher` service, so Telegram latency or downtime never blocks
proxy traffic. Account and pool signals are enabled by default; noisy user/key
guardrail signals start muted.

The connected bot also supports on-demand account status queries in the saved
chat (and only in the saved forum topic, when one is configured):

```text
/claude status usable
/claude status available
/claude status all
```

`usable` shows healthy accounts that can serve traffic immediately. `available`
matches the dashboard's active pool: enabled, authenticated accounts, including
accounts that are temporarily unusable because of quota or degraded
health. `all` also includes disabled and reauthentication-required accounts. Each
entry reports the account label and email, remaining usage for both the
five-hour and weekly windows, both rotation thresholds, and current eligibility
status. A provider reset time is shown only when one is available, using the
notification timezone. The
command defaults to `usable` when the argument is omitted. Give each independently
deployed proxy its own bot token: Telegram
permits only one reliable `getUpdates` consumer per bot, so sharing a token
between proxy deployments can make command updates race.

The dashboard's **Authenticated accounts** filter normally excludes accounts
whose provider health is `REAUTH_REQUIRED`. An account can be explicitly marked
**Show in Authenticated accounts** from its Edit dialog to keep it visible while
you investigate or re-authenticate it. This presentation-only override never
changes provider health, usable/available eligibility, or request routing.
This proxy does not expose banked limit-reset redemption: the integrated
Anthropic subscription flow has no equivalent reset-credit operation to gate
by weekly usage.
Expired 429 cooldowns are normalized back to Active automatically when accounts
are listed, so stale cooldown labels cannot hide an eligible account.

The available events are:

| Event | When it is sent | Default | Repeat cooldown |
| --- | --- | --- | --- |
| **Telegram notifier connected** | Once, when a Telegram token and destination are saved and the channel is enabled for the first time. Re-enabling it later does not resend the event. | On | Once |
| **Pooled Claude account added** | After a new Claude subscription account is saved and its first quota probe completes. Includes the account label, email, plan, usage, and pool capacity by default. | On | Once per account |
| **Account authentication expired** | When stored OAuth credentials are rejected or unreadable and the account first enters reauthentication-required state. A normal access-token expiry that refreshes successfully does not trigger it. | On | Once per authentication cycle |
| **Account rotation threshold reached** | Once per limiting five-hour or weekly quota window when that window reaches its own configured rotation threshold and the account is removed from selection. If the weekly window remains exhausted, later five-hour windows do not create duplicate alerts. | On | Once per limiting window |
| **Provider hard usage limit reached** | Once per limiting five-hour or weekly quota window when Anthropic reports a hard limit, blocked state, or payment-required state and traffic fails over. | On | Once per limiting window |
| **Entire account pool unavailable** | When an incoming request has no account available and is about to receive `503`. It only repeats after the cooldown when another request arrives. | On | 15 minutes |
| **User request rate limit exceeded** | When the user's combined API-key traffic exceeds its requests-per-minute limit and the request receives `429`. | Off | 15 minutes |
| **User monthly token budget exhausted** | When the user's month-to-date usage reaches its configured token budget and the next request receives `403`. | Off | 60 minutes |
| **API key request rate limit exceeded** | When one API key exceeds its own requests-per-minute limit and receives `429`; the user's other keys are unaffected. | Off | 15 minutes |
| **API key monthly token budget exhausted** | When one API key reaches its month-to-date token budget and receives `403`; the user's other keys remain available. | Off | 60 minutes |
| **Daily usage report** | After the previous local calendar day completes. Includes total requests, total tokens, and every active user (a user with usage in that period) with request/token shares. | On | Once per day |
| **Weekly usage report** | After the previous Monday–Sunday local reporting week completes. Includes the same totals and active-user distribution. | On | Once per week |
| **Monthly usage report** | After the previous local calendar month completes. Includes the same totals and active-user distribution. | On | Once per month |

Each event's template, enabled state, and cooldown can be customized independently.
The authentication-expired template exposes `account_label`, `account_email`,
`account_tier`, `authentication_code`, `authentication_reason`, `event_time`,
and `dashboard_url`. It becomes eligible again only after the account
successfully authenticates and later returns to reauthentication-required state.
Account templates expose explicit `five_hour_usage_percent`,
`five_hour_reset_at`, `weekly_usage_percent`, `weekly_reset_at`, and
`limiting_window` variables. Usage-percent variables render numeric percentage
values (for example, `42.5`), so templates can append `%`. The older `session_usage_percent`,
`session_reset_at`, `usage_percent`, and `reset_at` names remain valid for
already-customized templates.
Report templates expose `period_start`, `period_end`, `generated_at`,
`total_requests`, `total_tokens`, `user_count`, and `user_distribution`.

## Configuration

All configuration is via `.env` (see `.env.example` for the annotated list):

| Variable | Default | Purpose |
| --- | --- | --- |
| `HTTP_PORT` | `8080` | Host port Traefik publishes for HTTP (set to `80` in production). |
| `HTTPS_PORT` | `8443` | Host port Traefik publishes for HTTPS (set to `443` in production). |
| `DOMAIN` | `localhost` | Public host; also the CORS origin. |
| `LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR`. |
| `POSTGRES_*` | — | Database connection (bundled Postgres by default). |
| `FERNET_KEY` | — | **Required.** Encrypts OAuth tokens at rest. |
| `JWT_SECRET` | — | **Required**, ≥ 32 chars. Signs admin sessions. |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / — | Dashboard login. |
| `QUOTA_REFRESH_INTERVAL_SECONDS` | `60` | How often the sidecar re-probes account quota/tier. |
| `WARMUP_ENABLED` | `true` | Enable demand-triggered and manual account warm-up. |
| `WARMUP_TRIGGER_POOL_USAGE_PCT` | `0.10` | Aggregate eligible five-hour pool usage that starts a batch. |
| `WARMUP_WEEKLY_RESERVE_PCT` | `0.90` | Stop synthetic traffic at this weekly utilization. |
| `WARMUP_MODEL` | `claude-haiku-4-5` | Minimal model used for warm-up requests. |
| `DEFAULT_KEY_RATE_LIMIT_PER_MINUTE` | `0` | Default per-key requests/min (0 = unlimited). |
| `ARCHIVE_ENABLED` | `false` | Capture exact Messages request/response bodies in S3-compatible storage. |
| `ARCHIVE_REQUIRED` | `true` | Fail closed if an archive write cannot be completed. |
| `ARCHIVE_S3_*` | — | S3/MinIO endpoint, `cc-proxy` bucket, credentials, and retry settings. |
| `TRAEFIK_ENTRYPOINT` | `web` | Traefik entrypoint the routers use; set to `websecure` for production HTTPS. |
| `ACME_EMAIL` | — | Contact for Let's Encrypt; only used when `TRAEFIK_ENTRYPOINT=websecure`. |

When `ARCHIVE_ENABLED=true`, the proxy stores exact client-facing request and
response bytes for `/api/v1/messages` and `/api/v1/messages/count_tokens`
directly in S3/MinIO. Every interaction has a UUID and a date-partitioned prefix
with exactly two gzip-compressed request/response objects. The proxy forwards
response chunks immediately while buffering only its private archive copy, then
writes one complete response.json.gz object. Authentication and cookie
headers are never stored; request bodies can still contain sensitive prompt or
tool data, so bucket access and retention must be restricted.

Rotation policy — the independent five-hour and weekly utilization thresholds,
post-`429` cooldown, and failover budget — is configured **per account in the
dashboard** (new accounts start at `1.0` / `1.0` / `60s` / `3`), not via
environment variables. Existing accounts inherit their former single
threshold for both windows during schema reconciliation.
When accounts share a priority, routing prefers the earliest known weekly reset;
if weekly reset data is unavailable or tied, it prefers the earliest known
five-hour reset, then falls back to a deterministic account order.
Editing an account's priority changes only that account, so multiple accounts
may intentionally share a priority level.

### Account-window warm-up

Warm-up stays completely idle until successful real traffic consumes the
configured share of the eligible pool's aggregate five-hour capacity (10% by
default). The backend then schedules one background batch that sends a minimal
internal Messages request to every other eligible account whose five-hour
window has not started. An advisory lock prevents concurrent requests from
starting duplicate batches.

Disabled, reauthentication-required, cooled-down, already-warm, and
weekly-reserve accounts are skipped. Administrators can also use the **Warm
Up** button on an account card to start one eligible cold account immediately.
Warm-up requests are not attributed to an API user or key, but they do consume
a small amount of provider capacity.

The complete schema is defined by the single canonical Alembic revision `001`
in `001_initial_migration.py`. Production databases created from the former
history are stamped to this schema-equivalent head without replaying migrations
or changing application data. The database-init service performs this guarded
transition automatically from known equivalent former heads (`0011` and
`002`–`005`);
unknown or older revision states fail closed instead of being stamped blindly.

## Architecture

- `backend/` — FastAPI app: the streaming proxy (`/api/v1/messages`), Anthropic API fallback management (`/api/v1/fallbacks`), the admin API (`/api/v1/{auth,accounts,users,stats,notifications}`), the self-service endpoint (`/api/v1/me/usage`), sync SQLAlchemy → Postgres, and Alembic. Runtime scripts live in `app/scripts/` (run with `python -m app.scripts.<name>`).
- `frontend/` — Next.js (App Router) admin dashboard (pnpm, standalone).
- `docker-compose*.yml` — the main app services, plus the bundled Postgres and Traefik overlays.
- `clients/` — end-user helpers (the Claude Code status line).

How a request flows: the `usr_` key arrives as `Authorization: Bearer` (or `x-api-key`); the proxy validates its hash, enforces the key's rate limit + budget, picks the highest-priority eligible pooled account (skipping disabled/cooled-down/over-threshold ones; no user pinning), refreshes the OAuth token if near expiry, injects the bearer + the `oauth-2025-04-20` beta header, streams the SSE response back, and records token usage parsed from the stream. Refresh-token rotation is serialized per account; if Anthropic returns a 401 before the JWT expiry, the proxy performs a locked forced refresh without writing a stale synthetic expiry. A capacity response places that account into a 60-second temporary cooldown and the request immediately moves to the next account; a `429` also parks the account on cooldown and the request is retried on the next account before any bytes reach the client. Only when every eligible subscription account is unavailable does it try enabled, healthy, under-budget Anthropic API fallbacks using `x-api-key`; fallback traffic is billed locally and attributed separately in the usage log.

### Upstream capacity failover

Capacity responses such as “Selected model is at capacity”, “try a different
model”, “service exhausted”, or temporary provider overload are handled before
any response bytes reach the client. The account is placed into a 60-second
temporary cooldown and the next eligible account is tried immediately. The
cooldown prevents a thundering herd while leaving the account available again
for a later request. The same behavior is applied to configured API fallbacks.

## Development

```bash
# Run the complete backend and frontend verification suite.
make verify

# In an operator checkout with docker-compose.live.yml configured:
make deploy          # rebuild and deploy every service
make deploy-frontend # rebuild only the dashboard frontend

# Backend
cd backend && uv sync && make lint && uv run pytest

# Frontend
cd frontend && pnpm install && pnpm lint && pnpm build
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for conventions and [SECURITY.md](SECURITY.md) for the threat model.

## License

[AGPL-3.0](LICENSE). If you run a modified version as a network service, you must make your source available to its users.

