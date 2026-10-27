from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, BigInteger, Float, func
)
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    tg_user_id = Column(BigInteger, unique=True, index=True)
    username = Column(String(100))
    status = Column(String(20), default="pending")
    is_banned = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    language = Column(String(5), default="uz")
    approved_by = Column(BigInteger, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

class ConnectedAccount(Base):
    __tablename__ = "connected_accounts"
    id = Column(Integer, primary_key=True)
    tg_user_id = Column(BigInteger, unique=True, index=True)
    encrypted_session = Column(Text, nullable=False)
    phone_hint = Column(String(20))
    delay = Column(Float, default=0.04)
    random_delay = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())

class Buffer(Base):
    __tablename__ = "buffers"
    id = Column(Integer, primary_key=True)
    tg_user_id = Column(BigInteger, unique=True, index=True)
    text = Column(Text, nullable=True)

class ActiveReply(Base):
    __tablename__ = "active_replies"
    id = Column(Integer, primary_key=True)
    tg_user_id = Column(BigInteger, index=True)
    target_user_id = Column(BigInteger)
    chat_id = Column(BigInteger)
    is_active = Column(Boolean, default=True)

class MandatoryChannel(Base):
    __tablename__ = "mandatory_channels"
    id = Column(Integer, primary_key=True)
    channel_id = Column(BigInteger, unique=True)
    channel_username = Column(String(100))
    channel_title = Column(String(200))
    created_at = Column(DateTime, server_default=func.now())
