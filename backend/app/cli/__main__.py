import argparse
from collections.abc import Sequence

from app.cli.platform_admin import add_platform_admin_commands
from app.core.logging import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="PEKA local operational commands",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_platform_admin_commands(subparsers)
    return parser


def main(argv: Sequence[str] | None = None, **handler_kwargs) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    return args.command_handler(args, **handler_kwargs)


if __name__ == "__main__":
    raise SystemExit(main())
