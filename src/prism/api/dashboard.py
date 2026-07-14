import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from prism.config import settings
from prism.core.analytics import get_dashboard_data
from prism.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])
_basic = HTTPBasic(auto_error=False)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def require_admin_basic(
    credentials: HTTPBasicCredentials | None = Depends(_basic),
) -> None:
    if credentials is None or credentials.password != settings.admin_secret:
        raise HTTPException(
            status_code=401,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


@router.get("/dashboard", dependencies=[Depends(require_admin_basic)])
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    data = await get_dashboard_data(db)
    data_json = json.dumps(data).replace("</", "<\\/")
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"data": data, "data_json": data_json},
    )
