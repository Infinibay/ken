"""Run a KQL2 query with python -m ken.kql2."""
import argparse

from .cli import configure, dispatch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    configure(parser)
    return dispatch(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
