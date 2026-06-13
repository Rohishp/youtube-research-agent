# control_plane/state.py
#
# The unified state object for the pipeline.
#
# ── WHAT THIS REPLACES ────────────────────────────────────────────────────────
# Before: state lived in 4+ separate variables
#   brief = ResearchBrief(...)
#   script = VideoScript(...)
#   quality_report = {...}
#   tracer = Tracer(...)
#
# After: one object carries everything
#   state = PipelineState(niche="morning routines")
#   state.research_brief = ...
#   state.video_script = ...
#   state.gate_history.append(...)
#   save_state(state)  ← one file, everything preserved
#
# ── WHY THIS MATTERS ─────────────────────────────────────────────────────────
# 1. Resumability — save after each stage, reload after crash
# 2. Inspectability — one JSON shows entire run status
# 3. API compatibility — GET /pipeline/run_id returns state.model_dump()
# ─────────────────────────────────────────────────────────────────────────────

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Literal
from pydantic import BaseModel, Field
from models.schemas import ResearchBrief, VideoScript


# ── Status flow ───────────────────────────────────────────────────────────────
# created → researching → research_complete → scripting → evaluating →
#   → improving → evaluating → completed
#                              │
#   → stopped (gate killed it)
#   → failed (unexpected error)
# ─────────────────────────────────────────────────────────────────────────────

PipelineStatus = Literal[
    "created",
    "researching",
    "research_complete",
    "scripting",
    "evaluating",
    "improving",
    "completed",
    "stopped",
    "failed",
]


class GateDecisionRecord(BaseModel):
    """Record of a single gate decision."""
    gate: str                   # "niche_gate" or "script_gate"
    attempt: int
    action: str                 # "proceed", "retry", "stop"
    reason: str
    detail: str = ""
    eval_score: Optional[int] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class StageTimingRecord(BaseModel):
    """Timing and cost for one pipeline stage."""
    stage: str
    attempt: int
    duration_seconds: float = 0.0
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0
    tool_calls: list[dict] = Field(default_factory=list)


class PipelineState(BaseModel):
    """
    The single source of truth for a pipeline run.

    Every component reads from this and writes to this.
    This is the whiteboard — the shared reality of the system.

    If saved to disk between stages, the pipeline can resume
    from where it stopped after a crash.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    run_id: str = Field(
        default_factory=lambda: f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    )
    niche: str
    status: PipelineStatus = "created"
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    # ── Research stage ────────────────────────────────────────────────────────
    research_brief: Optional[ResearchBrief] = None
    research_attempts: int = 0
    research_query_used: Optional[str] = None   # Tracks if we broadened the query

    # ── Script stage ──────────────────────────────────────────────────────────
    video_script: Optional[VideoScript] = None
    script_attempts: int = 0

    # ── Evaluation ────────────────────────────────────────────────────────────
    eval_score: Optional[int] = None
    eval_breakdown: Optional[dict] = None       # Full scoring breakdown
    eval_feedback: Optional[str] = None         # Formatted feedback for improvement agent

    # ── Gate history ──────────────────────────────────────────────────────────
    gate_history: list[GateDecisionRecord] = Field(default_factory=list)

    # ── Observability ─────────────────────────────────────────────────────────
    stage_timings: list[StageTimingRecord] = Field(default_factory=list)
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    total_cost_usd: float = 0.0
    duration_seconds: float = 0.0

    # ── Warnings and errors ───────────────────────────────────────────────────
    warnings: list[str] = Field(default_factory=list)
    error: Optional[str] = None

    # ── Convenience methods ───────────────────────────────────────────────────

    def record_gate_decision(
        self,
        gate: str,
        attempt: int,
        action: str,
        reason: str,
        detail: str = "",
        eval_score: int = None,
    ):
        """Record a gate decision into state history."""
        self.gate_history.append(GateDecisionRecord(
            gate=gate,
            attempt=attempt,
            action=action,
            reason=reason,
            detail=detail,
            eval_score=eval_score,
        ))

    def add_warning(self, warning: str):
        """Record a quality warning."""
        self.warnings.append(warning)

    def set_error(self, error: str):
        """Mark the pipeline as failed with an error message."""
        self.status = "failed"
        self.error = error

    @property
    def is_terminal(self) -> bool:
        """Has the pipeline reached a final state?"""
        return self.status in ("completed", "stopped", "failed")

    @property
    def summary(self) -> dict:
        """Compact summary for API responses and logging."""
        return {
            "run_id": self.run_id,
            "niche": self.niche,
            "status": self.status,
            "opportunity_score": self.research_brief.opportunity_score if self.research_brief else None,
            "eval_score": self.eval_score,
            "video_title": self.video_script.seo.title if self.video_script else None,
            "research_attempts": self.research_attempts,
            "script_attempts": self.script_attempts,
            "total_cost_usd": round(self.total_cost_usd, 4),
            "duration_seconds": round(self.duration_seconds, 2),
            "warnings": self.warnings,
            "error": self.error,
        }


# ── Persistence ───────────────────────────────────────────────────────────────
# Save and load state from disk.
# This is what enables resumability — save after each stage,
# reload if the process crashes.

STATES_DIR = Path("output/states")


def save_state(state: PipelineState) -> Path:
    """
    Save pipeline state to disk as JSON.
    Called after every stage transition.
    """
    STATES_DIR.mkdir(parents=True, exist_ok=True)
    path = STATES_DIR / f"{state.run_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state.model_dump(), f, indent=2, ensure_ascii=False, default=str)
    return path


def load_state(run_id: str) -> PipelineState:
    """
    Load pipeline state from disk.
    Used to resume a crashed pipeline or to serve API requests.
    """
    path = STATES_DIR / f"{run_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"No state found for run: {run_id}")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return PipelineState(**data)


def list_states(last_n: int = None) -> list[dict]:
    """
    List all saved pipeline states as summaries.
    Useful for the dashboard and API listing endpoints.
    """
    if not STATES_DIR.exists():
        return []

    files = sorted(STATES_DIR.glob("*.json"), reverse=True)
    if last_n:
        files = files[:last_n]

    summaries = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)
            state = PipelineState(**data)
            summaries.append(state.summary)
        except Exception:
            pass

    return summaries
