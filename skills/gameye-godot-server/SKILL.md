---
name: gameye-godot-server
description: Produce a Godot 4 dedicated server build that runs on Gameye — the dedicated_server export feature, headless mode, high-level multiplayer with ENet or WebSocket, runtime configuration, and containerization specifics. Use whenever building or debugging a Godot multiplayer server, exporting a Godot headless Linux build, or when the user mentions Godot dedicated servers, ENetMultiplayerPeer, or hosting a Godot game on Gameye.
metadata:
  version: "1.0.0"
---

# Godot 4 dedicated servers on Gameye

Read `gameye-server-design` for the architecture contract and `gameye-containerize`
for the container contract first; this skill covers what's Godot-specific.

Godot 4 is a genuinely good fit for hosted dedicated servers: the export template is
small, headless mode is first-class, and the whole server image can land well under
100 MB — which means fast fleet preloads and fast session boots.

## Export

Create a **Linux** export preset for the server and add the `dedicated_server`
feature tag (Export dialog → Features). That tag does two things: strips visual and
audio resources from the export (textures export as placeholders), and makes
`OS.has_feature("dedicated_server")` true at runtime so one codebase can branch
cleanly between client and server behavior.

Run the exported binary with `--headless` — no display server, no rendering, works in
a bare container. Export from CI:

```bash
godot --headless --export-release "LinuxServer" build/game-server.x86_64
```

Structure scenes so server logic never touches stripped resources (guard with
`OS.has_feature("dedicated_server")`), or maintain a separate server entry scene.

## Networking

Godot's high-level multiplayer (`MultiplayerAPI`, `MultiplayerSpawner`,
`MultiplayerSynchronizer`, RPCs) with an authoritative server:

```gdscript
func _ready() -> void:
    var port := int(OS.get_environment("GAME_PORT")) if OS.get_environment("GAME_PORT") else 7777
    var peer := ENetMultiplayerPeer.new()
    var err := peer.create_server(port, int(OS.get_environment("MAX_PLAYERS")) if OS.get_environment("MAX_PLAYERS") else 16)
    if err != OK:
        push_error("bind failed: %s" % err)
        get_tree().quit(1)
    multiplayer.multiplayer_peer = peer
    multiplayer.peer_connected.connect(_on_join)
    multiplayer.peer_disconnected.connect(_on_leave)
    print("READY port=%d" % port)
```

- **ENet** (UDP) for desktop/mobile clients — register the port as UDP in your Gameye
  application's port bindings.
- **WebSocketMultiplayerPeer** (TCP) when clients are browsers (Godot web export) —
  then the TLS/mixed-content reality in `gameye-web-server` applies to you too; read
  that section before shipping a browser-facing Godot server.

Authority discipline: mark server-owned state, validate RPCs
(`@rpc("any_peer")` handlers must treat `multiplayer.get_remote_sender_id()` as
untrusted input), and never let a client set outcomes directly.

## Configuration, logging, lifecycle

- Config via env (`OS.get_environment`) as shown — that's what Gameye injects from
  the session-start call. Session `args` are also available via `OS.get_cmdline_args()`
  if you prefer flag-style config. Env is readable by any `session:read` token in
  your organization: only short-lived per-match values (a join secret) go there,
  never a Gameye API token. Under warm pools request env and args are ignored, so
  fetch match config from your backend at boot (`gameye-server-design`).
- `print()` goes to stdout, which is exactly where the Gameye logs endpoint reads.
  Log the boot config line, READY, joins/leaves, and the final result. Report
  joins/leaves to your backend, which relays them to Gameye's player join/leave
  endpoints — the server itself never calls Gameye.
- Tick rates are explicit decisions: `Engine.physics_ticks_per_second` for the
  simulation, and set `Engine.max_fps` (e.g. to the tick rate) so the headless main
  loop doesn't spin a core flat out.
- **Match end**: report results to your backend, write anything durable, then
  `get_tree().quit(0)`. Exiting ends the Gameye session cleanly.
- **SIGTERM** (stop request / TTL): verify your cleanup runs under
  `docker stop` — put it in one function wired to both the match-end path and
  `NOTIFICATION_WM_CLOSE_REQUEST` in `_notification()`, and confirm behavior with the
  drain test in `gameye-local-testing` rather than assuming the engine's signal
  handling matches your Godot version. Flush the essentials within about 10 seconds
  of SIGTERM; the window before the container is killed is up to 50 seconds.

## Container specifics

```dockerfile
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 game \
 && useradd --system --uid 10001 --gid game --no-create-home --shell /usr/sbin/nologin game
WORKDIR /server
COPY --chown=game:game build/game-server.x86_64 build/game-server.pck /server/
RUN chmod +x /server/game-server.x86_64
USER game
EXPOSE 7777/udp
ENTRYPOINT ["/server/game-server.x86_64", "--headless"]
```

Exec-form entrypoint keeps Godot as PID 1 for signal delivery; build with
`--platform=linux/amd64`. Then `gameye-local-testing` for the parity checklist and
`gameye-matchmaking` for the allocator.
