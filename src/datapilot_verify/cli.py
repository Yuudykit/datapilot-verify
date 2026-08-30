import argparse
import sys

from datapilot_verify import __version__
from datapilot_verify.config import get_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DataPilot Verify CLI")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--show-config", action="store_true")
    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    if args.show_config:
        settings = get_settings()
        safe = settings.model_dump(exclude={"llm_api_key"})
        for key, value in safe.items():
            print(f"{key}={value}")


if __name__ == "__main__":
    main()
