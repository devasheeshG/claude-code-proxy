# Install Claude Code Proxy with an AI agent

Copy this entire file into a capable coding or operations agent. The agent must
have terminal access to the target host. Keep the agent supervised: it must stop
for your deployment choices and for the Claude OAuth authorization step.

---

You are installing **Claude Code Proxy** from
`https://github.com/devasheeshG/claude-code-proxy` for the user. Own the setup
from discovery through a verified Claude Code client, but follow every safety
requirement below.

## Non-negotiable rules

- Do not make any change until you have completed the interview and the user has
  confirmed your summarized plan.
- Never ask for, display, log, commit, or paste passwords, API keys, OAuth tokens,
  cookies, database credentials, Telegram tokens, or archived request bodies.
- Never ask the user for their Anthropic password, MFA code, session cookie, or
  OAuth token. The user must complete Anthropic authorization in Anthropic's own
  browser flow.
- Do not add an account unless the user controls it and confirms they are
  permitted to use it this way.
- Treat `.env`, Claude Code settings, generated proxy keys, backups, and curl
  config/header files as secrets. Use restrictive permissions (`umask 077`, file
  mode `0600`) and delete temporary secret-bearing files when finished.
- Preserve unrelated files and settings. Never overwrite an existing install,
  database, reverse-proxy configuration, or `~/.claude/settings.json` without a
  backup and explicit confirmation.
- Do not open database, backend, or dashboard ports to the public internet by
  accident. Do not start a second Traefik on ports already owned by another
  gateway.
- Do not run destructive Docker, Git, database, or filesystem commands. Do not
  prune images, volumes, networks, or databases.
- For an existing production installation, read `AGENTS.md`, `README.md`, and the
  deployment scripts first. Updates must use `scripts/blue-green.sh` or
  `make deploy-blue-green`; never perform an in-place production update.
- Do not claim success until the containers, migrations, public health endpoint,
  dashboard login, subscription account, proxy user/key, and client setup have
  each been checked. Clearly report anything the user chose to leave unfinished.

## 1. Interview the user

Ask these questions together in one concise message, explain any option the user
may not recognize, and wait for answers. Do not request secret values in a chat
that may be recorded; arrange a secure interactive prompt or let the user enter
them directly into a protected file or dashboard.

1. Is this a new local/testing install, a new production install, or an update to
   an existing production install?
2. Which absolute directory should contain the repository? If it already exists,
   may you inspect it, and are there local changes that must be preserved?
3. Where will Claude Code run: on this host, on another private-network machine,
   or over the public internet?
4. What hostname or domain should serve the proxy? For production, is its DNS
   already pointed at this host?
5. Which ingress option should be used?
   - bundled Traefik with automatic TLS;
   - an existing Traefik instance;
   - another existing reverse proxy such as Caddy or Nginx; or
   - local-only HTTP.
6. If there is an existing reverse proxy, what Docker network, certificate
   resolver, public entrypoint, and unused loopback/upstream ports should be used?
   Confirm who terminates TLS. If using bundled Traefik, ask for the ACME contact
   email and confirm that ports 80 and 443 are available in production.
7. Should the stack create bundled PostgreSQL 16, or use an existing PostgreSQL
   server? For an existing server, collect the host, port, database, and username
   securely; confirm that an empty database/user can be provisioned and that the
   target is reachable from the application containers. Let the user enter the
   password securely. Do not reuse another application's database.
8. Which host ports may the local setup use? The defaults are HTTP `8080` and
   HTTPS `8443`. Detect conflicts before accepting them.
9. Should raw request/response archiving be disabled, or stored in an existing
   S3-compatible service? If enabled, securely collect the endpoint, region,
   bucket, prefix, path-style requirement, access credentials, whether writes
   must fail closed, and the desired retention policy. Warn that archives can
   contain prompts, responses, and tool payloads.
10. Should Telegram notifications be configured after startup? If yes, ask for
    the desired chat/topic, timezone, event types, and reporting schedule. The
    bot token must be entered only into the protected dashboard or another
    secure input, never echoed.
11. What dashboard admin username should be used? Should strong admin, database,
    and application secrets be generated, or will the user enter them securely?
12. What should the initial proxy user's name, priority, and required API-key
    label be? Ask whether any user limits or model policies are needed. Keep API
    fallback disabled unless the user explicitly enables and configures it.
13. Should the optional Claude Code pool-usage status line be installed? Confirm
    the target OS/user account and whether existing Claude Code settings must be
    preserved.

Summarize the resulting architecture before proceeding: install path, mode,
public origin and API base URL, TLS owner, selected Compose files or override,
database owner, published ports, archive choice, notifications choice, and
client target. Do not include secret values in the summary.

## 2. Inspect the host and repository

After confirmation:

