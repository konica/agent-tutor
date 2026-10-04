"""Learner profile routes (accounts module)."""

from fastapi import APIRouter
from pydantic import BaseModel

from smart_tutor.apps.api.deps import CurrentPrincipal

router = APIRouter(tags=["accounts"])


class MeResponse(BaseModel):
    user_id: str
    name: str
    roles: list[str]


@router.get("/me", operation_id="get_me")
async def get_me(principal: CurrentPrincipal) -> MeResponse:
    return MeResponse(user_id=principal.user_id, name=principal.name, roles=sorted(principal.roles))
