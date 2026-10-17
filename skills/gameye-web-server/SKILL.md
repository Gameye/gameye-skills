---
name: gameye-web-server
description: Build an authoritative Node.js game server for a browser game and host it on Gameye — WebSocket room servers (ws or Colyseus), the tick loop, session-per-match process lifecycle, the TLS/mixed-content reality for browser clients, and the Dockerfile variant for Node servers. Use whenever adding multiplayer to a web game (Phaser, PixiJS, three.js, Kaplay, vanilla canvas — including AI/agent-built games), writing a WebSocket game server, or when the user mentions browser multiplayer, .io-style games, Colyseus, or socket servers.
metadata:
  version: "1.2.0"
---

# Web game servers on Gameye

Browser games are where most new — and most agent-built — multiplayer games start.
The hosting shape: a Node.js process that is the authoritative simulation, speaking
WebSocket to browser clients, one Gameye session per match. Read
`gameye-server-design` for the architecture contract; this skill covers the web
specifics.

## Stack choice

- **`ws` + a hand-rolled room** — smallest possible surface; the pattern below. Right
  for arena/.io games and anything an agent is generating from scratch.
- **Colyseus** — rooms, state sync, matchmaking hooks out of the box. Right when you
  want schema-based state replication without building it. Its dedicated-process
  deployment maps directly onto a Gameye session.

Rendering in three.js (or another 3D engine)? The server side below is the same.
[references/threejs-client.md](references/threejs-client.md) covers the client half:
joining, interpolating remote players, predicting the local one, shared movement code
and headless physics.

Either way the process serves **one TCP port** for both HTTP (health endpoint, join
handshake) and the WebSocket upgrade — register it as TCP in your Gameye
application's port bindings.

## The authoritative core

```javascript
// server.js — one match per process (session-per-match, see gameye-server-design)
import { WebSocketServer } from "ws";
import { createServer } from "http";

const PORT = Number(process.env.GAME_PORT ?? 8080);
const MATCH_ID = process.env.MATCH_ID ?? "local";
const TICK_HZ = 30;

const httpd = createServer((req, res) => {          // health probe + debug
  res.writeHead(200); res.end("ok");
});
const wss = new WebSocketServer({ server: httpd });

const state = createMatchState();
const inputs = new Map();                            // playerId -> latest intents

wss.on("connection", (ws) => {
  const playerId = authenticate(ws);                 // validate a join token your
  if (!playerId) return ws.close(4001);              // backend minted — never trust
  ws.isAlive = true;                                 // an unauthenticated socket
  ws.on("pong", () => (ws.isAlive = true));
  ws.on("message", (m) => inputs.set(playerId, parseIntent(m))); // intents only
  ws.on("close", () => onLeave(playerId));
  onJoin(playerId);
});

// Fixed-timestep tick: simulate from intents, broadcast snapshots.
// Clients render interpolated state; they never report outcomes.
setInterval(() => {
  simulate(state, inputs, 1 / TICK_HZ);
  broadcast(wss, snapshot(state));
  if (state.finished) endMatch();
}, 1000 / TICK_HZ);

// Reap dead sockets — browsers vanish without closing.
setInterval(() => wss.clients.forEach((ws) => {
  if (!ws.isAlive) return ws.terminate();
  ws.isAlive = false; ws.ping();
}), 15000);

async function endMatch() {
  await reportResults(MATCH_ID, state);   // push to your backend
  process.exit(0);                        // ends the Gameye session cleanly
}
process.on("SIGTERM", async () => {       // stop request / TTL: drain
  broadcast(wss, { type: "server-closing" });
  await reportResults(MATCH_ID, state);   // keep this under ~10s; the window
  process.exit(0);                        // before SIGKILL is up to 50s
});

httpd.listen(PORT, "0.0.0.0", () => console.log(`READY port=${PORT}`));
```

The load-bearing details: bind `0.0.0.0` on a fixed port; authenticate joins with a
token your matchmaker minted (report joins/leaves to your backend, which relays them
to Gameye's player endpoints — the server never holds a Gameye API token);
heartbeat-reap dead sockets so `playerCount` stays honest and empty
matches actually end; exit 0 on match end and on SIGTERM.

## TLS and mixed content — decide this early

A game page served over `https://` **cannot open `ws://`** to a raw `ip:port` —
browsers block mixed content. A Gameye session hands you exactly a raw `ip:port`.
Every browser game must pick one of:

1. **Per-session DNS + wildcard cert** (the production pattern). Your allocator, on
   session start, creates a DNS A record `s-<sessionId>.play.yourgame.example` →
   session host IP (any DNS provider with an API; low TTL). The Node server
   terminates TLS itself (`https.createServer` + `WebSocketServer`) with a wildcard
   certificate for `*.play.yourgame.example`, and clients connect
   `wss://s-<id>.play.yourgame.example:<hostPort>`. Scope the wildcard to a dedicated
   subdomain used for nothing else, so a leaked key can impersonate game sessions
   and nothing more.

   The server fetches the key at boot from your backend over an authenticated call
   (a deliberate, tiny exception to "no downloads at boot"). It presents its
   short-lived per-match join secret and `MATCH_ID` from env; your backend checks the
   secret against the one it issued for that match and confirms a live session for it
   (for example `GET /session?filter[match-id]=<MATCH_ID>`, or the session ID it
   recorded at allocation) before returning the key. An unauthenticated key endpoint
   hands every session hostname to anyone who finds it. Never bake the key into the
   image (registries are not secret stores) and never pass it in session `env`, which
   any `session:read` token in your organization can read. Renew the certificate on
   your backend; servers pick up the new key on their next boot.
2. **A WebSocket relay at the edge.** The page opens `wss://relay.yourgame.example/match?token=…`
   to a small relay (for example a Cloudflare Worker) that holds TLS, and the relay
   opens `ws://` to the session. No DNS records per session and no certificate on the
   game server. The load-bearing details:
   - Your backend mints a short-lived relay token naming the session's host and port
     (HMAC-signed, a few minutes' expiry), and the relay connects only to the address
     in a valid token. A relay that takes the target from the URL is an open proxy.
   - The relay accepts only your page's `Origin` (403 otherwise). Test clients must
     send that `Origin` header too.
   - Cloudflare Workers' `fetch` refuses bare-IP hosts. Turn the session IP into a
     hostname with wildcard DNS (`203.0.113.7.sslip.io`, or your own zone).
   - The relay-to-server hop is unencrypted, and every frame takes one extra hop.
     Keep join authentication on the game server as well.

   [Scrapyard on Gameye](https://github.com/Gameye/scrapyard-nakama) runs this
   pattern in production across three continents (`edge/worker.js`).
3. **Non-browser packaging** — Electron/Tauri/mobile wrappers aren't subject to
   mixed-content rules and may use `ws://ip:port` directly.
4. **Plain-HTTP page** during development only. Fine on `http://localhost`, not
   shippable.

Build the join flow around option 1 or 2 unless the game will never ship in a browser.

## Container specifics

```dockerfile
FROM node:22-slim AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev

FROM node:22-slim
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY server/ ./server/
USER node
EXPOSE 8080/tcp
ENTRYPOINT ["node", "server/server.js"]
```

Run `node` directly — **never `npm start`** as the entrypoint: npm sits between PID 1
and your process and swallows SIGTERM, so your drain handler simply never runs.
Build with `--platform=linux/amd64` (see `gameye-containerize` for the full
contract), then `gameye-local-testing` for the parity checklist and
`gameye-matchmaking` for the allocator that starts these sessions.
