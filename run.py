#!/usr/bin/env python
"""Development startup script for AI Scene Planner add-on."""
import os
import sys
import asyncio
import uvicorn
from pathlib import Path

from app.version_sync import sync_integration_manifest

# Add addon app to path
addon_path = Path(__file__).parent / "addon" / "app"
sys.path.insert(0, str(addon_path.parent))

# Configuration
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").lower()
RELOAD = os.getenv("RELOAD", "true").lower() == "true"

# API Key validation
api_key = os.getenv("OPENAI_API_KEY") or os.getenv("NVIDIA_API_KEY")
if not api_key and not RELOAD:
    print("⚠️  Warning: No API key found. Set OPENAI_API_KEY or NVIDIA_API_KEY.")
    print("   Using mock/test mode only.")


def main():
    """Start the FastAPI server."""
    version_sync = sync_integration_manifest()

    print(f"🚀 Starting AI Scene Planner")
    if version_sync.updated:
        print(f"   Integration manifest version updated to {version_sync.integration_version}")
    else:
        print(f"   Version: {version_sync.addon_version}")
    print(f"   Host: {HOST}")
    print(f"   Port: {PORT}")
    print(f"   Log Level: {LOG_LEVEL}")
    print(f"   Reload: {RELOAD}")
    print(f"   API Key: {'✓ Configured' if api_key else '✗ Not configured'}")
    print()
    
    config = uvicorn.Config(
        "app.main:app",
        host=HOST,
        port=PORT,
        reload=RELOAD,
        log_level=LOG_LEVEL
    )
    server = uvicorn.Server(config)
    
    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        print("\n⏹️  Shutdown requested")
        sys.exit(0)


if __name__ == "__main__":
    main()
