# Releasing gameye-skills and gameye-mcp

This checklist covers both repositories: `gameye-skills` (this repo) and `gameye-mcp`. The steps are ordered so that no public artifact ever references a package or repository that does not exist yet.

Every outward-facing step is marked **needs Andrew's approval**. Do not perform it, or ask an agent to perform it, until Andrew has approved that specific step.

## Pre-release gate

Every item must hold, in both repos, before step 1:

- [ ] All CI jobs green on the release commit: skills `validate` (tests, reference freshness, validator, internal-reference scan, gitleaks) and mcp `CI` (tests on Node 20 and 22, typecheck, build, package contents, internal-reference scan, gitleaks).
- [ ] Secret and internal-reference scans clean locally as well: `python3 scripts/scan_internal_refs.py` (skills), `node scripts/scan-internal-refs.mjs` (mcp), and `gitleaks detect --source . --redact` in each repo.
- [ ] Git history on `main` is clean: no secrets, internal planning documents, personal paths, private hosts or abandoned-attempt code in any commit (gitleaks and the reference scan cover the tree; review the history before the first public push).
- [ ] Eval baseline recorded (`evals/prompts.yaml` run against sandbox, results stored with the release).
- [ ] Sandbox smoke passed with a low-scope sandbox token: launch, describe, join, logs, stop through `gameye-mcp`.
- [ ] Install smoke passed: `npx skills add --list` against a local checkout, and local Claude Code plugin marketplace add.
- [ ] `CHANGELOG.md` entry for the release in each repo; skills `Pack version:` and per-skill `metadata.version` match the entry; `gameye-mcp` `package.json` version matches its entry.
- [ ] Partner names in the skills (Pragma, Nakama, Photon Fusion) confirmed as publicly announced integrations, or the wording changed before publish.
- [ ] `npm pack --dry-run` file list for `gameye-mcp` reviewed (CI asserts it; a human reads it once).

## Release steps

### 1. Publish `gameye-mcp` to npm — needs Andrew's approval

Publish `gameye-mcp` (or, at minimum, a name-reserving placeholder) **before the skills repo goes public**. The Claude Code plugin in this repo runs `npx gameye-mcp@0`; if the name is unclaimed when the skills go public, anyone could register it and ship code to every user who installs the plugin.

- Confirm the npm account or org that will own the package, with 2FA enabled (see step 4).
- Publish `0.x` from a clean checkout of the release commit: `npm ci && npm test && npm run build && npm publish --access public`. Once step 4 is in place, all later publishes go through GitHub Actions only.
- Verify `npx gameye-mcp@0` starts and lists its tools against sandbox.

### 2. Create both GitHub repos under the `gameye` org and push `main` — needs Andrew's approval

- Create `gameye/gameye-mcp` and `gameye/gameye-skills`, empty (no generated README, license or `.gitignore`).
- Push `main` for `gameye-mcp` first, then `gameye-skills`.
- Set the default branch to `main`, add descriptions and topics, and enable private vulnerability reporting or point to `SECURITY.md`.
- Confirm the first CI runs on `main` are green in both repos.
- Check that the issue templates show up under **New issue** in both repos. Blank issues are off. Security and account problems link out to the helpdesk.

### 2a. Point bug reports at GitHub Issues — when the repos go public

While the repos are private, users can't see them, so the gameye-mcp beta notice and READMEs send bug reports to the helpdesk. Once both repos are public:

- In gameye-mcp `src/beta.ts`, change the reporting line to `https://github.com/gameye/gameye-mcp/issues`. Add a warning never to paste tokens or session IDs there, and keep the helpdesk (https://helpdesk.gameye.com/) for account, session and billing problems. Update the matching assertions in `tests/unit/registration.test.ts` and `tests/unit/context.test.ts`.
- Add a short "Reporting bugs" section to both READMEs, next to the Security section. It points to each repo's own Issues tab (`https://github.com/gameye/gameye-skills/issues` for skills), carries the same never-paste-tokens warning, and sends account problems to the helpdesk.
- Leave `SECURITY.md` alone. Vulnerabilities are always reported privately.
- Release a gameye-mcp patch version so the new notice reaches installed users.

### 3. Branch protection on `main` — needs Andrew's approval

In both repos:

- Require a pull request with at least one approving review before merging; dismiss stale approvals on new commits.
- Require status checks to pass (skills: `skills`, `internal-refs`, `secrets`; mcp: `test` matrix, `internal-refs`, `secrets`) and require branches to be up to date.
- Block direct pushes and force pushes to `main`, including for admins.

Installed skills and the plugin update automatically, so an unreviewed merge ships straight to users. These rules are the main control against that.

### 4. npm trusted publishing with provenance — needs Andrew's approval

- Configure npm trusted publishing (OIDC) for `gameye-mcp` from the `gameye/gameye-mcp` GitHub Actions release workflow, and publish with provenance (`npm publish --provenance`).
- Remove any long-lived npm automation tokens once trusted publishing works.
- Enable 2FA on the npm account that owns the package (and on every maintainer account), with "require 2FA for publishing" set on the package.

### 5. Announce and enable the Claude Code marketplace — needs Andrew's approval

- Confirm the plugin marketplace manifest in this repo installs from the public `gameye/gameye-skills` repo and resolves `gameye-mcp` from npm.
- Announce the marketplace and the `npx skills add gameye/gameye-skills` path (docs site, helpdesk article, customer channels).

### 6. MCP Registry — later — needs Andrew's approval

Once the npm package is stable (and the registry is out of preview): add `server.json` and the `mcpName` field to `gameye-mcp`'s `package.json`, then publish to the MCP Registry.

### 7. Drop the GHCR "confirm with support" condition — needs Andrew's approval

When GHCR support is generally released (docs page live, private pulls and the GHCR webhook enabled on both sandbox and production), remove the "confirm with Gameye support that GHCR is enabled for your environment" condition from the skills, following the versioning rule in `CONTRIBUTING.md`.

## Core follow-ups for maintainers

These are changes in the private core repository, found while verifying the skills against the server. The skills and `gameye-mcp` record the current server behavior in `spec/overrides.yaml`; each fix below becomes an overrides change plus a regenerated reference. Raising them as core issues needs Andrew's approval.

- [ ] Add the missing `security` blocks to the client spec for join session, leave session, edit application and list regions.
- [ ] Fix the leave-session request body in the spec so it matches what the handler accepts.
- [ ] Decide whether enable-tag's server-side `regions:read` scope check is a bug (the spec says `application:write`). If core changes it, update the overrides entry and the least-privilege token recipes.
- [ ] Document the logs `follow` default in the spec.
- [ ] Document the artifacts response compression (plain tar or gzip) in the spec.
- [ ] Make the organization ID needed for the GitHub webhook URL discoverable to customers (API or dashboard).
- [ ] Enable the GHCR webhook (and private GHCR pulls) on sandbox and production; this unblocks step 7.
- [ ] Clarify the spec wording for what happens when `version` is omitted from a session launch.
- [ ] Document the warm-pool cold-start fallback behavior (what happens when no warm instance is available).
