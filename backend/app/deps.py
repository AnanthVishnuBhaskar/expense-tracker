from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User
from app.pipeline.ai import AnthropicReceiptAI, ReceiptAI
from app.security import COOKIE, session_user_id


@lru_cache
def get_ai() -> ReceiptAI:
    return AnthropicReceiptAI(get_settings())


def current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User:
    user_id = session_user_id(get_settings().session_secret, request.cookies.get(COOKIE))
    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(401, "Please sign in")
    return user


DB = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]
AI = Annotated[ReceiptAI, Depends(get_ai)]
