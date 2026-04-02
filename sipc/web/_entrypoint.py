"""Console script entry point: ``sipc-serve``."""

from __future__ import annotations

import uvicorn


def main() -> None:
    """Start the SIPC web console with uvicorn."""
    uvicorn.run(
        "sipc.web.app:app",
        host="0.0.0.0",  # nosec B104 — intentional: local-network server
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
