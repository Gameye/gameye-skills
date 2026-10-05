# Registries, applications and tags

Detail for the "Registries" section of `gameye-containerize`. Every path ends the
same way: a tag that returns `{"exists": true}` from
`GET /tag/{region}/{image}/{version}` in each region you run in.

Hosts (`<host>` below):

| Customers | Host |
|---|---|
| Self-serve (permanent home, not a staging step) | `https://api.sandbox-gameye.gameye.net` |
| Enterprise | `https://api.production-gameye.gameye.net` |

Exact request and response schemas: `gameye-sessions-api` (generated API reference)
and each host's live `/openapi.yaml`.

Gameye's pull account is **`gameyedocker`** unless your Gameye contact supplies a
different name. You never need Gameye's registry credentials; Gameye manages its
own pull credential.

---

## Docker Hub

### Access

1. Use a Docker Hub plan that allows private repositories and collaborators (Team
   or larger).
2. Repository → **Settings → Collaborators** → add `gameyedocker` as a
   **read-only** collaborator.

### Webhook

Repository → **Webhooks** → add:

```
https://anything:<TOKEN>@<host>/v1/integrations/dockerhub
```

- Only the password is read; the username is ignored. Docker Hub webhooks cannot
  set headers, which is why the token sits in the URL.
- `<TOKEN>` must be a Gameye token with the `webhook:dockerhub` scope. Give it no
  other scopes — it is stored in Docker Hub. Gameye may hand you this URL during
  onboarding.
- Responses: **204** the tag was registered; **404** no application uses this
  repository (check the application's repository field).

Without the webhook, new tags are not registered automatically; enable them
manually (below).

---

## AWS ECR

Pull access for Gameye is configured together with Gameye during onboarding — ask
your Gameye contact for what to grant and confirm the repository URI they will pull
from. There is no customer-side webhook endpoint for ECR in the Gameye API, so
register each new tag manually (below) or ask Gameye how pushes are picked up for
your account.

---

## GitHub Container Registry (GHCR)

> **Confirm with Gameye support that GHCR is enabled for your environment** before
> relying on any of this — private pulls and the webhook both depend on it. GHCR
> support is not generally released yet.

The lowercase GitHub image owner must match your Gameye organization name (for
`ghcr.io/studio-name/game-server`, the owner is `studio-name`). The image must
include `linux/amd64`.

### Access

1. **Organization-owned package:** invite `gameyedocker` through **Organization →
   People → Invite member** and ask Gameye to accept. Personal-account packages
   skip this step.
2. Open the package → **Package settings → Manage access → Invite teams or
   people** → add `gameyedocker` with role **Read**.
3. If **Invite teams or people** is missing, the package inherits access from its
   linked repository. In **Package settings**, untick **Inherit access from source
   repository**, then invite as above. This shares the package only, not the
   repository contents.

Do not grant access through a personal-account repository: personal repositories
have no Read role, so `gameyedocker` would get write access.

### Application

Registry **GitHub Container Registry** (`ghcr`), Repository
`ghcr.io/studio-name/game-server` — no tag in the repository field.

### Webhook (optional, same enablement caveat)

1. Ask Gameye support to confirm GHCR webhooks are enabled and for your
   organization ID.
2. Mint the signing secret: a token with **only** the `webhook:github` scope,
   created with `POST /token` by a token that holds `token:write` (it does not need
   `webhook:github` itself). The token value is shown once.

   ```json
   { "name": "github-webhook", "scopes": ["webhook:github"] }
   ```

3. In GitHub, on the repository the package is connected to (for example through
   the `org.opencontainers.image.source` label that `docker/metadata-action` adds)
   or on the organization to cover all its packages: **Settings → Webhooks → Add
   webhook**:

   | Field | Value |
   |---|---|
   | Payload URL | `https://<host>/v1/integrations/github/<ORGANIZATION-ID>` |
   | Content type | `application/json` (form-encoded is rejected) |
   | Secret | The `webhook:github` token from step 2 |
   | Events | Let me select individual events → **Packages** only |
   | Active | Ticked |

4. Check **Recent Deliveries**: the ping on save should show 200; then push a new
   tag.

| Response | Meaning |
|---|---|
| 204 | Tag registered; Gameye is pulling it |
| 200 | Nothing to do: ping, a non-publish event, untagged push, or tag already registered (body says which) |
| 400 | Body is not JSON — set content type to `application/json` |
| 401 | Signature mismatch — the secret must be an active `webhook:github` token of the organization in the URL |
| 404 | No GHCR application matches the package — check the application's repository |

Caveats:

- GitHub can take a few minutes to deliver a package event after a push. Wait
  before changing the webhook.
- GitHub only sends a delivery when the push creates a **new package version**.
  Pushing an image identical to an existing one just adds the tag to that version
  and sends nothing. Stamp the commit SHA so every build differs:

  ```bash
  docker buildx build --platform=linux/amd64 \
    --label org.opencontainers.image.revision="$(git rev-parse HEAD)" \
    -t ghcr.io/studio-name/game-server:"$(git rev-parse --short HEAD)" --push .
  ```

  (Or set it in the Dockerfile with `ARG GIT_SHA` + `LABEL org.opencontainers.image.revision=$GIT_SHA`
  and `--build-arg GIT_SHA=...`.) Otherwise, enable the tag manually.
- To rotate the secret: create a new `webhook:github` token, update the GitHub
  webhook secret, then delete the old token (Admin Panel → Users → API tokens).
  Both work until the old one is deleted.

---

## Enabling a tag manually

Works for every registry and is the fallback when a webhook didn't fire.

1. See which tags Gameye can read from the registry (also a good access check):

   ```
   GET /application/{name}/tags/available
   ```

2. Enable the exact tag (server checks the `regions:read` scope):

   ```
   POST /application/{name}/tags
   ```

   ```json
   { "tag": "3f9c2ab" }
   ```

   204 on success. The Admin Panel tag picker does the same; for private images
   prefer the exact tag via the API.

## Confirming a tag per region

```
GET /tag/{region}/{image}/{version}
```

`{image}` is the application name, `{version}` the tag. Poll each region you run in
until it returns `{"exists": true}`, then start sessions with that `version`. If it
stays false, check: pull access is effective (GHCR org invitation accepted, Read
role), the application repository matches the pushed image, the image includes
`linux/amd64`, and the region and node pool have capacity — then ask Gameye to check
image-sync errors.

## Applications and tag retention

- An application binds a registry + repository to ports, resources, regions and a
  node pool. Create it in the Admin Panel or with `POST /application`; change it
  with `PUT /application/{name}`; list with `GET /application`.
- `tagKeep` ("Tags to keep", typically 2) is how many tags stay warm on the fleet.
  Current + previous covers deploy and rollback; older tags drop out.
- Pin immutable SHA tags in session starts. Omitting `version` runs the most
  recently registered tag, and re-pushing a mutable tag such as `latest` does not
  trigger a new pull.