1. Check the operating system, available disk/RAM, current user privileges, DNS,
   listening ports, running containers, Docker networks, and existing proxy or
   database services. Use read-only commands first.
2. Require Git, curl, Docker Engine, and Docker Compose v2. The optional status
   line also requires Bash, `jq`, curl, and GNU `date`/coreutils on the Claude
   Code machine. Install missing packages only after explaining the package
   manager changes and obtaining approval where required.
3. If the destination is empty, clone the repository into the confirmed path:

   ```bash
   git clone https://github.com/devasheeshG/claude-code-proxy.git <confirmed-path>
   ```

   If the repository already exists, inspect its remote, branch, worktree, and
   deployment status. Do not discard changes or replace an existing `.env`.
4. Read `README.md`, `.env.example`, every selected Compose file, and
   `scripts/blue-green.sh` before constructing commands. Also read `AGENTS.md` if
   present and follow it.

## 3. Prepare configuration safely

1. Set `umask 077`. For a new installation, copy `.env.example` to `.env` without
   overwriting an existing file and set `.env` to mode `0600`.
2. Populate the confirmed values. At minimum, set `DOMAIN`, the selected ports,
   `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`,
   `POSTGRES_DB`, `FERNET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and
   `JWT_SECRET`.
3. Generate independent cryptographically random values for all generated
   secrets. `FERNET_KEY` must be a URL-safe base64 encoding of exactly 32 random
   bytes; `JWT_SECRET` must be at least 32 characters. Generate them directly
   into the protected `.env` rather than printing them. Use a URL-safe database
   password because the current application constructs its PostgreSQL URI from
   separate fields.
4. Never use sample values such as `change-me`, reuse a secret between fields, or
   commit `.env`. Confirm with `git status` that no secret file is tracked.
5. With bundled PostgreSQL, keep `POSTGRES_HOST=postgres` and include
   `docker-compose.postgres.yml`. With external PostgreSQL, omit that overlay,
   use a hostname reachable from the containers, verify connectivity without
   printing the password, and let the normal init service apply migrations.
6. With bundled Traefik, include `docker-compose.traefik.yml`. For production set
   `DOMAIN`, `HTTP_PORT=80`, `HTTPS_PORT=443`, `TRAEFIK_ENTRYPOINT=websecure`, and
   `ACME_EMAIL`; confirm DNS and firewall access first.
7. With an existing Traefik, do not launch the bundled Traefik. Create the
   smallest site-specific Compose override that attaches only the backend and
   frontend to its external network and routes `/api` to backend port 80 and `/`
   to frontend port 3000. Preserve the `/api` prefix. Use unique router/service
   names and the confirmed entrypoint/resolver.
8. With Caddy, Nginx, or another gateway, omit bundled Traefik and create a small
   site-specific override publishing backend and frontend only on confirmed
   loopback ports. Configure `/api` to backend port 80 without stripping the
   prefix, and all remaining paths to frontend port 3000. The existing gateway
   must terminate TLS. Validate its configuration before reloading it.
9. For local-only HTTP, include bundled Traefik and retain unused non-privileged
   ports such as `8080`/`8443`. When loopback-only access was requested, bind the
   published values explicitly (for example `HTTP_PORT=127.0.0.1:8080` and
   `HTTPS_PORT=127.0.0.1:8443`) and confirm the rendered Compose ports do not use
   `0.0.0.0`.
10. If archiving is enabled, fill every selected `ARCHIVE_*` setting, enforce
    least-privilege bucket credentials, test bucket access, and confirm the
    retention behavior before enabling deletion. Leave `ARCHIVE_ENABLED=false`
    otherwise.

Keep site-specific overrides outside tracked source unless they are generic and
the user explicitly wants them committed. Validate the exact merged Compose
configuration with `docker compose ... config --quiet`. Inspect the rendered
ports, networks, mounts, and router labels; never print the expanded environment
or a rendered config containing secrets.

## 4. Build, start, and verify the service

For a **new** installation, use the exact Compose-file set selected above. The
common all-in-one command is:

```bash
docker compose \
  -f docker-compose.yaml \
  -f docker-compose.postgres.yml \
  -f docker-compose.traefik.yml \
  up -d --build --wait
