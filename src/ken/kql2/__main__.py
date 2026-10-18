"""Run a KQL2 query with python -m ken.kql2."""
import argparse

from .cli import configure, dispatch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    configure(parser)
    args = parser.parse_args()
    if args.capabilities or args.explain or args.save:
        return dispatch(args)
    from .process import prepare_process
    prepare_process(freeze=False)
    return dispatch(args)


if __name__ == '__main__':
    raise SystemExit(main())
