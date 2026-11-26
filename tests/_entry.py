"""Stand-in for an installed console script; the test symlinks it under an art's name."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ascii_art.cli import main

sys.exit(main())
