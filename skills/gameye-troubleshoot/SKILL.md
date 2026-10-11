---
name: gameye-troubleshoot
description: Diagnose why a game server on Gameye won't start, from the customer side, using the Gameye API and the user's own registry. Use when a new tag stays on Preloading or never becomes Ready, a session start returns 404 or 420 (OUT_OF_COMPUTE), a region is missing from the location list, a GHCR or Docker Hub image doesn't load, a server starts and then exits straight away, or the user says their Gameye server or deploy "isn't working".
metadata:
  version: "1.0.0"
---

# Troubleshooting a Gameye deploy

Work out which stage failed, check it with the API, and tell the user the fix. Most
failures are one of three: the tag isn't registered, Gameye can't pull the image, or
the server crashes after it starts.

You can't see Gameye's own pull logs. When the checks below point at a pull problem
and the user has done everything listed, have them contact Gameye support with the
application name, the tag and the time they registered it.

Use the Gameye MCP tools when they're available (`gameye_list_applications`,
`gameye_check_tag`, `gameye_get_locations`, `gameye_launch_session`,
`gameye_get_logs`). Otherwise call the API on the customer's host (see the `gameye`
skill for which host). The token needs `application:read` and `regions:read`, plus
`session:start`, `session:read`, `session:stop` and `logs:read` for step 5.

## 1. Read the application

`GET /application` lists each application's `name`, `repository` and `regions`. Find
the one in question and check `repository`:

| Looks like | Problem | Fix |
|---|---|---|
| Capital letters (`ghcr.io/Studio/game`) | Docker requires lowercase | Change it to all lowercase |
| `https://…` or `github.com/…` | A web address, not an image | `ghcr.io/<owner>/<package>`, or `<user>/<repository>` for Docker Hub |
| A tag on the end (`…/game:1.2`) | The tag doesn't belong here | Remove it; tags are registered separately |
| `ghcr.io/<owner>/<package>` with an owner that isn't the Gameye organization name | Gameye pulls a GHCR image only when its owner is the organization name | Push under that owner, or contact Gameye support about renaming the organization |

The user changes `repository` in the Admin Panel, on the application's page.

## 2. Check the tag is registered and pulled

`GET /tag/{region}/{image}/{version}` returns `{"exists": true}` once the tag is
downloaded in that region. `{image}` is the application name, not the repository.

- **`exists: false` for a few minutes after registering**: normal. Gameye's servers
  are still downloading it. Wait, then check again.
- **`exists: false` in every region for more than about 10 minutes**: Gameye can't
  pull the image. Go to step 3.
- **The tag was never registered**: `POST /session` returns `404` for it. Register it
  with `POST /application/{name}/tags` (or the registry webhook, or
  `gameye/deploy-action`; see `gameye-containerize`).

## 3. Check Gameye can pull the image

Gameye pulls with its account `gameyedocker`. Go through the list with the user:

1. **The image is where the application says.** The exact `repository` path exists in
   the registry, with the tag pushed to it. A common miss is an image still on Docker
   Hub while the application points at GHCR, or the other way round.
2. **Public or private.** For GHCR, this returns `200` for a public package and `401`
   for a private or missing one:
   `curl -s -o /dev/null -w '%{http_code}' 'https://ghcr.io/token?scope=repository:<owner>/<package>:pull'`
3. **Private: `gameyedocker` has Read on that package.** GHCR: Package settings →
   Manage access → Invite teams or people → `gameyedocker`, role Read. Access is per
   package, so a second package needs its own grant. If *Invite teams or people* is
   missing, untick *Inherit access from source repository*. Docker Hub: add
   `gameyedocker` as a collaborator with read access.
4. **Organization-owned GHCR package: `gameyedocker` is a member.** Invite it through
   Organization → People → Invite member, and Gameye accepts. If the invitation has
   been pending for a while, contact Gameye support. Personal-account packages skip
   this step.
5. **The image is built for `linux/amd64`.**

Once the fix is in, step 2 should show `exists: true` within a few minutes.

## 4. Read a failed session start

| Response | Meaning | Next |
|---|---|---|
| `404` | The application, tag or region isn't known. The error's details say which | Step 1 or 2, or fix the region name |
| `420` right after a new tag, or for a tag that isn't `exists: true` in that region | No server in the region has the image yet. Retrying won't help until it does | Steps 2 and 3 |
| `420` for a tag that is `exists: true` in that region | The region is busy | Retry with backoff, or fall back to another region (`gameye-matchmaking`) |
| `402` / `429` | Trial or organization quota | See `gameye-launch` |

## 5. A server that starts, then exits

Start one session on the tag with a short `ttl`, describe it until it leaves
`created`, and fetch its logs with `GET /logs`. A session that reaches `exited` or
`dead` within seconds is almost always the game server itself: a missing file, a crash
on boot, the wrong port or a missing environment variable. `gameye-local-testing`
reproduces most of these on a laptop. Stop the session when you're done.

## 6. A region is missing

`GET /available-location/{image}` lists only the locations that can run the image
now. A region can be missing because:

- the tag isn't downloaded there yet (step 2), or
- the application isn't set up for that region (`regions` in step 1), or
- the region isn't offered on the customer's platform. Self-serve (sandbox) and
  enterprise (production) don't offer the same regions. Ask Gameye support.
