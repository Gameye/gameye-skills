---
name: gameye-sessions-api
description: The Gameye REST API for starting, listing, inspecting, and stopping game server sessions, plus player tracking, logs, artifacts, tokens and scopes, applications and tags, regions, and locations. Use whenever writing code that calls the Gameye API, wiring a backend or matchmaker to Gameye, debugging a session via the API, minting or scoping Gameye tokens, or when the user mentions starting game servers programmatically, session endpoints, api.sandbox-gameye.gameye.net, api.production-gameye.gameye.net, warm pools, or Gameye error codes. Registry and webhook setup is in gameye-containerize. Load it rather than guessing endpoint shapes — several requests and responses differ from what the published schema suggests.
metadata:
  version: "1.0.1"
---

# Gameye sessions API

Everything below is HTTPS + JSON with `Authorization: Bearer <token>`, against the
host for the customer's tier:

| Customer | Base URL |
|---|---|
| Self-serve | `https://api.sandbox-gameye.gameye.net` |
| Enterprise | `https://api.production-gameye.gameye.net` |

Sandbox is the permanent home of self-serve customers and carries their live matches.
Keep the base URL configurable (`GAMEYE_API_URL`, defaulting to sandbox) so the same
code runs on either host.

Where to find what:

- **This file**: procedure and pitfalls per domain.
- **[references/api-reference.md](references/api-reference.md)**: every operation with
  method, path, server-checked scope, MCP tool and corrected notes. Generated; trust its
  Notes column over the published schema.
- **`<host>/openapi.yaml`**: the live schema each host serves, for exact field types.
  Where it disagrees with the reference's Notes, the Notes describe what the server
  actually does.
- **Tools or HTTP?** Follow the routing rule in the `gameye` skill's
  [references/routing.md](../gameye/references/routing.md): act through `gameye_*`
  tools when you have them; code for the user's backend always uses HTTP.

## Sessions

### Start a session

```
POST /session          → 201 Created
```

```json
{
  "id": "my-game-3f2b8c1e-7d4a-4c55-9e0b-2a6f1d9c8e47",
  "location": "eu-central-1",
  "image": "my-game-server",
  "version": "a1b2c3d",
  "env": { "MAX_PLAYERS": "16", "MATCH_ID": "3f2b8c1e-7d4a-4c55-9e0b-2a6f1d9c8e47" },
  "args": ["--tickrate=64"],
  "labels": { "match-id": "3f2b8c1e-7d4a-4c55-9e0b-2a6f1d9c8e47", "mode": "competitive" },
  "restart": false,
  "ttl": "2h",
  "external_id": "3f2b8c1e-7d4a-4c55-9e0b-2a6f1d9c8e47"
}
```

| Field | Required | Notes |
|---|---|---|
| `location` | yes | Region name; take it from the available-locations call for this image |
| `image` | yes | Your application's name, not a registry path |
| `id` | no | Custom session ID. Omit and Gameye generates a UUID. IDs are unique **across all of Gameye**, not just your organization, and stay taken after the session ends, so derive them from a globally unique value: a UUID match ID, or `<game-slug>-<uuid>`. A retry with the same ID returns `409`, which makes cold launches idempotent — but see warm pools and the `409` row under Errors |
| `version` | no | Image tag to run. **Pin it.** Omitted, the server runs the most recently registered tag, so a fresh push silently changes what new matches run. An unavailable tag returns `404` |
| `env` / `args` | no | Injected into the container — how per-match config reaches the server. Not secret storage (see below) |
| `labels` | no | Your metadata; matched by `filter[...]` in list calls |
| `restart` | no | Auto-restart on failure. Leave `false` for match servers that exit when done |
| `ttl` | no | Hard lifetime cap in `m`/`h` units (`"90m"`, `"2h30m"`). Set it on virtually every session |
| `external_id` | no | Your own identifier for the session (match ID, ticket ID) |

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

Players connect to `host:<ports[].host>` (`203.0.113.42:25159`), never to the
container port. Host ports are allocated in the 20000–30000 range. When several ports
are bound, pick the game-traffic one by its `container`/`type` values — the
application's port bindings define which is which.

The call is synchronous: when it returns, the address is final and the container is
starting. Poll describe for `running` if you want confirmed readiness, or let clients
retry the connection for a few seconds.

### Warm pools

If a warm pool is enabled for the image and region, the request is served from the
pool, and:

- `env`, `args` and `labels` from the request are **ignored, even when the pool is
  exhausted** — the cold fallback uses the pool's configured values. Per-match config
  must reach the server another way (for example the server fetches it from your
  backend on start, keyed by its session ID).
