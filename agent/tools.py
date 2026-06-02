# agent/tools.py
#
# Tool schemas tell the model what tools exist and how to call them.
#
# ── KEY DIFFERENCE vs Anthropic API ──────────────────────────────────────────
# Anthropic format:
#   {
#     "name": "search_youtube",
#     "description": "...",
#     "input_schema": { "type": "object", "properties": {...} }
#   }
#
# OpenAI format:
#   {
#     "type": "function",          ← required wrapper
#     "function": {
#       "name": "search_youtube",
#       "description": "...",
#       "parameters": {            ← called "parameters" not "input_schema"
#         "type": "object",
#         "properties": {...}
#       }
#     }
#   }
#
# The actual content — name, description, properties — is identical.
# Only the wrapper structure changes.
# ─────────────────────────────────────────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_youtube",
            "description": """Search YouTube for videos matching a query and return metadata including
            view counts, like counts, and descriptions. Use this to discover what content is already
            performing well in a niche. Run multiple searches with different query variations to get
            a comprehensive picture. Always start broad, then narrow down.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query. Use natural language like a real YouTube user would search. Examples: 'morning routine for productivity', 'morning routine mistakes beginners make'"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Number of videos to return. Use 10 for broad searches, 5 for narrow follow-up searches.",
                        "default": 10
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_transcript",
            "description": """Fetch the full transcript (subtitles) of a YouTube video given its video ID.
            Use this to understand what top creators are actually saying — their hooks, structure,
            language patterns, and how they deliver value. This reveals far more than titles and
            descriptions alone. Get transcripts for the top 3-5 most-viewed videos you find.""",
            "parameters": {
                "type": "object",
                "properties": {
                    "video_id": {
                        "type": "string",
                        "description": "The YouTube video ID — the part after 'v=' in a YouTube URL. Example: if URL is youtube.com/watch?v=dQw4w9WgXcQ, the video_id is 'dQw4w9WgXcQ'"
                    }
                },
                "required": ["video_id"]
            }
        }
    }
]
