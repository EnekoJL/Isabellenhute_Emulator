"""Entry point: `python -m isascale` / `isascale-emulator`."""

from __future__ import annotations

import logging
import sys
from typing import Sequence

from isascale.bootstrap import build_app, parse_args, run_headless


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args(argv)
    ctx = build_app(args)
    if args.headless:
        return run_headless(ctx)
    # Qt is imported only for the GUI so headless/HIL runs need no PySide6.
    from isascale.presentation.main_window import run_gui

    return run_gui(ctx)


if __name__ == "__main__":
    sys.exit(main())
