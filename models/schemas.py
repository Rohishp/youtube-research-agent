# models/schemas.py
#
# Pydantic models define the SHAPE of data flowing through the agent.
# This is important: when an agent produces output, you want a guarantee
# about what fields exist, what types they are, and whether they're valid.
# Without this, you're just hoping the model returns something useful.

from pydantic import BaseModel, Field
from typing import Optional


class VideoMetadata(BaseModel):
    """Represents one YouTube video returned by the search tool."""
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
    """A specific topic or angle that is underserved in the niche."""
    gap_title: str
    explanation: str                    # Why this gap exists
    estimated_demand: str               # "high" / "medium" / "low"
    suggested_video_title: str          # Concrete video idea to fill it


class VideoIdea(BaseModel):
    """A concrete video idea with a hook and structure."""
    title: str
    hook: str                           # First 30 seconds - what grabs attention
    target_emotion: str                 # What the viewer feels: curiosity, fear, hope
    estimated_search_volume: str        # "high" / "medium" / "low"
    competition_level: str              # "high" / "medium" / "low"
    why_it_will_work: str


class ToneProfile(BaseModel):
    """The dominant communication style of top performers in this niche."""
    dominant_style: str                 # e.g., "authoritative", "conversational", "motivational"
    pacing: str                         # e.g., "fast-cut", "slow-deliberate"
    visual_style: str                   # e.g., "talking head", "b-roll heavy"
    common_hooks: list[str]             # Recurring opening patterns
    words_to_use: list[str]             # Language that resonates in this niche
    words_to_avoid: list[str]           # Language that feels off


class ResearchBrief(BaseModel):
    """
    The final output of the research agent.
    This is what gets saved to disk and used by the script writing agent later.
    """
    niche: str
    opportunity_score: int = Field(..., ge=1, le=10)  # 1-10, enforced by Pydantic
    opportunity_score_reasoning: str

    top_videos_analyzed: list[VideoMetadata]

    key_themes: list[str]               # What topics dominate this niche
    content_gaps: list[ContentGap]      # Where the opportunity actually is
    video_ideas: list[VideoIdea]        # Ready-to-use video concepts
    tone_profile: ToneProfile

    recommended_video_length: str       # e.g., "8-12 minutes"
    best_upload_days: list[str]         # Based on engagement patterns
    summary: str                        # 2-3 sentence executive summary
