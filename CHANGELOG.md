# Changelog

All notable changes to the Gameye agent skills are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

Each release has a **pack version**: the `Pack version:` line in
[`skills/gameye/SKILL.md`](skills/gameye/SKILL.md). Each skill also has its own
`metadata.version` in its frontmatter. Installs track the latest commit on `main` through
`npx skills update` or Claude Code plugin updates, so you get fixes without waiting for a
release. The versions here tell you what changed and whether your copy is current.

From 1.6.1, each release is also a git tag (`v1.6.1`) with a GitHub release, so you can
pin a known version. Earlier versions shipped on `main` without a tag.

## 1.6.1 - 2026-10-24

Pack version 1.6.1.

### Fixed

- **`gameye-matchmaking`** (1.1.1) and **`gameye-sessions-api`** (1.0.3). A `420` for
  a tag that isn't downloaded in the region yet (`exists: false`) is no longer treated
  as busy capacity: retrying that region won't help, so skip to a region where the
  tag shows `exists: true`, or wait if none does. A `420` for a downloaded tag still
  means busy: back off, then fall back. This matches `gameye-troubleshoot`.
- **Evals setup.** The MCP install line now passes `GAMEYE_API_TOKEN` from an exported
  variable instead of a literal token, and pins `gameye-mcp@0`.

## 1.6.0

Pack version 1.6.0. Lessons from building [Scrapyard on Gameye](https://github.com/Gameye/scrapyard-nakama),
a multi-region browser game.

### Changed

- **`gameye-matchmaking`** (1.1.0). Region selection no longer assumes every client
  can ping: browser clients can't send ICMP, so the skill now describes estimating
  latency from a signed, server-side location, matching within a region, and a region
  picker whose choice is forced at session start. The Nakama row names the Gameye Fleet
  Manager for Nakama (v0.2.0+: latency-based placement and the `gameye.region` override).
- **`gameye-web-server`** (1.2.0). New TLS option: a WebSocket relay at the edge, with
  signed relay tokens, an `Origin` check, and the Cloudflare Workers bare-IP limit.
- **`gameye-launch`** (1.0.2). After adding a region, wait for `/available-location`
  as well as the tag, since the location list can trail it by minutes.

## 1.5.0

Pack version 1.5.0.

### Changed

- **`gameye`** (1.1.0). New "Keeping these skills current" section: with the Gameye MCP
  server, the agent runs `gameye_update_skills` once per conversation and asks before
  updating. `GAMEYE_ENABLE_ADMIN_TOOLS` is gone from the MCP server table: since
  `gameye-mcp` 0.2.0 the application and token tools are always registered, and the
  token's scopes decide what they can do. `references/routing.md` says the same.
- **`gameye-sessions-api`** (1.0.2). The API reference no longer marks
  `create-token`, `create-application` and `edit-application` as admin-gated opt-in
  tools.

## 1.4.0

Pack version 1.4.0.

### Added

- **`gameye-troubleshoot`** (1.0.0). Diagnoses a deploy that isn't working from the
  customer side: a malformed `repository`, a tag that never becomes `exists: true`,
  Gameye unable to pull the image (path, public or private, `gameyedocker` access,
  organization invitation, `linux/amd64`), what `404` and `420` from `POST /session`
  mean, a server that exits on boot, and a missing region.

### Changed

- **`gameye-launch`** (1.0.1). A `420` for a tag that isn't downloaded in the region
  yet is not a capacity problem, and retrying won't help. Links to
  `gameye-troubleshoot`.
- **`gameye-sessions-api`** (1.0.1). The generated API reference records when
  `POST /session` returns `420` for a tag that isn't downloaded in the region yet.
- **`gameye`** (1.0.3). The task table routes "why won't it load or start" to
  `gameye-troubleshoot`.

## 1.3.0

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

## 1.2.0

Pack version 1.2.0.

### Added

- **three.js clients** (`gameye-web-server` 1.1.0). A new reference,
  `references/threejs-client.md`, covers the browser half of a 3D web game: joining with a
  backend-issued token, snapshot interpolation for remote players, prediction and
  reconciliation for the local player, a shared movement step, headless physics with
  Rapier or cannon-es, and keeping the client out of the server image. A new eval prompt
  checks it.

## 1.1.0

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

## 1.0.1

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
