import os, json, uuid, time
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel
import jwt
import httpx

SECRET_KEY = os.getenv("JWT_SECRET", "supersecret_jwt_key_2024")
ALGORITHM = "HS256"
DB_FILE = Path("orders_db.json")

USERS_URL = os.getenv("USERS_URL", "http://localhost:5001")
PRODUCTS_URL = os.getenv("PRODUCTS_URL", "http://localhost:5002")

app = FastAPI(title="Orders Service")


def load_db() -> dict:
    if DB_FILE.exists():
        return json.loads(DB_FILE.read_text())
    return {"orders": {}}


def save_db(db: dict):
    DB_FILE.write_text(json.dumps(db, indent=2))


def verify_token(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization.split(" ", 1)[1]
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


class OrderRequest(BaseModel):
    userId: str
    productId: str
    quantity: int = 1


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/orders", status_code=201)
async def create_order(req: OrderRequest, payload: dict = Depends(verify_token)):
    if payload.get("userId") != req.userId:
        raise HTTPException(status_code=403, detail="Cannot create orders for other users")

    async with httpx.AsyncClient(timeout=5.0) as client:
        # Validate product exists
        try:
            r = await client.get(f"{PRODUCTS_URL}/products/{req.productId}")
            if r.status_code == 404:
                raise HTTPException(status_code=404, detail="Product not found")
            r.raise_for_status()
            product = r.json()
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Products service unavailable")

        if product.get("stock", 0) < req.quantity:
            raise HTTPException(status_code=400, detail="Insufficient stock")

    db = load_db()
    order_id = str(uuid.uuid4())
    order = {
        "id": order_id,
        "userId": req.userId,
        "productId": req.productId,
        "productName": product.get("name"),
        "quantity": req.quantity,
        "unitPrice": product.get("price"),
        "total": product.get("price", 0) * req.quantity,
        "status": "confirmed",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db["orders"][order_id] = order
    save_db(db)
    return order


@app.get("/orders/{user_id}")
def get_user_orders(user_id: str, payload: dict = Depends(verify_token)):
    if payload.get("userId") != user_id and payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    db = load_db()
    orders = [o for o in db["orders"].values() if o["userId"] == user_id]
    return orders