- A claimed warm container also ignores `version`, `restart` and `id`. The response
  `id` is the warm container's name. **Always read the session ID from the response**,
  never assume it equals the `id` you sent.
- Because `id` is ignored, a duplicate `id` does not produce `409`; deduplicate retries
  in your own backend (record the match → session mapping before retrying).
- `ttl` and `external_id` are honored.

### Session env is not secret

List and describe return `labels`, which hold the raw container labels: `tags` (your
launch labels, as a JSON string), `env` (the full launch environment, as a JSON
string) and `gameye` (system labels). Any token in your organization with
`session:read` can read every launch env value. Never put a Gameye API token or other
long-lived credential in `env` or `args`. Short-lived per-match values, such as a join
secret, are acceptable. If a game server needs something from Gameye, it asks your
backend, and your backend calls Gameye.

### List sessions

```
GET /session?location=eu-central-1&image=my-game-server&playerCount[lt]=16&filter[mode]=competitive
```

| Parameter | Behavior |
|---|---|
| `all=true` | Include non-running sessions. **Without it, only running sessions are returned.** |
| `location`, `image`, `tag`, `host` | Plain exact-match parameters on the session's fields |
| `playerCount[lt]=N`, `playerCount[gt]=N` | Strict less-than / greater-than |
| `filter[key]=value` | Matches **only launch labels** (never env, status or other fields) |
| `filterNot[key]=value` | Excludes by launch label; a session without the key fails both `filter` and `filterNot`, so unlabeled sessions are not returned |

Response is `{ "sessions": [ ... ] }`; each entry has `id`, `image`, `tag`,
`location`, `host`, `status`, `playerCount`, `labels`, `port` (map format, see
describe) and `created` (Unix **milliseconds**). To read your own labels from an
entry, JSON-parse `labels.tags`.

Pitfalls: a `filter[...]` keyed on a session field name (location, status, image)
matches a launch label of that name, not the session field, and silently returns
nothing. Use the plain parameters for session fields. Filter server-side
rather than fetching everything. Under warm pools, request labels are dropped, so
label filters only see the pool's labels.

### Describe a session

```
GET /session/{id}
```

Returns `status`, `host`, `image`, `tag`, `location`, `labels`, `created` (Unix ms),
`players: { "joined": ["p1", "p2"], "joinedCount": 2 }` — and ports in a **different
wire format** than session start, under the singular key `port`:

```
"port": { "7777/udp": 25159 }
```

A map of `"<container-port>/<protocol>"` → host port. Do not reuse the start-response
parser here.

### Stop a session

```
DELETE /session/{id}   → 204 No Content
```

Sends SIGTERM; the session moves through `draining → shuttingdown → exited`. The
server gets a grace period (by default about 50 seconds) to flush results and
artifacts before the container is killed; keep shutdown well inside it. Stopping an
already-terminated session returns `409` — treat it as success in cleanup paths.

### Session status values

`created` (initializing) → `running` → on stop/TTL: `draining` → `shuttingdown` →
`exited` (final). Exceptional states: `restarting` (crashed, `restart: true`), `dead`
(unrecoverable), `server_unreachable` (host lost contact; may recover — don't stop it
on first sight).

## Players

```
PUT /session/player/join
```

```json
{ "session": "c5c7c507-f5de-443e-b772-af4b444cfc21", "players": ["p-1001", "p-1002"] }
```

```
DELETE /session/player/leave
```

```json
{ "session": "c5c7c507-f5de-443e-b772-af4b444cfc21", "players": ["p-1001"] }
```

Procedure: your **backend** reports joins and leaves as players connect and drop
(the game server tells your backend; your backend calls Gameye with a `session:write`
token). This is what makes `playerCount` real, which powers backfill queries and
"is this session empty and stoppable?" decisions.

Pitfalls:

- Both bodies take `session` plus a **plural** `players` array. A singular `player`
  field registers nothing. The leave body needs `session` even though the published
  schema omits it; without it the server returns `404`.
- Join responds with **every** player now in the session (`players`, `count`), not only
  the ones just added. Leave responds with the players remaining; `players` is `null`
  (not `[]`) when the session is empty, so guard before iterating.
- Use the session ID from the start response. An unknown or foreign session is `404`.
- Use opaque player IDs, not emails or other PII.

## Logs and artifacts

```
GET /logs?id=<session-id>&follow=false              → text/plain
GET /artifacts?session=<session-id>&path=/app/out   → tar stream
```

