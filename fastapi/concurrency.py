from __future__ import annotations

import asyncio
from functools import partial
from typing import Any


async def run_in_threadpool(func, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - thin wrapper
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


__all__ = ["run_in_threadpool"]
