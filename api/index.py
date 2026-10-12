"""Vercel entrypoint for the Keel FastAPI application."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wealth_advisor.ui.server import app

__all__ = ["app"]
