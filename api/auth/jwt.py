from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from api.database import get_db
from api.auth.models import User

SECRET_KEY = "change-this-in-production-use-env-var"
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def create_access_token(user_id: int, username: str) -> str:
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """FastAPI dependency — decodes JWT and returns the current user."""
    print("--> get_current_user called", flush=True)
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
        print(f"--> Decoded token for user_id={user_id}", flush=True)
    except (JWTError, TypeError):
        print("--> Failed to decode token", flush=True)
        raise credentials_error

    print(f"--> Querying database for user_id={user_id}", flush=True)
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        print(f"--> User not found or inactive", flush=True)
        raise credentials_error

    print(f"--> Updating last_active_at for user {user.username}", flush=True)
    user.last_active_at = datetime.now(timezone.utc)
    db.commit()
    print(f"--> db.commit() successful", flush=True)
    db.refresh(user)
    print(f"--> db.refresh() successful", flush=True)

    return user

