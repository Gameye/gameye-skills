---
name: gameye-unity-server
description: Produce a Unity dedicated server build that runs on Gameye — the Dedicated Server build target, netcode choices (Netcode for GameObjects, FishNet, Mirror, Photon Fusion), runtime configuration, containerization specifics, and the gameye-unity-bootstrap fast path. Use whenever building or debugging a Unity multiplayer server, adding dedicated server support to a Unity project, or when the user mentions Unity headless builds, Unity server hosting, Unity Matchmaker, or running Unity on Gameye.
---

# Unity dedicated servers on Gameye

Read `gameye-server-design` for the architecture contract and `gameye-containerize`
for the container contract first; this skill covers what's Unity-specific.

## The fast path

If the project will use **Unity Matchmaker** for matchmaking, use the
[`gameye-unity-bootstrap`](https://github.com/gameye/gameye-unity-bootstrap) CLI
before hand-rolling anything:

```bash
npm install -g gameye-unity-bootstrap
gameye-unity init        # writes config + starter Dockerfile
gameye-unity login       # Unity, Gameye, Docker Hub credentials
gameye-unity image push  # linux/amd64 build, <git-sha> + latest tags
gameye-unity deploy      # deploys the Cloud Code allocator module
gameye-unity smoke-test  # real Matchmaker ticket end to end
gameye-unity doctor      # points at the exact broken link when something fails
```

It encodes the working Unity Matchmaker + Gameye + Docker Hub recipe, including the
Cloud Code allocator that calls `POST /session` when a match forms. The rest of this
skill still applies to the server build itself, and entirely applies when using a
different matchmaker.

## Build target

Use the **Dedicated Server** build target (Unity 2021.2+; install the "Linux
Dedicated Server Build Support" module). Target platform **Linux**. This is not the
old "headless mode" checkbox: the Dedicated Server target compiles with the
`UNITY_SERVER` define and strips rendering, audio, and other client-only subsystems
from both build size and runtime cost.

- Prefer **IL2CPP** scripting backend for production servers (throughput, smaller
  attack surface); Mono is fine while iterating.
- Guard client-only code with `#if !UNITY_SERVER` and server-only code with
  `#if UNITY_SERVER` so one project produces both builds.
- CLI build for CI:
  `unity -batchmode -quit -projectPath . -buildTarget Linux64 -standaloneBuildSubtarget Server -executeMethod BuildScript.BuildServer`

## The tick-rate trap

A dedicated server build runs its main loop **as fast as the CPU allows** — there is
no vsync to throttle it, so an unconfigured server pins a full core doing nothing.
Set the loop rate explicitly at boot:

```csharp
Application.targetFrameRate = 60;   // match your netcode tick rate
QualitySettings.vSyncCount = 0;
```

This is the difference between a match fitting comfortably in its resource profile
and mystery 100% CPU on every session.

## Netcode options

Any Unity netcode stack with a server-authoritative dedicated mode works — Gameye
just runs the process:

- **Netcode for GameObjects (NGO)** with Unity Transport — Unity's first-party stack;
  pairs naturally with Unity Matchmaker and the bootstrap CLI.
- **FishNet** — Gameye maintains a runnable reference:
  [`gameye-fishnet-sample`](https://github.com/gameye/gameye-fishnet-sample) (project,
  Dockerfile, CI). Start from it rather than from a blank page.
- **Mirror** — mature and widely documented; same integration shape.
- **Photon Fusion** in dedicated server mode — a Gameye integration exists; here
  Fusion handles simulation/replication while Gameye replaces Photon cloud as the
  place servers run.

Whichever stack: listen on `0.0.0.0` on a fixed port. With Unity Transport:

```csharp
var transport = NetworkManager.Singleton.GetComponent<UnityTransport>();
transport.SetConnectionData("0.0.0.0", port);   // listen address, container port
NetworkManager.Singleton.StartServer();
```

## Runtime configuration

Read match config exactly as Gameye injects it (see `gameye-sessions-api`):

```csharp
static string Env(string k, string fallback) =>
    Environment.GetEnvironmentVariable(k) ?? fallback;

ushort port = ushort.Parse(Env("GAME_PORT", "7777"));
string matchId = Env("MATCH_ID", "local");
// args: Environment.GetCommandLineArgs() for --key=value extras
```

Log a `READY port=7777` line once `StartServer()` succeeds, and log joins/leaves —
your backend relays those to Gameye's player join/leave endpoints.

## Shutdown

On SIGTERM the Unity player initiates an orderly quit. Put flush logic in one place
and wire it to both paths — signal-initiated quit and natural match end:

```csharp
Application.quitting += ReportResultsAndFlush;
// on match end: ReportResultsAndFlush(); Application.Quit(0);
```

Exiting after the match is the correct behavior (`gameye-server-design` explains
why); don't return to a lobby scene.

## Container specifics

The Linux Dedicated Server build output is a binary plus a `_Data` folder (and for
IL2CPP, `UnityPlayer.so` and friends). On top of the standard pattern in
`gameye-containerize`:

```dockerfile
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 game \
 && useradd --system --uid 10001 --gid game --no-create-home --shell /usr/sbin/nologin game
WORKDIR /server
COPY --chown=game:game Build/LinuxServer/ /server/
RUN chmod +x /server/MyGameServer
USER game
EXPOSE 7777/udp
ENTRYPOINT ["/server/MyGameServer", "-batchmode", "-nographics", "-logFile", "-"]
```

- **`-logFile -`** routes the Unity player log to stdout — without it your logs go to
  a file inside the container and the Gameye logs endpoint shows nothing.
- Exec-form `ENTRYPOINT` keeps the Unity process as PID 1 for SIGTERM delivery.
- Build the image with `--platform=linux/amd64` (Apple Silicon gotcha — see
  `gameye-containerize`).

Then: `gameye-local-testing` for the parity checklist, `gameye-matchmaking` for the
allocator.
