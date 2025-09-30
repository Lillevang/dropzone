import hashlib
import os
import secrets

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path
from starlette.concurrency import run_in_threadpool
from typing import List, Optional


DEST_DIR = Path(os.getenv("DEST_DIR", "./uploads")).resolve()
DEST_DIR.mkdir(parents=True, exist_ok=True)

# TOKEN REQUIRED
TOKEN = os.getenv("DROPZONE_TOKEN")

# Default 10 GiB
MAX_BYTES = int(os.getenv("MAX_BYTES", str(10*1024 * 1024 * 1024)))
ALLOW_OVERWRITE = os.getenv("ALLOW_OVERWRITE", "false").lower() == "true"
SAFE_EXTS = set(
    (os.getenv("SAFE_EXTS", ".zip,.tar.gz,.tgz,.7z,.rar,.txt,.csv,.pdf").split(",")))


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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ========= app =========
app = FastAPI(title="Dropzone", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"]
)

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
      <div id="list"></div>
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

    tokenInput.value = localStorage.getItem('dz_token') || '';
    saveBtn.onclick = () => {
      localStorage.setItem('dz_token', tokenInput.value || '');
      alert('Token saved locally in this browser.');
    };

    drop.addEventListener('click', ()=> fileInput.click());
    drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drag'); });
    drop.addEventListener('dragleave', ()=> drop.classList.remove('drag'));
    drop.addEventListener('drop', e => {
      e.preventDefault(); drop.classList.remove('drag');
      handleFiles(e.dataTransfer.files);
    });
    fileInput.addEventListener('change', e => handleFiles(e.target.files));

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
        } else {
          status.textContent = `Error ${xhr.status}: ${xhr.responseText}`;
        }
      };
      xhr.onerror = () => status.textContent = 'Network error';
      xhr.send(form);
      status.textContent = 'Uploading…';
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
    return {"max_bytes": MAX_BYTES, "max_bytes_human": human_bytes(MAX_BYTES), "dest_dir": str(DEST_DIR)}


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/upload")
async def upload(
    request: Request,
    files: List[UploadFile] = File(...),
    x_token: Optional[str] = Header(default=None)
):
    # Enforce token from header
    if not TOKEN or x_token != TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    results = []
    for up in files:
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
