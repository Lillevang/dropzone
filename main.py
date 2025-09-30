from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse


# ========= app =========
app = FastAPI(title="Dropzone", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"]
)

INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Dropzone is OFF</title>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate, max-age=0"/>
  <meta name="robots" content="noindex,nofollow"/>
  <style>
    :root { color-scheme: light dark; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font: 16px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    .card {
      width: min(640px, 92vw);
      border: 1px solid #8883;
      border-radius: 16px;
      padding: 2rem;
      text-align: center;
      box-shadow: 0 6px 20px #0001;
    }
    h1 { margin: 0 0 .5rem 0; font-weight: 700; font-size: 1.6rem; }
    p { margin: .25rem 0; opacity: .9; }
    .muted { opacity: .7; font-size: .95rem; }
    code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
      background: #8882; padding: .15rem .35rem; border-radius: 6px;
    }
    .dot {
      display: inline-block; width: .6rem; height: .6rem; border-radius: 50%; margin-right: .35rem;
      background: #e53935;
      box-shadow: 0 0 0 3px #e539351a;
      vertical-align: middle;
    }
  </style>
</head>
<body>
  <main class="card" role="main" aria-labelledby="title">
    <h1 id="title"><span class="dot" aria-hidden="true"></span>Dropzone is turned off</h1>
    <p>This endpoint is intentionally disabled. Turn it on from ArgoCD when you need to upload.</p>
    <p class="muted">Status: <code>OFF</code></p>
  </main>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(INDEX_HTML)


@app.get("/healthz")
def healthz():
    return {"ok": True}
