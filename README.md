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

CLI Sanity check:

```bash
echo "hello" > test.txt
curl -H "X-Token": "$DROPZONE_TOKEN" -F "files=@test.txt" http://localhost:8080/upload
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
| `ALLOW_OVERWRITE` | `false`                                     | If `true`, overwrite existing files; else auto-rename like `name (1).ext` |
| `SAFE_EXTS`       | `.zip,.tar.gz,.tgz,.7z,.rar,.txt,.csv,.pdf` | Comma-separated allowlist. Set empty to allow all                         |


---

## API

- GET / — drag-and-drop UI.

- GET /meta — JSON with max size and destination path.

- GET /healthz — health check.

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

- Endpoint is publicly reachable, but uploads require the shared header token.

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


## Roadmap

- Resumeable uploads via [tus] (Uppy UI + `tusd` backend)
- Optional Virus scanning (ClamAV sidecar or async job)
- Auth via oauth2-proxy / OIDC
- `/list` and retention policy (auto-purge after N days)
- Kubernetes manifests (Kustomize/Argo) with NFS PV to local NAS



