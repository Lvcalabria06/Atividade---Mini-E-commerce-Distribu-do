import os, json, uuid, time, sys, logging

logger = logging.getLogger("products")
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel
import jwt
import httpx

SECRET_KEY = os.getenv("JWT_SECRET", "supersecret_jwt_key_2024")
SERVICE_TOKEN = os.getenv("SERVICE_TOKEN", "internal_service_secret_2024")
ALGORITHM = "HS256"

# Each replica uses its own DB file, determined by PORT env var
PORT = int(os.getenv("PORT", "5002"))
DB_FILE = Path(f"products_db_{PORT}.json")

# Replica address — primary knows about replica and vice versa
REPLICA_URL = os.getenv("REPLICA_URL", "")  # e.g. http://localhost:5012
IS_PRIMARY = os.getenv("IS_PRIMARY", "true").lower() == "true"

app = FastAPI(title=f"Products Service (port {PORT})")


def load_db() -> dict:
    if DB_FILE.exists():
        return json.loads(DB_FILE.read_text())
    return {"products": {}}


def save_db(db: dict):
    DB_FILE.write_text(json.dumps(db, indent=2))


def verify_token(authorization: str = Header(None)) -> dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing token")
    # Accept internal service-to-service token
    if authorization == f"Service {SERVICE_TOKEN}":
        return {"userId": "service", "role": "service"}
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid token format")
    token = authorization.split(" ", 1)[1]
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def require_admin(payload: dict = Depends(verify_token)) -> dict:
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return payload


async def propagate_to_replica(product: dict):
    """Propagate write to replica for strong consistency."""
    if not REPLICA_URL or not IS_PRIMARY:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{REPLICA_URL}/internal/products", json=product)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Replication failed: {e}")


class ProductRequest(BaseModel):
    name: str
    description: str = ""
    price: float
    stock: int = 0


@app.get("/health")
def health():
    return {"status": "ok", "port": PORT}


@app.get("/products")
def list_products():
    db = load_db()
    return list(db["products"].values())


@app.get("/products/{product_id}")
def get_product(product_id: str):
    db = load_db()
    product = db["products"].get(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.post("/products", status_code=201)
async def create_product(req: ProductRequest, payload: dict = Depends(require_admin)):
    db = load_db()
    product_id = str(uuid.uuid4())
    product = {
        "id": product_id,
        "name": req.name,
        "description": req.description,
        "price": req.price,
        "stock": req.stock,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    # Propagate to replica first (strong consistency: write both before confirming)
    await propagate_to_replica(product)
    db["products"][product_id] = product
    save_db(db)
    return product


@app.put("/products/{product_id}")
async def update_product(product_id: str, req: ProductRequest, payload: dict = Depends(require_admin)):
    db = load_db()
    if product_id not in db["products"]:
        raise HTTPException(status_code=404, detail="Product not found")
    product = db["products"][product_id]
    product.update({"name": req.name, "description": req.description, "price": req.price, "stock": req.stock})
    await propagate_to_replica(product)
    db["products"][product_id] = product
    save_db(db)
    return product


# Internal endpoint — receives single replication write from primary
@app.post("/internal/products", status_code=201, include_in_schema=False)
def internal_replicate(product: dict):
    db = load_db()
    db["products"][product["id"]] = product
    save_db(db)
    return {"replicated": True}


# Internal endpoint — full sync after replica recovery
@app.post("/internal/sync", include_in_schema=False)
def internal_sync(products: list):
    db = load_db()
    db["products"] = {p["id"]: p for p in products}
    save_db(db)
    logger.info("Full sync received: %d products", len(products))
    return {"synced": len(products)}
