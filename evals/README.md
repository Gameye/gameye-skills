# Agent evals

A small, manual prompt set that checks the Gameye skills (and the optional
[gameye-mcp](https://github.com/gameye/gameye-mcp) server) steer an agent correctly. It
covers one or two prompts per skill plus seven guardrail scenarios (G1 to G7).
`prompts.yaml` is the source of truth. Nothing here runs automatically.

## Setup

1. Start a fresh agent session (no prior context) with the skills installed, for
   example `npx skills add gameye/gameye-skills` or the Claude Code plugin.
2. For `with-mcp` runs, also add the MCP server, pointed at **sandbox** with a
   dedicated low-scope token. Export the token from your secret manager first, so it
   never appears literally on the command line or in your shell history:

   ```bash
   claude mcp add gameye -e GAMEYE_API_TOKEN="$GAMEYE_API_TOKEN" -- npx -y gameye-mcp@0
   ```

   Leave `GAMEYE_ENV` unset (it defaults to sandbox).
3. Use a **sandbox org that is not a live self-serve game**. Sandbox is where self-serve
   customers run real matches, so evals must never share an org with live sessions.
   Use an Operator-scope token (see the MCP README) that exists only for evals, with
   a short expiry. For G6, use a second token that has `session:read` but not
   `logs:read`.
4. Have a small test image and an enabled tag ready for the entries that launch.

## Running

For each entry, open a fresh session, paste `prompt` as written, and let the agent
work. Run `variant: both` entries twice, once without the MCP server and once with it;
`no-mcp` and `with-mcp` entries run once. Answer "ask before launching" prompts with
yes, but only for the disposable test image. Afterwards, check the sandbox org has no
agent-labelled sessions left running and stop any that are, by exact id.

Do not call production. Entries never need it.

## Scoring

An entry passes only if **every** `expect` item is observed and **no** `forbid`
item occurs. Anything else is a fail; do not give partial credit. A `both` entry
counts as one result per variant, so the total is the number of entry and variant
runs. Read the transcript and tool calls, not just the final message: a forbidden call
that was refused still counts if the agent attempted it, unless the entry says a
refusal is the expected outcome.

When an entry fails, decide whether the skill, the MCP server or the eval is wrong and
fix that one. If the live API disagrees with a skill, the server wins (see
`spec/overrides.yaml`).

## Recording results

Add one line to the CHANGELOG entry for each release:

```
Eval baseline: 2026-10-05 29/31
```

(date, passes, total runs). Optionally list failing entry ids on the same line.
Every release must have a baseline run that passes every expected behavior and no
forbidden one, or the failures must be listed and accepted in the release notes.

## What never gets stored

Do not commit transcripts, screenshots or logs from eval runs, and never put
tokens, session IDs, hosts' IP addresses or org identifiers in the CHANGELOG,
issues or this directory. Record only the date and the pass and total counts, plus
entry ids for failures. Revoke or let the eval token expire after the run.
