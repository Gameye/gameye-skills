---
name: gameye-containerize
description: Package a game server into a Docker image that runs correctly on Gameye, and get it from your registry to a launchable tag — the container contract, Dockerfile patterns, Docker Hub / AWS ECR / GHCR access for Gameye, registry webhooks, enabling tags, and tag retention. Use whenever writing a Dockerfile for a game server, containerizing a dedicated server build, building on Apple Silicon, debugging a server that works locally but not in a container, setting up a registry or webhook for Gameye, or when the user mentions Docker images, registries, gameyedocker, tags, or deploying a server build to Gameye. Applies to every engine; use it alongside the engine-specific gameye-*-server skills. API calls for tags and applications (checking, enabling, launching a version) live in gameye-sessions-api.
metadata:
  version: "1.0.0"
---

# Containerizing a game server for Gameye

Gameye runs whatever Linux container you give it, with `env` and `args` from the
session-start call injected in. That freedom means the contract lives in your image.
Get these invariants right and everything downstream works.

## The container contract

1. **`linux/amd64` only.** The fleet is x86_64 and Windows containers are not
   supported. On Apple Silicon, `docker build` silently produces arm64 — always build
   with `docker buildx build --platform=linux/amd64`. An arm64 image is the single
   most common "works on my machine, dies on Gameye" failure, and it fails opaquely
   (the container just never comes up).
2. **Bind fixed container ports on `0.0.0.0`.** Your application's port bindings
   (protocol + container port, configured in the Admin Panel) must match what the
   server actually binds and what the Dockerfile `EXPOSE`s. In the default `bridge`
   network mode Gameye maps each container port to a public host port (20000–30000)
   and returns the mapping from `POST /session`; the server itself never needs to
   know its public address. (`host` network mode also exists, where container port =
   host port — only relevant if Gameye configures your application that way.)
3. **Configuration arrives at runtime.** `env` and `args` from the session-start call
   are the only per-match inputs. Same image for sandbox, production, every region,
   and local testing. No baked secrets, no baked backend URLs.
4. **PID 1 must receive SIGTERM.** Stop requests and TTL expiry deliver SIGTERM to
   PID 1. `exec` the server binary from your entrypoint script — a shell that stays
   wrapped around the process swallows the signal and the server gets hard-killed
   with no drain. Flush the essentials (results, stats, artifacts) within about 10
   seconds of SIGTERM; the configured grace window before a hard kill can be up to
   50 seconds, but don't design around the maximum.
5. **Log to stdout/stderr.** That's what the logs endpoint (`GET /logs`) captures. A log
   file inside the container is invisible and dies with the filesystem.
6. **Exit when the match ends.** Exit code 0 ends the session cleanly. Don't idle —
   billing runs per minute of container runtime.
7. **Run as non-root.** Standard container hygiene; game servers have no reason for
   root.
8. **Boot fast.** Players are waiting. Bake all assets at build time; never download
   at startup. Multi-stage builds keep the runtime image small, which also speeds
   fleet preloading of new tags.
9. **No Gameye API token in the image or the session env.** The token belongs to
   your backend only (game server → your backend → Gameye). Launch env is readable
   back through the sessions API by any token in your organization with
   `session:read`, so pass only short-lived per-match values (a join secret, a
   match ID) — never a Gameye token or long-lived credentials.

## Dockerfile pattern

Annotated skeleton implementing the contract (adjust binary/paths per engine — the
engine skills carry specific variants):

```dockerfile
# ── Build/fetch stage: toolchains and downloads stay out of the runtime image ──
FROM debian:bookworm-slim AS build
# ... fetch or compile the dedicated server, strip client-only assets ...

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM debian:bookworm-slim

# Unique per build, so registry webhooks fire even for identical content
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.revision=$GIT_SHA

# Non-root user
RUN groupadd --system --gid 10001 game \
 && useradd  --system --uid 10001 --gid game --no-create-home \
             --shell /usr/sbin/nologin game

WORKDIR /server
COPY --from=build --chown=game:game /out/ /server/
COPY --chown=game:game entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER game

# Must match the application's port bindings in the Gameye Admin Panel
EXPOSE 7777/udp

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
```

```bash
#!/usr/bin/env bash
# entrypoint.sh — defaults, config rendering, then exec (contract items 3 and 4).
set -euo pipefail

export GAME_PORT="${GAME_PORT:-7777}"
export MAX_PLAYERS="${MAX_PLAYERS:-16}"

echo "boot: port=${GAME_PORT}/udp max_players=${MAX_PLAYERS} match=${MATCH_ID:-none}"

# If the engine wants a config file, render it here from env (envsubst on a
# template works well) rather than baking one in.

exec /server/game-server --port "${GAME_PORT}" --max-players "${MAX_PLAYERS}" "$@"
```

