"""Point d'entrée utilisable sans installer le paquet."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from vibe_claw_light.cli import main

if __name__ == "__main__":
    raise SystemExit(main(default_root=Path(__file__).resolve().parent))
