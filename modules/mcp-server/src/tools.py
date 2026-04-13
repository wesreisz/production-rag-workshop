from src.api_client import ApiClient
from src.config import get_settings
from src.server import mcp


def _format_results(header, results):
    parts = [header]
    if not results:
        parts.append("No results found.")
        return "\n".join(parts)

    for i, r in enumerate(results, 1):
        parts.append(f"### Result {i} (similarity: {r['similarity']:.2f})")
        parts.append(f"**Speaker:** {r['speaker']} | **Title:** {r['title']}")
        parts.append(f"**Time:** {r['start_time']}s \u2013 {r['end_time']}s\n")
        parts.append(f"{r['text']}\n\n---")

    return "\n".join(parts)


@mcp.tool()
async def ask_video_question(question: str, top_k: int = 5) -> str:
    """Ask a natural language question about indexed video content and receive relevant transcript chunks."""
    if not question or not question.strip():
        raise ValueError("question must not be empty")

    settings = get_settings()
    client = ApiClient(settings)
    data = await client.ask(question, top_k)

    header = f'## Results for: "{question}"\n'
    return _format_results(header, data["results"])


@mcp.tool()
async def list_indexed_videos() -> str:
    """List all videos currently indexed in the system."""
    settings = get_settings()
    client = ApiClient(settings)
    data = await client.list_videos()

    parts = [
        "## Indexed Videos\n",
        "| Video ID | Title | Speaker | Chunks |",
        "|----------|-------|---------|--------|",
    ]
    for video in data["videos"]:
        parts.append(
            f"| {video['video_id']} | {video['title']} "
            f"| {video['speaker']} | {video['chunk_count']} |"
        )

    return "\n".join(parts)


@mcp.tool()
async def search_by_speaker(speaker: str, question: str, top_k: int = 5) -> str:
    """Search across all content from a specific speaker."""
    if not question or not question.strip():
        raise ValueError("question must not be empty")
    if not speaker or not speaker.strip():
        raise ValueError("speaker must not be empty")

    settings = get_settings()
    client = ApiClient(settings)
    data = await client.ask(question, top_k, speaker=speaker)

    header = f'## Results from {speaker} for: "{question}"\n'
    return _format_results(header, data["results"])
