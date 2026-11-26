"""Entry script PyInstaller freezes; the console scripts of an install call the same function."""
import sys

from ascii_art.cli import main

sys.exit(main())
