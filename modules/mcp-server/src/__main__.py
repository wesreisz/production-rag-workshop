import logging
import sys

from pydantic import ValidationError

from src import __version__
from src.config import get_settings
from src.server import mcp
import src.tools  # noqa: F401 — registers @mcp.tool() decorators


def _configure_logging() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)


logger = logging.getLogger(__name__)


def main() -> None:
    _configure_logging()
    logger.info("Starting video-knowledge MCP Server v%s", __version__)

    try:
        get_settings()
    except ValidationError as e:
        missing = [err["loc"][0] for err in e.errors()]
        print(
            f"Configuration error: missing or invalid environment variables: {', '.join(str(f) for f in missing)}\n"
            "Set the following before starting the server:\n"
            "  API_ENDPOINT  — Question API base URL (e.g. https://....execute-api.us-east-1.amazonaws.com/prod)\n"
            "  API_KEY       — API Gateway API key",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        mcp.run()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception:
        logger.exception("Unexpected error, server shutting down")
        sys.exit(1)


if __name__ == "__main__":
    main()
