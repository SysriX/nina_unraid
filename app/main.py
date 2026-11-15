"""NINA – Netzwerk- und IT-Geräteliste. Startpunkt (FastAPI + uvicorn)."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import kern

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


@asynccontextmanager
async def lebenszyklus(app):
    import agent
    import dienste
    import zugang
    try:
        kern.fernet()
        if kern.db_starten():
            kern.log("Datenbank:", (kern.konfig_lesen().get("db") or {}).get("typ"))
    except Exception as e:  # noqa: BLE001
        kern.log("Datenbank nicht bereit:", e)
    zugang.code_melden()
    if kern.db_bereit():
        agent.DIENST.start()
    import asyncio
    await asyncio.to_thread(dienste.MDNS.start)   # Zeroconf-API blockiert – nicht im Event-Loop aufrufen
    aufgaben = dienste.starten()
    kern.log(f"NINA {kern.VERSION} bereit auf Port {dienste.port()}")
    yield
    for t in aufgaben:
        t.cancel()
    agent.DIENST.stop()
    await asyncio.to_thread(dienste.MDNS.stop)


app = FastAPI(title="NINA", version=kern.VERSION, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lebenszyklus)


@app.middleware("http")
async def schutz(req: Request, call_next):
    # CSRF: schreibende Aufrufe aus dem Browser nur mit eigenem Header; API-Schlüssel (Bearer) brauchen ihn nicht
    if req.url.path.startswith("/api/") and req.method in ("POST", "PUT", "PATCH", "DELETE") \
            and req.headers.get("x-ni") != "1" and not req.headers.get("authorization", "").lower().startswith("bearer "):
        return JSONResponse({"detail": "Header X-NI fehlt"}, status_code=403)
    resp = await call_next(req)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("Content-Security-Policy",
                            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                            "script-src 'self'; connect-src 'self'; frame-ancestors 'self'; form-action 'self'")
    if req.url.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    elif req.url.path.startswith("/static/"):
        resp.headers.setdefault("Cache-Control", "no-cache")
    return resp


@app.exception_handler(PermissionError)
async def _verboten(req, e):
    return JSONResponse({"detail": str(e)}, status_code=403)


@app.exception_handler(LookupError)
async def _fehlt(req, e):
    return JSONResponse({"detail": str(e)}, status_code=404)


@app.exception_handler(ValueError)
async def _wert(req, e):
    return JSONResponse({"detail": str(e)}, status_code=400)


@app.exception_handler(RuntimeError)
async def _laufzeit(req, e):
    kern.log("Fehler:", repr(e))
    return JSONResponse({"detail": str(e)}, status_code=500)


import agent  # noqa: E402
import haapi  # noqa: E402
import inventar  # noqa: E402
import katalog  # noqa: E402
import verwaltung  # noqa: E402
import zeitplan  # noqa: E402
import zugang  # noqa: E402

for r in (zugang.router, inventar.router, katalog.router, agent.router, verwaltung.router, zeitplan.router, haapi.router):
    app.include_router(r)


@app.get("/gesund")
def gesund():
    return {"ok": True, "eingerichtet": zugang.eingerichtet(), "version": kern.VERSION}


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "DELETE"])
def api_unbekannt(rest: str):
    raise HTTPException(404, "unbekannt")


app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/")
def start():
    return FileResponse(os.path.join(WEB, "index.html"), headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn
    tls = {}
    if os.environ.get("NINA_TLS_CERT") and os.environ.get("NINA_TLS_KEY"):
        tls = {"ssl_certfile": os.environ["NINA_TLS_CERT"], "ssl_keyfile": os.environ["NINA_TLS_KEY"]}
    uvicorn.run(app, host=os.environ.get("NINA_HOST", "0.0.0.0"), port=int(os.environ.get("NINA_PORT", "8080")), proxy_headers=True,
                forwarded_allow_ips=os.environ.get("NINA_PROXY_IPS", "127.0.0.1"), log_level="warning",
                server_header=False, **tls)
