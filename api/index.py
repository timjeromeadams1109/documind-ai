from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt
from datetime import datetime, timedelta
import hashlib
import secrets
import httpx
import json
import os

# Config
SECRET_KEY = os.environ.get("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

# In-memory store (for demo - use a real DB in production)
users_db = {}
reset_tokens = {}

app = FastAPI(title="ATSai - Document Analysis")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(plain: str, hashed: str) -> bool:
    return hash_password(plain) == hashed

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str) -> str:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# Landing page HTML
@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <!DOCTYPE html>
    <html><head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ATSai</title>
    <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-950 text-white min-h-screen flex items-center justify-center">
    <div class="text-center">
        <h1 class="text-6xl font-bold bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 bg-clip-text text-transparent mb-4">ATSai</h1>
        <p class="text-xl text-gray-400 mb-8">AI-Powered Document Analysis</p>
        <p class="text-gray-500">API running on Vercel</p>
        <div class="mt-8 space-x-4">
            <a href="/docs" class="px-6 py-3 bg-indigo-600 rounded-lg hover:bg-indigo-700">API Docs</a>
        </div>
    </div>
    </body></html>
    """

@app.get("/health")
async def health():
    return {"status": "healthy", "platform": "vercel"}

@app.post("/auth/register")
async def register(username: str, email: str, password: str):
    if username in users_db:
        raise HTTPException(status_code=400, detail="Username already registered")
    users_db[username] = {
        "username": username,
        "email": email,
        "hashed_password": hash_password(password)
    }
    return {"message": "User created", "username": username}

@app.post("/auth/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = users_db.get(form_data.username)
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token(data={"sub": user["username"]})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/auth/me")
async def get_current_user(token: str = Depends(oauth2_scheme)):
    username = verify_token(token)
    user = users_db.get(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"username": user["username"], "email": user["email"]}

@app.post("/auth/forgot-password")
async def forgot_password(email: str):
    for username, user in users_db.items():
        if user["email"] == email:
            reset_token = secrets.token_urlsafe(32)
            reset_tokens[reset_token] = {"username": username, "expires": datetime.utcnow() + timedelta(hours=1)}
            return {"message": "Reset token generated", "reset_token": reset_token}
    raise HTTPException(status_code=404, detail="Email not found")

@app.post("/auth/reset-password")
async def reset_password(token: str, new_password: str):
    if token not in reset_tokens:
        raise HTTPException(status_code=400, detail="Invalid reset token")
    data = reset_tokens[token]
    if data["expires"] < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Token expired")
    users_db[data["username"]]["hashed_password"] = hash_password(new_password)
    del reset_tokens[token]
    return {"message": "Password reset successful"}

@app.get("/auth/models")
async def list_models():
    return {"models": {
        "mistral:latest": {"name": "Mistral 7B", "type": "general"},
        "llama3.2:latest": {"name": "Llama 3.2", "type": "general"},
        "deepseek-coder:6.7b": {"name": "DeepSeek Coder", "type": "code"}
    }}

@app.post("/auth/analyze")
async def analyze_document(
    instructions: str = Form(...),
    file: UploadFile = File(...),
    model: str = Form(default="mistral:latest"),
    token: str = Depends(oauth2_scheme)
):
    verify_token(token)

    content = await file.read()
    try:
        text_content = content.decode('utf-8')
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be text-based")

    prompt = f"""You are an expert document analyst. Analyze the following document according to the user's instructions.

INSTRUCTIONS: {instructions}

DOCUMENT ({file.filename}):
---
{text_content[:12000]}
---

Provide your analysis."""

    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            response = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False}
            )
            result = response.json()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"AI error: {str(e)}")

    return {
        "filename": file.filename,
        "instructions": instructions,
        "analysis": result.get("response", "No response"),
        "model": model
    }