```

Omit or replace overlays according to the confirmed architecture. The
`backend-init-db` service performs migrations; do not manually edit Alembic's
version or application tables during a normal installation.

For an **existing production** installation, do not use the command above. Run
`scripts/blue-green.sh status`, validate the blue/green Compose rendering as
documented by the repository, and deploy only with `scripts/blue-green.sh` or
`make deploy-blue-green`. If `scripts/probe-availability.sh` exists, run it
against the public health URL during the rollout; otherwise use a temporary,
non-mutating one-second curl probe with short connection and request timeouts.
Confirm the probe recorded no outage.

Then:

1. Inspect Compose service state and bounded recent logs. Redact sensitive
   values from anything shown to the user.
2. Verify the public endpoint returns a healthy response:

   ```text
   <public-origin>/api/health
   ```

3. Verify the dashboard loads at `<public-origin>/`, its certificate is valid in
   production, and the configured admin login works. Do not put the admin
   password on a command line.
4. If a public health check fails, separately test the internal service and
   ingress path to locate the failure. Do not weaken TLS, authentication, or
   firewall rules as a workaround.

## 5. Add a Claude subscription account

1. Sign in to the dashboard and open **Accounts**.
2. Start **Add account**, enter a clear account label, and obtain the generated
   Anthropic authorization URL.
3. Pause and ask the user to open that URL, authenticate directly with
   Anthropic, approve the requested access, and return only the authorization
   result the dashboard explicitly asks them to paste. Do not observe or request
   their credentials.
4. Complete the dashboard flow and confirm the account is active, its email/tier
   was detected when available, and its provider quota check succeeds. If it
   requires reauthentication or is degraded, diagnose that state rather than
   pretending the account is usable.

## 6. Create the first user and labelled key

1. In **Users**, create the agreed user with the confirmed priority, budgets,
   allowed models/thinking levels, and any model rewrites. Leave fallback off
   unless explicitly requested.
2. Create one API key with the required, meaningful key label. An empty or
   `untitled` label is not acceptable.
3. The plaintext `usr_...` key is shown exactly once. Transfer it directly to a
   password manager or a mode-`0600` client configuration without echoing it,
   including it in screenshots, or leaving it in shell history. Do not store it
   in the repository. Close the one-time reveal only after confirming secure
   storage.

Prefer the dashboard for these operations. If browser automation is unavailable,
guide the user through the two screens. If you use the admin API instead, first
inspect the live OpenAPI schema at `/api/docs`; keep admin and user tokens in
protected files or secure input, never command-line arguments, and remove all
temporary authentication material afterward.

## 7. Configure native Claude Code

The API base URL is the public origin plus `/api`, for example
`https://claude-proxy.example.com/api`.

On the confirmed Claude Code machine and user account:

1. Back up `~/.claude/settings.json` with a timestamp. Parse it as JSON and stop
   if it is invalid; never replace an invalid or non-object file.
2. Merge these values into the existing top-level `env` object while preserving
   every unrelated setting:

   ```json
   {
     "env": {
       "ANTHROPIC_BASE_URL": "https://claude-proxy.example.com/api",
       "ANTHROPIC_AUTH_TOKEN": "<the one-time usr_ key>"
     }
   }
   ```

3. Write atomically and set the settings file to mode `0600`. Keep the real key
   out of terminal output, command history, process arguments, reports, and Git.
4. If the user selected the status line, download it from
   `<api-base>/v1/clients/claude-code-statusline.sh` to a private executable path
   such as `~/.claude/bin/claude-code-statusline.sh`, inspect it before execution,
   set mode `0700`, and merge this object without removing other settings:

   ```json
   {
     "statusLine": {
       "type": "command",
       "command": "/absolute/path/to/claude-code-statusline.sh",
       "refreshInterval": 1
     }
   }
   ```

5. Verify authenticated connectivity without spending tokens by requesting
   `<api-base>/v1/me/usage` with the proxy key using a protected header/config
   file or another method that does not expose it in process listings. Then ask
   the user to start a fresh `claude` session and confirm requests appear in the
   dashboard. Do not send a paid inference merely for testing without approval.

If Claude Code is on another machine you cannot access, generate precise steps
for that machine but do not reveal the key in your response. Let the user paste
the key locally through a hidden prompt.

## 8. Optional notifications

If selected, configure Telegram from **Notifications** only after the core proxy
is healthy. Let the user enter the bot token in the protected dashboard. Set the
confirmed destination, optional topic, timezone, event switches, templates, and
report schedules; send a test notification and confirm receipt. Do not enable
events the user did not request.

## 9. Final checks and handoff

Before declaring completion, confirm:

- migrations completed and every expected service is healthy;
- the public `/api/health` endpoint and dashboard work over the intended URL;
- TLS, ingress, ports, Docker networks, and PostgreSQL match the approved plan;
- at least one authorized Claude account is active and provider-checked;
- the initial user and meaningfully labelled API key exist;
- native Claude Code settings preserve prior values and use the `/api` base URL;
- the optional status line and Telegram test work if selected;
- `.env` and client settings have restrictive permissions;
- no secrets or archives entered Git, shell history, logs, or your final report;
- no unnecessary gateway, database, container, or public port was created.

Give the user a concise handoff containing the install path, repository revision,
deployment architecture, public dashboard/API URLs, service health, account and
user labels (not secrets), backup paths, enabled optional features, and exact
safe commands for status, logs, and future blue-green updates. State where the
user stored the one-time key without reproducing it. List any unresolved warning
or manual follow-up explicitly.
