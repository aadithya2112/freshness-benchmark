from __future__ import annotations

import sys

from .benchmark_pack import run_benchmark_pack
from .config import build_parser, compare_config_from_args, config_from_args, pack_config_from_args
from .runner import run_benchmark, run_compare
from .visualize import generate_report_from_args


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "run":
            config = config_from_args(args)
            run_benchmark(config)
        elif args.command == "compare":
            config = compare_config_from_args(args)
            summary = run_compare(config)
            print(f"comparison_written={config.out_dir}/comparison.html runs={len(summary.rows)}")
        elif args.command == "pack":
            config = pack_config_from_args(args)
            summary = run_benchmark_pack(config)
            print(f"benchmark_pack_written={config.out_dir}/benchmark_pack.html rows={len(summary.rows)}")
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
