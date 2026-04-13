from fastmcp import FastMCP

from src.prompts import EXAMPLE_QUESTIONS, FORMATTING_GUIDANCE, VIDEO_KNOWLEDGE_OVERVIEW

mcp = FastMCP("video-knowledge")


@mcp.prompt()
def video_knowledge_overview() -> str:
    return VIDEO_KNOWLEDGE_OVERVIEW


@mcp.prompt()
def example_questions() -> str:
    return EXAMPLE_QUESTIONS


@mcp.prompt()
def formatting_guidance() -> str:
    return FORMATTING_GUIDANCE
