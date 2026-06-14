# Vercel serverless entry point — imports the FastAPI app
import sys
import os

# Ensure the backend root is on the path so `app` package resolves
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.main import app  # noqa: F401 — Vercel picks up `app`
