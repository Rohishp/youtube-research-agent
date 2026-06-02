# tools/youtube_search.py
#
# This file handles everything related to the YouTube Data API v3.
# The agent calls this when it needs to discover videos in a niche.
#
# To get a YouTube API key:
# 1. Go to console.cloud.google.com
# 2. Create a project
# 3. Enable "YouTube Data API v3"
# 4. Create credentials -> API key
# Free quota: 10,000 units/day. A search costs 100 units. You get 100 searches/day free.

import os
import requests
from models.schemas import VideoMetadata


YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


def search_youtube(query: str, max_results: int = 10) -> dict:
    """
    Search YouTube for videos matching a query.
    Returns video metadata including stats.

    This is what the agent calls when it wants to understand
    what's already ranking in a niche.
    """
    if not YOUTUBE_API_KEY:
        raise ValueError("YOUTUBE_API_KEY not set in environment")

    # Step 1: Search for video IDs
    search_params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max_results,
        "order": "relevance",           # Most relevant first
        "videoDuration": "medium",      # 4-20 minutes (skip shorts and hour-longs)
        "key": YOUTUBE_API_KEY,
    }

    search_response = requests.get(YOUTUBE_SEARCH_URL, params=search_params)
    search_response.raise_for_status()
    search_data = search_response.json()

    if "error" in search_data:
        return {"error": search_data["error"]["message"], "videos": []}

    # Extract video IDs from search results
    video_ids = [item["id"]["videoId"] for item in search_data.get("items", [])]

    if not video_ids:
        return {"error": "No videos found for this query", "videos": []}

    # Step 2: Get detailed stats for those video IDs
    # The search endpoint doesn't return view counts - we need the videos endpoint
    stats_params = {
        "part": "statistics,contentDetails,snippet",
        "id": ",".join(video_ids),
        "key": YOUTUBE_API_KEY,
    }

    stats_response = requests.get(YOUTUBE_VIDEOS_URL, params=stats_params)
    stats_response.raise_for_status()
    stats_data = stats_response.json()

    # Step 3: Combine search results with stats
    videos = []
    for item in stats_data.get("items", []):
        stats = item.get("statistics", {})
        snippet = item.get("snippet", {})
        content = item.get("contentDetails", {})

        video = VideoMetadata(
            video_id=item["id"],
            title=snippet.get("title", ""),
            channel_name=snippet.get("channelTitle", ""),
            view_count=int(stats.get("viewCount", 0)),
            like_count=int(stats.get("likeCount", 0)),
            comment_count=int(stats.get("commentCount", 0)),
            published_at=snippet.get("publishedAt", ""),
            duration=content.get("duration", ""),  # ISO 8601 format e.g. PT8M30S
            description=snippet.get("description", "")[:500],  # First 500 chars
        )
        videos.append(video)

    # Sort by view count descending - most viewed first
    videos.sort(key=lambda v: v.view_count, reverse=True)

    return {
        "query": query,
        "total_found": len(videos),
        "videos": [v.model_dump() for v in videos],
    }
