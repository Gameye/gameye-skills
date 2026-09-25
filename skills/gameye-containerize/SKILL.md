---
name: gameye-containerize
description: Package a game server into a Docker image that runs correctly on Gameye — the container contract, Dockerfile patterns, registries, and tag strategy. Use whenever writing a Dockerfile for a game server, containerizing a dedicated server build, debugging a server that works locally but not in a container, or when the user mentions Docker images, registries, tags, or deploying a server build to Gameye. Applies to every engine; use it alongside the engine-specific gameye-*-server skills.
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
   with no drain.
5. **Log to stdout/stderr.** That's what the logs endpoint and Kibana capture. A log
   file inside the container is invisible and dies with the filesystem.
6. **Exit when the match ends.** Exit code 0 ends the session cleanly. Don't idle —
   billing runs per minute of container runtime.
7. **Run as non-root.** Standard container hygiene; game servers have no reason for
   root.
8. **Boot fast.** Players are waiting. Bake all assets at build time; never download
   at startup. Multi-stage builds keep the runtime image small, which also speeds
   fleet preloading of new tags.

## Dockerfile pattern

Annotated skeleton implementing the contract (adjust binary/paths per engine — the
engine skills carry specific variants):

```dockerfile
# ── Build/fetch stage: toolchains and downloads stay out of the runtime image ──
FROM debian:bookworm-slim AS build
# ... fetch or compile the dedicated server, strip client-only assets ...

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM debian:bookworm-slim

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

If your server can write match replays/stats/crash dumps, write them to the artifact
location agreed with Gameye for your application — that's what `GET /artifacts`
tars up after exit (see `gameye-sessions-api`).

## Registry and tags

Push to Docker Hub or AWS ECR (others on request). Gameye integrates with your
registry once, then **preloads new tags onto the fleet automatically** — you never
push to Gameye, and session start doesn't pull cold images.

Tag strategy that works:

- Tag every build with an immutable ID — the git SHA — and additionally move
  `latest`. Start production sessions with an explicit pinned `version`, never
  implicit latest, so a mid-rollout push can't change what the matchmaker launches.
- Applications keep a limited number of tags warm (the "Tags to keep" setting,
  typically 2): current + previous is the working set, which is exactly what a
  deploy-and-rollback flow needs. Don't design around launching old versions.
- After CI pushes a tag, verify it's preloaded before flipping traffic:
  `GET /tag/{region}/{image}/{version}` → `{ "exists": true }` per region you run in.

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
