---
name: gameye-launch
description: Take a Gameye-hosted game from "the smoke test passes" to live players — the launch checklist, the right API host for the customer's tier, token hygiene and scopes, tag and rollout strategy, TTL and cost control, capacity and quota behavior, observability, and incident basics. Use when preparing a launch or playtest on Gameye, reviewing production readiness, or when the user mentions going live, launch day, rollout, or operating game servers with real players.
metadata:
  version: "1.0.0"
---

# Launching and operating on Gameye

Everything here assumes the sandbox smoke test (`gameye-local-testing`) passes. This
skill is the gap between "it works" and "it's operable".

**Which host is "live" depends on the customer's tier**, not on a dev/prod split:

| Customer | Live host |
|---|---|
| Self-serve | `https://api.sandbox-gameye.gameye.net` — the self-serve product itself; launch day happens here, there is no move to another host |
| Enterprise | `https://api.production-gameye.gameye.net` — onboarded by the Gameye team |

If you don't know the tier, ask. When you act on Gameye yourself during a launch
(checking tags, reading logs, stopping a session), follow the routing rule in the
`gameye` skill's [references/routing.md](../gameye/references/routing.md); code for
the user's backend always calls HTTP.

## Pre-launch checklist

**Access and tokens**
- Separate tokens per system (allocator, player relay, CI, dashboards), each with
  minimum scopes — use the least-privilege recipes in `gameye-sessions-api` (for
  example `session:start` + `session:read` for the allocator, `session:write` for the
  backend that relays player join/leave, `regions:read` for CI tag checks). Tokens
  are shown once at creation — store them in your secret manager immediately.
- No Gameye token in any game server container, image, or session `env`; the server
  talks to your backend, and your backend talks to Gameye (`gameye-server-design`).
- The two hosts take different tokens. Make base URL + token one configuration unit
  (`GAMEYE_API_URL` + `GAMEYE_API_TOKEN`) so a token can never be paired with the
  wrong host; a mismatch shows up as `401`.
- CI mints short-lived tokens (`POST /token` with `expires_after`) rather than
  holding a long-lived one — omitting `expires_after` creates a token that never
  expires. Rotate what can't be short-lived.

**Application configuration (Admin Panel)**
- Port bindings match the Dockerfile `EXPOSE` and what the server binds.
- Resource profile sized from measured full-match load (`docker stats` numbers from
  `gameye-local-testing`) plus margin — it's guaranteed *and* billed; both
  undersizing and oversizing are real costs, one in player experience, one in money.
- Regions enabled where your players are; confirm via `GET /available-location/{image}`.
- "Tags to keep" understood: current + previous stay warm; older tags rotate out.

**Rollout mechanics**
- Sessions start with a pinned `version` (git-SHA tag), never implicit latest.
- Deploy = push tag → make it launchable (registry webhook, or enable-tag with
  `POST /application/{name}/tags` — setup in `gameye-containerize`) → verify preload
  per region (`GET /tag/{region}/{image}/{version}` → `exists: true`) → flip the pinned
  version in the allocator config → new matches get the new build while running
  matches finish on the old one. Rollback = flip the pin back (previous tag is still
  warm).
- Never re-push a changed image under an existing tag — you lose the ability to know
  what a session ran.
- Omitting `version` runs the most recently registered tag, so an unpinned allocator
  silently picks up every push.
- Warm pools ignore a request's `version` (and `env`, `args`, `labels`); if you use
  them, rollout is a pool configuration change — coordinate it with Gameye.

**Cost and leak control**
- TTL on every session (`ttl: "90m"`, `m`/`h` units), sized to max match length +
  margin.
- Reconciliation loop live (`gameye-matchmaking`): orphaned sessions get stopped,
  not discovered on the invoice.
- Know your billing granularity and your limits: `402` on session start means a
  trial quota is exhausted, `429` means an organization quota is exceeded
  (`X-Quota-Type`, `X-Quota-Limit` headers). Neither is fixed by retrying — alert on
  them and stop idle sessions or get the quota raised before launch day.

## Launch-day behavior

- **Capacity**: Gameye runs bare metal per region and bursts to cloud automatically —
  but `420` (no compute available) is still a possible answer under spikes. Your
  allocator's backoff-and-fallback-region path (`gameye-matchmaking`) is the
  player-facing difference between "finding a server…" and an error screen. For a
  marketing-driven spike, tell Gameye in advance so regional capacity is warm.
- **Watch the funnel, not just servers**: session starts succeeding (rate of `201`
  vs `420`/`429`/`5xx`), time from start to `running`, players-per-session distribution
  (`GET /session` + `playerCount`), and session end states — a rising `dead` count
  is a crashing build.
- Keep a pinned-version-known-good in the allocator config and rehearse the
  rollback flip before you need it.

## Observability

- **Logs**: `GET /logs?id=<session-id>&follow=false` per session for spot checks
  (without `follow=false` the stream stays open). This is why the engine skills insist on stdout logging with a
  boot-config line and READY marker — they make sessions greppable.
- **Artifacts**: fetch match replays/crash dumps after `exited` for any session
  players report (`GET /artifacts?session=<session-id>&path=<path>`, an uncompressed
  tar); they last only until the container is removed, so wire crash-dump retrieval
  into your triage flow rather than fetching by hand days later.
- **The Admin Panel dashboard** shows per-application nodes, active containers over
  time, and real-time resource usage — the first place to look when "is it us or
  them" questions arise.

## When something breaks

Gameye intentionally returns limited error detail — internal faults surface as a
generic error plus an **`identifier`** (trace ID) in the error body. Log it on every
failed API call; it's the exact key Gameye support uses to pull the full server-side
context. An error report with an identifier and a session ID gets answered in one
round trip; "sessions seem broken" does not.

Escalation order: your own funnel metrics → session logs → Admin Panel dashboard →
Gameye support with identifiers.

## After launch

Revisit quarterly: region set vs actual player geography (latency data from your
matchmaker tickets tells you), resource profile vs observed usage, TTL values vs
real match-length distributions, and token inventory (kill unused ones).
