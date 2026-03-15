import logging

from src.prompts import (
    EXAMPLE_QUESTIONS,
    FORMATTING_GUIDANCE,
    VIDEO_KNOWLEDGE_OVERVIEW,
)
from src.tools import mcp

logger = logging.getLogger(__name__)


@mcp.prompt
def video_knowledge_overview() -> str:
    """Explains what the video knowledge base contains and how to query it."""
    return VIDEO_KNOWLEDGE_OVERVIEW


@mcp.prompt
def example_questions() -> str:
    """Provides sample questions participants can try."""
    return EXAMPLE_QUESTIONS


@mcp.prompt
def formatting_guidance() -> str:
    """Tips for writing effective questions to get better results."""
    return FORMATTING_GUIDANCE


logger.info("video-knowledge MCP server configured with 3 tools and 3 prompts")

__all__ = ["mcp"]
