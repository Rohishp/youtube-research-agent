# api/app.py
#
# FastAPI layer that exposes the pipeline as a service.
#
# This transforms the project from:
#   python main.py "morning routines"     ← one person, one terminal
# To:
#   POST /pipeline {"niche": "morning routines"}  ← any client, any time
#   GET  /pipeline/run_abc123                      ← check status
#   GET  /pipeline/run_abc123/report               ← view HTML report
#   GET  /pipelines                                ← list all runs
#   GET  /dashboard                                ← performance metrics
#
# ── WHY THIS MATTERS ──────────────────────────────────────────────────────────
# A CLI tool is a demo. A service is a product.
# The difference:
#   - Multiple users can submit requests concurrently
#   - Runs execute in the background — client doesn't wait
#   - Results are retrievable by run ID at any time
#   - Status is checkable while the pipeline is still running
#
# Run it:
#   uvicorn api.app:app --reload --port 8000
#
# Then open: http://localhost:8000/docs  ← interactive API documentation
# ─────────────────────────────────────────────────────────────────────────────

import sys
import json
import threading
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

# Add project root to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from control_plane.state import PipelineState, save_state, load_state, list_states, STATES_DIR
from models.schemas import ResearchBrief


# ── REQUEST / RESPONSE MODELS ────────────────────────────────────────────────
# These define what the API accepts and returns.
# Separate from PipelineState — the API exposes a subset, not everything.

class PipelineRequest(BaseModel):
    """What the client sends to start a pipeline run."""
    niche: str

    class Config:
        json_schema_extra = {
            "example": {
                "niche": "morning routines for entrepreneurs"
            }
        }


class PipelineStartResponse(BaseModel):
    """What the client gets back immediately after starting a run."""
    run_id: str
    niche: str
    status: str
    message: str


class PipelineSummary(BaseModel):
    """Compact summary for list views."""
    run_id: str
    niche: str
    status: str
    opportunity_score: int | None = None
    eval_score: int | None = None
    video_title: str | None = None
    duration_seconds: float = 0.0
    warnings: list[str] = []


# ── BACKGROUND PIPELINE RUNNER ────────────────────────────────────────────────
# The pipeline runs in a background thread so the API responds immediately.
# The client polls GET /pipeline/{run_id} to check progress.

def _run_pipeline_background(niche: str, run_id: str):
    """
    Execute the pipeline in a background thread.

    Why threading instead of async?
    The pipeline uses synchronous OpenAI SDK calls and synchronous file I/O.
    Running it in a thread is simpler than converting everything to async.
    For a production system you'd use a task queue (Celery, RQ) instead.
    """
    from dotenv import load_dotenv
    load_dotenv()

    try:
        from orchestrator import run_pipeline
        from control_plane.state import load_state
        
        # Load the state already created by the API endpoint
        # This ensures the orchestrator uses the SAME run_id
        existing_state = load_state(run_id)
        state = run_pipeline(niche=niche, run_id=run_id)
    except ValueError as e:
        # Gate stopped the pipeline — expected, not an error
        # State is already saved by the orchestrator
        print(f"[API] Pipeline stopped for '{niche}': {e}")
    except Exception as e:
        # Unexpected error — try to save error state
        print(f"[API] Pipeline failed for '{niche}': {e}")
        try:
            state = load_state(run_id)
            state.set_error(str(e))
            save_state(state)
        except Exception:
            pass


# Track running threads so we can report active runs
_active_runs: dict[str, threading.Thread] = {}


# ── APP ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="YouTube Research & Script Pipeline API",
    description="Multi-agent AI pipeline that researches YouTube niches and produces video scripts.",
    version="1.0.0",
)


@app.post("/pipeline", response_model=PipelineStartResponse)
def start_pipeline(request: PipelineRequest):
    """
    Start a new pipeline run.

    Returns immediately with a run_id. The pipeline executes in the background.
    Poll GET /pipeline/{run_id} to check progress.
    """
    # Create initial state and save it so it's immediately queryable
    state = PipelineState(niche=request.niche)
    save_state(state)

    # Start pipeline in background thread
    thread = threading.Thread(
        target=_run_pipeline_background,
        args=(request.niche, state.run_id),
        daemon=True,
    )
    _active_runs[state.run_id] = thread
    thread.start()

    return PipelineStartResponse(
        run_id=state.run_id,
        niche=request.niche,
        status="created",
        message=f"Pipeline started. Poll GET /pipeline/{state.run_id} for status.",
    )


