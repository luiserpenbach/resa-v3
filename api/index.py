"""Vercel entrypoint: the RESA Studio API as one Python function (ASGI).

vercel.json rewrites /api/* here; the static web app (web/dist) is served by
the CDN. See docs/DEPLOY.md.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resa_studio.api.main import app  # noqa: E402,F401
