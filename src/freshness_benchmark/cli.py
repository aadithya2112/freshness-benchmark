from __future__ import annotations

import sys

from .config import build_parser, config_from_args
from .runner import run_benchmark
from .visualize import generate_report_from_args


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "run":
            config = config_from_args(args)
            run_benchmark(config)
        elif args.command == "report":
            output = generate_report_from_args(args)
            print(f"report_written={output}")
        else:
            parser.error("Unsupported command.")
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
