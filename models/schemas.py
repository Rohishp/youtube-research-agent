# models/schemas.py
#
# Pydantic models for the full pipeline.
# ResearchBrief is the output of Agent 1 and the input to Agent 2.
# VideoScript is the output of Agent 2.
#
# This file is the contract between agents.
# If you change a field here, both agents are affected.

from pydantic import BaseModel, Field
from typing import Optional


# ─────────────────────────────────────────────────────────────
# RESEARCH AGENT OUTPUT (Agent 1)
# ─────────────────────────────────────────────────────────────

class VideoMetadata(BaseModel):
    """One YouTube video returned by the search tool."""
    video_id: str
    title: str
    channel_name: str
    view_count: int
    like_count: int
    comment_count: int
    published_at: str
    duration: str
    description: str


class ContentGap(BaseModel):
    """A topic or angle that is underserved in the niche."""
    gap_title: str
    explanation: str
    estimated_demand: str               # "high" / "medium" / "low"
    suggested_video_title: str


class VideoIdea(BaseModel):
    """A concrete video idea with hook and structure."""
    title: str
    hook: str
    target_emotion: str
    estimated_search_volume: str
    competition_level: str
    why_it_will_work: str


class ToneProfile(BaseModel):
    """The dominant communication style of top performers in this niche."""
    dominant_style: str
    pacing: str
    visual_style: str
    common_hooks: list[str]
    words_to_use: list[str]
    words_to_avoid: list[str]


class ResearchBrief(BaseModel):
    """
    Full output of the Research Agent.
    This is serialized to JSON and passed directly as input to the Script Agent.
    The script agent reads every field — especially content_gaps, video_ideas,
    and tone_profile — to make decisions about what to write.
    """
    niche: str
    opportunity_score: int = Field(..., ge=1, le=10)
    opportunity_score_reasoning: str
    top_videos_analyzed: list[VideoMetadata]
    key_themes: list[str]
    content_gaps: list[ContentGap]
    video_ideas: list[VideoIdea]
    tone_profile: ToneProfile
    recommended_video_length: str
    best_upload_days: list[str]
    summary: str


# ─────────────────────────────────────────────────────────────
# SCRIPT AGENT OUTPUT (Agent 2)
# ─────────────────────────────────────────────────────────────

class ScriptSection(BaseModel):
    """
    One section of the video script.
    Every section has the words to say AND directions for what to show.
    Visual direction is important — YouTube is a visual medium.
    """
    section_type: str = Field(
        ...,
        description="One of: hook, problem, agitation, solution_preview, main_point, evidence, story, cta"
    )
    title: str                          # Internal label e.g. "The Counterintuitive Truth"
    script: str                         # The actual words spoken on camera
    duration_seconds: int               # Estimated speaking time at natural pace
    visual_direction: str               # What is on screen while this plays
    b_roll_notes: str                   # Specific B-roll footage to source


class SEOPackage(BaseModel):
    """Everything needed to publish and rank the video."""
    title: str                          # Primary title — specific, with number or claim
    title_variants: list[str]           # 2 alternative titles to A/B test
    description: str                    # Full YouTube description (first 150 chars matter most)
    tags: list[str]                     # 10-15 tags
    thumbnail_concept: str              # Specific visual: "Close-up face, shocked expression,
                                        # red clock in background, text: 'I WASTED 30 DAYS'"
    thumbnail_text: str                 # The 3-5 words on the thumbnail


class VideoScript(BaseModel):
    """
    Full output of the Script Writing Agent.
    This is a production-ready script — a creator can pick this up and film.
    
    The connection back to the research brief is explicit:
    - addresses_gap: which ContentGap this video fills
    - based_on_idea: which VideoIdea this was derived from
    This makes the pipeline traceable — you can see why each creative decision was made.
    """
    niche: str
    addresses_gap: str                  # The gap_title from ResearchBrief.content_gaps
    based_on_idea: str                  # The title from ResearchBrief.video_ideas

    hook_statement: str                 # The single opening line — first words out of mouth
    estimated_duration_minutes: float
    word_count: int

    sections: list[ScriptSection]
    seo: SEOPackage

    production_notes: str               # Equipment, lighting, editing style suggestions
    pattern_interrupt_moments: list[str] # Timestamps where energy/format should shift
    rewatch_hook: str                   # A mystery or open loop that makes people rewatch
