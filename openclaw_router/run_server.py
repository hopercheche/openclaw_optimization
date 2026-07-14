#!/usr/bin/env python3
"""Start the FastAPI server."""

import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).parent))

if __name__ == "__main__":
    uvicorn.run("src.api.server:app", host="0.0.0.0", port=8000, reload=True)
