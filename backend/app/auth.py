"""JWT login + role-based access control."""
import os, time
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from passlib.hash import bcrypt
from . import db  # noqa: F401  (loads .env)

SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
ALGO, EXPIRE_MIN = "HS256", 30
ROLES = {"admin", "planner", "transport", "depot", "post"}
oauth2 = OAuth2PasswordBearer(tokenUrl="/login")
_fails = {}   # username -> (count, locked_until)

def verify(password, hashed):
    return bcrypt.verify(password, hashed)

def hash_pw(password):
    return bcrypt.hash(password)

def make_token(user):
    exp = datetime.now(timezone.utc) + timedelta(minutes=EXPIRE_MIN)
    return jwt.encode({"sub": user.username, "role": user.role, "loc": user.location_id, "exp": exp}, SECRET, algorithm=ALGO)

def decode(token):
    return jwt.decode(token, SECRET, algorithms=[ALGO])

def current_user(token: str = Depends(oauth2)):
    try:
        return decode(token)
    except JWTError:
        raise HTTPException(401, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})

def require(*roles):
    def checker(user=Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(403, f"Role '{user['role']}' is not allowed to do this")
        return user
    return checker

def check_lock(username):
    count, until = _fails.get(username, (0, 0))
    if until > time.time():
        raise HTTPException(429, f"Too many failed attempts. Try again in {int(until - time.time())} s")

def record_fail(username):
    count, _ = _fails.get(username, (0, 0))
    count += 1
    _fails[username] = (count, time.time() + 300 if count >= 5 else 0)
    if count >= 5:
        _fails[username] = (0, time.time() + 300)

def clear_fail(username):
    _fails.pop(username, None)
