---
name: gameye
description: Ship and host a multiplayer game on Gameye, the managed dedicated game server platform (Docker image in, ip:port out). Use this skill whenever the user mentions Gameye, wants to host or deploy a multiplayer game server, asks how players will connect to matches, wants dedicated servers for a Unity/Unreal/Godot/web game, or has built a game and asks how to run its multiplayer backend — even if they never say the word "hosting". It orients on the platform and routes to the specialized gameye-* skills for server design, engine builds, containerization, the sessions API, matchmaking, testing, and launch.
---

# Gameye

Gameye is managed dedicated game server hosting. The whole platform reduces to one
interaction: you push a Docker image of your game server to your registry, and your
backend calls `POST /session` with a region. Gameye starts a container on bare metal
near your players (bursting to cloud when needed) and returns an `ip` and `ports`.
Players connect. The match ends, the container exits, billing stops.

There is no SDK to link, no Kubernetes to run, no Terraform to write. Anything that
runs in a **Linux** container runs on Gameye — any engine, any language. Windows
containers are not supported.

## Does this game need Gameye at all?

Route honestly before routing enthusiastically:

- **Single-player or local co-op** → no dedicated servers needed. Static hosting or a
  store page. Stop here.
- **Turn-based / async multiplayer** (correspondence chess, word games) → a normal web
  backend and database beat a dedicated game server. Stop here.
- **Real-time multiplayer where fairness or consistency matters** (shooters, racers,
  co-op action, .io-style arena games, competitive anything) → an authoritative
  dedicated server is the correct architecture, and that is exactly what Gameye hosts.
  Continue.
- **Real-time but cozy and trust-tolerant** (2-4 friends, invite-only) → client-hosted
  or relayed P2P can work, but it inherits NAT pain, host-migration pain, and host
  cheating. A dedicated server is still the simpler long-term answer; use judgment.

## The path from game to hosted game

Work through these skills in order; skip what's already done:

| Step | Skill | You have it done when |
|---|---|---|
| 1 | `gameye-server-design` | The server is authoritative, session-scoped, and configured via env/args |
| 2 | `gameye-unity-server` / `gameye-unreal-server` / `gameye-godot-server` / `gameye-web-server` | A headless **linux/amd64** server build exists |
| 3 | `gameye-containerize` | `docker run` starts a working server locally |
| 4 | `gameye-local-testing` | Parity tests pass; sandbox smoke test passes |
| 5 | `gameye-sessions-api` | Your backend can start/stop/inspect sessions |
| 6 | `gameye-matchmaking` | A formed match reliably becomes a connected lobby |
| 7 | `gameye-launch` | The production checklist is green |

For a game engine not listed (Bevy, custom C++, LÖVE, …): `gameye-server-design` and
`gameye-containerize` are engine-agnostic and cover everything Gameye actually
requires. The engine skills only add build-pipeline specifics.

## Vocabulary you'll see everywhere

- **Application** — your game server as Gameye knows it: an image alias (e.g.
  `"mygame"`, not a full registry path), its port bindings, and a resource profile
  (guaranteed CPU/memory — never oversubscribed). Configured in the Admin Panel.
- **Session** — one running container, usually one match. Lifecycle:
  `created → running → draining → shuttingdown → exited`.
- **Location** — a named region (`eu-central-1`, …). You pick one per session; the
  authoritative list for your image comes from the available-locations endpoint.
- **TTL** — a hard cap on session lifetime, set at start. The reliable cost-control
  and leak-prevention tool; use it on almost every session.
- **Labels** — your metadata on a session (`match-id`, `mode`, …), filterable later.

## Accounts and environments

Onboarding currently goes through the Gameye team (self-service is on the roadmap).
You receive access to the Admin Panel, where API tokens are created (Users → API
Tokens) with **scopes** such as `session:start` and `session:read` — issue
narrowly-scoped tokens per system, and short-lived ones programmatically when
automation needs them. Two environments exist — develop against sandbox, keep
production tokens out of dev tools:

| Environment | Base URL |
|---|---|
| Sandbox | `https://api.sandbox-gameye.gameye.net` |
| Production | `https://api.gameye.io` |

Registry integration (Docker Hub, AWS ECR) is configured once; after that Gameye
preloads new tags from your registry onto its fleet automatically — you never push
images to Gameye directly.

## Related tooling worth knowing about

- **gameye-mcp** — an MCP server exposing the session API as agent tools; useful for
  operating live sessions conversationally while these skills cover building for them.
- **gameye-unity-bootstrap** — a CLI that stands up the Unity Matchmaker + Gameye +
  Docker Hub pipeline end to end, with a `doctor` command. The fast path for Unity;
  see `gameye-unity-server`.
- **Integrations** — Nakama, Prokma, and Photon Fusion integrations exist; see
  `gameye-matchmaking` before hand-rolling an allocator.
