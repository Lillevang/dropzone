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
