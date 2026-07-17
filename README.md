# Dropzone

A tiny, single-file FastAPI app that lets you **drag-and-drop files in a browser** and streams them to disk.  
Designed for quick transfers from constrained environments (e.g., Citrix) to your own storage (local folder, Synology NAS, later a K8s PV).

- **Auth:** single shared header token (`X-Token`)
- **Simple UI:** one page, no build step
- **Streamed uploads:** constant memory usage; SHA-256 returned for integrity
- **Container-friendly:** minimal image, non-root by default

---

## Quick start (local)

```bash
python -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn[standard] python-multipart

export DROPZONE_TOKEN='<paste a strong token>'
export DEST_DIR='./uploads'          # will be created if missing
uvicorn main:app --host 0.0.0.0 --port 8080
```
Open http://localhost:8080, paste the token, click **Save** and drop files.

CLI examples:

```bash
# Upload
echo "hello" > test.txt
curl -H "X-Token: $DROPZONE_TOKEN" -F "files=@test.txt" http://localhost:8080/upload

# List files
curl -H "X-Token: $DROPZONE_TOKEN" http://localhost:8080/files

# Download a file (with progress)
curl -H "X-Token: $DROPZONE_TOKEN" http://localhost:8080/files/archive.zip --progress-bar -o archive.zip

# Delete a file
curl -X DELETE -H "X-Token: $DROPZONE_TOKEN" http://localhost:8080/files/test.txt
```

Health:

```bash
curl http://localhost:8080/healthz
```

---

## Docker

Build & run:

```bash
docker build -t dropzone:local .
mkdir -p uploads

# generate a strong token
TOKEN=<Insert or generate your token here>

# If on SELinux (Fedora/RHEL), add :Z to the -v flag
docker run --rm -p 8080:8080 \
  -e DROPZONE_TOKEN="$TOKEN" \
  -e DEST_DIR="/data/uploads" \
  -v "$PWD/uploads:/data/uploads" \
  --name dropzone \
  dropzone:local  
```

**Note on permissions:** the container runs as non-root user (UID 10001). Either:

- chown the host folder: `sudo chown -R 10001:10001 ./uploads`, or
- run the container as your uid: `--user $(id -u):$(id -g)`, or
- add :Z on SELinux systems.

---

## Podman

Podman is a drop-in replacement for Docker and runs rootless by default, which pairs naturally with the non-root container setup.

Build & run:

```bash
podman build -t dropzone:local .
mkdir -p uploads

TOKEN=<your-token>

podman run --rm -p 8080:8080 \
  -e DROPZONE_TOKEN="$TOKEN" \
  -e DEST_DIR="/data/uploads" \
  -v "$PWD/uploads:/data/uploads:Z" \
  --name dropzone \
  dropzone:local
```

The `:Z` label on the volume is needed on SELinux systems (Fedora/RHEL) — Podman will relabel the directory. On non-SELinux systems you can omit it.

Because Podman is rootless, the container's UID 10001 maps to your own UID on the host, so the bind-mounted `uploads/` directory is owned by you with no extra `chown` needed.

Pull and run from GHCR:

```bash
podman pull ghcr.io/lillevang/dropzone:latest

podman run --rm -p 8080:8080 \
  -e DROPZONE_TOKEN='<your-token>' \
  -v "$PWD/uploads:/data/uploads:Z" \
  ghcr.io/lillevang/dropzone:latest
```

---

## GHCR image

This repo builds and publishes the docker image to ghcr on main and tags (see .github/workflows/container.yml).


Pull:
```bash
docker pull ghcr.io/lillevang/dropzone:latest
```

Run:
```bash
docker run --rm -p 8080:8080 \
  -e DROPZONE_TOKEN='<your-token>'
  -v "$PWD/uploads:/data/uploads" \
  ghcr.io/lillevang/dropzone:latest
```

---

## Pointing at a Synology NAS

**Option A - NFS (recommended)**

1. **Synlogy:** Control Panel -> File Services -> NFS -> Enable. Shared Folder -> *your share* -> Edit -> NFS Permissions -> add your host IP -> READ/WRITE, squash as needed.

2. Client:

```bash
sudo mkdir -p /mnt/nas/dropzone
sudo mount -t nfs <NAS_IP>:/volume1/dropzone /mnt/nas/dropzone
docker run --rm -p 8080:8080 \
  -e DROPZONE_TOKEN="$TOKEN" \
  -v /mnt/nas/dropzone:/data/uploads \
  ghcr.io/<your-gh-username>/dropzone:latest  
``` 

**Option B - SMB/CIFS**

```bash
sudo apt-get install -y cifs-utils
sudo mkdir -p /mnt/nas/dropzone
sudo mount -t cifs //NAS_IP/dropzone /mnt/nas/dropzone \
  -o username=<user>,password=<pass>,iocharset=utf8,file_mode=0660,dir_mode=0770,uid=$(id -u),gid=$(id -g)
docker run --rm -p 8080:8080 \
  -e DROPZONE_TOKEN="$TOKEN" \
  -v /mnt/nas/dropzone:/data/uploads \
  ghcr.io/<your-gh-username>/dropzone:latest 
```

---

## Configuration

