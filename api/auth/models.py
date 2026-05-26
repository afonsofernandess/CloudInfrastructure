from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from api.database import Base


class User(Base):
    """
    Local user table.
    Each user here has a corresponding account in OpenNebula (one_user_id).
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)

    # ID of the corresponding user in OpenNebula
    one_user_id = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_active_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=True)

