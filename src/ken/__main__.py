"""Allow `python -m ken` for development without the console script."""

import sys

from ken.cli import main

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
