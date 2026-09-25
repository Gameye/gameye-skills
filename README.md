# Gameye Agent Skills

**Teach your coding agent to ship multiplayer.**

[Agent Skills](https://agentskills.io) that give Claude Code, Cursor, Copilot, and any
SKILL.md-compatible coding agent the procedural knowledge to take a game from
"single-player build on my laptop" to "authoritative dedicated servers running
worldwide" — on [Gameye](https://gameye.com), the managed game server hosting platform.

AI-assisted game development has an art department ([scenario-labs/skills](https://github.com/scenario-labs/skills)),
engine skills ([awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills)),
and code generation built in. What it doesn't have is a hosting department: the moment a
game goes multiplayer, someone has to design an authoritative server, containerize it,
and run it near players. These skills make that part something your agent already knows.

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
┃ ┣ 📄 gameye-containerize  · · · the container contract, Dockerfiles
┃ ┣ 📄 gameye-local-testing · · · parity testing before you deploy
┃ ┗ 📄 gameye-launch  · · · · · · production checklist + operations
┃
┗ 📁 Orchestration
  ┣ 📄 gameye-sessions-api  · · · the full REST API reference
  ┗ 📄 gameye-matchmaking · · · · allocators, backfill, region selection
```

## Install

```bash
npx skills add gameye/gameye-skills --skill "*"
```

Or install selectively — an agent working on a Godot game doesn't need the Unity skill:

```bash
npx skills add gameye/gameye-skills --skill "gameye" --skill "gameye-godot-server" \
  --skill "gameye-containerize" --skill "gameye-sessions-api"
```

Skills are plain `SKILL.md` files under `skills/`. Any agent that supports the open
Agent Skills format can use them; copying a skill directory into your agent's skills
folder also works.

## What you need

- **Docker** installed locally, and an image registry (Docker Hub or AWS ECR).
- **A Gameye account** — an API token, an application (your image alias + port
  bindings, configured in the Admin Panel), and your enabled regions. Onboarding is
  currently handled by the Gameye team: [gameye.com](https://gameye.com). Sandbox
  environment available for development.
- A multiplayer game — or a coding agent about to build one.

## The golden path

1. **`gameye`** — orient: what the platform does, which skills apply to your game.
2. **`gameye-server-design`** — shape the server: authoritative, session-scoped, config-injected.
3. **`gameye-<engine>-server`** — produce a headless Linux server build for your engine.
4. **`gameye-containerize`** — package it to the container contract.
5. **`gameye-local-testing`** — prove parity locally, then smoke-test in the sandbox.
6. **`gameye-sessions-api`** + **`gameye-matchmaking`** — wire your backend: start
   sessions on demand, hand players an `ip:port`.
7. **`gameye-launch`** — the production checklist.

## Prefer conversational control?

The [Gameye MCP server](https://github.com/gameye/gameye-mcp) exposes the same API as
agent tools (`gameye_launch_session`, `gameye_describe_session`, …) so you can manage
live sessions from your editor. These skills and the MCP server compose: skills teach
the agent *how to build for* Gameye, the MCP server lets it *operate* Gameye.

## Contributing

Each skill is a directory under `skills/` with a `SKILL.md` (YAML frontmatter: `name`,
`description`) and optional `references/`. Run `python3 scripts/validate_skills.py`
before opening a PR — CI runs the same check.

## License

[MIT](LICENSE)
