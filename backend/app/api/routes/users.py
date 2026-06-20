from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, field_validator

from app.api.deps import CurrentUser, SessionDep
from app.core import security
from app.models.user import User

router = APIRouter()

# Cap the stored avatar payload (~2 MB data URL) so a huge upload can't bloat the row.
_MAX_AVATAR_CHARS = 2_800_000


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    avatar_url: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("Name cannot be empty")
        return value.strip() if value else value

    @field_validator("avatar_url")
    @classmethod
    def _avatar_size(cls, value: Optional[str]) -> Optional[str]:
        if value and len(value) > _MAX_AVATAR_CHARS:
            raise ValueError("Avatar image is too large (max ~2 MB)")
        return value


class PasswordChange(BaseModel):
    current_password: Optional[str] = None
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _strong_enough(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("New password must be at least 8 characters")
        return value


@router.get("/me", response_model=User, responses={401: {"description": "Not authenticated"}, 403: {"description": "Credentials invalid"}})
async def read_user_me(
    current_user: CurrentUser,
) -> Any:
    """
    Get details of the currently authenticated user session.
    """
    return current_user


@router.patch("/me", response_model=User, responses={401: {"description": "Not authenticated"}, 403: {"description": "Credentials invalid"}, 404: {"description": "User profile not found"}})
async def update_user_me(
    body: ProfileUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """
    Update the current user's profile display name and/or avatar URL.
    """
    user = await session.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.name is not None:
        user.name = body.name
    if body.avatar_url is not None:
        # Empty string clears the avatar; otherwise store the provided data URL / URL.
        user.avatar_url = body.avatar_url or None

    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.post("/me/change-password", status_code=status.HTTP_200_OK, responses={401: {"description": "Not authenticated"}, 403: {"description": "Credentials invalid"}, 404: {"description": "User profile not found"}})
async def change_password(
    body: PasswordChange,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict:
    """
    Change the current user's password.

    If the account already has a password set, the correct current_password
    is required. Google-OAuth accounts without a password can set one directly.
    """
    user = await session.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.password_hash:
        if not body.current_password or not security.verify_password(
            body.current_password, user.password_hash
        ):
            raise HTTPException(status_code=400, detail="Current password is incorrect")

    user.password_hash = security.get_password_hash(body.new_password)
    session.add(user)
    await session.commit()
    return {"status": "ok"}
