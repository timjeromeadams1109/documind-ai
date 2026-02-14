from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from jose import JWTError, jwt
from datetime import datetime, timedelta
import hashlib
import secrets
import httpx
import json
import sys
sys.path.insert(0, '/Users/timothyadams/generated-apps/fastapi-auth-app')
from database import SessionLocal, Base, engine
from sqlalchemy import Column, Integer, String, DateTime

# User model
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    reset_token = Column(String, nullable=True)
    reset_token_expires = Column(DateTime, nullable=True)

# Create tables
Base.metadata.create_all(bind=engine)

# Config
SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
OLLAMA_URL = "http://localhost:11434"

# Available models with descriptions
AVAILABLE_MODELS = {
    "mistral:latest": {
        "name": "Mistral 7B",
        "description": "Best for general analysis, summarization, and business documents",
        "type": "general"
    },
    "llama3.2:latest": {
        "name": "Llama 3.2",
        "description": "Balanced model good for most tasks",
        "type": "general"
    },
    "deepseek-coder:6.7b": {
        "name": "DeepSeek Coder",
        "description": "Specialized for code review and technical analysis",
        "type": "code"
    }
}

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(plain: str, hashed: str) -> bool:
    return hash_password(plain) == hashed

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str) -> str:
    """Verify JWT token and return username"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def chunk_text(text: str, chunk_size: int = 8000, overlap: int = 500) -> list:
    """Split text into overlapping chunks for large document processing"""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap
    return chunks

@router.post("/register")
async def register(username: str, email: str, password: str, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="Username already registered")

    user = User(username=username, email=email, hashed_password=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": "User created", "username": user.username}

@router.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me")
async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    username = verify_token(token)
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"username": user.username, "email": user.email}

# ============================================
# Password Reset
# ============================================

@router.post("/forgot-password")
async def forgot_password(email: str, db: Session = Depends(get_db)):
    """Request password reset - returns token directly (no email)"""
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Email not found")

    reset_token = secrets.token_urlsafe(32)
    user.reset_token = reset_token
    user.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
    db.commit()

    return {
        "message": "Password reset token generated",
        "reset_token": reset_token,
        "expires_in": "1 hour"
    }

@router.post("/reset-password")
async def reset_password(token: str, new_password: str, db: Session = Depends(get_db)):
    """Reset password using token"""
    user = db.query(User).filter(User.reset_token == token).first()

    if not user:
        raise HTTPException(status_code=400, detail="Invalid reset token")

    if user.reset_token_expires < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Reset token expired")

    user.hashed_password = hash_password(new_password)
    user.reset_token = None
    user.reset_token_expires = None
    db.commit()

    return {"message": "Password reset successful"}

# ============================================
# AI Models
# ============================================

@router.get("/models")
async def list_models():
    """List available AI models"""
    return {"models": AVAILABLE_MODELS}

# ============================================
# Document Analysis (Standard)
# ============================================

@router.post("/analyze")
async def analyze_document(
    instructions: str = Form(..., description="What to analyze or extract from the document"),
    file: UploadFile = File(..., description="Document to analyze"),
    model: str = Form(default="mistral:latest", description="AI model to use"),
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    """Analyze a document according to your instructions"""
    verify_token(token)

    # Read file content
    content = await file.read()
    try:
        text_content = content.decode('utf-8')
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be text-based")

    # Handle large documents with chunking
    chunks = chunk_text(text_content, chunk_size=12000)

    if len(chunks) == 1:
        # Single chunk - standard analysis
        prompt = f"""You are an expert document analyst. Analyze the following document according to the user's instructions. Be thorough and detailed.

INSTRUCTIONS: {instructions}

DOCUMENT ({file.filename}):
---
{chunks[0]}
---

Provide your analysis based on the instructions above."""
    else:
        # Multiple chunks - summarize approach
        prompt = f"""You are an expert document analyst. This is a large document split into {len(chunks)} parts. Analyze it according to the user's instructions.

INSTRUCTIONS: {instructions}

DOCUMENT ({file.filename}) - Part 1 of {len(chunks)}:
---
{chunks[0]}
---

Note: This document continues. Focus on extracting key information relevant to the instructions.

Provide your analysis based on the instructions above."""

    # Call Ollama
    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            response = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False}
            )
            result = response.json()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="AI model timeout - try a shorter document")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"AI error: {str(e)}")

    return {
        "filename": file.filename,
        "instructions": instructions,
        "analysis": result.get("response", "No response"),
        "model": model,
        "chunks_processed": len(chunks)
    }

# ============================================
# Document Analysis (Streaming)
# ============================================

@router.post("/analyze/stream")
async def analyze_document_stream(
    instructions: str = Form(...),
    file: UploadFile = File(...),
    model: str = Form(default="mistral:latest"),
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    """Analyze document with streaming response for real-time output"""
    verify_token(token)

    content = await file.read()
    try:
        text_content = content.decode('utf-8')
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be text-based")

    chunks = chunk_text(text_content, chunk_size=12000)

    prompt = f"""You are an expert document analyst. Analyze the following document according to the user's instructions. Be thorough and detailed.

INSTRUCTIONS: {instructions}

DOCUMENT ({file.filename}):
---
{chunks[0]}
---

Provide your analysis based on the instructions above."""

    async def generate():
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                f"{OLLAMA_URL}/api/generate",
                json={"model": model, "prompt": prompt, "stream": True}
            ) as response:
                async for line in response.aiter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            if "response" in data:
                                yield f"data: {json.dumps({'text': data['response']})}\n\n"
                            if data.get("done"):
                                yield f"data: {json.dumps({'done': True})}\n\n"
                        except json.JSONDecodeError:
                            continue

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )
