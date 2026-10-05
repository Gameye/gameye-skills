---
name: gameye-unreal-server
description: Produce an Unreal Engine dedicated server build that runs on Gameye — the Server build target, Linux cross-compilation, packaging, runtime flags, and containerization specifics. Use whenever building or debugging an Unreal dedicated server, adding a Server target to a UE project, packaging a Linux server build, or when the user mentions Unreal server hosting, UE dedicated servers, or running Unreal on Gameye.
metadata:
  version: "1.0.0"
---

# Unreal dedicated servers on Gameye

Read `gameye-server-design` for the architecture contract and `gameye-containerize`
for the container contract first; this skill covers what's Unreal-specific.

Unreal's client-server model is native — `AGameModeBase` and all gameplay authority
already live server-side. The work is almost entirely build pipeline, not netcode
architecture.

## The Server target (requires engine source)

Dedicated server builds need a **source build of the engine** — the Epic Games
Launcher binary distribution cannot compile Server targets. Get engine source access
via Epic's GitHub organization, or use a CI image that ships a source-built engine.
Surface this constraint early: it's the long pole for teams on launcher builds.

Add `Source/MyGameServer.Target.cs` next to the existing targets:

```csharp
public class MyGameServerTarget : TargetRules
{
    public MyGameServerTarget(TargetInfo Target) : base(Target)
    {
        Type = TargetType.Server;
        DefaultBuildSettings = BuildSettingsVersion.Latest;
        ExtraModuleNames.Add("MyGame");
    }
}
```

Guard code paths with `UE_SERVER` (and `WITH_SERVER_CODE`) where the server build
should differ; cook content with the server in mind so client-only assets stay out.

## Building for Linux

- **On Windows/macOS**: install Epic's Linux cross-compile toolchain matching your
  engine version, then package for platform `Linux`.
- **On Linux**: native builds work directly; this is the usual CI shape.

Package via UAT:

```bash
RunUAT.sh BuildCookRun -project=MyGame.uproject -platform=Linux \
  -server -serverplatform=Linux -noclient -build -cook -stage -pak -archive \
  -archivedirectory=/out
```

The archived `LinuxServer/` directory is self-contained: `MyGameServer.sh`, the
`MyGameServer` binary under `MyGame/Binaries/Linux/`, and cooked content. Strip debug
symbols for the image (`-nodebuginfo`, or skip shipping `.debug`/`.sym` files) —
Unreal server images get large, and image size is fleet-preload time.

## Runtime flags and configuration

Launch shape for containers:

```
./MyGameServer.sh MyMap -port=7777 -log -stdout -FullStdOutLogOutput -unattended
```

- `-port=7777` — the listen port; keep it a fixed container port on `0.0.0.0` (the
  default bind). Gameye maps it to a public host port (see `gameye-containerize`).
- `-log -stdout -FullStdOutLogOutput` — put the full log on stdout where the Gameye
  logs endpoint can see it, not only in `Saved/Logs/`.
- `-unattended` — no interactive prompts.
- The startup map/mode can come straight from session `args`
  (`MyMap?game=MyGameMode`), which your matchmaker sets per match. Under warm pools
  request `args` and `env` are ignored, so fetch the match config from your backend
  at boot instead (`gameye-server-design`).

Read env config with `FPlatformMisc::GetEnvironmentVariable(TEXT("MATCH_ID"))`;
parse extra args with `FParse::Value(FCommandLine::Get(), ...)`. Log a
`READY port=7777` line from `AGameModeBase::BeginPlay` (or once `OnStart` completes),
and log player logins/logouts (`PostLogin`/`Logout`). Report them to your backend,
which relays them to Gameye's player join/leave endpoints — the server never holds a
Gameye API token, and session env (readable by any `session:read` token in your
organization) carries only short-lived per-match values.

## Shutdown

SIGTERM triggers Unreal's engine-exit path. Hook cleanup once and reuse it for the
natural match end:

```cpp
FCoreDelegates::OnEnginePreExit.AddStatic(&ReportResultsAndFlush);
// on match end: ReportResultsAndFlush(); FPlatformMisc::RequestExit(false);
```

Get the essentials out within about 10 seconds of SIGTERM; the window before the
container is killed is up to 50 seconds, but don't spend it. Write replays/stats you
want post-mortem to one fixed directory before exiting, and fetch it after `exited`
with `GET /artifacts?session=<session-id>&path=<that-directory>` (a plain tar;
`gameye-sessions-api` → artifacts). Exit when the match
ends; don't seamless-travel back to a lobby on a hosted session.

## Container specifics

```dockerfile
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 game \
 && useradd --system --uid 10001 --gid game --no-create-home --shell /usr/sbin/nologin game
WORKDIR /server
COPY --chown=game:game LinuxServer/ /server/
USER game
EXPOSE 7777/udp
ENTRYPOINT ["/server/MyGameServer.sh", "-port=7777", "-log", "-stdout", \
            "-FullStdOutLogOutput", "-unattended"]
```

`MyGameServer.sh` execs the real binary, so PID 1 signal delivery works. Build with
`--platform=linux/amd64`. UE servers are hungrier than most — measure a full match
with `docker stats` and size the Gameye resource profile honestly (guaranteed and
billed; see `gameye-containerize`).

## Matchmaking pairing

Typical stacks: **EOS Matchmaking/Sessions** or **PlayFab** forming the match, then
your allocator calling Gameye `POST /session` and distributing `host:port` to clients
(full patterns in `gameye-matchmaking`).
