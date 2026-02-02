import asyncio
import json
from typing import Any, Dict, Set

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

router = APIRouter(tags=["realtime"])

_subscribers: Set[asyncio.Queue] = set()


async def broadcast(event_type: str, payload: Dict[str, Any]) -> None:
    dead = []
    for q in _subscribers:
        try:
            q.put_nowait({"event": event_type, "data": payload})
        except Exception:
            dead.append(q)

    for q in dead:
        _subscribers.discard(q)


@router.get("/events")
async def sse_events():
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers.add(queue)

    async def generator():
        try:
            while True:
                msg = await queue.get()
                yield {
                    "event": msg["event"],
                    "data": json.dumps(msg["data"], ensure_ascii=False),
                }
        except asyncio.CancelledError:
            pass
        finally:
            _subscribers.discard(queue)

    return EventSourceResponse(generator())