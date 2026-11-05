from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User
from app.pipeline.ai import AnthropicReceiptAI, ReceiptAI
from app.security import COOKIE, session_user


@lru_cache
def get_ai() -> ReceiptAI:
    return AnthropicReceiptAI(get_settings())


def current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User:
    settings = get_settings()
    session = session_user(settings.session_secret, request.cookies.get(COOKIE))
    user = db.get(User, session[0]) if session else None
    # A password reset bumps the version, which signs out every older session.
    if user is None or session is None or user.session_version != session[1]:
        raise HTTPException(401, "Please sign in")
    if user.email_verified_at is None:
        raise HTTPException(401, "Please confirm your email first")
    return user


DB = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]
AI = Annotated[ReceiptAI, Depends(get_ai)]
