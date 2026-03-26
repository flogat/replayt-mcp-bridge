"""Allow ``python -m replayt`` when the ``replayt`` console script is not on ``PATH``."""

from __future__ import annotations

from replayt.cli.main import main

if __name__ == "__main__":
    main()
