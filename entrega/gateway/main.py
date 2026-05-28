import os, asyncio, logging, time
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse
import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("gateway")

USERS_URL = os.getenv("USERS_URL", "http://localhost:5001")
PRODUCTS_PRIMARY_URL = os.getenv("PRODUCTS_PRIMARY_URL", "http://localhost:5002")
PRODUCTS_REPLICA_URL = os.getenv("PRODUCTS_REPLICA_URL", "http://localhost:5012")
ORDERS_URL = os.getenv("ORDERS_URL", "http://localhost:5003")

HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "5"))
HEARTBEAT_TIMEOUT = float(os.getenv("HEARTBEAT_TIMEOUT", "2.0"))

# Service registry: name -> {url, healthy, failures}
services: dict[str, dict] = {
    "users":    {"url": USERS_URL,            "healthy": True, "failures": 0},
    "products": {"url": PRODUCTS_PRIMARY_URL, "healthy": True, "failures": 0},
    "products_replica": {"url": PRODUCTS_REPLICA_URL, "healthy": True, "failures": 0},
    "orders":   {"url": ORDERS_URL,           "healthy": True, "failures": 0},
}

_rr_counter = 0  # round-robin index for product reads


def products_read_url() -> str:
    """Return URL of a healthy products replica using round-robin."""
    global _rr_counter
    candidates = []
    if services["products"]["healthy"]:
        candidates.append(services["products"]["url"])
    if services["products_replica"]["healthy"]:
        candidates.append(services["products_replica"]["url"])
    if not candidates:
        return services["products"]["url"]  # try anyway; will 503 downstream
    url = candidates[_rr_counter % len(candidates)]
    _rr_counter += 1
    return url


app = FastAPI(title="API Gateway")


async def check_service(name: str, info: dict):
    url = info["url"]
    try:
        async with httpx.AsyncClient(timeout=HEARTBEAT_TIMEOUT) as client:
            r = await client.get(f"{url}/health")
            r.raise_for_status()
        if not info["healthy"]:
            logger.info("SERVICE RECOVERED  | %s at %s | %s", name, url,
                        datetime.now(timezone.utc).isoformat())
        info["healthy"] = True
        info["failures"] = 0
    except Exception:
        info["failures"] += 1
        if info["failures"] >= 2 and info["healthy"]:
            info["healthy"] = False
            logger.warning("SERVICE DOWN       | %s at %s | %s", name, url,
                           datetime.now(timezone.utc).isoformat())


async def heartbeat_loop():
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        await asyncio.gather(*[check_service(n, s) for n, s in services.items()])


@app.on_event("startup")
async def startup():
    asyncio.create_task(heartbeat_loop())
    logger.info("API Gateway started. Heartbeat every %ds.", HEARTBEAT_INTERVAL)


def require_healthy(service_name: str):
    if not services[service_name]["healthy"]:
        raise HTTPException(status_code=503, detail=f"Service '{service_name}' is unavailable")


async def proxy(request: Request, target_url: str, path: str) -> Response:
    method = request.method
    headers = dict(request.headers)
    headers.pop("host", None)
    body = await request.body()
    params = dict(request.query_params)
    full_url = f"{target_url}{path}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(
                method, full_url, headers=headers, content=body, params=params
            )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=dict(resp.headers),
            media_type=resp.headers.get("content-type", "application/json"),
        )
    except httpx.RequestError as e:
        logger.error("Proxy error -> %s: %s", full_url, e)
        raise HTTPException(status_code=503, detail="Upstream service unreachable")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def gateway_health():
    return {
        "status": "ok",
        "services": {n: {"healthy": s["healthy"]} for n, s in services.items()},
    }


# ── Users routes ──────────────────────────────────────────────────────────────

@app.api_route("/users/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def users_proxy(path: str, request: Request):
    require_healthy("users")
    return await proxy(request, USERS_URL, f"/users/{path}")


# ── Products routes ───────────────────────────────────────────────────────────

@app.api_route("/products", methods=["GET"])
async def products_list(request: Request):
    # read from a healthy replica via round-robin
    url = products_read_url()
    return await proxy(request, url, "/products")


@app.api_route("/products", methods=["POST"])
async def products_create(request: Request):
    require_healthy("products")
    return await proxy(request, PRODUCTS_PRIMARY_URL, "/products")


@app.api_route("/products/{path:path}", methods=["GET"])
async def products_get(path: str, request: Request):
    url = products_read_url()
    return await proxy(request, url, f"/products/{path}")


@app.api_route("/products/{path:path}", methods=["PUT", "DELETE"])
async def products_write(path: str, request: Request):
    require_healthy("products")
    return await proxy(request, PRODUCTS_PRIMARY_URL, f"/products/{path}")


# ── Orders routes ─────────────────────────────────────────────────────────────

@app.api_route("/orders/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def orders_proxy(path: str, request: Request):
    require_healthy("orders")
    return await proxy(request, ORDERS_URL, f"/orders/{path}")


@app.api_route("/orders", methods=["POST"])
async def orders_create(request: Request):
    require_healthy("orders")
    return await proxy(request, ORDERS_URL, "/orders")


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/dashboard", response_class=JSONResponse, include_in_schema=False)
async def dashboard():
    from fastapi.responses import HTMLResponse
    html = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8"/>
  <meta http-equiv="refresh" content="5"/>
  <title>Gateway Dashboard</title>
  <style>
    body{font-family:sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:24px}
    h1{color:#38bdf8;margin-bottom:24px}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
    .card{background:#1e293b;border-radius:12px;padding:20px;border:1px solid #334155}
    .name{font-weight:700;font-size:1.1rem;margin-bottom:8px}
    .status{display:inline-block;padding:4px 12px;border-radius:20px;font-size:.85rem;font-weight:600}
    .ok{background:#16a34a;color:#fff}
    .down{background:#dc2626;color:#fff}
    footer{margin-top:32px;font-size:.8rem;color:#64748b}
  </style>
</head>
<body>
  <h1>&#128268; API Gateway — Service Monitor</h1>
  <div class="grid">
"""
    for name, info in services.items():
        status_cls = "ok" if info["healthy"] else "down"
        status_txt = "ONLINE" if info["healthy"] else "OFFLINE"
        html += f"""
    <div class="card">
      <div class="name">{name}</div>
      <div>{info['url']}</div>
      <div style="margin-top:10px"><span class="status {status_cls}">{status_txt}</span></div>
      <div style="margin-top:6px;font-size:.8rem;color:#94a3b8">Failures: {info['failures']}</div>
    </div>"""
    html += """
  </div>
  <footer>Auto-refresh every 5s &nbsp;|&nbsp; Mini E-commerce Distribuído</footer>
</body>
</html>"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(html)