| Env var           | Default                                     | Description                                                               |
| ----------------- | ------------------------------------------- | ------------------------------------------------------------------------- |
| `DROPZONE_TOKEN`  | **(required)**                              | Shared secret; must match `X-Token` header from browser/curl              |
| `DEST_DIR`        | `./uploads`                                 | Destination directory (bind/mount your NAS here)                          |
| `MAX_BYTES`       | `10737418240` (10 GiB)                      | Per-file size cap                                                         |
| `MAX_TOTAL_BYTES` | `0` (unlimited)                             | Total bytes allowed in `DEST_DIR`; uploads are rejected with 507 once reached |
| `ALLOW_OVERWRITE` | `false`                                     | If `true`, overwrite existing files; else auto-rename like `name (1).ext` |
| `SAFE_EXTS`       | `.zip,.tar.gz,.tgz,.7z,.rar,.txt,.csv,.pdf` | Comma-separated allowlist. Set empty to allow all                         |
| `ALLOWED_HOSTS`   | *(empty — any)*                             | Comma-separated Host allowlist (e.g. `dropzone.lillevang.dev`). Requests with any other Host get an empty 404; `/healthz` is always exempt |
| `RATE_LIMIT_RPS`  | `10`                                        | Per-client sustained requests/second; `0` disables rate limiting          |
| `RATE_LIMIT_BURST`| `30`                                        | Requests a client may burst before 429s kick in                           |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1`                             | Read by uvicorn. Behind a proxy/ingress, set to the proxy's IPs/CIDRs so the real client IP (from `X-Forwarded-For`) is used for rate limiting |


---

## API

- GET / — drag-and-drop UI.

- GET /meta — JSON with the per-file size limit.

- GET /healthz — health check.

- GET /files — list uploaded files (name, size).
  **Header required:** X-Token: <DROPZONE_TOKEN>

- GET /files/{filename} — download a file, streamed.
  **Header required:** X-Token: <DROPZONE_TOKEN>

- DELETE /files/{filename} — delete a file.
  **Header required:** X-Token: <DROPZONE_TOKEN>

- POST /upload — multipart form, one or more files=@... parts.
  **Header required:** X-Token: <DROPZONE_TOKEN>

Response:

```bash
{
  "ok": true,
  "results": [
    { "name": "file.zip", "bytes": 123, "sha256": "…", "path": "/data/uploads/file.zip" }
  ]
} 
```

---


## Security model (public endpoint)

- Endpoint is publicly reachable, but uploads, listing, download and delete all require the shared header token.

- FastAPI's auto-docs (`/docs`, `/redoc`, `/openapi.json`) are disabled so scanners can't enumerate the API.

- Per-client rate limiting (10 r/s, burst 30 by default) answers probe floods with 429. For it to key on the real client IP behind a proxy, set `FORWARDED_ALLOW_IPS` to the proxy's address.

- Set `ALLOWED_HOSTS` in real deployments so requests that arrive by IP or a foreign Host header get an empty 404 instead of the app.

- Use long, random tokens (>= 32 bytes). Rotate after use.

- Always run behind HTTPS in real deployments (ingress / reverse proxy).

- For extra safety later: IP allowlist at the proxy, short token TTLs, or OAuth/OIDC via an auth proxy.

Generate a token:

```bash
python - <<'PY'
import secrets; print(secrets.token_hex(32))
PY  
```

---

## Troubleshooting
- **401 Unauthorized:** header not sent or token mismatch. Check DevTools -> Network -> `POST /upload` -> Request Headers.
- **PermissionError on writes:** fix bind mount perms (see Docker section).
- **Large files fila:** Increase `MAX_BYTES`, and ensure your proxy allows large bodies (client_max_body_size / ingress annotations).
- **SELinux denies writes:** add `:Z` to the volume.

---

## Releasing

Releases are cut **locally** with [Task](https://taskfile.dev) — there is no CI
image push. Every published image is signed with cosign on the way out, because
the cluster's Kyverno `verify-image-signatures` policy requires every
`ghcr.io/lillevang/*` image to carry a signature.

The signing key is deliberately GitHub-independent: private key + password live
only in 1Password, and no CI system holds a secret.

```bash
task bump          # or: task bump TARGET=minor
task release       # build → health check → push → sign → commit + tag
```

`.version` holds bare semver; images are tagged `v<version>` (e.g. `v0.1.2`).

**Prerequisites:** `podman` (or `docker`), `skopeo`, `jq`, `cosign`, `op`, plus:

```bash
# GHCR login
gh auth token | podman login ghcr.io -u Lillevang --password-stdin

# a live 1Password session — a stale one makes cosign fail with a
# misleading "invalid pem block"
eval $(op signin)
```

Verify any published image against the public key (committed in the infra repo's
`apps/kyverno-policies/verify-images.yaml`):

```bash
cosign verify --key cosign.pub ghcr.io/lillevang/dropzone:<tag>
```

After releasing, bump the image tag in the infra repo's app manifest to deploy.

---


## Roadmap

- Resumeable uploads via [tus] (Uppy UI + `tusd` backend)
- Optional Virus scanning (ClamAV sidecar or async job)
- Auth via oauth2-proxy / OIDC
- `/list` and retention policy (auto-purge after N days)
- Kubernetes manifests (Kustomize/Argo)


