# Contributing to gameye-skills

Thanks for helping improve the Gameye agent skills. Every fact in a skill is copied by agents into customer code, so accuracy matters more than coverage.

## Setup

You need Python 3.10 or newer.

```bash
git clone https://github.com/gameye/gameye-skills.git
cd gameye-skills
python3 -m pip install -r requirements-dev.txt
```

## Repository layout

```
skills/<name>/SKILL.md        one skill: YAML frontmatter + Markdown body
skills/<name>/references/     optional supporting files the skill links to
skills/gameye/SKILL.md        the router skill; carries the pack version
spec/client.yaml              snapshot of the live client API spec
spec/webhook.yaml             snapshot of the webhook API spec
spec/overrides.yaml           recorded server-vs-spec divergences
scripts/                      validator, reference generator, spec sync, scans
```

Each `SKILL.md` starts with frontmatter:

```yaml
---
name: gameye-example          # kebab-case, equal to the directory name
description: What the skill does and when an agent should use it (max 1024 chars).
metadata:
  version: "1.0.0"
---
```

`skills/gameye-sessions-api/references/api-reference.md` is generated. Do not edit it by hand.

Where API facts come from, in order of authority: observed server behavior (recorded in `spec/overrides.yaml`), then `spec/client.yaml` and `spec/webhook.yaml`, then existing skill text. A skill claim that cannot be traced to the spec, the overrides file, or a cited server handler does not belong in a skill.

## Checks

Run all of these before you open a pull request. CI runs the same ones.

```bash
python3 -m pytest scripts/tests                 # script tests
python3 scripts/generate_reference.py --check   # generated reference is current
python3 scripts/validate_skills.py              # format, banned facts, endpoints, request bodies
python3 scripts/scan_internal_refs.py           # no private hosts, personal paths or emails
```

CI also runs a secret scan (gitleaks) over the full history.

The versioning check only runs in pull requests. To run it locally, pass the base branch:

```bash
python3 scripts/validate_skills.py --base origin/main
```

## Versioning rule

When you change the body of any `SKILL.md`, the same pull request must:

1. add an entry to `CHANGELOG.md` describing the change;
2. bump that skill's `metadata.version` (semver: patch for corrections, minor for new guidance, major for changes that alter code customers have already copied, such as environment variable names or the default host);
3. bump the `Pack version: X.Y.Z` line in `skills/gameye/SKILL.md`.

Changing only the pack version line does not count as a change to the `gameye` skill. The validator enforces all three in CI.

## Refreshing the spec snapshots

`spec/client.yaml` comes from the public sandbox endpoint:

```bash
python3 scripts/sync_spec.py            # refresh spec/client.yaml
python3 scripts/sync_spec.py --check    # exit 1 if the live spec differs from the snapshot
python3 scripts/generate_reference.py   # regenerate the reference afterwards
```

`spec/webhook.yaml` is not served by any public host. Gameye maintainers refresh it from a checkout of the core repository:

```bash
python3 scripts/sync_spec.py --core ../core
```

After a refresh, review the diff, regenerate the reference, run the validator, and update any skill text the change affects (following the versioning rule). A scheduled workflow checks both API hosts and the live spec weekly and opens an issue when they drift.

## Recording a server-vs-spec divergence

When the server behaves differently from the spec, the server wins, and the divergence is recorded once in `spec/overrides.yaml` rather than patched into individual skills. Add an entry to the `overrides:` list with:

- `operation`: the `operationId` in `spec/client.yaml`;
- `kind`: `scope`, `request-body`, `query-params`, `response` or `behavior`;
- `fact`: the corrected fact, as it should read in the reference;
- the kind-specific field (`scope`, `body` or `params`) where one applies;
- `spec_says`: what the spec claims, if anything;
- `evidence`: the server source that proves it, as `{file, function}` entries.

Then run `python3 scripts/generate_reference.py`, write skill text against the corrected fact, and run the checks. The header of `spec/overrides.yaml` documents every field. External contributors who cannot cite server source should open an issue with the request, the response and the error `identifier` instead.

## Pull requests

- Keep each pull request focused on one change, and explain what it changes and why.
- Never put a real Gameye API token, webhook secret or customer data in a skill, test, issue or commit.
- Use only the two public API hosts, `https://api.sandbox-gameye.gameye.net` and `https://api.production-gameye.gameye.net`.
- CI must pass and a maintainer must approve before a pull request can be merged.

## Reporting issues

Report wrong or outdated skill guidance and feature requests in [GitHub issues](https://github.com/gameye/gameye-skills/issues). Report security issues privately, as described in [SECURITY.md](SECURITY.md).

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE), and that you will follow our [Code of Conduct](CODE_OF_CONDUCT.md).
