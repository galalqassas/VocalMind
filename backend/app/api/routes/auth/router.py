# Auth router: password login + Google ID-token login (existing users only).
# Logic: All auth HTTP handlers in one file, right next to the service and schemas they use.

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status, Response, Query
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import select

from app.api.deps import SessionDep
from app.core import security
from app.core.config import settings
from app.models.user import User as UserModel
from app.api.routes.auth.schemas import Token
from app.api.routes.auth.service import verify_google_token

router = APIRouter()


def _create_token(user_id: Any) -> dict:
    expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": security.create_access_token(user_id, expires_delta=expires),
        "token_type": "bearer",
    }


# ---------- Password login ----------

@router.post("/login/access-token", response_model=Token, responses={400: {"description": "Incorrect email or password, or inactive user"}})
async def login_access_token(
    response: Response,
    session: SessionDep,
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Any:
    """
    Authenticate user using email and password and return a bearer access token.
    Also sets the 'vocalmind_token' cookie.
    """
    statement = select(UserModel).where(UserModel.email == form_data.username)
    result = await session.exec(statement)
    user = result.first()

    if (
        not user
        or not user.password_hash
        or not security.verify_password(form_data.password, user.password_hash)
    ):
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    token_data = _create_token(user.id)
    response.set_cookie(
        key="vocalmind_token",
        value=token_data["access_token"],
        httponly=True,
        secure=False,  # Set to True in production with HTTPS
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    return token_data


# ---------- Google OAuth (direct ID-token from frontend) ----------

@router.post("/google", response_model=Token, responses={400: {"description": "Invalid Google token or inactive user"}, 403: {"description": "No VocalMind account for this email"}})
async def google_auth(
    token: str = Query(..., description="The Google ID token received from the frontend Google sign-in."),
    response: Response = None,
    session: SessionDep = None,
) -> Any:
    """
    Log in an existing user with a Google ID token and return a bearer access token.
    Never creates accounts: the email must belong to a user a manager already added.
    """
    google_user = verify_google_token(token)
    if not google_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Google token")

    result = await session.exec(select(UserModel).where(UserModel.email == google_user.email))
    user = result.first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No VocalMind account for this email; ask your manager to add you.",
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    token_data = _create_token(user.id)
    response.set_cookie(
        key="vocalmind_token",
        value=token_data["access_token"],
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    return token_data


@router.post("/logout")
async def logout(response: Response):
    """
    Log out the currently authenticated user by deleting the vocalmind_token cookie.
    """
    response.delete_cookie(key="vocalmind_token", httponly=True, samesite="lax")
    return {"message": "Logged out successfully"}
