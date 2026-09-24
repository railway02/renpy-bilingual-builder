"""Isolated source-mode helper. Game input paths are never put on sys.path."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.decompile import worker

if __name__ == "__main__":
    worker(Path(sys.argv[1]))
