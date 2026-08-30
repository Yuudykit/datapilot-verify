from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from datapilot_verify.agent import build_graph, build_live_tool_loop
from datapilot_verify.app import build_registry
from datapilot_verify.config import get_settings
from datapilot_verify.tools import ToolContext
from webapp.desktop import normalize_live_result

ROOT = Path(__file__).resolve().parents[1]
API_WORKSPACE = ROOT / "artifacts" / "api-workspace"
API_OUTPUT = ROOT / "artifacts" / "api-output"
API_WORKSPACE.mkdir(parents=True, exist_ok=True)
API_OUTPUT.mkdir(parents=True, exist_ok=True)


def _ensure_sample_workspace() -> None:
    # API 的分析、上传、证据、重放统一使用 api-workspace 数据面；
    # 无数据时用内置样例补齐，保证首次请求即可运行（BUG-023）。
    for name in ("orders.csv", "stores.csv"):
        target = API_WORKSPACE / name
        if not target.is_file():
            shutil.copy2(ROOT / "data" / "sample" / name, target)


_ensure_sample_workspace()
GRAPH = build_graph(ROOT)
GRAPH.context = ToolContext("api", API_WORKSPACE, API_OUTPUT)
REGISTRY = build_registry(ROOT)
app = FastAPI(title="DataPilot Verify API", version="0.1.0")


class AnalyzeRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    metric_choice: str | None = None
    thread_id: str | None = None


class SnapshotRequest(BaseModel):
    snapshot_id: str = Field(min_length=3, max_length=100)


def _context() -> ToolContext:
    return ToolContext("api", API_WORKSPACE, API_OUTPUT)


@app.get("/api/health")
def health() -> dict[str, str | bool]:
    return {"ok": True, "service": "datapilot-verify", "mode": "langgraph-offline"}


@app.post("/api/analyze")
def analyze(request: AnalyzeRequest) -> dict:
    return GRAPH.invoke(
        request.question,
        metric_choice=request.metric_choice,
        thread_id=request.thread_id,
    )


@app.post("/api/agent")
def agent(request: AnalyzeRequest) -> dict:
    settings = get_settings()
    if settings.llm_mode == "mock":
        return analyze(request)
    if not settings.llm_api_key:
        raise HTTPException(status_code=503, detail="DATAPILOT_LLM_API_KEY is required")
    loop = build_live_tool_loop(
        ROOT,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        max_steps=settings.max_tool_steps,
        workspace=API_WORKSPACE,
        output_dir=API_OUTPUT,
    )
    return normalize_live_result(
        request.question, loop.run(request.question), API_WORKSPACE, API_OUTPUT
    )


@app.post("/api/evidence")
def evidence(request: SnapshotRequest) -> dict:
    result = REGISTRY.execute("get_evidence", request.model_dump(), _context())
    return result.model_dump(mode="json")


@app.post("/api/replay")
def replay(request: SnapshotRequest) -> dict:
    result = REGISTRY.execute("replay_analysis", request.model_dump(), _context())
    return result.model_dump(mode="json")


@app.post("/api/report")
def report(request: SnapshotRequest) -> dict:
    result = REGISTRY.execute("export_report", request.model_dump(), _context())
    return result.model_dump(mode="json")


@app.post("/api/datasets")
async def upload_dataset(file: Annotated[UploadFile, File()]) -> dict:
    suffix = Path(file.filename or "").suffix.casefold()
    if suffix not in {".csv", ".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="only CSV/XLSX/XLS files are supported")
    safe_name = f"{uuid.uuid4().hex[:10]}_{Path(file.filename or 'dataset').name}"
    target = API_WORKSPACE / safe_name
    with target.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)
    context = ToolContext("api", API_WORKSPACE, API_OUTPUT)
    result = REGISTRY.execute("register_dataset", {"path": safe_name}, context)
    if not result.ok:
        detail = result.error.message if result.error else "registration failed"
        raise HTTPException(status_code=400, detail=detail)
    return result.model_dump(mode="json")
