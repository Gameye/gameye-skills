---
name: gameye-server-design
description: Design an authoritative dedicated game server that fits session-based hosting on Gameye. Use whenever adding multiplayer to a game, converting a client-hosted or peer-to-peer game to dedicated servers, or when the user asks about netcode architecture, authoritative servers, match lifecycle, server tick loops, cheat prevention, or how a game server should behave — even if Gameye isn't mentioned yet. Engine-agnostic; apply it before any engine-specific server skill.
metadata:
  version: "1.0.0"
---

# Designing a server for session-based hosting

A Gameye session is one container running one match. Everything in this skill follows
from that: the server is born for a specific match, lives exactly as long as the match,
and dies when it ends. Servers designed as long-lived daemons with internal lobby
rotation fight the platform; servers designed as single-match processes get scaling,
billing, and crash isolation for free.

## Authority

The server owns the truth. Clients send *intents* (inputs, actions); the server
simulates, validates, and broadcasts resulting *state*. Never trust a client-reported
outcome — position, score, currency, hit registration — because any client can be
modified. This is the entire reason dedicated servers exist; give it up and you've
built an expensive relay.

Standard companions to authority, apply as the game demands:

- **Client prediction + reconciliation** for the local player's movement, so input
  feels instant despite RTT. The server remains authoritative; the client replays
  unacknowledged inputs on top of server state.
- **Interpolation** for remote entities (render ~100ms in the past between known
  snapshots) rather than extrapolation.
- **Server tick rate** as a deliberate budget decision: 60Hz for fast shooters, 20–30Hz
  for most action games, 10Hz for slow sims. Tick rate × entity count × player count
  is your CPU bill — it must fit the resource profile (guaranteed CPU/memory)
  configured for your Gameye application.

## The session lifecycle contract

Design the server process to move through exactly these phases:

**1. Boot fast.** Players are staring at a loading screen while the container starts.
Do nothing at boot that can be done at build time (bake assets into the image, don't
download them). Target seconds, not minutes.

**2. Read configuration from the environment.** Gameye passes `env` and `args` from
the session-start call straight into the container. Everything match-specific arrives
that way: map, mode, expected players, match ID, your backend's URL. Never bake
per-match or per-environment values into the image — the same image must serve every
region, both Gameye hosts, and local testing.

Session env is **not secret**: any token in your organization with `session:read`
can read every launch env value through list and describe. Put only short-lived
per-match values there (a join secret that expires with the match), never long-lived
credentials.

**Warm pools change this.** When a warm pool is enabled for the image and region,
the request's `env`, `args` and `labels` are ignored — even when the pool is
exhausted and the session is started cold. If you use warm pools, the server fetches
its match config from your backend at boot instead: your backend maps the session ID
returned by `POST /session` to the match, and the server asks for "my match" once it
is up. Design for this from the start if pools are on your roadmap; it also works
fine without them.

**The game server never holds a Gameye API token.** Not in `env`, not in `args`, not
baked into the image. Anything the server needs from Gameye goes server → your
backend → Gameye. The server reports joins, leaves and results to your backend; your
backend calls Gameye with its own token (a `session:write` token for player join and
leave). A leaked server binary or a curious session reader then exposes nothing that
can start, stop or inspect sessions.

**3. Bind a fixed port on `0.0.0.0`.** Pick a constant container port (7777/udp,
whatever suits) and always bind it. Gameye maps it to a public host port and returns
the mapping to your backend — the server itself never needs to know its public
address. Binding `127.0.0.1` or a random port are the two classic ways to be
unreachable in production while working on a laptop.

**4. Signal readiness.** Log one unambiguous line (`READY port=7777`) once accepting
connections. Your backend and every human debugging a session will look for it in the
session logs.

**5. Play the match.** Track joins and leaves; report them to your backend so it can
relay them to Gameye's player join/leave endpoints with a `session:write` token (that
powers player-count filtering and backfill — see `gameye-matchmaking`). The server
talks to your backend, never to Gameye directly.

**6. End deliberately.** When the match concludes: report results to your backend
(push from the server — don't rely on someone polling), write anything worth keeping
to disk (see artifacts, below), then **exit 0**. Exiting is correct and expected —
an idle server is pure spend, and with `restart: false` (the default posture for
matches) exit cleanly ends the session. Do not loop back to a lobby.

**7. Drain on SIGTERM.** A stop request or TTL expiry delivers SIGTERM (session goes
`draining`). Handle it: announce shutdown to players, flush results and artifacts,
then exit. You get a grace window, not forever — write the important things first.
Aim to have the essentials (results to your backend, the artifacts you care about)
flushed within about 10 seconds of SIGTERM. The configured window is up to 50
seconds before the container is killed, but treat the remainder as slack, not
budget.

Two platform mechanisms back this contract up:

- **TTL** (`ttl: "2h"` at session start) force-terminates stragglers. Set it to
  max-expected-match-length plus margin on every session; it's the leak-proof
  cost control.
- **`restart: true`** exists for the rare always-on shape and for crash-recovery
  experiments, but it's mutually exclusive with the exit-when-done model. Match
  servers should crash loudly and let the matchmaker start a fresh session.

## Statelessness and artifacts

Treat the container filesystem as scratch space that evaporates on exit — because it
does. Durable state lives in your backend (results, progression, inventory), pushed
out before exit.

The exception is **artifacts**: files written to disk that Gameye makes downloadable
*after* the session reaches `exited` — match replays, detailed stats dumps, crash
dumps/core files. Write anything you'd want for postmortems there; it's the black box
recorder. Retrieval is `GET /artifacts?session=<session-id>&path=<absolute-path>`
(both parameters required), which returns a plain, uncompressed tar of that path —
do not gunzip it. Write artifacts to one known directory (e.g. `/app/out`) so the
path is constant. Details in `gameye-sessions-api`.

## Logging

Log to stdout/stderr, unbuffered, one event per line. Gameye captures container
output and serves it via the logs endpoint; a log file inside
the container is invisible. Log the config you booted with, the READY line, joins and
leaves, match phase transitions, and the final result — that set answers 90% of
"what happened in session X" questions.

## A note on determinism and lockstep

Deterministic lockstep (RTS-style, inputs-only networking) also hosts fine on Gameye —
the server becomes an input relay + arbiter. The lifecycle contract above applies
unchanged; only the simulation location differs. Choose it for thousands-of-units
games; choose state replication for everything else.

## Next

- Engine build: `gameye-unity-server`, `gameye-unreal-server`, `gameye-godot-server`,
  or `gameye-web-server`.
- Packaging the contract into an image: `gameye-containerize`.
