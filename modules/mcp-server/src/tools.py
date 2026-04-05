from src.api_client import ApiClient
from src.server import mcp


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
