"""CLI エントリポイント。エンジンのイベントをログとして垂れ流す。

GUI 版は gui.py(exe 化して配布する想定)。
"""

from __future__ import annotations

import argparse
import logging
import queue
import sys
from pathlib import Path

from .engine import NormalizerEngine
from .i18n import set_language, t
from .settings import load_config

logger = logging.getLogger("dvn")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="voice-normalizer-for-discord",
        description=t("cli.description"),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.toml"),
        help=t("cli.config_help"),
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.config.exists():
        sys.exit(t("cli.no_config", path=args.config))
    config = load_config(args.config)
    set_language(config.get("ui", {}).get("language", "auto"))

    engine = NormalizerEngine(config, args.config.resolve().parent)
    engine.start()
    exit_code = 0
    try:
        while True:
            try:
                ev = engine.events.get(timeout=0.5)
            except queue.Empty:
                continue
            kind = ev["kind"]
            if kind == "status":
                logger.info("%s", ev["text"])
            elif kind == "log":
                getattr(logger, ev["level"], logger.info)("%s", ev["text"])
            elif kind == "notice" and ev["msg"]:
                logger.warning("%s", t(ev["msg"], **ev["args"]))
            elif kind == "error":
                logger.error("%s", t(ev["msg"], **ev["args"]))
                exit_code = 1
            elif kind == "stopped":
                break
    except KeyboardInterrupt:
        logger.info("%s", t("cli.exiting"))
        engine.request_stop()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
