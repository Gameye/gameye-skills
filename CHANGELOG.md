# Changelog

All notable changes to the Gameye agent skills are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

Each release has a **pack version**: the `Pack version:` line in
[`skills/gameye/SKILL.md`](skills/gameye/SKILL.md). Each skill also has its own
`metadata.version` in its frontmatter. Installs track the latest commit on `main` through
`npx skills update` or Claude Code plugin updates, so you get fixes without waiting for a
release. The versions here tell you what changed and whether your copy is current.

## 1.0.0 - Unreleased

First public release. Pack version 1.0.0; all eleven skills are at `metadata.version`
1.0.0.

Eval baseline: pending

### Added

- **Hosts by customer tier.** The skills name exactly two API hosts and pick between them
  by tier, not by development stage:
  `https://api.sandbox-gameye.gameye.net` for self-serve customers (their permanent home,
  where their live matches run) and `https://api.production-gameye.gameye.net` for
  enterprise customers.
- **Full API coverage.** `gameye-sessions-api` covers every operation in the client API:
  sessions, players, artifacts, logs, tokens, applications, application tags, regions,
  locations and tag existence, plus Docker Hub and GitHub webhook setup.
- **Server-verified reference.** A request/response reference generated from the API spec
  snapshot plus recorded server divergences (`spec/overrides.yaml`), with pointers to each
  host's live `/openapi.yaml` for the authoritative schema.
- **Registry guidance for Docker Hub, AWS ECR and GHCR.** Granting `gameyedocker` Read
  access (including unticking GHCR's inherited access), enabling tags, webhook
  registration with delivery-delay and identical-image caveats, and tag retention. GHCR
  support must be confirmed with Gameye support for your environment.
- **Gameye MCP sister project.** The `gameye` skill introduces
  [gameye-mcp](https://github.com/gameye/gameye-mcp), shares one environment variable
  scheme (`GAMEYE_API_TOKEN`, `GAMEYE_ENV`) and one `gameye_*` tool naming scheme, and
  states one routing rule: an agent acting on Gameye itself uses the MCP tools when they
  are present and HTTP otherwise; code written for the user's backend always uses HTTP.
- **Update channel.** Install and update with `npx skills add` / `npx skills update`, or
  as a Claude Code plugin from this repository's marketplace, which also bundles the MCP
  server (`npx -y gameye-mcp@0`) with the API token stored as a sensitive setting.
- **Version awareness.** The `gameye` skill states its pack version and tells the agent to
  suggest an update when the API and the skills disagree.

### Changed

- API facts corrected against observed server behavior, including player request bodies,
  list query semantics, artifacts parameters, the logs streaming default, warm-pool
  fields, version selection, error codes and the stop grace period.
- The API token is kept out of game server containers: the skills teach the
  game server → your backend → Gameye pattern.

### Removed

- References to unpublished bootstrap CLIs, including install instructions.
