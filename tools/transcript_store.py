# tools/transcript_store.py
#
# Saves fetched transcripts to disk so the RAG agent can ingest them.
#
# ── WHY THIS FILE EXISTS ──────────────────────────────────────────────────────
# The research agent fetches full transcripts to generate briefs.
# Previously those transcripts were used once then discarded.
# This file intercepts them and saves them permanently.
#
# After this change, every research run builds your RAG knowledge base.
# Run 5 niches through the research agent → 15-25 real transcripts saved →
# RAG agent has genuine knowledge to retrieve from.
#
# ── WHERE FILES ARE SAVED ─────────────────────────────────────────────────────
# output/transcripts/{video_id}.json
#
# Each file contains:
# - video_id, transcript text, niche (if known), fetch timestamp
#
# The RAG agent's ingest.py reads from this folder with:
#   python ingest.py --from-transcripts ../youtube_research_agent/output/transcripts/
# ─────────────────────────────────────────────────────────────────────────────

import json
from pathlib import Path
from datetime import datetime


TRANSCRIPTS_DIR = Path("output/transcripts")


def save_transcript(transcript_result: dict, niche: str = "unknown") -> str | None:
    """
    Save a transcript result dict to disk.

    Parameters
    ----------
    transcript_result : dict
        The dict returned by get_transcript() — must have 'video_id' and 'transcript' keys
    niche : str
        The niche being researched when this transcript was fetched.
        Used by the RAG indexer to categorise the content.

    Returns
    -------
    str | None
        Path where the file was saved, or None if skipped/failed.
    """
    video_id = transcript_result.get("video_id")
    transcript_text = transcript_result.get("transcript")

    # Don't save if no transcript content
    if not video_id or not transcript_text:
        return None

    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = TRANSCRIPTS_DIR / f"{video_id}.json"

    # If file exists, check if it has a proper niche — update it if not
    if file_path.exists():
        try:
            with open(file_path, encoding="utf-8") as f:
                existing = json.load(f)
            # Only skip if the existing file already has a real niche
            if existing.get("niche") not in (None, "unknown", ""):
                return str(file_path)
            # Otherwise fall through and overwrite with correct niche
        except Exception:
            pass  # Corrupted file — overwrite it

    data = {
        "video_id": video_id,
        "transcript": transcript_text,
        "niche": niche,
        "char_count": transcript_result.get("char_count", len(transcript_text)),
        "is_truncated": transcript_result.get("is_truncated", False),
        "saved_at": datetime.now().isoformat(),
    }

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"  [Saved] Transcript → {file_path}")
    return str(file_path)
