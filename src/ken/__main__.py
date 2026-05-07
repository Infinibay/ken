"""Allow `python -m ken` for development without the console script."""

from ken.cli import main

if __name__ == "__main__":  # pragma: no cover
    main()