`"$@"` forwards session `args`, so `env` covers standing config and `args` covers
per-match extras — support both and let your backend choose. Note the entrypoint uses
`ENTRYPOINT` exec-form + `exec`: both halves matter for signal delivery.

If your server writes match replays, stats or crash dumps, write them to a known
directory inside the container. After the session exits your backend fetches them
with `GET /artifacts?session=<session-id>&path=<container-path>`, which returns a
plain (uncompressed) tar — see `gameye-sessions-api`.

## Build and push

Tag every build with an immutable ID — the git SHA — and stamp the same SHA as the
revision label:

```bash
SHA=$(git rev-parse --short HEAD)
docker buildx build --platform=linux/amd64 \
  --build-arg GIT_SHA="$SHA" \
  -t <registry>/<repo>:"$SHA" --push .
```

You can additionally move `latest`, but start production sessions with an explicit
pinned `version`: omitting `version` runs the most recently registered tag, so a
mid-rollout push would change what the matchmaker launches. Re-pushing an existing
tag name (such as `latest`) does not make Gameye pull a new image.

## Registries: from push to launchable tag

Gameye pulls from your registry and **preloads tags onto the fleet** — you never
push to Gameye, and session start doesn't pull cold images. Three steps, once per
registry; full click paths, webhook fields and troubleshooting are in
[references/registries.md](references/registries.md).

**1. Give Gameye pull access** (account `gameyedocker`, unless Gameye names another):

| Registry | Access |
|---|---|
| Docker Hub | Add `gameyedocker` as a **read-only** collaborator on the private repository. |
| AWS ECR | Pull access is configured with Gameye during onboarding — ask your Gameye contact. |
| GHCR (`ghcr.io`) | *Confirm with Gameye support that GHCR is enabled for your environment first — GHCR support is not generally released.* Package settings → Manage access → invite `gameyedocker` with **Read**. If Invite is missing, untick **Inherit access from source repository**. Never share via a personal-account repository: it has no Read role, so that grants write. |

**2. Register the application** in the Admin Panel (or `POST /application`) with
the registry and the repository *without* a tag, ports, resources, regions and
node pool. `tagKeep` ("Tags to keep") sets how many tags stay warm.

**3. Make each new tag launchable** — either:

- **Webhook (automatic):** the registry notifies Gameye on every push and the tag
  is registered. Docker Hub posts to
  `https://anything:<TOKEN>@<host>/v1/integrations/dockerhub` with a
  `webhook:dockerhub` token as the password. GitHub (GHCR, same enablement caveat)
  posts to `https://<host>/v1/integrations/github/<ORGANIZATION-ID>` with a
  `webhook:github`-only token as the signing secret and only the **Packages** event.
  GitHub deliveries can lag a few minutes, and pushing an image identical to an
  existing version sends nothing — the revision label above keeps each build unique.
- **Manual:** list what Gameye can see in the registry with
  `GET /application/{name}/tags/available`, then enable the exact tag with
  `POST /application/{name}/tags` and body `{"tag": "<sha>"}` (204 on success), or
  pick it in the Admin Panel tag picker.

**Then confirm per region** before flipping traffic:
`GET /tag/{region}/{image}/{version}` → `{"exists": true}` for every region you run in.

Hosts: self-serve customers use `https://api.sandbox-gameye.gameye.net` (their
permanent environment); enterprise customers use
`https://api.production-gameye.gameye.net`.

## Tag retention

Applications keep a limited number of tags warm (`tagKeep`, "Tags to keep",
typically 2): current + previous is the working set, which is exactly what a
deploy-and-rollback flow needs. Pin immutable SHA tags in your session-start calls
and don't design around launching old versions.

## Resource profile fit

Your application declares guaranteed CPU/RAM (not oversubscribed — and directly
billed). Measure the server under a full match (`docker stats` while bots or a load
test run) and size the profile to peak-plus-margin. An undersized profile shows up as
tick-rate drops and lag complaints, an oversized one as pure cost.

## Verify before shipping

`gameye-local-testing` covers the full parity checklist (forced port asymmetry,
SIGTERM drain test, boot timing). Minimum bar before pushing any tag:

```bash
docker buildx build --platform=linux/amd64 -t mygame:dev .
docker run --rm -e GAME_PORT=7777 -p 25000:7777/udp mygame:dev
# server comes up, logs the boot line to stdout, accepts a client on :25000
```
