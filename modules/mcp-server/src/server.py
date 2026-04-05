from fastmcp import FastMCP

from src import prompts

mcp = FastMCP("video-knowledge")


@mcp.prompt()
def video_knowledge_overview() -> str:
    return prompts.VIDEO_KNOWLEDGE_OVERVIEW


@mcp.prompt()
def example_questions() -> str:
    return prompts.EXAMPLE_QUESTIONS


@mcp.prompt()
def formatting_guidance() -> str:
    return prompts.FORMATTING_GUIDANCE
