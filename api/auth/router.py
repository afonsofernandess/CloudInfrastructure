from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from api.database import get_db
from api.auth.models import User
from api.auth.schemas import UserRegister, UserLogin, UserUpdate, UserResponse, TokenResponse
from api.auth.jwt import create_access_token, get_current_user
from api.auth.opennebula_sync import create_one_user, update_one_user_password, delete_one_user

router = APIRouter(prefix="/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# POST /auth/register
@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(data: UserRegister, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed = pwd_context.hash(data.password)

    # Create the user in OpenNebula first to get their one_user_id
    try:
        one_user_id = create_one_user(data.username, data.password)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenNebula error: {e}")

    user = User(
        username=data.username,
        email=data.email,
        hashed_password=hashed,
        one_user_id=one_user_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# POST /auth/login
@router.post("/login", response_model=TokenResponse)
def login(data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username).first()
    if not user or not pwd_context.verify(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    token = create_access_token(user.id, user.username)
    return {"access_token": token}


# GET /auth/me  (requires token)
@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    from api.auth.opennebula_sync import get_one_user_ssh_key
    ssh_key = None
    if current_user.one_user_id:
        ssh_key = get_one_user_ssh_key(current_user.one_user_id)
    current_user.ssh_public_key = ssh_key
    return current_user


# PUT /auth/me  (requires token)
@router.put("/me", response_model=UserResponse)
def update_me(data: UserUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if data.email:
        if db.query(User).filter(User.email == data.email, User.id != current_user.id).first():
            raise HTTPException(status_code=400, detail="Email already in use")
        current_user.email = data.email

    if data.password:
        current_user.hashed_password = pwd_context.hash(data.password)
        # Mirror password change to OpenNebula
        if current_user.one_user_id:
            try:
                update_one_user_password(current_user.one_user_id, data.password)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"OpenNebula error: {e}")

    if data.ssh_public_key is not None:
        if current_user.one_user_id:
            try:
                from api.auth.opennebula_sync import update_one_user_ssh_key
                update_one_user_ssh_key(current_user.one_user_id, data.ssh_public_key)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"OpenNebula error updating SSH key: {e}")

    db.commit()
    db.refresh(current_user)

    from api.auth.opennebula_sync import get_one_user_ssh_key
    current_user.ssh_public_key = get_one_user_ssh_key(current_user.one_user_id) if current_user.one_user_id else None
    return current_user


# DELETE /auth/me  (requires token)
@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Remove from OpenNebula first
    if current_user.one_user_id:
        try:
            delete_one_user(current_user.one_user_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"OpenNebula error: {e}")

    db.delete(current_user)
    db.commit()
