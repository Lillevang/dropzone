import hashlib
import hmac
import os
import secrets
import time

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from pathlib import Path
from starlette.concurrency import run_in_threadpool
from typing import List, Optional


DEST_DIR = Path(os.getenv("DEST_DIR", "./uploads")).resolve()
DEST_DIR.mkdir(parents=True, exist_ok=True)

# TOKEN REQUIRED
TOKEN = os.getenv("DROPZONE_TOKEN")

# Default 10 GiB per file; 0 = unlimited total
MAX_BYTES = int(os.getenv("MAX_BYTES", str(10*1024 * 1024 * 1024)))
MAX_TOTAL_BYTES = int(os.getenv("MAX_TOTAL_BYTES", "0"))
ALLOW_OVERWRITE = os.getenv("ALLOW_OVERWRITE", "false").lower() == "true"
SAFE_EXTS = set(
    (os.getenv("SAFE_EXTS", ".zip,.tar.gz,.tgz,.7z,.rar,.txt,.csv,.pdf").split(",")))

# Host allowlist (comma-separated, e.g. "dropzone.lillevang.dev"). Empty = any
# Host accepted. /healthz is always exempt so kubelet/Docker probes that hit
# the pod IP or localhost keep working.
ALLOWED_HOSTS = {
    h.strip().lower() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()
}

# Per-client rate limit (token bucket), mirroring the nginx limit_req settings
# used by the other *.lillevang.dev apps: 10 r/s sustained, burst 30, 429 when
# exceeded. RATE_LIMIT_RPS=0 disables. Keyed on the client IP uvicorn reports;
# behind a proxy set FORWARDED_ALLOW_IPS so X-Forwarded-For is honored,
# otherwise all visitors share the proxy's bucket.
RATE_LIMIT_RPS = float(os.getenv("RATE_LIMIT_RPS", "10"))
RATE_LIMIT_BURST = float(os.getenv("RATE_LIMIT_BURST", "30"))


# ========= helpers =========
def sanitize_filename(name: str) -> str:
    base = "".join(c for c in (name or "")
                   if c.isalnum() or c in "-._ ").strip()
    return base or secrets.token_hex(8)


