# Gameye Agent Skills

[![Discord](https://img.shields.io/badge/Discord-join%20chat-5865F2?logo=discord&logoColor=white)](https://discord.com/invite/QvJ3KH5max)

**Teach your coding agent to ship multiplayer.**

[Agent Skills](https://agentskills.io) that give Claude Code, Cursor, Copilot, and any
SKILL.md-compatible coding agent the procedural knowledge to take a game from
"single-player build on my laptop" to "authoritative dedicated servers running
worldwide" on [Gameye](https://gameye.com), the managed game server hosting platform.

AI-assisted game development has an art department ([scenario-labs/skills](https://github.com/scenario-labs/skills)),
engine skills ([awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills)),
and code generation built in. What it doesn't have is a hosting department: the moment a
game goes multiplayer, someone has to design an authoritative server, containerize it,
and run it near players. These skills make that part something your agent already knows.

Every API fact in the skills is checked against the live Gameye server, and the request
and response reference is generated from the API spec plus the recorded places where the
server differs from it.

```
📁 Gameye Skills
┃
┣ 📁 Architecture
┃ ┣ 📄 gameye · · · · · · · · · · start here: platform overview + routing
┃ ┗ 📄 gameye-server-design · · · authoritative servers, session lifecycle
┃
┣ 📁 Engines
┃ ┣ 📄 gameye-unity-server  · · · Unity Dedicated Server builds
┃ ┣ 📄 gameye-unreal-server · · · Unreal dedicated server targets
┃ ┣ 📄 gameye-godot-server  · · · Godot 4 headless exports
┃ ┗ 📄 gameye-web-server  · · · · Node.js servers for browser games
┃
┣ 📁 Shipping
┃ ┣ 📄 gameye-containerize  · · · the container contract, registries, webhooks
┃ ┣ 📄 gameye-local-testing · · · parity testing before you deploy
┃ ┣ 📄 gameye-launch  · · · · · · production checklist + operations
┃ ┗ 📄 gameye-troubleshoot  · · · deploys that won't load or start
┃
┗ 📁 Orchestration
  ┣ 📄 gameye-sessions-api  · · · the full REST API, server-verified
  ┗ 📄 gameye-matchmaking · · · · allocators, backfill, region selection
```

## Install

Pick one of these. They all install the same twelve skills from `skills/`.

### With the `skills` CLI (any agent)

Install every skill into the current project:

```bash
npx skills add gameye/gameye-skills --skill "*"
```

Install them for your user account instead, so every project gets them:

```bash
npx skills add gameye/gameye-skills --skill "*" -g
```

Or install selectively. An agent working on a Godot game doesn't need the Unity skill:

```bash
npx skills add gameye/gameye-skills --skill "gameye" --skill "gameye-godot-server" \
  --skill "gameye-containerize" --skill "gameye-sessions-api"
```

To see what's available without installing anything:

```bash
npx skills add gameye/gameye-skills --list
```

**On Windows**, run these in Command Prompt, or type `npx.cmd` instead of `npx` in
PowerShell. On a new Windows install, PowerShell refuses to run `npx` with "running
scripts is disabled on this system", because Node installs it as a PowerShell script.
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` also fixes that. The skills CLI copies
the skills on Windows instead of linking them. We've tested the skills CLI, the Claude Code
plugin and the MCP server on Windows 11 with Node.js 22. If something breaks on Windows,
please open an issue.

### As a Claude Code plugin (skills + MCP server)

This repository is also a Claude Code plugin marketplace. In a Claude Code session:

```
/plugin marketplace add gameye/gameye-skills
/plugin install gameye@gameye
```

The plugin installs all twelve skills and the [Gameye MCP server](#gameye-mcp-server).
When you enable it, Claude Code asks for two settings:

| Setting | What to enter |
|---|---|
| Gameye API token | A token from the Admin Panel (Users → API Tokens) with the narrowest scopes you need. Claude Code keeps it in your system's secure credential store, not in `settings.json`. |
| Gameye environment | `sandbox` (default) or `production`. See [Which host is yours](#which-host-is-yours). |

The MCP server settings need a recent version of Claude Code. If you only want the
skills, use the `skills` CLI above instead.

### Manual copy

Skills are plain `SKILL.md` files. Copy the directories you want from `skills/` into your
agent's skills folder (for Claude Code, `.claude/skills/` in a project or
`~/.claude/skills/` for your user). Manual copies don't update themselves; see below.

## Gameye MCP server

[gameye-mcp](https://github.com/gameye/gameye-mcp) is the sister project to these skills.
It exposes every Gameye client API operation as a `gameye_*` tool, so your agent can
launch, inspect and stop sessions, check tags, and fetch logs and artifacts from the
conversation. The skills teach the agent *how to build for* Gameye; the MCP server lets it
*operate* Gameye. Both use the same environment variables (`GAMEYE_API_TOKEN`,
`GAMEYE_ENV`).

The Claude Code plugin above bundles it and keeps the token in secure storage; prefer
it. For other MCP clients, export `GAMEYE_API_TOKEN` from your secret manager or shell
profile, then run:

```bash
npx -y gameye-mcp
# Claude Code without the plugin:
claude mcp add gameye -e GAMEYE_API_TOKEN="$GAMEYE_API_TOKEN" -- npx -y gameye-mcp@0
```

On Windows, start it through `cmd /c` (`-- cmd /c npx -y gameye-mcp@0`); the
[gameye-mcp README](https://github.com/gameye/gameye-mcp#windows) has the details.

Avoid putting the token literally on the command line (`GAMEYE_API_TOKEN=<token> ...`):
it stays in your shell history.

Add `GAMEYE_ENV=production` for an enterprise production token. The
[gameye-mcp README](https://github.com/gameye/gameye-mcp) has client configuration
examples and the full list of tools and settings.

When an agent acts on Gameye itself, it uses the `gameye_*` tools if they're available and
plain HTTP otherwise. Code it writes for your backend always uses HTTP.

## Staying up to date

The skills get corrections as the Gameye API evolves, and every merged change reaches you
without waiting for a release.

- **`skills` CLI:** run `npx skills update` (add `-g` or `-p` to pick global or project
  scope). The CLI tracks each skill folder's content and updates the ones that changed.
- **Pin the skills for your team:** a project install writes `skills-lock.json`. Commit it
  so everyone gets the same skill versions, then run `npx skills update` and commit the
  new lock file when you want to move forward.
- **Claude Code plugin:** Claude Code doesn't auto-update third-party marketplaces unless
  you ask it to. To turn auto-update on, open `/plugin`, go to **Marketplaces**, select
  `gameye`, and choose **Enable auto-update**. Or update by hand with
  `/plugin marketplace update gameye`.
- **With the Gameye MCP server:** `gameye_update_skills` checks your installs (skills
  CLI, user-wide or project, and the Claude Code plugin) against the latest pack, and
  updates them through the same tools when you agree. The `gameye` skill asks your
  agent to run the check once per conversation.
- **Manual copies:** copy the directories again.

Each release is listed in [CHANGELOG.md](CHANGELOG.md). The `gameye` skill states its pack
version (`Pack version:` in [`skills/gameye/SKILL.md`](skills/gameye/SKILL.md)), and each
skill carries a `metadata.version`. If your agent hits an API response the skills don't
describe, it will suggest updating.

## Which host is yours

Gameye has two API hosts. Which one you use depends on your customer tier, not on how far
along your game is:

| Customer | Host |
|---|---|
| Self-serve | `https://api.sandbox-gameye.gameye.net` |
| Enterprise | `https://api.production-gameye.gameye.net` |

Sandbox is the self-serve product and the permanent home of self-serve customers. Live
matches run there, and there is no move to production later. Enterprise customers are
onboarded onto production by the Gameye team. Tokens from one host don't work on the
other.

## What you need

- **Docker** installed locally, and an image registry: Docker Hub, AWS ECR, or GitHub
  Container Registry (GHCR). On self-serve, GHCR is the zero-cost private option; see
  [Gameye's GHCR guide](https://gameye.com/docs/getting-started/ghcr/).
- **A Gameye account:** an API token, an application (your image alias and port bindings,
  configured in the Admin Panel), and your enabled regions. See
  [gameye.com](https://gameye.com) to get started.
- A multiplayer game, or a coding agent about to build one.

## The golden path

1. **`gameye`**: orient on what the platform does and which skills apply to your game.
2. **`gameye-server-design`**: shape the server so it's authoritative, session-scoped and
   configured at launch.
3. **`gameye-<engine>-server`**: produce a headless Linux server build for your engine.
4. **`gameye-containerize`**: package it to the container contract and connect your
   registry.
5. **`gameye-local-testing`**: prove parity locally, then smoke-test against your Gameye
   host.
6. **`gameye-sessions-api`** + **`gameye-matchmaking`**: wire your backend to start
   sessions on demand and hand players an `ip:port`.
7. **`gameye-launch`**: work through the production checklist.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the repository layout, where API facts come
from, the checks CI runs, and the versioning rules for skill changes.

## About Gameye

[Gameye](https://gameye.com/?utm_source=github&utm_medium=readme&utm_campaign=gameye-skills) is a managed hosting platform for multiplayer game servers. You bring a container image, and Gameye starts a dedicated server for each match through one API.

- Getting started: [gameye.com/docs/getting-started](https://gameye.com/docs/getting-started/?utm_source=github&utm_medium=readme&utm_campaign=gameye-skills)
- Gameye docs: [gameye.com/docs](https://gameye.com/docs/?utm_source=github&utm_medium=readme&utm_campaign=gameye-skills)
- Try it free: [trial.gameye.com](https://trial.gameye.com/?utm_source=github&utm_medium=readme&utm_campaign=gameye-skills)

## Security

Please report vulnerabilities privately as described in [SECURITY.md](SECURITY.md), not in
public issues.

## License

[MIT](LICENSE)
