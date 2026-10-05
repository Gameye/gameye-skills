---
name: gameye-matchmaking
description: Wire matchmaking to Gameye so a formed match reliably becomes a running server with connected players — allocator patterns, idempotent session creation, latency-based region selection, backfill, and the Nakama/Prokma/Photon Fusion/Unity Matchmaker integrations. Use whenever building a matchmaker or allocator, connecting an existing matchmaking service to dedicated servers, or when the user asks how players get into a match, how to pick a region, how to backfill sessions, or how to handle allocation failures.
metadata:
  version: "1.0.0"
---

# Matchmaking on top of Gameye sessions

Gameye deliberately doesn't matchmake — it turns "start a server in region X" into an
`ip:port`. The allocator is the piece you own: the code that runs when a match forms.
This skill is that piece. Endpoint details live in `gameye-sessions-api`; load both.
The allocator code you write for the user calls the HTTP API; when you act on Gameye
yourself, follow the routing rule in the `gameye` skill's
[references/routing.md](../gameye/references/routing.md).

## The allocation flow

```
players queue → matchmaker forms group → allocator: POST /session
  → deliver host:port (+ join tokens) to players → players connect
  → server tells your backend about joins/leaves → backend relays them to Gameye
  → match ends → server exits (or DELETE /session/{id})
```

Design rules that keep this robust:

**Make creation idempotent.** Pass your own session `id` derived from the match
(`match-<matchId>`). If the allocator retries after a timeout, the duplicate create
returns `409` — treat that as "already allocated", look the session up, and reuse its
address. Without this, network blips double-allocate servers and split lobbies.

Warm pools break this: a claimed warm container ignores the `id` you send, so there
is no `409` and the response `id` is the warm container's name. **Always read the
session ID from the response**, and when pools are enabled, deduplicate in your own
backend — record the match → session mapping before you retry.

**Carry the match in `env`/`labels`.** `env: { MATCH_ID, ... }` configures the
server; `labels: { "match-id": ..., "mode": ... }` make sessions findable later
(`GET /session?filter[match-id]=...`). A short-lived join secret in `env` lets the
server verify that connecting players belong to this match. Nothing long-lived goes
there — any `session:read` token in your organization can read launch env — and
never a Gameye API token. Under warm pools, request `env`, `args` and `labels` are
ignored (even on cold fallback), so the server fetches its match config from your
backend at boot, keyed by the session ID your backend got back from `POST /session`.

**Always set a TTL.** Max expected match length plus margin. An allocator bug or an
abandoned lobby then costs minutes, not a weekend.

**Handle `420` as a real outcome.** It means no compute available in that region
right now. Back off briefly and retry, then fall back to the group's second-best
region. Surface "high demand, finding you a server…" to players rather than failing
the ticket.

**`429` and `402` are not capacity.** `429` means your organization's quota is
exceeded (`X-Quota-Type`, `X-Quota-Limit` headers); `402` means a trial quota is
exhausted. Switching region or hot-retrying won't help — alert, stop idle sessions,
or get the quota raised.

**Confirm before you announce.** Either poll `GET /session/{id}` until `running`
before sending players, or send them immediately and have clients retry connection
for a few seconds. Pick one deliberately; the second is faster, the first gives
cleaner failure messaging.

**Close the loop on match end.** Servers that exit on completion end their own
sessions; the allocator's job is the exceptional path — `DELETE /session/{id}` for
abandoned matches (all players left, reported via player-leave) and reconciliation:
periodically `GET /session` — without `all=true` it returns only running sessions,
which is exactly the set to check — and compare against matches your backend
believes are live. Orphans get stopped; TTL is the backstop beneath that. (A
`DELETE` on an already-terminated session returns `409`; treat it as done.)

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
GET /session?location=eu-central-1&playerCount[lt]=16&filter[mode]=competitive
```

`location` (like `image`, `tag`, `host`) is a plain parameter on the session field;
`playerCount[lt]=<capacity>` keeps only sessions with room (strict less-than); and
`filter[...]` matches **only your launch labels** — never put a session field such
as location or status inside `filter[...]`, it silently matches nothing. The default
list already excludes non-running sessions. From the candidates, pick the fullest
session (consolidating players lets empty sessions end), mint a join token, hand out
its address. This only works if the server reports joins/leaves promptly — the
player-tracking endpoints aren't optional bookkeeping, they're what makes
`playerCount` truthful.

## Integrations — check before hand-rolling

| Matchmaker | How it meets Gameye | Allocator role |
|---|---|---|
| Nakama (Heroic Labs) | Nakama's match lifecycle can drive Gameye session management | Your Nakama match handler calls `POST /session` |
| Prokma | Matchmaking service that can call the Gameye API when a group forms | Handled by the service; little developer-side glue |
| Photon Fusion | Fusion dedicated-server builds can run as Gameye sessions | Fusion's session management pairs with the allocation flow above |
| Unity Matchmaker (UGS) | A Cloud Code module acts as the allocator when a match is formed | Your Cloud Code module calls `POST /session` from the server side and returns the address |
| EOS / PlayFab (common with Unreal) | Their matchmaking forms groups | Your backend runs the generic allocator flow here |

Whichever row applies, the allocator holds the Gameye token on the server side —
never in a game client or game server.

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
      // 409 = already allocated (cold launches only; warm pools ignore `id`,
      // so record match → response id in your backend before retrying)
      if (e.status === 409) return { connect: await lookup(`match-${match.id}`) };
      if (e.status === 420) { await backoff(); continue; }   // no compute: next region
      throw e;                          // 402/429 quota, real failures: log identifier
    }
  }
  throw new NoCapacityError(match.id);
}
```
