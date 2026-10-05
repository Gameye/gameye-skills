---
name: gameye-local-testing
description: Prove a game server container behaves identically on a laptop and on Gameye before deploying — parity docker runs, the forced port-asymmetry test, the SIGTERM drain test, boot timing, and the sandbox smoke test sequence. Use before any first deploy or new tag rollout, when a server works locally but fails on Gameye, or when the user mentions testing a game server container, docker run testing, or a Gameye sandbox smoke test.
metadata:
  version: "1.0.0"
---

# Testing before you deploy

Every failure mode this skill catches costs seconds locally and an opaque debugging
session with live players. Run the local battery on every meaningful change; run the
smoke test before any tag reaches real players.

## Parity run

Reproduce exactly what Gameye does: your image, env/args injected, ports mapped.

```bash
docker buildx build --platform=linux/amd64 -t mygame:dev .

docker run --rm --name mygame-test \
  -e GAME_PORT=7777 -e MATCH_ID=local-test -e MAX_PLAYERS=4 \
  -p 25000:7777/udp \
  mygame:dev --tickrate=30
```

Checks, in order:

1. **It boots on amd64.** On Apple Silicon this runs under emulation — slow is fine,
   *crashing* is a real bug you just caught early (usually a native dependency built
   for arm64).
2. **Logs appear via `docker logs mygame-test`** — boot config line, then `READY`.
   If stdout is empty, the Gameye logs endpoint will be empty too (engine logging to
   a file: see your engine skill for the stdout flag).
3. **Time to READY.** Wall-clock from `docker run` to the READY line is what players
   experience as matchmaking delay. Seconds: good. Tens of seconds: find the
   startup download or lazy compile and move it to build time.

## The port-asymmetry test

Deliberately map a host port that differs from the container port — above, host
`25000` → container `7777`. Now connect a real client to `localhost:25000`.

This single test catches the most common class of hosting bug: any place the server
leaks its *bind* port to clients — in a server-browser advertisement, a redirect
handshake, a "reconnect to me on port X" message — instead of letting clients use
the address they were given. On Gameye the public port is never the container port
(bridge-mode allocations land in 20000–30000), so a server that fails this test
works on a laptop with `-p 7777:7777` and loses every player in production.

## The drain test

```bash
docker stop --time 50 mygame-test
```

`docker stop` sends SIGTERM then SIGKILL after the grace period — the same shape as
a Gameye stop request or TTL expiry, and `--time 50` mirrors the configured window of
up to 50 seconds. Don't let the generous window hide a slow drain: verify from the
timestamped logs (`docker logs -t`) that the handler ran and the essentials —
results flushed, artifacts written — land **within about 10 seconds** of SIGTERM,
followed by a clean exit 0 well before the deadline. If the container only dies at the SIGKILL, PID 1 isn't your server
(missing `exec`, shell-form ENTRYPOINT, or `npm start` — see `gameye-containerize`)
or the handler isn't wired.

Also test the natural ending: run a bot match or scripted short match to completion
and confirm the process exits 0 on its own.

## Multi-session sanity

Two sessions on one host is normal on Gameye. Locally:

```bash
docker run -d -e GAME_PORT=7777 -p 25000:7777/udp mygame:dev
docker run -d -e GAME_PORT=7777 -p 25001:7777/udp mygame:dev
```

Both must be independently joinable. Failures here mean a hardcoded singleton
resource — a fixed secondary port, a lock file path, an assumption of exclusivity.

Measure while you're here: `docker stats` during a full match gives the numbers for
resource-profile sizing (`gameye-containerize`).

## Sandbox smoke test

With the tag pushed and the host and token configured — sandbox
(`https://api.sandbox-gameye.gameye.net`) for self-serve customers, production for
enterprise; see `gameye-sessions-api`. When you, the agent, run this sequence, use
the `gameye_*` tools if you have them, otherwise HTTP, per the routing rule in the
`gameye` skill's [references/routing.md](../gameye/references/routing.md). Ask before
starting the session — it is billed.

```
1. GET  /available-location/{image}          → your region is listed
2. GET  /tag/{region}/{image}/{version}      → { "exists": true }  (preload done)
3. POST /session  (version pinned, env, args, ttl "15m", an agent/test label)
                                             → 201; note id, host + ports from the response
4. GET  /session/{id}                        → status reaches "running"
5. GET  /logs?id={id}&follow=false           → boot line + READY visible
6. Connect a real client to host:hostPort    → gameplay works
7. DELETE /session/{id}                      → 204; drain visible in logs
8. Poll describe until "exited", then
   GET /artifacts?session={id}&path=/app/out → uncompressed tar with the expected files
```

Notes: without `follow=false` the logs request stays open until it times out. Use
the session `id` from the start response (a warm pool replaces the one you sent).
Artifacts need both `session` and `path`, return a plain tar (don't gunzip), and are
only kept until the container is removed — fetch right after `exited`.

Automate this sequence in CI with a short-lived token. A tag that passes it has proven the image, the
registry integration, the port bindings, the config injection, the drain path, and
the artifact pipeline — everything `gameye-launch` assumes.