def resolve_collision(path: Path) -> Path:
    if ALLOW_OVERWRITE or not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    i = 1
    while True:
        candidate = path.with_name(f"{stem} ({i}){suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def dir_usage(path: Path) -> int:
    return sum(f.stat().st_size for f in path.iterdir() if f.is_file())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ========= app =========
# Auto-docs are disabled: /docs, /redoc and /openapi.json would hand scanners
# a complete API map of a publicly reachable service.
app = FastAPI(title="Dropzone", version="0.1.0",
              docs_url=None, redoc_url=None, openapi_url=None)

# ip -> (tokens, last refill). Single-process state; fine for one uvicorn worker.
_buckets: dict = {}


@app.middleware("http")
async def gatekeeper(request: Request, call_next):
    if request.url.path == "/healthz":
        return await call_next(request)

    if ALLOWED_HOSTS:
        host = (request.headers.get("host") or "").split(":")[0].strip().lower()
        if host not in ALLOWED_HOSTS:
            # Same idea as the nginx default-server 444: unknown vhosts get
            # nothing useful. ASGI can't drop the connection, so a bare 404.
            return PlainTextResponse("", status_code=404)

    if RATE_LIMIT_RPS > 0:
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        tokens, last = _buckets.get(ip, (RATE_LIMIT_BURST, now))
        tokens = min(RATE_LIMIT_BURST, tokens + (now - last) * RATE_LIMIT_RPS)
        if tokens < 1:
            _buckets[ip] = (tokens, now)
            return JSONResponse({"detail": "Too Many Requests"}, status_code=429)
        _buckets[ip] = (tokens - 1, now)
        if len(_buckets) > 10_000:
            cutoff = now - 60
            for key in [k for k, (_, t) in _buckets.items() if t < cutoff]:
                del _buckets[key]

    return await call_next(request)

INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Dropzone</title>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>
    :root { color-scheme: light dark; }
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 2rem; }
    .wrap { max-width: 760px; margin: 0 auto; }
    .panel { border: 1px solid #8883; border-radius: 12px; padding: 1.5rem; }
    .drop { border: 2px dashed #8886; border-radius: 12px; padding: 3rem; text-align: center; margin-top: 1rem; }
    .drop.drag { background: #8881; }
    .row { display: flex; gap: .5rem; align-items: center; }
    input, button { font: inherit; padding: .6rem .9rem; border-radius: 8px; border: 1px solid #8886; }
    button { cursor: pointer; }
    .muted { opacity: .8; font-size: .9rem; }
    progress { width: 100%; height: 10px; }
    .file { border-bottom: 1px solid #8882; padding: .5rem 0; }
    code { background: #8882; border-radius: 6px; padding: .1rem .3rem; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Dropzone</h1>
    <div class="panel">
      <div class="row">
        <label for="token">X-Token:</label>
        <input id="token" placeholder="paste shared token"/>
        <button id="saveToken">Save</button>
      </div>
      <div class="drop" id="drop">Drag files here or click to select</div>
      <input type="file" id="fileInput" multiple style="display:none"/>
      <h3>Uploads</h3>
      <div id="list"></div>
      <h3>Files on server</h3>
      <div id="serverFiles"></div>
      <p class="muted">
        Files are streamed to the server and written directly to disk.<br/>
        Limit: <span id="limit"></span>. Destination is server-side configured.
      </p>
    </div>
  </div>
  <script>
    const limitEl = document.getElementById('limit');
    fetch('/meta').then(r=>r.json()).then(m => limitEl.textContent = m.max_bytes_human);

    const drop = document.getElementById('drop');
    const fileInput = document.getElementById('fileInput');
    const list = document.getElementById('list');
    const tokenInput = document.getElementById('token');
    const saveBtn = document.getElementById('saveToken');
    const serverFiles = document.getElementById('serverFiles');

    tokenInput.value = localStorage.getItem('dz_token') || '';
    saveBtn.onclick = () => {
      localStorage.setItem('dz_token', tokenInput.value || '');
      alert('Token saved locally in this browser.');
      loadServerFiles();
    };

    drop.addEventListener('click', ()=> fileInput.click());
    drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drag'); });
    drop.addEventListener('dragleave', ()=> drop.classList.remove('drag'));
    drop.addEventListener('drop', e => {
      e.preventDefault(); drop.classList.remove('drag');
      handleFiles(e.dataTransfer.files);
    });
    fileInput.addEventListener('change', e => handleFiles(e.target.files));

    loadServerFiles();

    function handleFiles(files) {
      [...files].forEach(uploadOne);
    }

    function uploadOne(file) {
      const row = document.createElement('div');
      row.className = 'file';
      row.innerHTML = `<div><strong>${file.name}</strong> (${(file.size/1048576).toFixed(2)} MiB)</div>
                       <progress max="100" value="0"></progress>
                       <div class="muted" data-status>Queued…</div>`;
      list.prepend(row);
      const prog = row.querySelector('progress');
      const status = row.querySelector('[data-status]');

      const form = new FormData();
      form.append('files', file, file.name);

      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/upload');
      const tok = localStorage.getItem('dz_token') || '';
      if (tok) xhr.setRequestHeader('X-Token', tok);

      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          prog.value = Math.round(e.loaded * 100 / e.total);
        }
      };
      xhr.onload = () => {
        if (xhr.status === 200) {
          const resp = JSON.parse(xhr.responseText);
          status.textContent = `Uploaded. SHA256: ${resp.results[0].sha256}`;
          prog.value = 100;
          loadServerFiles();
        } else {
          status.textContent = `Error ${xhr.status}: ${xhr.responseText}`;
        }
      };
      xhr.onerror = () => status.textContent = 'Network error';
      xhr.send(form);
      status.textContent = 'Uploading…';
    }

    async function loadServerFiles() {
      serverFiles.textContent = 'Loading…';
      const tok = localStorage.getItem('dz_token') || '';
      const headers = {};
      if (tok) headers['X-Token'] = tok;
      const resp = await fetch('/files', { headers });
      if (!resp.ok) {
        serverFiles.textContent = `Could not load files (${resp.status}). Save a valid token first.`;
        return;
      }
      const data = await resp.json();
      if (!data.files.length) {
        serverFiles.textContent = 'No files uploaded yet.';
        return;
      }
      serverFiles.innerHTML = '';
      data.files.forEach(file => {
        const row = document.createElement('div');
        row.className = 'file';
        row.innerHTML = `<div class="row" style="justify-content:space-between">
            <div><code>${file.name}</code> (${file.bytes_human})</div>
            <div class="row">
              <a href="/files/${encodeURIComponent(file.name)}" target="_blank" rel="noreferrer">Download</a>
              <button data-del>Delete</button>
            </div>
          </div>
          <div class="muted" data-status></div>`;
        const btn = row.querySelector('[data-del]');
        const status = row.querySelector('[data-status]');
        btn.onclick = async () => {
          if (!confirm(`Delete ${file.name}?`)) return;
          btn.disabled = true;
          status.textContent = 'Deleting…';
          const delResp = await fetch(`/files/${encodeURIComponent(file.name)}`, {
            method: 'DELETE',
            headers
          });
          if (delResp.ok) {
            status.textContent = 'Deleted.';
            row.remove();
            if (!serverFiles.children.length) {
              serverFiles.textContent = 'No files uploaded yet.';
            }
          } else {
            status.textContent = `Delete failed (${delResp.status})`;
            btn.disabled = false;
          }
        };
        serverFiles.appendChild(row);
      });
    }
  </script>
</body>
</html>
"""


def human_bytes(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.2f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024


@app.get("/", response_class=HTMLResponse)
def index():
    if not TOKEN:
        return HTMLResponse("<pre>Server misconfigured: missing DROPZONE_TOKEN</pre>", status_code=500)
    return HTMLResponse(INDEX_HTML)


@app.get("/meta")
def meta():
    # Unauthenticated (the UI fetches it before a token is saved), so it must
    # not expose server internals like the destination path.
    return {"max_bytes": MAX_BYTES, "max_bytes_human": human_bytes(MAX_BYTES)}


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/files")
def list_files(x_token: Optional[str] = Header(default=None)):
    if not TOKEN or not hmac.compare_digest(x_token or "", TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")
    files = sorted(
        f for f in DEST_DIR.iterdir() if f.is_file() and not f.name.startswith(".part-")
    )
    return {"files": [{"name": f.name, "bytes": f.stat().st_size, "bytes_human": human_bytes(f.stat().st_size)} for f in files]}


@app.get("/files/{filename}")
def download_file(filename: str, x_token: Optional[str] = Header(default=None)):
    if not TOKEN or not hmac.compare_digest(x_token or "", TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")
    # Resolve and confirm the path stays inside DEST_DIR
    path = (DEST_DIR / sanitize_filename(filename)).resolve()
    if not path.is_relative_to(DEST_DIR) or not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@app.delete("/files/{filename}")
def delete_file(filename: str, x_token: Optional[str] = Header(default=None)):
    if not TOKEN or not hmac.compare_digest(x_token or "", TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")
    path = (DEST_DIR / sanitize_filename(filename)).resolve()
    if not path.is_relative_to(DEST_DIR) or not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    path.unlink()
    return {"ok": True, "deleted": path.name}


@app.post("/upload")
async def upload(
    request: Request,
    files: List[UploadFile] = File(...),
    x_token: Optional[str] = Header(default=None)
):
    # Enforce token from header (compare_digest prevents timing attacks)
    if not TOKEN or not hmac.compare_digest(x_token or "", TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")

    results = []
    for up in files:
        if MAX_TOTAL_BYTES and dir_usage(DEST_DIR) >= MAX_TOTAL_BYTES:
            raise HTTPException(status_code=507, detail="Storage limit reached")

        safe_name = sanitize_filename(up.filename)

        # Enforce extension allowlist (optional)
        if SAFE_EXTS and any(ext.strip() for ext in SAFE_EXTS):
            allowed = any(safe_name.lower().endswith(ext.strip())
                          for ext in SAFE_EXTS if ext.strip())
            if not allowed:
                raise HTTPException(
                    status_code=400, detail=f"File type not allowed: {up.filename}")

        tmp = DEST_DIR / f".part-{secrets.token_hex(8)}"
        final_path = resolve_collision(DEST_DIR / safe_name)

        size = 0
        try:
            with tmp.open("wb") as f:
                while True:
                    chunk = await up.read(1024 * 1024)  # 1 MiB
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise HTTPException(
                            status_code=413, detail=f"{up.filename}: file too large")
                    f.write(chunk)

            # Atomic move
            tmp.replace(final_path)

            # Hash off the main loop
            digest = await run_in_threadpool(sha256_file, final_path)

            results.append({
                "name": final_path.name,
                "bytes": size,
                "sha256": digest,
                "path": str(final_path),
            })
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except Exception:
                    pass

    return JSONResponse({"ok": True, "results": results})
