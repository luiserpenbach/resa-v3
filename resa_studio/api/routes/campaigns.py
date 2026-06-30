"""Campaign runner endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from resa_studio.adapters.campaign_service import CampaignService

router = APIRouter(prefix="/campaigns", tags=["campaigns"])
_campaigns = CampaignService()


class CampaignRunBody(BaseModel):
    campaign_path: str


@router.get("/list")
def list_campaigns() -> list[dict[str, str]]:
    return _campaigns.list_campaigns()


@router.post("/run")
def run_campaign(body: CampaignRunBody) -> dict[str, Any]:
    try:
        return _campaigns.run(body.campaign_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
