---
name: gameye-web-server
description: Build an authoritative Node.js game server for a browser game and host it on Gameye — WebSocket room servers (ws or Colyseus), the tick loop, session-per-match process lifecycle, managed TLS (wss) for browser clients served over https, and the Dockerfile variant for Node servers. Use whenever adding multiplayer to a web game (Phaser, PixiJS, three.js, Kaplay, vanilla canvas — including AI/agent-built games), writing a WebSocket game server, or when the user mentions browser multiplayer, .io-style games, Colyseus, or socket servers.
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
application's port bindings, with `"tls": true` (see TLS below).

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
browsers block mixed content. Use Gameye's managed TLS:

1. **Mark the game port `"tls": true`** in the application's port bindings. Gameye
   then terminates TLS on the host with an automatically renewed certificate for
   the session's IP address. Your server is unchanged: it still speaks plain `ws`
   on that container port (`createServer` from `http`, as above). No DNS records,
   no certificates, no keys on your side.

   ```json
   { "ports": [ { "requested": 8080, "protocol": "tcp", "tls": true } ] }
   ```

   Set it **when the application is created** (`POST /application`, see
   `gameye-sessions-api`), or ask Gameye support to set it. Editing an application's
   ports (`PUT /application/{name}`) does not apply the flag: ports sent through edit
   end up `tls=false`. `GET /application` shows the current value.
2. **Clients connect `wss://<host>:<hostPort>`**, using the `host` and the game
   port's `ports[].host` from the session start (or describe) response, exactly as
   a native client would use `host:hostPort`.
3. **Verify the first connection in a real browser** before you build on it: load
   the game from its `https://` page against a sandbox session in each region you
   launch in, and confirm in devtools (Network → WS) that the `wss://` connection
   opens with no certificate error. If it doesn't, contact Gameye support rather
   than working around it.

Other cases:

- **You need a named hostname** (for example, a policy that requires one) — the
  fallback is per-session DNS plus a wildcard certificate: on session start your
  allocator creates an A record `s-<sessionId>.play.yourgame.example` → session IP,
  the server terminates TLS itself with a cert for `*.play.yourgame.example` (on a
  port without `"tls": true`), and clients connect
  `wss://s-<id>.play.yourgame.example:<hostPort>`. Scope the wildcard to a dedicated
  subdomain; have the server fetch the key at boot from your backend over a call
  authenticated by its per-match join secret, checked against a live session; never
  bake the key into the image or pass it in session `env`; renew it on your backend.
- **Non-browser packaging** — Electron/Tauri/mobile wrappers aren't subject to
  mixed-content rules and may use `ws://ip:port` directly.
- **Local development** — a plain-HTTP page on `http://localhost` with `ws://` to a
  local container. TLS only applies on Gameye; see `gameye-local-testing`.

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
