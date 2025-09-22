"""Soulseek API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.soulseek_client import SoulseekClient, SoulseekClientError
from app.dependencies import get_soulseek_client
from app.schemas import (
    SoulseekCancelResponse,
    SoulseekDownloadRequest,
    SoulseekDownloadStatus,
    SoulseekSearchRequest,
    StatusResponse,
)

router = APIRouter()


@router.get("/status", response_model=StatusResponse)
async def soulseek_status(client: SoulseekClient = Depends(get_soulseek_client)) -> StatusResponse:
    try:
        await client.get_download_status()
    except Exception:
        return StatusResponse(status="disconnected")
    return StatusResponse(status="connected")


@router.post("/search")
async def soulseek_search(
    payload: SoulseekSearchRequest,
    client: SoulseekClient = Depends(get_soulseek_client),
):
    return await client.search(payload.query)


@router.post("/download")
async def soulseek_download(
    payload: SoulseekDownloadRequest,
    client: SoulseekClient = Depends(get_soulseek_client),
):
    try:
        return await client.download(payload.model_dump())
    except (ValueError, SoulseekClientError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/downloads", response_model=SoulseekDownloadStatus)
async def soulseek_downloads(client: SoulseekClient = Depends(get_soulseek_client)) -> SoulseekDownloadStatus:
    response = await client.get_download_status()
    downloads = response.get("downloads") if isinstance(response, dict) else None
    if isinstance(downloads, list):
        return SoulseekDownloadStatus(downloads=downloads)
    if isinstance(response, list):
        return SoulseekDownloadStatus(downloads=response)
    return SoulseekDownloadStatus(downloads=[response] if response else [])


@router.delete("/download/{download_id}", response_model=SoulseekCancelResponse)
async def soulseek_cancel(
    download_id: str,
    client: SoulseekClient = Depends(get_soulseek_client),
) -> SoulseekCancelResponse:
    try:
        await client.cancel_download(download_id)
    except SoulseekClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SoulseekCancelResponse(cancelled=True)
