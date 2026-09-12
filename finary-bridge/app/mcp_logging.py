"""Keep optional MCP query arguments out of Uvicorn access logs."""

import logging


class McpAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5:
            path = args[2]
            if isinstance(path, str) and path.startswith("/v3/"):
                record.args = (*args[:2], path.split("?", 1)[0], *args[3:])
        return True


def protect_access_logs() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, McpAccessFilter) for item in logger.filters):
        logger.addFilter(McpAccessFilter())