**Logs** are the container's stdout/stderr. `follow` **defaults to `true`**: without
`follow=false` the server keeps the stream open until you disconnect or the request
times out. Use `follow=false` for a snapshot (debugging, CI, an agent reading logs);
use the default only when you deliberately tail with a streaming reader.

**Artifacts** download a file or folder from the container. Both query parameters are
required: `session` (the session ID — not `id`) and `path` (an absolute path inside
the container). The response is an **uncompressed tar** (`application/octet-stream`,
filename `<session>.tar`); do not gunzip it. Artifacts become available once the
session has terminated and remain only until the container is removed from its host,
so fetch promptly after `exited`. A `404` right after stopping usually means it's still
shutting down; poll describe until `exited`, then fetch. Keep downloads under 100 MB.

## Tokens and scopes

Tokens are created in the Admin Panel (**Users → edit account → API Tokens → + Add
Token**) and shown **once**. Each token carries scopes; the server checks one scope
per operation (listed in the reference). Legacy unscoped tokens skip the check, so
moving to scoped tokens can surface `403`s that were hidden before.

### Least-privilege recipes

| Integration | Scopes |
|---|---|
| Allocator / matchmaker backend | `session:start` `session:read` (add `session:stop` if it ends matches, `regions:read` for available locations) |
| Player relay (reports joins/leaves) | `session:write` |
| Observer / dashboard / agent debugging | `session:read` `logs:read` `artifact:read` `regions:read` (add `region:read` to list all regions) |
| CI: verify and enable tags | `regions:read` (tag check and enable-tag), plus `application:read` to list upstream registry tags |
| Registry webhook | `webhook:dockerhub` or `webhook:github` only — set up in `gameye-containerize` |
| Token minting service | `token:write` plus every scope it hands out |

Note the two region scopes: `GET /region` checks `region:read` (singular), while
available locations, tag checks and enable-tag check `regions:read`. Enable-tag is
checked as `regions:read` today although the published schema declares
`application:write`; this may be corrected, so a CI token that should survive the
change can also hold `application:write`.

### Mint short-lived tokens

```
POST /token          → 201 { "token": "..." }
```

```json
{ "name": "ci-build-1234", "scopes": ["regions:read"], "expires_after": "1h" }
```

- The caller needs `token:write`, and the requested `scopes` must be a subset of the
  caller's own scopes (`403` otherwise). The one exception: `webhook:github` can be
  delegated by any `token:write` caller.
- **Omitting `expires_after` creates a token that never expires.** Always set it for
  CI jobs and anything ephemeral (`m`/`h` units, e.g. `"30m"`, `"12h"`).
- The token appears only in the response. Store it in a secret manager; never log it.
- Names are unique per user, but a duplicate `name` currently fails with `500`, not
  `409`. Always include a unique suffix (build number, timestamp), and do not retry a
  token-create `500` with the same name.
- With the `gameye_create_token` tool, the token is written to a file, never returned
  in chat. Give it a path outside any git working tree (the tool refuses a path inside
  one), never print or `cat` the file, and tell the user which system should read it
  (their secret manager, CI secret store, or backend config).

## Applications and tags

An application is usually created and edited in the Admin Panel. The API equivalents
(`POST /application`, `PUT /application/{name}`) need `application:write`; treat them
as admin actions and confirm with the user before calling them. `GET /application`
lists applications with their registry, repository, `tagKeep`, resources, regions and
port bindings.

Tag procedure (registry and webhook setup itself is in `gameye-containerize`):

1. **See what the registry has:** `GET /application/{name}/tags/available` lists tags
   in the upstream registry (`page`, `pageSize` up to 1000) as `{ "tags": [ { "version":
   "..." } ] }`. Being in the registry does not mean Gameye has it.
2. **Enable a tag** when the webhook did not register it (or to pull its preload
   forward):

   ```
   POST /application/{name}/tags     → 204
   ```

   ```json
   { "tag": "a1b2c3d" }
   ```

3. **Verify before use:** `GET /tag/{region}/{image}/{version}` → `{ "exists": true }`
   once the tag is preloaded in that region. Call it in CI after a push and as a
   pre-flight before rolling a version.
4. **Launch with `version` pinned** to that tag.

Pitfalls: preload is fast but not instantaneous; the application keeps only its
`tagKeep` most recent tags ("Tags to keep"), so old versions rotate out; and launches
without `version` follow whichever tag was registered last.

## Regions and locations

```
GET /available-location/{image}   → { "locations": [ { "id": "eu-central-1", "ips": ["..."] } ] }
GET /region                        → { "regions": ["..."] }
```

