---
name: gameye-sessions-api
description: The complete Gameye REST API reference for starting, listing, inspecting, and stopping game server sessions, plus tokens, locations, tag verification, logs, artifacts, and player tracking. Use whenever writing code that calls the Gameye API, wiring a backend or matchmaker to Gameye, debugging a session via API, or when the user mentions starting game servers programmatically, session endpoints, api.gameye.io, or Gameye tokens. Load it rather than guessing endpoint shapes — several responses have non-obvious wire formats.
---

# Gameye sessions API

Everything below is HTTPS + JSON against one of two environments:

| Environment | Base URL |
|---|---|
| Production | `https://api.gameye.io` |
| Sandbox | `https://api.sandbox-gameye.gameye.net` |

Build against sandbox first. Keep the base URL configurable — the same code must run
against both. Full OpenAPI spec and per-endpoint pages: [gameye.com/docs](https://gameye.com/docs/)
(API V2 section). An MCP server (`gameye-mcp`) wraps this API as agent tools if you
want conversational session control rather than code.

## Authentication and tokens

Every request carries:

```
Authorization: Bearer YOUR_TOKEN
```

Tokens are created in the Admin Panel (**Users → edit account → API Tokens → + Add
Token**) and are shown **once**, at creation. Tokens carry **scopes** (for example
`session:start`, `session:read`) — give each integration only what it uses: a
matchmaker needs `session:start` + `session:read`; a dashboard needs `session:read`
alone.

Short-lived tokens can be minted programmatically with `POST /token` using an
existing token: pass `expires_after` (e.g. `"30m"`, `"12h"`) and the scopes to
delegate. A token can only delegate scopes it already holds. Use this for CI jobs and
anything ephemeral; rotate long-lived tokens periodically.

## Start a session

```
POST /session          → 201 Created
```

```json
{
  "location": "eu-central-1",
  "image": "my-game-server",
  "version": "a1b2c3d",
  "env": { "MAX_PLAYERS": "16", "MATCH_ID": "m-8842" },
  "args": ["--tickrate=64"],
  "labels": { "match-id": "m-8842", "mode": "competitive" },
  "restart": false,
  "ttl": "2h"
}
```

| Field | Required | Notes |
|---|---|---|
| `location` | yes | Region name; must come from the available-locations call for this image |
| `image` | yes | Your application's image alias, not a registry path |
| `id` | no | Custom session ID. Omit and Gameye generates an RFC4122 UUID. Supplying your own makes creation **idempotent**: a retry of the same ID returns `409`, which your matchmaker can treat as "already started" instead of double-allocating |
| `version` | no | Image tag to run. Pin explicitly in production; verify first with the tag endpoint |
| `env` / `args` | no | Injected into the container verbatim — this is how match config reaches the server |
| `labels` | no | Your metadata; filterable in list calls |
| `restart` | no | Auto-restart on failure. Leave `false` for match servers that exit when done |
| `ttl` | no | Hard lifetime cap (`"90m"`, `"2h"`). Set it on virtually every session — it is the leak-proof cost control |

Response:

```json
{
  "id": "c5c7c507-f5de-443e-b772-af4b444cfc21",
  "host": "203.0.113.42",
  "ports": [
    { "type": "udp", "container": 7777, "host": 25159 }
  ]
}
```

Read the port mapping carefully: the server bound `container` (7777) inside the
container; players connect to `host:host-port` (`203.0.113.42:25159`). Host ports are
allocated in the 20000–30000 range. Never hand players the container port. When
several ports are bound, pick the game-traffic one by its `container`/`type` values —
your application's port bindings (Admin Panel) define which is which.

The call is synchronous — when it returns, the container is being started and the
address is final. Poll describe (below) for `running` if you want confirmed readiness
before sending players, or just let clients retry connection for a few seconds.

## List sessions

```
GET /session?filter[location]=eu-central-1&filterNot[status]=exited
```

Query parameters: `all` (include non-running), `filter[<field>]` and
`filterNot[<field>]` to match or exclude on session fields and labels. Response is
`{ "sessions": [ ... ] }`, each entry carrying `id`, `image`, `tag`, `location`,
`status`, `playerCount`, `labels`, and `created` (Unix **milliseconds**).

This powers backfill queries ("competitive sessions in EU that aren't full") and
ops dashboards. Filter server-side rather than fetching everything.

## Describe a session

```
GET /session/{id}
```

Returns full detail: `status`, `host`, `labels`, `args`, `restart`, `ttl`,
`players: { "joined": ["p1", "p2"], "joinedCount": 2 }`, `created` (Unix ms) — and
ports in a **different wire format** than session start:

```json
"port": { "7777/udp": 25159 }
```

A map of `"<container-port>/<protocol>"` → host port, under the singular key `port`.
Parse accordingly; do not reuse the start-response parser here.

## Stop a session

```
DELETE /session/{id}   → 204 No Content
```

Sends SIGTERM; the session moves through `draining → shuttingdown → exited`, giving
the server its grace window to flush results and artifacts. Stopping an
already-terminated session returns `409`.

## Session status values

`created` (initializing, not yet accepting connections) → `running` → on stop/TTL:
`draining` → `shuttingdown` → `exited` (final; artifacts now retrievable). Exceptional
states: `restarting` (crashed, `restart: true`), `dead` (unrecoverable),
`server_unreachable` (host lost contact; may recover — don't insta-kill on first
sight of it).

## Player tracking

```
PUT    /session/player/join    { "session": "<id>", "player": "<player-id>" }
DELETE /session/player/leave   { "session": "<id>", "player": "<player-id>" }
```

Report joins and leaves from your backend as players connect and drop. This is what
makes `playerCount` real, which in turn makes backfill filtering and "is this session
empty and stoppable?" decisions possible. Use opaque player IDs, not PII.

## Locations

```
GET /available-location/{image}
```

Returns `{ "locations": [ { "id": "eu-central-1", "ips": ["..."] } ] }` — the regions
where your image can run right now, each with **ping IPs**. Have game clients ping
those IPs and report latencies to your matchmaker; pick the region with the best
aggregate for the match group. Region availability can change; fetch rather than
hardcode.

## Tag verification

```
GET /tag/{region}/{image}/{version}   → { "exists": true }
```

Confirms a tag is actually available in a region before you start sessions on it.
Call it in CI after pushing a new tag (Gameye preloads tags from your registry;
preload is fast but not instantaneous) and as a pre-flight before rolling a new
version. Your application keeps a limited number of tags warm ("Tags to keep",
typically 2) — old tags rotate out, so don't expect ancient versions to still exist.

## Logs and artifacts

```
GET /logs?id=<session-id>            → text/plain (add follow=true to stream)
GET /artifacts?id=<session-id>       → tar archive of the container's artifact files
```

Logs are the container's stdout/stderr. Artifacts are only available once the session
reaches `exited` — a 404 right after stopping usually means it's still shutting down;
poll describe until `exited`, then fetch. Game servers log a lot; prefer streaming and
narrow time windows over repeated full dumps.

## Errors

Error bodies look like:

```json
{ "statusCode": 422, "code": "INVALID_INPUT", "message": "...", "details": [...],
  "identifier": "…", "path": "/session", "timestamp": "…" }
```

| HTTP | Meaning | Handle it by |
|---|---|---|
| 401 | Bad/missing token | Fix credentials; check environment (sandbox token on production URL is a classic) |
| 404 | Session/tag not found | For artifacts: session may not be `exited` yet |
| 409 | Duplicate session ID, or session already terminated | For idempotent creates: treat as success and look the session up |
| 420 | No capacity in region, or rate limited | Back off and retry; offer an alternate region |
| 422 | Validation failed | Read `details`/violations — field-level messages |
| 5xx | Gameye-side fault | Record the `identifier` (trace ID) and include it when contacting Gameye support |

Always log the `identifier` from error responses — it's the key support uses to find
the full server-side context.

## Minimal client sketch

```typescript
const BASE = process.env.GAMEYE_API_URL ?? "https://api.sandbox-gameye.gameye.net";
const auth = { Authorization: `Bearer ${process.env.GAMEYE_API_TOKEN}`,
               "Content-Type": "application/json" };

export async function startMatchServer(matchId: string, location: string) {
  const res = await fetch(`${BASE}/session`, {
    method: "POST", headers: auth,
    body: JSON.stringify({
      location, image: "my-game-server", version: process.env.GAME_VERSION,
      id: `match-${matchId}`,                       // idempotent under retry
      env: { MATCH_ID: matchId },
      labels: { "match-id": matchId },
      ttl: "2h",
    }),
  });
  if (res.status === 409) return lookupSession(`match-${matchId}`); // already started
  if (!res.ok) throw new Error(`gameye ${res.status}: ${await res.text()}`);
  const s = await res.json();
  const game = s.ports.find((p: any) => p.type === "udp") ?? s.ports[0];
  return { sessionId: s.id, connect: `${s.host}:${game.host}` };
}
```

For allocator patterns, backfill, and region selection strategy built on these calls,
load `gameye-matchmaking`.
