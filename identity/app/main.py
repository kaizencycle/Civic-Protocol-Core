# identity/app/main.py
"""
Mobius Identity Service

Authentication and identity management for the Mobius platform.
Provides email/password signup, login, JWT token-based authentication.
"""

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy import create_engine, Column, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from passlib.context import CryptContext
from datetime import datetime, timedelta
import jwt
import os
import uuid

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./identity.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30

# Database setup
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Models
class User(Base):
    __tablename__ = "users"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(255))
    civic_id = Column(String(255), unique=True, index=True)  # Link to Civic Protocol identity
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Create tables
Base.metadata.create_all(bind=engine)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Security
security = HTTPBearer()


# Pydantic models
class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    name: str | None
    civic_id: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse


class UserUpdateRequest(BaseModel):
    name: str | None = None


# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Auth functions
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("user_id")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    user_id = verify_token(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid authentication")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return user


def generate_civic_id(user_id: str) -> str:
    """Generate a unique Civic ID for a user"""
    short_hash = uuid.uuid5(uuid.NAMESPACE_DNS, user_id).hex[:12]
    return f"civic::{short_hash}"


# FastAPI app
app = FastAPI(
    title="Mobius Identity Service",
    description="Authentication and identity management for Mobius",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://mobius-browser-shell.vercel.app",
        "https://mobius-browser-shell-*.vercel.app",
        "http://localhost:5173",
        "http://localhost:3000",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Routes
@app.get("/")
async def root():
    return {
        "service": "mobius-identity-service",
        "version": "1.0.0",
        "docs": "/docs",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "Mobius Identity Service",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/auth/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(request: SignupRequest, db: Session = Depends(get_db)):
    """Create a new user account"""
    
    # Check if user exists
    existing_user = db.query(User).filter(User.email == request.email.lower()).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create user
    user_id = str(uuid.uuid4())
    civic_id = generate_civic_id(user_id)
    
    user = User(
        id=user_id,
        email=request.email.lower(),
        password_hash=pwd_context.hash(request.password),
        name=request.name,
        civic_id=civic_id
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # Create token
    token = create_access_token({"user_id": user.id, "civic_id": civic_id})
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user
    }


@app.post("/auth/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Login with email and password"""
    
    # Find user
    user = db.query(User).filter(User.email == request.email.lower()).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Verify password
    if not pwd_context.verify(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Create token
    token = create_access_token({"user_id": user.id, "civic_id": user.civic_id})
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user
    }


@app.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current authenticated user"""
    return current_user


@app.patch("/auth/me", response_model=UserResponse)
async def update_me(
    request: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update current user profile"""
    if request.name is not None:
        current_user.name = request.name
    
    current_user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(current_user)
    
    return current_user


@app.post("/auth/logout")
async def logout():
    """Logout (client should delete token)"""
    return {"message": "Logged out successfully"}


@app.get("/auth/introspect")
async def introspect(current_user: User = Depends(get_current_user)):
    """Introspect token - returns user info for token validation"""
    return {
        "active": True,
        "user_id": current_user.id,
        "civic_id": current_user.civic_id,
        "email": current_user.email,
        "name": current_user.name
    }


@app.get("/auth/verify/{civic_id}")
async def verify_civic_id(civic_id: str, db: Session = Depends(get_db)):
    """Verify a civic ID exists"""
    user = db.query(User).filter(User.civic_id == civic_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Civic ID not found")
    
    return {
        "valid": True,
        "civic_id": civic_id,
        "created_at": user.created_at.isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
