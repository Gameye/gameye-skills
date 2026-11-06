---
name: gameye-godot-server
description: Produce a Godot 4 dedicated server build that runs on Gameye — the dedicated_server export feature, headless mode, high-level multiplayer with ENet or WebSocket, runtime configuration, and the Dockerfile variant for Godot server builds. Use whenever building or debugging a Godot multiplayer server, exporting a Godot headless Linux build, or when the user mentions Godot dedicated servers, ENetMultiplayerPeer, or hosting a Godot game on Gameye.
metadata:
  version: "1.1.0"
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
  exit 0: call `shutdown()` from the hook below. Exiting ends the Gameye session
  cleanly.
- **SIGTERM** (stop request / TTL): needs the wrapper and hook below, because
  Godot does not run your script on SIGTERM by itself.

## Shutdown

Godot 4 does not turn SIGTERM into a notification for your scripts. In a drain test
on Godot 4.7.2 (Linux, `--headless`, `docker stop`), Godot as PID 1 ignored SIGTERM
until the SIGKILL, and as a child process it died at once without running any script,
so `NOTIFICATION_WM_CLOSE_REQUEST` in `_notification()` never fired. The fix: the
container's entrypoint is a small `sh` wrapper (under Container specifics) that turns
SIGTERM into a stop file, and an autoload polls for that file. One `shutdown()`
function serves the stop file, a quit request and the natural match end.

<!-- gameye-template: godot/shutdown-hook -->
Written against Godot 4.7.2 and drain-tested there. Signal handling can change
between Godot versions: rerun the drain test in `gameye-local-testing` after an
engine upgrade rather than assuming it still holds.

```gdscript
# match_lifecycle.gd: add as an autoload (Project Settings → Globals → Autoload).
extends Node

const STOP_FILE := "/tmp/gameye-stop"   # start.sh creates it on SIGTERM

var _stopping := false


func _ready() -> void:
    get_tree().set_auto_accept_quit(false)   # quit only after shutdown() has flushed
    var poll := Timer.new()
    poll.wait_time = 0.25
    poll.timeout.connect(_check_stop_file)
    add_child(poll)
    poll.start()


func _check_stop_file() -> void:
    if FileAccess.file_exists(STOP_FILE):
        shutdown()


func _notification(what: int) -> void:
    if what == NOTIFICATION_WM_CLOSE_REQUEST:   # a quit request (not SIGTERM)
        shutdown()


# The one cleanup path: stop request or TTL (via the stop file) and match end.
func shutdown() -> void:
    if _stopping:
        return
    _stopping = true
    print("SHUTDOWN")
    # Hard cap: the essentials should be out within ~10s; SIGKILL follows within 50s.
    get_tree().create_timer(10.0).timeout.connect(get_tree().quit.bind(0))
    await report_results_and_flush()
    get_tree().quit(0)


func report_results_and_flush() -> void:
    pass   # push results to your backend; write artifacts to one fixed directory
```
<!-- /gameye-template -->

## Container specifics

<!-- gameye-template: godot/dockerfile -->
```dockerfile
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 game \
 && useradd --system --uid 10001 --gid game --no-create-home --shell /usr/sbin/nologin game
WORKDIR /server
COPY --chown=game:game build/game-server.x86_64 build/game-server.pck /server/
# Godot ignores SIGTERM as PID 1 and dies without cleanup as a child, so this
# wrapper is PID 1: it turns SIGTERM into the stop file match_lifecycle.gd polls.
COPY <<'EOF' /server/start.sh
#!/bin/sh
trap 'touch /tmp/gameye-stop' TERM INT
rm -f /tmp/gameye-stop
/server/game-server.x86_64 --headless "$@" &
child=$!
wait "$child"; rc=$?
while kill -0 "$child" 2>/dev/null; do wait "$child"; rc=$?; done
exit "$rc"
EOF
RUN chmod +x /server/game-server.x86_64 /server/start.sh
USER game
EXPOSE 7777/udp
ENTRYPOINT ["/server/start.sh"]
```
<!-- /gameye-template -->

The wrapper is PID 1 and passes session args through to Godot; keep `ENTRYPOINT` in
exec form so SIGTERM reaches the wrapper and not another shell. The inline
`COPY <<'EOF'` needs BuildKit, the default builder since Docker 23. Build with
`--platform=linux/amd64`. Then `gameye-local-testing` for the parity checklist and
`gameye-matchmaking` for the allocator.
