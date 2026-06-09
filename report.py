#!/usr/bin/env python3
# report.py
#
# Generates a clean HTML report from pipeline output.
# Opens automatically in your browser when done.
#
# Usage:
#   python report.py output/brief_xyz.json output/script_xyz.json
#   python report.py output/brief_xyz.json output/script_xyz.json --no-open

import json
import sys
import argparse
import webbrowser
from pathlib import Path
from datetime import datetime


def generate_report(brief_path: str, script_path: str) -> str:
    """Generate a self-contained HTML report from brief + script JSON files."""

    with open(brief_path, encoding="utf-8") as f:
        brief = json.load(f)
    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    # ── Score colour ──────────────────────────────────────────────────────────
    score = brief.get("opportunity_score", 0)
    score_color = "#22c55e" if score >= 7 else "#f59e0b" if score >= 5 else "#ef4444"

    # ── Content gaps ─────────────────────────────────────────────────────────
    gaps_html = ""
    for gap in brief.get("content_gaps", []):
        demand = gap.get("estimated_demand", "medium")
        demand_color = {"high": "#22c55e", "medium": "#f59e0b", "low": "#94a3b8"}.get(demand, "#94a3b8")
        gaps_html += f"""
        <div class="gap-card">
            <div class="gap-header">
                <span class="gap-title">{gap.get('gap_title', '')}</span>
                <span class="demand-badge" style="background:{demand_color}20;color:{demand_color};border:1px solid {demand_color}40">{demand} demand</span>
            </div>
            <p class="gap-explanation">{gap.get('explanation', '')}</p>
            <div class="suggested-title">💡 {gap.get('suggested_video_title', '')}</div>
        </div>"""

    # ── Video ideas ───────────────────────────────────────────────────────────
    ideas_html = ""
    for idea in brief.get("video_ideas", []):
        comp = idea.get("competition_level", "medium")
        comp_color = {"low": "#22c55e", "medium": "#f59e0b", "high": "#ef4444"}.get(comp, "#94a3b8")
        ideas_html += f"""
        <div class="idea-card">
            <div class="idea-title">{idea.get('title', '')}</div>
            <div class="idea-hook">🎣 {idea.get('hook', '')}</div>
            <div class="idea-meta">
                <span>🎯 {idea.get('target_emotion', '')}</span>
                <span style="color:{comp_color}">⚔️ {comp} competition</span>
                <span>📊 {idea.get('estimated_search_volume', '')} volume</span>
            </div>
            <p class="idea-why">{idea.get('why_it_will_work', '')}</p>
        </div>"""

    # ── Script sections ───────────────────────────────────────────────────────
    sections_html = ""
    section_colors = {
        "hook": "#8b5cf6",
        "problem": "#ef4444",
        "agitation": "#f97316",
        "solution_preview": "#3b82f6",
        "main_points": "#22c55e",
        "main_point": "#22c55e",
        "evidence": "#06b6d4",
        "story": "#8b5cf6",
        "cta": "#f59e0b",
    }
    for i, section in enumerate(script.get("sections", []), 1):
        stype = section.get("section_type", "").lower()
        color = section_colors.get(stype, "#64748b")
        duration = section.get("duration_seconds", 0)
        mins = duration // 60
        secs = duration % 60
        duration_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"

        sections_html += f"""
        <div class="section-card">
            <div class="section-header">
                <div style="display:flex;align-items:center;gap:12px">
                    <span class="section-number">{i}</span>
                    <div>
                        <div class="section-title">{section.get('title', '')}</div>
                        <span class="section-type" style="background:{color}20;color:{color};border:1px solid {color}40">{stype}</span>
                    </div>
                </div>
                <span class="section-duration">⏱ {duration_str}</span>
            </div>
            <div class="script-text">{section.get('script', '').replace(chr(10), '<br>')}</div>
            <div class="direction-box">
                <div class="direction-label">🎬 Visual Direction</div>
                <div>{section.get('visual_direction', '')}</div>
            </div>
            <div class="broll-box">
                <div class="direction-label">📹 B-Roll</div>
                <div>{section.get('b_roll_notes', '')}</div>
            </div>
        </div>"""

    # ── Top videos ────────────────────────────────────────────────────────────
    videos_html = ""
    for video in brief.get("top_videos_analyzed", [])[:5]:
        views = f"{video.get('view_count', 0):,}"
        likes = f"{video.get('like_count', 0):,}"
        videos_html += f"""
        <div class="video-row">
            <a href="https://youtube.com/watch?v={video.get('video_id', '')}" target="_blank" class="video-title-link">
                {video.get('title', '')}
            </a>
            <div class="video-meta">
                <span>📺 {video.get('channel_name', '')}</span>
                <span>👁 {views} views</span>
                <span>👍 {likes} likes</span>
            </div>
        </div>"""

    # ── SEO section ───────────────────────────────────────────────────────────
    seo = script.get("seo", {})
    tags_html = " ".join(f'<span class="tag">{t}</span>' for t in seo.get("tags", []))
    variants_html = "".join(f'<li>{v}</li>' for v in seo.get("title_variants", []))

    # ── Tone profile ─────────────────────────────────────────────────────────
    tone = brief.get("tone_profile", {})
    use_words = " ".join(f'<span class="word-badge use">{w}</span>' for w in tone.get("words_to_use", []))
    avoid_words = " ".join(f'<span class="word-badge avoid">{w}</span>' for w in tone.get("words_to_avoid", []))

    # ── Assemble HTML ─────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pipeline Report: {brief.get('niche', '').title()}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f172a; color: #e2e8f0; line-height: 1.6; }}
  .container {{ max-width: 1000px; margin: 0 auto; padding: 40px 20px; }}

  /* Header */
  .header {{ background: linear-gradient(135deg, #1e293b, #0f172a);
             border: 1px solid #334155; border-radius: 16px;
             padding: 40px; margin-bottom: 32px; }}
  .pipeline-label {{ font-size: 12px; letter-spacing: 2px; color: #64748b;
                     text-transform: uppercase; margin-bottom: 8px; }}
  .niche-title {{ font-size: 32px; font-weight: 700; color: #f1f5f9;
                  margin-bottom: 24px; line-height: 1.2; }}
  .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 16px; }}
  .metric {{ background: #1e293b; border: 1px solid #334155;
             border-radius: 12px; padding: 16px; text-align: center; }}
  .metric-value {{ font-size: 28px; font-weight: 700; }}
  .metric-label {{ font-size: 12px; color: #64748b; margin-top: 4px; }}

  /* Section headings */
  .section {{ margin-bottom: 32px; }}
  .section-heading {{ font-size: 18px; font-weight: 600; color: #94a3b8;
                      letter-spacing: 1px; text-transform: uppercase;
                      margin-bottom: 16px; padding-bottom: 8px;
                      border-bottom: 1px solid #1e293b; }}

  /* Cards */
  .card {{ background: #1e293b; border: 1px solid #334155;
           border-radius: 12px; padding: 20px; margin-bottom: 12px; }}

  /* Gaps */
  .gap-card {{ background: #1e293b; border: 1px solid #334155;
               border-radius: 12px; padding: 20px; margin-bottom: 12px; }}
  .gap-header {{ display: flex; justify-content: space-between;
                 align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 8px; }}
  .gap-title {{ font-weight: 600; font-size: 15px; color: #f1f5f9; }}
  .demand-badge {{ font-size: 11px; padding: 3px 10px; border-radius: 20px;
                   font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
  .gap-explanation {{ color: #94a3b8; font-size: 14px; margin-bottom: 10px; }}
  .suggested-title {{ background: #0f172a; border-left: 3px solid #3b82f6;
                      padding: 8px 12px; border-radius: 0 8px 8px 0;
                      font-size: 14px; color: #93c5fd; }}

  /* Ideas */
  .idea-card {{ background: #1e293b; border: 1px solid #334155;
                border-radius: 12px; padding: 20px; margin-bottom: 12px; }}
  .idea-title {{ font-weight: 700; font-size: 16px; color: #f1f5f9; margin-bottom: 8px; }}
  .idea-hook {{ color: #a78bfa; font-size: 14px; margin-bottom: 10px; }}
  .idea-meta {{ display: flex; gap: 16px; flex-wrap: wrap;
                font-size: 13px; color: #64748b; margin-bottom: 10px; }}
  .idea-why {{ color: #94a3b8; font-size: 14px; }}

  /* Script sections */
  .section-card {{ background: #1e293b; border: 1px solid #334155;
                   border-radius: 12px; padding: 24px; margin-bottom: 16px; }}
  .section-header {{ display: flex; justify-content: space-between;
                     align-items: flex-start; margin-bottom: 16px; }}
  .section-number {{ width: 32px; height: 32px; border-radius: 50%;
                     background: #0f172a; border: 1px solid #334155;
                     display: flex; align-items: center; justify-content: center;
                     font-weight: 700; font-size: 14px; flex-shrink: 0; }}
  .section-title {{ font-weight: 600; color: #f1f5f9; margin-bottom: 4px; }}
  .section-type {{ font-size: 11px; padding: 2px 8px; border-radius: 20px;
                   font-weight: 600; text-transform: uppercase; }}
  .section-duration {{ color: #64748b; font-size: 13px; flex-shrink: 0; }}
  .script-text {{ color: #cbd5e1; font-size: 15px; line-height: 1.8;
                  margin-bottom: 16px; padding: 16px; background: #0f172a;
                  border-radius: 8px; }}
  .direction-box, .broll-box {{ font-size: 13px; color: #94a3b8;
                                 margin-top: 10px; padding: 10px 14px;
                                 border-radius: 8px; }}
  .direction-box {{ background: #1a2744; border-left: 3px solid #3b82f6; }}
  .broll-box {{ background: #1a1f2e; border-left: 3px solid #64748b; }}
  .direction-label {{ font-weight: 600; color: #64748b; margin-bottom: 4px;
                      font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }}

  /* SEO */
  .seo-title {{ font-size: 20px; font-weight: 700; color: #f1f5f9;
                margin-bottom: 8px; }}
  .tags {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
  .tag {{ background: #1e293b; border: 1px solid #334155; padding: 4px 10px;
          border-radius: 20px; font-size: 12px; color: #94a3b8; }}
  .seo-desc {{ color: #94a3b8; font-size: 14px; margin: 12px 0; line-height: 1.7; }}
  .variants {{ color: #64748b; font-size: 14px; padding-left: 20px; }}
  .variants li {{ margin-bottom: 4px; }}

  /* Videos */
  .video-row {{ padding: 14px 0; border-bottom: 1px solid #1e293b; }}
  .video-row:last-child {{ border-bottom: none; }}
  .video-title-link {{ color: #60a5fa; text-decoration: none; font-weight: 500;
                       font-size: 14px; display: block; margin-bottom: 6px; }}
  .video-title-link:hover {{ color: #93c5fd; }}
  .video-meta {{ display: flex; gap: 16px; font-size: 12px; color: #64748b; flex-wrap: wrap; }}

  /* Tone */
  .word-badge {{ padding: 4px 10px; border-radius: 20px; font-size: 12px; }}
  .word-badge.use {{ background: #14532d30; color: #4ade80;
                     border: 1px solid #14532d; }}
  .word-badge.avoid {{ background: #7f1d1d30; color: #f87171;
                       border: 1px solid #7f1d1d; }}
  .tone-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  .tone-item {{ background: #0f172a; border-radius: 8px; padding: 14px; }}
  .tone-label {{ font-size: 11px; color: #64748b; text-transform: uppercase;
                 letter-spacing: 1px; margin-bottom: 6px; }}
  .tone-value {{ color: #e2e8f0; font-size: 14px; }}

  /* Footer */
  .footer {{ text-align: center; color: #334155; font-size: 12px;
             margin-top: 48px; padding-top: 24px; border-top: 1px solid #1e293b; }}

  @media (max-width: 600px) {{
    .tone-grid {{ grid-template-columns: 1fr; }}
    .section-header {{ flex-direction: column; gap: 8px; }}
  }}
</style>
</head>
<body>
<div class="container">

  <!-- Header -->
  <div class="header">
    <div class="pipeline-label">YouTube Research & Script Pipeline</div>
    <div class="niche-title">{brief.get('niche', '').title()}</div>
    <div class="metrics">
      <div class="metric">
        <div class="metric-value" style="color:{score_color}">{score}/10</div>
        <div class="metric-label">Opportunity Score</div>
      </div>
      <div class="metric">
        <div class="metric-value" style="color:#60a5fa">{len(brief.get('content_gaps', []))}</div>
        <div class="metric-label">Content Gaps</div>
      </div>
      <div class="metric">
        <div class="metric-value" style="color:#a78bfa">{script.get('word_count', 0):,}</div>
        <div class="metric-label">Script Words</div>
      </div>
      <div class="metric">
        <div class="metric-value" style="color:#34d399">{script.get('estimated_duration_minutes', 0)}m</div>
        <div class="metric-label">Video Length</div>
      </div>
      <div class="metric">
        <div class="metric-value" style="color:#f59e0b">{len(brief.get('top_videos_analyzed', []))}</div>
        <div class="metric-label">Videos Analyzed</div>
      </div>
    </div>
  </div>

  <!-- Opportunity Reasoning -->
  <div class="section">
    <div class="section-heading">Opportunity Analysis</div>
    <div class="card">
      <p style="color:#94a3b8">{brief.get('opportunity_score_reasoning', '')}</p>
      <div style="margin-top:16px;display:flex;flex-wrap:wrap;gap:8px">
        {''.join(f'<span class="tag" style="background:#1e3a5f;color:#60a5fa;border-color:#1e3a5f">{t}</span>' for t in brief.get('key_themes', []))}
      </div>
    </div>
  </div>

  <!-- Content Gaps -->
  <div class="section">
    <div class="section-heading">Content Gaps ({len(brief.get('content_gaps', []))} found)</div>
    {gaps_html}
  </div>

  <!-- Video Ideas -->
  <div class="section">
    <div class="section-heading">Video Ideas</div>
    {ideas_html}
  </div>

  <!-- Script -->
  <div class="section">
    <div class="section-heading">Full Video Script</div>
    <div class="card" style="margin-bottom:16px">
      <div class="seo-title">{seo.get('title', '')}</div>
      <div style="color:#64748b;font-size:13px;margin-top:4px">
        Addresses gap: {script.get('addresses_gap', '')}
      </div>
      <div style="margin-top:12px;padding:12px;background:#0f172a;border-radius:8px;
                  border-left:3px solid #8b5cf6;color:#c4b5fd;font-size:15px;font-style:italic">
        "{script.get('hook_statement', '')}"
      </div>
    </div>
    {sections_html}
  </div>

  <!-- SEO Package -->
  <div class="section">
    <div class="section-heading">SEO Package</div>
    <div class="card">
      <div class="seo-title">{seo.get('title', '')}</div>
      <p style="color:#64748b;font-size:12px;margin-bottom:12px">Title variants:</p>
      <ul class="variants">{variants_html}</ul>
      <p class="seo-desc">{seo.get('description', '')}</p>
      <div style="margin:12px 0;padding:14px;background:#0f172a;border-radius:8px">
        <div class="tone-label">Thumbnail Concept</div>
        <div style="color:#e2e8f0;font-size:14px">{seo.get('thumbnail_concept', '')}</div>
        <div style="margin-top:8px;font-weight:700;color:#fbbf24;font-size:18px">
          "{seo.get('thumbnail_text', '')}"
        </div>
      </div>
      <div class="tags">{tags_html}</div>
    </div>
  </div>

  <!-- Tone Profile -->
  <div class="section">
    <div class="section-heading">Tone Profile</div>
    <div class="card">
      <div class="tone-grid">
        <div class="tone-item">
          <div class="tone-label">Style</div>
          <div class="tone-value">{tone.get('dominant_style', '')}</div>
        </div>
        <div class="tone-item">
          <div class="tone-label">Pacing</div>
          <div class="tone-value">{tone.get('pacing', '')}</div>
        </div>
        <div class="tone-item">
          <div class="tone-label">Visual Style</div>
          <div class="tone-value">{tone.get('visual_style', '')}</div>
        </div>
        <div class="tone-item">
          <div class="tone-label">Recommended Length</div>
          <div class="tone-value">{brief.get('recommended_video_length', '')}</div>
        </div>
      </div>
      <div style="margin-top:16px">
        <div class="tone-label" style="margin-bottom:8px">Words to use</div>
        <div style="display:flex;flex-wrap:wrap;gap:6px">{use_words}</div>
      </div>
      <div style="margin-top:12px">
        <div class="tone-label" style="margin-bottom:8px">Words to avoid</div>
        <div style="display:flex;flex-wrap:wrap;gap:6px">{avoid_words}</div>
      </div>
    </div>
  </div>

  <!-- Top Videos -->
  <div class="section">
    <div class="section-heading">Top Videos Analyzed</div>
    <div class="card">
      {videos_html}
    </div>
  </div>

  <!-- Production Notes -->
  <div class="section">
    <div class="section-heading">Production Notes</div>
    <div class="card">
      <p style="color:#94a3b8;font-size:14px">{script.get('production_notes', '')}</p>
      <div style="margin-top:16px">
        <div class="tone-label" style="margin-bottom:8px">Pattern Interrupt Moments</div>
        {''.join(f'<div style="padding:6px 0;border-bottom:1px solid #0f172a;font-size:13px;color:#64748b">• {m}</div>' for m in script.get('pattern_interrupt_moments', []))}
      </div>
      <div style="margin-top:16px;padding:12px;background:#0f172a;border-radius:8px;
                  border-left:3px solid #f59e0b">
        <div class="tone-label">Rewatch Hook</div>
        <div style="color:#fcd34d;font-size:14px">{script.get('rewatch_hook', '')}</div>
      </div>
    </div>
  </div>

  <div class="footer">
    Generated by YouTube Research & Script Pipeline ·
    {datetime.now().strftime("%B %d, %Y at %H:%M")}
  </div>

</div>
</body>
</html>"""

    return html


def main():
    parser = argparse.ArgumentParser(description="Generate HTML report from pipeline output")
    parser.add_argument("brief", help="Path to research brief JSON")
    parser.add_argument("script", help="Path to script JSON")
    parser.add_argument("--no-open", action="store_true", help="Don't open in browser")
    parser.add_argument("--output", type=str, default=None, help="Output HTML file path")
    args = parser.parse_args()

    if not Path(args.brief).exists():
        print(f"Error: brief not found: {args.brief}")
        sys.exit(1)
    if not Path(args.script).exists():
        print(f"Error: script not found: {args.script}")
        sys.exit(1)

    html = generate_report(args.brief, args.script)

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"report_{timestamp}.html"

    output_path.write_text(html, encoding="utf-8")
    print(f"Report saved: {output_path}")

    if not args.no_open:
        webbrowser.open(output_path.resolve().as_uri())
        print("Opened in browser.")


if __name__ == "__main__":
    main()
