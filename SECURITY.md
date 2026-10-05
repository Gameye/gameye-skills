# Security Policy

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues, discussions or pull requests.**

Report them privately through the Gameye helpdesk instead:

**https://helpdesk.gameye.com/**

Mark the ticket clearly as a **security report for gameye-skills**. Please include:

- a description of the issue and its impact;
- the affected skill and pack version (the `Pack version:` line in `skills/gameye/SKILL.md`, or the skill's `metadata.version`);
- steps to reproduce, or the prompt and agent output that show the problem.

Security issues in this repository include skill text that leads an agent to leak a Gameye API token (for example, passing it to a game server container or committing it), to target the wrong environment, or to run unsafe commands, as well as anything in the scripts or CI workflows.

Never include a real Gameye API token in a report. Revoke any token you think has been exposed.

We will acknowledge your report, keep you updated as we investigate, and credit you in the release notes if you would like us to.

## Supported versions

Only the latest release on `main` receives fixes. Installed skills pick up fixes through `npx skills update` or Claude Code plugin updates.
