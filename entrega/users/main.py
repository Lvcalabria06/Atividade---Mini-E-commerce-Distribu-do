import os, json, uuid, hashlib, time
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel
import jwt

SECRET_KEY = os.getenv("JWT_SECRET", "supersecret_jwt_key_2024")
ALGORITHM = "HS256"
DB_FILE = Path("users_db.json")

app = FastAPI(title="Users Service")


def load_db() -> dict:
    if DB_FILE.exists():
        return json.loads(DB_FILE.read_text())
    return {"users": {}}


def save_db(db: dict):
    DB_FILE.write_text(json.dumps(db, indent=2))


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def create_token(user: dict) -> str:
    payload = {
        "userId": user["id"],
        "email": user["email"],
        "role": user.get("role", "user"),
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


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


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    role: str = "user"


class LoginRequest(BaseModel):
    email: str
    password: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/users/register", status_code=201)
def register(req: RegisterRequest):
    db = load_db()
    for u in db["users"].values():
        if u["email"] == req.email:
            raise HTTPException(status_code=409, detail="Email already registered")
    user_id = str(uuid.uuid4())
    db["users"][user_id] = {
        "id": user_id,
        "name": req.name,
        "email": req.email,
        "password_hash": hash_password(req.password),
        "role": req.role,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    save_db(db)
    return {"id": user_id, "name": req.name, "email": req.email, "role": req.role}


@app.post("/users/login")
def login(req: LoginRequest):
    db = load_db()
    for user in db["users"].values():
        if user["email"] == req.email and user["password_hash"] == hash_password(req.password):
            token = create_token(user)
            return {"token": token, "userId": user["id"], "role": user["role"]}
    raise HTTPException(status_code=401, detail="Invalid credentials")


@app.get("/users/{user_id}")
def get_user(user_id: str, payload: dict = Depends(verify_token)):
    db = load_db()
    user = db["users"].get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]}