@app.get("/pipeline/{run_id}")
def get_pipeline_status(run_id: str):
    """
    Get the current status of a pipeline run.

    Returns the full state including research brief, script,
    eval scores, gate decisions, and timing.
    """
    try:
        state = load_state(run_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    # Check if thread is still running
    is_running = run_id in _active_runs and _active_runs[run_id].is_alive()

    result = state.summary
    result["is_running"] = is_running

    # Add research brief summary if available
    if state.research_brief:
        result["opportunity_score"] = state.research_brief.opportunity_score
        result["content_gaps"] = len(state.research_brief.content_gaps)
        result["videos_analyzed"] = len(state.research_brief.top_videos_analyzed)

    # Add script info if available
    if state.video_script:
        result["video_title"] = state.video_script.seo.title
        result["script_word_count"] = state.video_script.word_count
        result["script_duration_minutes"] = state.video_script.estimated_duration_minutes

    # Add gate history
    result["gate_decisions"] = [
        {"gate": g.gate, "action": g.action, "reason": g.reason}
        for g in state.gate_history
    ]

    return result


@app.get("/pipeline/{run_id}/state")
def get_full_state(run_id: str):
    """
    Get the complete pipeline state — everything the system knows about this run.
    This is the full whiteboard.
    """
    try:
        state = load_state(run_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    return state.model_dump()


@app.get("/pipeline/{run_id}/report", response_class=HTMLResponse)
def get_pipeline_report(run_id: str):
    """
    Get the HTML report for a completed pipeline run.
    Opens as a visual report in the browser.
    """
    try:
        state = load_state(run_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    if not state.research_brief or not state.video_script:
        raise HTTPException(
            status_code=400,
            detail=f"Run {run_id} has status '{state.status}' — no report available yet."
        )

    # Use the report generator
    from report import generate_report

    # Generate report from state data
    brief_dict = state.research_brief.model_dump()
    script_dict = state.video_script.model_dump()

    # The report generator expects file paths but we have dicts
    # Write temp files — or better, refactor generate_report to accept dicts
    # For now, write temp JSON and generate
    import tempfile, os
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as bf:
        json.dump(brief_dict, bf, ensure_ascii=False)
        brief_path = bf.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as sf:
        json.dump(script_dict, sf, ensure_ascii=False)
        script_path = sf.name

    try:
        html = generate_report(brief_path, script_path)
    finally:
        os.unlink(brief_path)
        os.unlink(script_path)

    return HTMLResponse(content=html)


@app.get("/pipelines")
def list_pipelines(last: int = 20):
    """
    List recent pipeline runs with their status and scores.
    """
    states = list_states(last_n=last)
    return {
        "total": len(states),
        "runs": states,
    }


@app.get("/dashboard")
def get_dashboard():
    """
    Performance metrics across all pipeline runs.
    """
    states = list_states()

    if not states:
        return {"message": "No pipeline runs found.", "total_runs": 0}

    completed = [s for s in states if s["status"] == "completed"]
    stopped   = [s for s in states if s["status"] in ("stopped", "stopped_by_gate")]
    failed    = [s for s in states if s["status"] == "failed"]

    scores = [s["eval_score"] for s in completed if s.get("eval_score")]
    costs  = [s.get("total_cost_usd", 0) for s in states]

    result = {
        "total_runs": len(states),
        "completed": len(completed),
        "stopped": len(stopped),
        "failed": len(failed),
        "total_cost_usd": round(sum(costs), 4),
    }

    if completed:
        result["avg_eval_score"] = round(sum(scores) / len(scores), 1) if scores else None
        result["avg_cost_per_run"] = round(sum(costs) / len(states), 4) if costs else None
        result["best_niche"] = max(completed, key=lambda s: s.get("eval_score", 0)).get("niche")
        result["best_score"] = max(s.get("eval_score", 0) for s in completed)

    result["recent_runs"] = states[:10]

    return result


@app.get("/health")
def health_check():
    """Simple health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}
