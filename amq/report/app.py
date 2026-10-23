"""amq.report.app: the AlgoMaschine results dashboard for any project (serves <out>/results.json and audit.json live,
and the method page).
    AMQ_OUT=outputs AMQ_TOKEN=... uvicorn amq.report.app:app --host 0.0.0.0 --port <free port>
Every route sits under the secret token prefix; anything else is a 404."""
import json
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response

TOKEN = os.environ.get("AMQ_TOKEN", "")
OUT = Path(os.environ.get("AMQ_OUT", "outputs")).resolve()
STATIC = Path(__file__).resolve().parent / "static"
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def guard(token):
    if not TOKEN or not secrets.compare_digest(token, TOKEN):
        raise HTTPException(status_code=404)


@app.get("/{token}/")
def index(token: str):
    guard(token)
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/{token}/method")
def method(token: str):
    guard(token)
    return FileResponse(STATIC / "method.html", headers={"Cache-Control": "no-cache"})


@app.get("/{token}/static/{name}")
def static(token: str, name: str):
    guard(token)
    p = STATIC / name
    if p.parent != STATIC or not p.exists():
        raise HTTPException(status_code=404)
    return FileResponse(p, headers={"Cache-Control": "no-cache"})


@app.get("/{token}/api/results")
def results(token: str):
    guard(token)
    p = OUT / "results.json"
    return Response(p.read_bytes(), media_type="application/json") if p.exists() else JSONResponse({"pending": True})


@app.get("/{token}/api/audit")
def audit(token: str):
    guard(token)
    p = OUT / "audit.json"
    return Response(p.read_bytes(), media_type="application/json") if p.exists() else JSONResponse({"pending": True})


@app.get("/{token}/api/status")
def status(token: str):
    guard(token)
    out = {}
    for name in ("status.json", "review.json"):
        try:
            out[name.split(".")[0]] = json.loads((OUT / name).read_text())
        except Exception:
            out[name.split(".")[0]] = None
    mon = sorted(OUT.glob("monitor_*.log"))
    out["monitor"] = mon[-1].read_text().strip().splitlines()[-1] if mon else None
    return out
