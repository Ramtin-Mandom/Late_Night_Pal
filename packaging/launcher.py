"""PyInstaller entry script (absolute import so the frozen app can find the package)."""
import sys

from late_night_workshop.__main__ import main

sys.exit(main())
