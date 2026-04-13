import logging
import sys

from pydantic import ValidationError

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("mcp-server")

try:
    from src.config import get_settings

    get_settings()
    logger.info("Starting video-knowledge MCP Server")

    from src.server import mcp
    import src.tools  # noqa: F401

    mcp.run()
except ValidationError as e:
    print(f"Configuration error: {e}", file=sys.stderr)
    sys.exit(1)
except KeyboardInterrupt:
    logger.info("Server stopped")
    sys.exit(0)
except Exception:
    logger.exception("Unexpected error")
    sys.exit(1)
