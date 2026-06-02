# tools/transcript.py
#
# Written against youtube-transcript-api==1.2.4 (verified June 2026)
#
# In this version the API is fully instance-based — no class methods.
# You must instantiate YouTubeTranscriptApi() before calling anything.
#
# The two available methods are:
#   .fetch(video_id, languages=('en',))  → FetchedTranscript (iterable of snippets)
#   .list(video_id)                      → TranscriptList (all available languages)
#
# Each snippet has: snippet.text (str), snippet.start (float), snippet.duration (float)

from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
    CouldNotRetrieveTranscript,
)


def get_transcript(video_id: str, max_chars: int = 8000) -> dict:
    """
    Fetch the transcript for a YouTube video.
    Returns the transcript as a single text string, capped at max_chars.
    """
    # Must instantiate — no class-level methods in v1.x
    ytt = YouTubeTranscriptApi()

    # Try English variants in order of preference
    language_attempts = [
        ('en',),
        ('en-US',),
        ('en-GB',),
        ('en-CA',),
        ('en-AU',),
    ]

    transcript = None

    for languages in language_attempts:
        try:
            transcript = ytt.fetch(video_id, languages=languages)
            break
        except NoTranscriptFound:
            continue
        except TranscriptsDisabled:
            return {
                "video_id": video_id,
                "transcript": None,
                "error": "Transcripts are disabled for this video",
            }
        except CouldNotRetrieveTranscript as e:
            last_error = str(e)
            continue
    # All English variants failed — try whatever language is available
    if transcript is None:
        try:
            transcript_list = ytt.list(video_id)
            # Grab the first available transcript
            for t in transcript_list:
                transcript = ytt.fetch(video_id, languages=(t.language_code,))
                break
        except Exception as e:
            return {
                "video_id": video_id,
                "transcript": None,
                "error": f"No transcript available in any language: {str(e)}",
            }

    if transcript is None:
        return {
            "video_id": video_id,
            "transcript": None,
            "error": "No transcript found",
        }

    # Each snippet has a .text attribute
    full_text = " ".join(snippet.text for snippet in transcript)
    full_text = full_text.replace("\n", " ").replace("[Music]", "").strip()

    if len(full_text) > max_chars:
        full_text = full_text[:max_chars] + "... [truncated]"

    return {
        "video_id": video_id,
        "transcript": full_text,
        "char_count": len(full_text),
        "is_truncated": len(full_text) >= max_chars,
    }
