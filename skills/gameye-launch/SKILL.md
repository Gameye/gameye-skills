---
name: gameye-launch
description: Take a Gameye-hosted game from working-in-sandbox to production — the launch checklist, token hygiene, tag and rollout strategy, TTL and cost control, capacity behavior, observability, and incident basics. Use when preparing a launch or playtest on Gameye, moving from sandbox to production, reviewing production readiness, or when the user mentions going live, launch day, rollout, or operating game servers in production.
---

# Launching and operating on Gameye

Everything here assumes the sandbox smoke test (`gameye-local-testing`) passes. This
skill is the gap between "it works" and "it's operable".

## Pre-launch checklist

**Access and tokens**
- Separate tokens per system (matchmaker, CI, dashboards), each with minimum scopes
  (`session:start` + `session:read` for the allocator; `session:read` for anything
  observational). Tokens are shown once at creation — store them in your secret
  manager immediately.
- Production and sandbox are different base URLs *and* different tokens
  (`https://api.gameye.io` vs `https://api.sandbox-gameye.gameye.net`). Make the
  pair one configuration unit so a sandbox token can never point at production.
- CI mints short-lived tokens (`POST /token` with `expires_after`) rather than
  holding a long-lived one. Rotate what can't be short-lived.

**Application configuration (Admin Panel)**
- Port bindings match the Dockerfile `EXPOSE` and what the server binds.
- Resource profile sized from measured full-match load (`docker stats` numbers from
  `gameye-local-testing`) plus margin — it's guaranteed *and* billed; both
  undersizing and oversizing are real costs, one in player experience, one in money.
- Regions enabled where your players are; confirm via `GET /available-location`.
- "Tags to keep" understood: current + previous stay warm; older tags rotate out.

**Rollout mechanics**
- Sessions start with a pinned `version` (git-SHA tag), never implicit latest.
- Deploy = push tag → verify preload per region (`GET /tag/...`) → flip the pinned
  version in the allocator config → new matches get the new build while running
  matches finish on the old one. Rollback = flip the pin back (previous tag is still
  warm).
- Never re-push a changed image under an existing tag — you lose the ability to know
  what a session ran.

**Cost and leak control**
- TTL on every session, sized to max match length + margin.
- Reconciliation loop live (`gameye-matchmaking`): orphaned sessions get stopped,
  not discovered on the invoice.
- Know your billing granularity (per minute/hour/day of container runtime) and, if
  on a trial quota, what happens at exhaustion (session starts refused; running
  containers may be terminated).

## Launch-day behavior

- **Capacity**: Gameye runs bare metal per region and bursts to cloud automatically —
  but `420` (no capacity / throttled) is still a possible answer under spikes. Your
  allocator's backoff-and-fallback-region path (`gameye-matchmaking`) is the
  player-facing difference between "finding a server…" and an error screen. For a
  marketing-driven spike, tell Gameye in advance so regional capacity is warm.
- **Watch the funnel, not just servers**: session starts succeeding (rate of `201`
  vs `420`/`5xx`), time from start to `running`, players-per-session distribution
  (`GET /session` + `playerCount`), and session end states — a rising `dead` count
  is a crashing build.
- Keep a pinned-version-known-good in the allocator config and rehearse the
  rollback flip before you need it.

## Observability

- **Logs**: `GET /logs?id=...` per session for spot checks; Kibana dashboards for
  fleet-wide queries. This is why the engine skills insist on stdout logging with a
  boot-config line and READY marker — they make sessions greppable.
- **Artifacts**: fetch match replays/crash dumps after `exited` for any session
  players report; wire crash-dump artifacts into your triage flow.
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
