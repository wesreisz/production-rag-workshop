import logging

from fastmcp import FastMCP

from src.api_client import ApiClient
from src.config import get_settings

logger = logging.getLogger(__name__)

mcp = FastMCP("video-knowledge")


def _format_results(question: str, data: dict) -> str:
    results = data.get("results", [])
    if not results:
        return f'## Results for: "{question}"\n\nNo results found.'

    lines = [f'## Results for: "{question}"\n']
    for i, r in enumerate(results, 1):
        lines.append(f"### Result {i} (similarity: {r.get('similarity', 0):.2f})")
        speaker = r.get("speaker") or "Unknown"
        title = r.get("title") or "Untitled"
        lines.append(f"**Speaker:** {speaker} | **Title:** {title}")
        start = r.get("start_time", 0)
        end = r.get("end_time", 0)
        lines.append(f"**Time:** {start}s \u2013 {end}s")
        lines.append("")
        lines.append(r.get("text", ""))
        lines.append("\n---\n")

    return "\n".join(lines)


def _format_videos(data: dict) -> str:
    videos = data.get("videos", [])
    if not videos:
        return "## Indexed Videos\n\nNo videos indexed yet."

    lines = [
        "## Indexed Videos\n",
        "| Video ID | Title | Speaker | Chunks |",
        "|----------|-------|---------|--------|",
    ]
    for v in videos:
        vid = v.get("video_id", "")
        title = v.get("title") or "Untitled"
        speaker = v.get("speaker") or "Unknown"
        chunks = v.get("chunk_count", 0)
        lines.append(f"| {vid} | {title} | {speaker} | {chunks} |")

    return "\n".join(lines)


@mcp.tool
async def ask_video_question(question: str, top_k: int = 5) -> str:
    """Ask a question about indexed video content and receive relevant transcript chunks."""
    if not question or not question.strip():
        raise ValueError("Question cannot be empty.")

    settings = get_settings()
    client = ApiClient(settings)
    result = await client.ask(question.strip(), top_k)
    return _format_results(question.strip(), result)


@mcp.tool
async def list_indexed_videos() -> str:
    """List all videos currently indexed in the knowledge base."""
    settings = get_settings()
    client = ApiClient(settings)
    result = await client.list_videos()
    return _format_videos(result)


@mcp.tool
async def search_by_speaker(speaker: str, question: str, top_k: int = 5) -> str:
    """Search across all content from a specific speaker."""
    if not question or not question.strip():
        raise ValueError("Question cannot be empty.")
    if not speaker or not speaker.strip():
        raise ValueError("Speaker cannot be empty.")

    settings = get_settings()
    client = ApiClient(settings)
    result = await client.ask(question.strip(), top_k, speaker=speaker.strip())
    return _format_results(question.strip(), result)


__all__ = ["mcp", "ask_video_question", "list_indexed_videos", "search_by_speaker"]
