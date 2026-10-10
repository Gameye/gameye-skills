# three.js clients

Detail for `gameye-web-server` when the browser game renders with three.js (or
any WebGL/WebGPU renderer). The server shape is unchanged: one authoritative
Node process per match, WebSocket over TLS, one Gameye session per match. This
file covers what the 3D client and the shared code need so that server stays
authoritative and the game still feels responsive.

## What runs where

| Piece | Runs in | Ships in |
|---|---|---|
| Rendering, camera, input capture, interpolation, prediction | Browser | Static hosting or a CDN, never the server image |
| Simulation, physics, hit checks, scoring | Node game server | The Gameye image |
| Constants, input format, movement step, snapshot format | Both | A `shared/` module imported by client and server |

Never run the three.js renderer on the server. It needs no WebGL context, so
don't add headless-gl or a GPU. If server code wants vector maths, import only
`Vector3` and `Quaternion` from `three` (they run in plain Node), or use plain
numbers. Keep the server image to `server/` plus `shared/`. Don't copy the
client bundle or its models and textures into it.

## Joining a match

The browser never calls the Gameye API and never holds a Gameye token. It asks
your backend for a match, then connects to the address the backend returns:

```javascript
// client/net.js
// Your own matchmaking backend, not the Gameye API.
const { url, joinToken } = await fetch("https://backend.yourgame.example/join", { method: "POST" })
  .then((r) => r.json());
// url is wss://<host>:<hostPort> from the session (port marked "tls": true), see "TLS and mixed content"
const ws = new WebSocket(url);
ws.binaryType = "arraybuffer";
ws.addEventListener("open", () => ws.send(JSON.stringify({ type: "join", joinToken })));
```

Send the join token as the first message rather than in the URL, because URLs end
up in proxy and server logs. The server drops any socket that sends anything else
first, or nothing within a few seconds.

## Shared movement step

Client prediction only works if client and server move a player the same way.
Put the step in `shared/` and give it nothing but plain data:

```javascript
// shared/movement.js
export const TICK_HZ = 30;
export const DT = 1 / TICK_HZ;
const SPEED = 6; // metres per second

// input: { seq, forward, right, yaw }, each axis in -1..1
export function step(player, input) {
  const sin = Math.sin(input.yaw), cos = Math.cos(input.yaw);
  player.x += (input.forward * sin + input.right * cos) * SPEED * DT;
  player.z += (input.forward * cos - input.right * sin) * SPEED * DT;
  player.yaw = input.yaw;
}
```

The server applies each input with `step` in its tick and records the last `seq`
it processed for each player in the snapshot it broadcasts.

## Remote entities: snapshot interpolation

Render other players a little in the past, between the two snapshots either side
of that moment. They then move smoothly even though snapshots arrive in bursts.

```javascript
// client/interpolation.js
import * as THREE from "three";

const RENDER_DELAY_MS = 100; // about three ticks at 30 Hz; raise it on jittery networks
const buffer = [];           // { t, entities: Map<id, { x, y, z, qx, qy, qz, qw }> }
const a = new THREE.Vector3(), b = new THREE.Vector3();
const qa = new THREE.Quaternion(), qb = new THREE.Quaternion();

export function onSnapshot(snap) {
  buffer.push({ t: snap.serverTime, entities: snap.entities });
  while (buffer.length > 30) buffer.shift();
}

export function interpolate(meshes, serverNow) {
  const renderTime = serverNow - RENDER_DELAY_MS;
  let i = buffer.length - 1;
  while (i > 0 && buffer[i - 1].t > renderTime) i--;
  const older = buffer[i - 1], newer = buffer[i];
  if (!older || !newer) return;
  const alpha = THREE.MathUtils.clamp((renderTime - older.t) / (newer.t - older.t), 0, 1);

  for (const [id, mesh] of meshes) {
    const s0 = older.entities.get(id), s1 = newer.entities.get(id);
    if (!s0 || !s1) continue;
    mesh.position.lerpVectors(a.set(s0.x, s0.y, s0.z), b.set(s1.x, s1.y, s1.z), alpha);
    mesh.quaternion.slerpQuaternions(qa.set(s0.qx, s0.qy, s0.qz, s0.qw), qb.set(s1.qx, s1.qy, s1.qz, s1.qw), alpha);
  }
}
```

Interpolate in the render loop (`renderer.setAnimationLoop`), not when a message
arrives. `serverNow` is the local clock plus an offset estimated from the
server's timestamps; a running average of `serverTime - Date.now()` across
snapshots is enough for interpolation. Reuse the scratch vectors as shown:
allocating a new `Vector3` per entity per frame causes garbage-collection
stutter.

## The local player: prediction and reconciliation

Waiting a round trip before your own character moves feels broken. Apply input
immediately, then correct to the server:

```javascript
// client/prediction.js
import { step } from "../shared/movement.js";

let seq = 0;
const pending = []; // inputs the server hasn't confirmed yet

export function sendInput(ws, local, input) {
  input.seq = ++seq;
  step(local, input);         // predict now
  pending.push(input);
  ws.send(JSON.stringify({ type: "input", ...input }));
}

export function reconcile(local, serverSelf) {
  // Restart from the server's state, then replay what it hasn't seen yet.
  Object.assign(local, serverSelf.state);
  while (pending.length && pending[0].seq <= serverSelf.lastSeq) pending.shift();
  for (const input of pending) step(local, input);
}
```

Sample input on the same fixed tick as the server (`DT`), not once per rendered
frame, or prediction drifts on high-refresh screens. When a correction is large,
ease the mesh towards the corrected position over a few frames rather than
snapping it.

## Physics

If the game needs real 3D physics (collisions, projectiles, vehicles), the
server's physics decides. The client may run the same engine to predict, but its
results are never trusted.

- **Rapier** (`@dimforge/rapier3d-compat`) runs in Node and the browser from one
  package (call `await RAPIER.init()` before use). It is the default choice.
- **cannon-es** is pure JavaScript and simpler for light physics.

Pin the same engine version on both sides and step it with the fixed `DT` from
`shared/`. Don't load the browser's GLTF meshes on the server for collision.
Export simple colliders (boxes, capsules, a level heightfield) to a JSON file in
`shared/`, and build both worlds from it.

## Bandwidth

- Start with JSON. Move to binary (`ArrayBuffer` with fixed offsets) once the
  game works and the snapshot size shows up in profiling.
- Send only entities that changed since the last acknowledged snapshot, and
  round positions to centimetres and rotations to a few decimal places.
- For large maps, send each player only the entities near them.
- A 30 Hz tick with snapshots on every tick suits most action games. Fewer
  snapshots save bandwidth at the cost of a longer render delay.

## Checklist

- The browser gets a `wss://` address and a join token from your backend, and
  never holds a Gameye token.
- Clients send inputs with sequence numbers, never positions or outcomes.
- Remote entities are interpolated with a render delay of a few ticks.
- The local player is predicted with the shared `step` and reconciled using the
  server's last processed `seq`.
- Server physics, if any, runs headless in Node; the client copy only predicts.
- The server image contains `server/` and `shared/`, not the three.js client or
  its assets.
