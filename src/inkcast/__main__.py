"""Entry point: ``inkcast [config.toml]``."""

import argparse
import asyncio
import logging
import time
from pathlib import Path

from .config import load_config
from .render import Renderer
from .server import InkcastServer


async def serve(config_path: Path) -> None:
    config = load_config(config_path)
    async with Renderer(settle_seconds=config.settle_seconds) as renderer:
        await InkcastServer(config, renderer).run()


def utc_formatter() -> logging.Formatter:
    """Log timestamps in UTC, e.g. ``2026-10-18T22:30:00.123Z``, like the status API."""
    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03dZ %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime
    return formatter


def main() -> None:
    parser = argparse.ArgumentParser(description="Show web pages and images on Visionect e-ink displays.")
    parser.add_argument("config", type=Path, nargs="?", default=Path("config.toml"))
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = parser.parse_args()
    handler = logging.StreamHandler()
    handler.setFormatter(utc_formatter())
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, handlers=[handler])
    asyncio.run(serve(args.config))


if __name__ == "__main__":
    main()
