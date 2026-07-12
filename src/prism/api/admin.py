import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prism.config import settings
from prism.core.security import generate_api_key
from prism.db.models import ApiKey, Team
from prism.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])
_bearer = HTTPBearer()


def require_admin(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> None:
    if credentials.credentials != settings.admin_secret:
        raise HTTPException(status_code=401, detail="Invalid admin secret")


class CreateTeamRequest(BaseModel):
    name: str
    monthly_budget_usd: float = 50.0


class CreateKeyRequest(BaseModel):
    team_id: uuid.UUID
    rate_limit_rpm: int = 60


@router.post("/teams", status_code=201, dependencies=[Depends(require_admin)])
async def create_team(
    body: CreateTeamRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    team = Team(name=body.name, monthly_budget_usd=body.monthly_budget_usd)
    db.add(team)
    await db.commit()
    await db.refresh(team)
    return {"id": str(team.id), "name": team.name}


@router.post("/keys", status_code=201, dependencies=[Depends(require_admin)])
async def create_key(
    body: CreateKeyRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    result = await db.execute(select(Team).where(Team.id == body.team_id))
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")

    raw_key, key_hash, key_prefix = generate_api_key()
    api_key = ApiKey(
        team_id=body.team_id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        rate_limit_rpm=body.rate_limit_rpm,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    return {"id": str(api_key.id), "key": raw_key, "key_prefix": key_prefix}


@router.delete("/keys/{key_id}", dependencies=[Depends(require_admin)])
async def revoke_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=404, detail="Key not found")

    api_key.is_active = False
    api_key.revoked_at = datetime.now(UTC)
    await db.commit()
    return {"revoked": True}
