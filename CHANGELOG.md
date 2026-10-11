# Changelog

All notable changes to the Gameye agent skills are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

Each release has a **pack version**: the `Pack version:` line in
[`skills/gameye/SKILL.md`](skills/gameye/SKILL.md). Each skill also has its own
`metadata.version` in its frontmatter. Installs track the latest commit on `main` through
`npx skills update` or Claude Code plugin updates, so you get fixes without waiting for a
release. The versions here tell you what changed and whether your copy is current.

## 1.3.0 - Unreleased

Pack version 1.3.0.

### Added

- **Gameye Deploy GitHub Action** (`gameye-containerize` 1.2.0). Agents now suggest
  [`gameye/deploy-action@v0`](https://github.com/Gameye/deploy-action) when an image is
  built in GitHub Actions: it registers the tag, waits until it is pulled in a region,
  and can smoke-test a session on it. `references/registries.md` covers the inputs,
  token scopes per step, the lowercase image-owner step, and the warm-pool and quota
  caveats. It complements the GHCR webhook and works with any registry Gameye pulls
  from.
  Public guide: <https://gameye.com/docs/guides/using-gameye/github-actions/>.

## 1.2.0 - Unreleased

Pack version 1.2.0.

### Added

- **three.js clients** (`gameye-web-server` 1.1.0). A new reference,
  `references/threejs-client.md`, covers the browser half of a 3D web game: joining with a
  backend-issued token, snapshot interpolation for remote players, prediction and
  reconciliation for the local player, a shared movement step, headless physics with
  Rapier or cannon-es, and keeping the client out of the server image. A new eval prompt
  checks it.

## 1.1.0 - Unreleased

Pack version 1.1.0; `gameye-containerize` 1.1.0, `gameye` 1.0.2.

### Changed

- **GHCR is generally available on self-serve** (from 2026-10-07). The skills drop the
  "confirm with Gameye support" condition and present GHCR alongside Docker Hub and AWS
  ECR as the zero-cost private option, with its gotchas: image owner must equal the
  Gameye organization name, org-owned packages need an org invite, the repository is
  saved unvalidated ("No tags available" on a typo), a `docker/build-push-action` build
  needs `provenance: false` or GitHub sends no package webhook, and the webhook URL is
  shown on the application page in the Admin Panel. Enterprise production does not have
  GHCR yet.

## 1.0.1 - Unreleased

First public release. Pack version 1.0.1; `gameye` and `gameye-matchmaking` are at
`metadata.version` 1.0.1 and the other nine skills are at 1.0.0.

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
  registration with delivery-delay and identical-image caveats, and tag retention.
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
- Custom session IDs are unique across all of Gameye, not per organization. The
  matchmaking and sessions API skills derive IDs from a globally unique value and treat
  a `409` followed by a describe `404` as "another organization owns this ID; retry with
  a fresh one".
- A duplicate token `name` returns `500`, not `409`. The skills say to give every token
  name a unique suffix and not to retry a token-create `500` with the same name.
- The Pragma matchmaking integration is now named correctly (it was misspelled) and
  described as Pragma Engine, a game backend whose matchmaking can request Gameye sessions
  when a match forms.

### Removed

- References to unpublished bootstrap CLIs, including install instructions.
