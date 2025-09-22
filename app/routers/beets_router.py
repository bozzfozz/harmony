import subprocess

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.utils.logging_config import get_logger

router = APIRouter()
logger = get_logger("beets_router")


@router.post("/import")
async def import_music(path: str) -> dict:
    try:
        result = await run_in_threadpool(
            subprocess.run,
            ["beet", "import", path],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
        return {"status": "success", "output": result.stdout}
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Beets import failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