Use **available locations** for placement: they are the regions that can host this
image right now, each with ping IPs. Have clients ping those IPs and report latency to
your matchmaker; pick the region with the best aggregate for the match group. Don't
cache the list — availability changes. `GET /region` lists your organization's regions
in general and does not say whether your image can run there; use it for dashboards
and configuration, not session placement.

## Errors

Error bodies:

```
{ "statusCode": 422, "code": "...", "message": "...", "details": "...",
  "violations": [ { "field": "...", "description": "..." } ],
  "identifier": "...", "path": "/session", "timestamp": "..." }
```

| HTTP | Meaning | Handle it by |
|---|---|---|
| 400 | Malformed request (bad duration or scope on `/token`, missing artifacts params) | Fix the request |
| 401 | Bad or missing token | Fix credentials; check the host (a token for one host fails on the other) |
| 402 | Trial quota exhausted (session start) | Stop and tell the user; retrying won't help |
| 403 | Token lacks the scope, or a token request asks for scopes the caller doesn't hold | Use a token with the scope in the reference |
| 404 | Session, application, image or tag not found, or not yours | For start: check `version` is enabled in that region. For artifacts: session may not be `exited` yet |
| 409 | Duplicate session ID (IDs are unique across all of Gameye), or session already terminated | Start: describe that ID. Found → an earlier attempt of yours started it; continue. `404` → another organization owns the ID; retry with a fresh one. Stop: treat as done |
| 420 | No compute available in the region right now | Back off and retry, or offer the next-best region |
| 422 | Validation failed | Read `violations` for field-level messages |
| 429 | Organization quota exceeded (`X-Quota-Type`, `X-Quota-Limit` headers) | Don't hot-retry; stop idle sessions or ask Gameye to raise the quota |
| 5xx | Gameye-side fault | Retry with backoff; record the `identifier` and include it when contacting support. Exception: a `500` from `POST /token` may be a duplicate `name` — retry only with a new name |

Always log the `identifier` from error responses — it's the key support uses to find
the server-side context.

## Minimal client sketch

```typescript
const BASE = process.env.GAMEYE_API_URL ?? "https://api.sandbox-gameye.gameye.net";
const TOKEN = process.env.GAMEYE_API_TOKEN; // backend only; never passed to the server
const headers = { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" };

async function gameye(path: string, init: RequestInit = {}, allow: number[] = []) {
  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!res.ok && !allow.includes(res.status)) {
    const body = await res.json().catch(() => ({}));
    throw Object.assign(new Error(`gameye ${res.status} ${body.code ?? ""}`),
      { status: res.status, identifier: body.identifier }); // log the identifier
  }
  return res;
}

// matchId is a UUID your backend generated. Session IDs are unique across all of
// Gameye, so never use a bare counter or short match code.
export async function startMatchServer(matchId: string, location: string) {
  let id = `my-game-${matchId}`;                    // idempotent on cold launches
  for (let attempt = 0; attempt < 2; attempt++) {
    const res = await gameye("/session", {
      method: "POST",
      body: JSON.stringify({
        id, location, image: "my-game-server",
        version: process.env.GAME_VERSION,          // pin; omitted = latest registered tag
        env: { MATCH_ID: matchId },                 // no tokens or long-lived secrets here
        labels: { "match-id": matchId },
        external_id: matchId,
        ttl: "2h",
      }),
    }, [409]);
    if (res.status !== 409) {
      const s = await res.json();
      const game = s.ports.find((p: any) => p.type === "udp") ?? s.ports[0];
      return { sessionId: s.id, connect: `${s.host}:${game.host}` }; // id from the response
    }
    const d = await gameye(`/session/${encodeURIComponent(id)}`, {}, [404]);
    if (d.ok) {                                     // ours: started by an earlier attempt
      const s = await d.json();
      const [hostPort] = Object.values(s.port as Record<string, number>);
      return { sessionId: s.id, connect: `${s.host}:${hostPort}` };
    }
    id = `my-game-${crypto.randomUUID()}`;          // 404: another org owns it; fresh id
  }
  throw new Error(`no free session id for match ${matchId}`);
}

export async function reportJoin(sessionId: string, playerIds: string[]) {
  await gameye("/session/player/join", {
    method: "PUT", body: JSON.stringify({ session: sessionId, players: playerIds }),
  });
}

export async function logSnapshot(sessionId: string) {
  return (await gameye(`/logs?id=${encodeURIComponent(sessionId)}&follow=false`)).text();
}
```

Handle 420 and 5xx with bounded retries (same `id`), 402 and 429 by surfacing the
problem instead of retrying, and stop sessions you no longer need. For allocator
patterns, backfill, and region selection built on these calls, load
`gameye-matchmaking`.
