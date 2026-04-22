from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.deps import require_api_user

router = APIRouter(prefix="/v1/debug", tags=["Debug"])

PROJECT_ROOT = Path(__file__).resolve().parents[2]

LOG_SOURCES: dict[str, tuple[str, Path]] = {
    "backend": ("后端主日志", PROJECT_ROOT / "backend.log"),
    "backend_runtime": ("后端运行日志", PROJECT_ROOT / "backend.runtime.log"),
    "frontend_runtime": ("前端运行日志", PROJECT_ROOT / "frontend" / "frontend.runtime.log"),
}


class LogSourceInfo(BaseModel):
    id: str
    label: str
    path: str
    exists: bool
    size_bytes: int
    modified_at: str | None = None


class RuntimeLogsResponse(BaseModel):
    source: LogSourceInfo
    lines: list[str]
    line_count: int
    max_lines: int
    truncated: bool
    read_at: str


@router.get("/log-sources")
def list_log_sources(current_user=Depends(require_api_user)) -> dict[str, list[LogSourceInfo]]:
    del current_user
    return {"sources": [_describe_source(source_id, label, path) for source_id, (label, path) in LOG_SOURCES.items()]}


@router.get("/logs", response_model=RuntimeLogsResponse)
def get_runtime_logs(
    source: str = Query("backend_runtime", description="日志来源 ID"),
    lines: int = Query(300, ge=1, le=2000, description="读取最后 N 行"),
    level: Literal["all", "error", "warning", "info"] = Query("all", description="日志级别过滤"),
    current_user=Depends(require_api_user),
) -> RuntimeLogsResponse:
    del current_user
    if source not in LOG_SOURCES:
        raise HTTPException(status_code=404, detail="未知日志来源")

    label, path = LOG_SOURCES[source]
    source_info = _describe_source(source, label, path)
    raw_lines = _tail_file(path, max_lines=lines)
    filtered_lines = _filter_lines(raw_lines, level)
    return RuntimeLogsResponse(
        source=source_info,
        lines=filtered_lines,
        line_count=len(filtered_lines),
        max_lines=lines,
        truncated=len(raw_lines) >= lines,
        read_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/logs/stream")
def stream_runtime_logs(
    source: str = Query("backend_runtime", description="日志来源 ID"),
    lines: int = Query(100, ge=0, le=2000, description="连接后先推送最后 N 行"),
    level: Literal["all", "error", "warning", "info"] = Query("all", description="日志级别过滤"),
    current_user=Depends(require_api_user),
) -> StreamingResponse:
    del current_user
    if source not in LOG_SOURCES:
        raise HTTPException(status_code=404, detail="未知日志来源")

    label, path = LOG_SOURCES[source]

    async def event_generator():
        last_size = path.stat().st_size if path.exists() and path.is_file() else 0
        if lines > 0:
            for line in _filter_lines(_tail_file(path, max_lines=lines), level):
                yield _sse_pack("log", {"line": line, "source": source, "initial": True})

        yield _sse_pack("ready", {"source": source, "label": label, "path": str(path.relative_to(PROJECT_ROOT))})

        while True:
            if not path.exists() or not path.is_file():
                yield _sse_pack("status", {"source": source, "message": "日志文件不存在，等待创建"})
                await asyncio.sleep(1)
                continue

            current_size = path.stat().st_size
            if current_size < last_size:
                last_size = 0

            if current_size > last_size:
                with path.open("rb") as file:
                    file.seek(last_size)
                    chunk = file.read(current_size - last_size)
                last_size = current_size
                for line in _filter_lines(chunk.decode("utf-8", errors="replace").splitlines(), level):
                    yield _sse_pack("log", {"line": line, "source": source, "initial": False})
            else:
                yield ": ping\n\n"

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _describe_source(source_id: str, label: str, path: Path) -> LogSourceInfo:
    exists = path.exists() and path.is_file()
    stat = path.stat() if exists else None
    return LogSourceInfo(
        id=source_id,
        label=label,
        path=str(path.relative_to(PROJECT_ROOT)),
        exists=exists,
        size_bytes=stat.st_size if stat else 0,
        modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat() if stat else None,
    )


def _tail_file(path: Path, max_lines: int) -> list[str]:
    if not path.exists() or not path.is_file():
        return []

    chunk_size = 8192
    chunks: list[bytes] = []
    line_breaks = 0
    with path.open("rb") as file:
        file.seek(0, 2)
        position = file.tell()
        while position > 0 and line_breaks <= max_lines:
            read_size = min(chunk_size, position)
            position -= read_size
            file.seek(position)
            chunk = file.read(read_size)
            chunks.append(chunk)
            line_breaks += chunk.count(b"\n")

    content = b"".join(reversed(chunks)).decode("utf-8", errors="replace")
    return content.splitlines()[-max_lines:]


def _filter_lines(lines: list[str], level: str) -> list[str]:
    if level == "all":
        return lines
    keywords = {
        "error": ("ERROR", "Error", "error", "失败", "Traceback", "Exception"),
        "warning": ("WARNING", "Warning", "warning", "WARN", "告警", "警告"),
        "info": ("INFO", "Info", "info"),
    }[level]
    return [line for line in lines if any(keyword in line for keyword in keywords)]


def _sse_pack(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
