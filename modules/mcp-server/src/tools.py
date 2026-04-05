import webbrowser

from src.api_client import ApiClient
from src.server import mcp

__all__ = ["mcp", "ask_video_question", "list_indexed_videos", "search_by_speaker", "watch_video_segment"]


@mcp.tool()
async def ask_video_question(question: str, top_k: int = 5) -> str:
    if not question.strip():
        raise ValueError("question cannot be empty")
    client = ApiClient()
    data = await client.ask(question, top_k)
    return _format_results(question, data.get("results", []))


@mcp.tool()
async def list_indexed_videos() -> str:
    client = ApiClient()
    data = await client.list_videos()
    videos = data.get("videos", [])
    lines = [
        "## Indexed Videos\n",
        "| Video ID | Title | Speaker | Chunks |",
        "|----------|-------|---------|--------|",
    ]
    for video in videos:
        lines.append(
            f"| {video['video_id']} | {video['title']} | {video['speaker']} | {video['chunk_count']} |"
        )
    return "\n".join(lines)


@mcp.tool()
async def search_by_speaker(speaker: str, question: str, top_k: int = 5) -> str:
    if not question.strip():
        raise ValueError("question cannot be empty")
    client = ApiClient()
    data = await client.ask(question, top_k, speaker=speaker)
    return _format_results(question, data.get("results", []))


@mcp.tool()
async def watch_video_segment(video_id: str, start_time: float = 0) -> str:
    """Open a video in the browser, seeking to a specific timestamp. Use this after asking a question to watch the relevant video segment."""
    if not video_id:
        raise ValueError("Video ID cannot be empty.")
    if start_time < 0:
        raise ValueError("Start time must be non-negative.")
    client = ApiClient()
    data = await client.presign(video_id)
    presigned_url = data["presigned_url"]
    playback_url = f"{presigned_url}#t={start_time}" if start_time > 0 else presigned_url
    webbrowser.open(playback_url)
    title = data.get("title", "")
    speaker = data.get("speaker", "")
    return (
        "## Now Playing\n\n"
        f"**Title:** {title}\n"
        f"**Speaker:** {speaker}\n"
        f"**Starting at:** {_format_time(start_time)}\n\n"
        "Opened in your default browser. The video will play from the specified timestamp."
    )


def _format_time(seconds: float) -> str:
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"


def _format_results(question: str, results: list) -> str:
    lines = [f'## Results for: "{question}"\n']
    for i, result in enumerate(results, start=1):
        similarity = result.get("similarity", 0)
        speaker = result.get("speaker", "")
        title = result.get("title", "")
        start_time = result.get("start_time", 0)
        end_time = result.get("end_time", 0)
        text = result.get("text", "")
        lines.append(f"### Result {i} (similarity: {similarity:.2f})")
        lines.append(f"**Speaker:** {speaker} | **Title:** {title}")
        lines.append(f"**Time:** {start_time}s \u2013 {end_time}s\n")
        lines.append(text)
        lines.append("\n---")
    return "\n".join(lines)
