---
name: gameye-matchmaking
description: Wire matchmaking to Gameye so a formed match reliably becomes a running server with connected players — allocator patterns, idempotent session creation, latency-based region selection, backfill, and the Nakama/Prokma/Photon Fusion/Unity Matchmaker integrations. Use whenever building a matchmaker or allocator, connecting an existing matchmaking service to dedicated servers, or when the user asks how players get into a match, how to pick a region, how to backfill sessions, or how to handle allocation failures.
---

# Matchmaking on top of Gameye sessions

Gameye deliberately doesn't matchmake — it turns "start a server in region X" into an
`ip:port`. The allocator is the piece you own: the code that runs when a match forms.
This skill is that piece. Endpoint details live in `gameye-sessions-api`; load both.

## The allocation flow

```
players queue → matchmaker forms group → allocator: POST /session
  → deliver host:port (+ join tokens) to players → players connect
  → server reports joins/leaves → match ends → server exits (or DELETE /session)
```

Design rules that keep this robust:

**Make creation idempotent.** Pass your own session `id` derived from the match
(`match-<matchId>`). If the allocator retries after a timeout, the duplicate create
returns `409` — treat that as "already allocated", look the session up, and reuse its
address. Without this, network blips double-allocate servers and split lobbies.

**Carry the match in `env`/`labels`.** `env: { MATCH_ID, ... }` configures the
server; `labels: { "match-id": ..., "mode": ... }` make sessions findable later
(`GET /session?filter[match-id]=...`). Put a join token secret in `env` so the server
can verify that connecting players belong to this match.

**Always set a TTL.** Max expected match length plus margin. An allocator bug or an
abandoned lobby then costs minutes, not a weekend.

**Handle `420` as a real outcome.** It means no capacity in that region right now (or
throttling). Back off briefly and retry, then fall back to the group's second-best
region. Surface "high demand, finding you a server…" to players rather than failing
the ticket.

**Confirm before you announce.** Either poll `GET /session/{id}` until `running`
before sending players, or send them immediately and have clients retry connection
for a few seconds. Pick one deliberately; the second is faster, the first gives
cleaner failure messaging.

**Close the loop on match end.** Servers that exit on completion end their own
sessions; the allocator's job is the exceptional path — `DELETE /session/{id}` for
abandoned matches (all players left, reported via player-leave) and reconciliation:
periodically `GET /session` (excluding `exited` via `filterNot[status]`) and compare
against matches your backend believes are live. Orphans get stopped; TTL is the
backstop beneath that.

## Region selection

`GET /available-location/{image}` returns each available region with **ping IPs**.

- **Static** — player base concentrated in one geography: pin the region, revisit
  quarterly.
- **Latency-based** — clients ping the ping IPs (once per queue entry, cached),
  submit latencies with their ticket; the matchmaker groups compatible players and
  the allocator picks the region minimizing the group's worst latency (p95, not
  mean — the worst-connected player defines match quality).

Fetch the region list rather than hardcoding; availability evolves.

## Backfill

To route joiners into in-progress matches with space:

```
GET /session?filter[mode]=competitive&filter[location]=eu-central-1&filterNot[status]=exited
```

Filter candidates by `playerCount` against capacity, pick the fullest non-full
session (consolidating players lets empty sessions end), mint a join token, hand out
its address. This only works if the server reports joins/leaves promptly — the
player-tracking endpoints aren't optional bookkeeping, they're what makes
`playerCount` truthful.

## Integrations — check before hand-rolling

- **Unity Matchmaker** — the `gameye-unity-bootstrap` CLI deploys a working Cloud
  Code allocator module end to end (see `gameye-unity-server`). Prefer it over a
  bespoke allocator for Unity + UGS projects.
- **Nakama** (Heroic Labs) — integration connects Nakama's match lifecycle to Gameye
  session management; your Nakama match handler plays the allocator role.
- **Prokma** — matchmaking service that calls the Gameye API directly when a group
  forms; no developer-side glue.
- **Photon Fusion** — dedicated server mode hosts on Gameye; Fusion's own session
  management pairs with the allocation flow above.
- **EOS / PlayFab** (typical for Unreal) — use their matchmaking to form groups, then
  the generic allocator flow here.

## Allocator sketch

```typescript
async function allocate(match: Match): Promise<{ connect: string }> {
  const region = pickRegion(match.playerLatencies);        // p95-minimizing
  for (const loc of [region, ...fallbacks(region)]) {
    try {
      const s = await gameye.startSession({
        id: `match-${match.id}`, image: IMAGE, version: PINNED_TAG,
        location: loc,
        env: { MATCH_ID: match.id, JOIN_SECRET: match.joinSecret },
        labels: { "match-id": match.id, mode: match.mode },
        ttl: "90m",
      });
      return { connect: s.connect };
    } catch (e) {
      if (e.status === 409) return { connect: await lookup(`match-${match.id}`) };
      if (e.status === 420) { await backoff(); continue; }   // try next region
      throw e;                                               // real failure: log identifier
    }
  }
  throw new NoCapacityError(match.id);
}
```
