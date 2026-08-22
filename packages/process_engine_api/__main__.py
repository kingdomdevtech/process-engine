"""Run the designer API: ``python -m process_engine_api`` (or ``process-engine-api``).

Binds loopback, which is right for development and behind a reverse proxy in
the same container. Serving it to other machines is the process manager's job:
``uvicorn "process_engine_api:create_app" --factory --host 0.0.0.0 --port 8000``.
"""

import logging
import os

import uvicorn

from .app import create_app


def main() -> None:
    logging.basicConfig(level=os.environ.get("PROCESS_ENGINE_LOG_LEVEL", "INFO"))
    uvicorn.run(create_app(), host=os.environ.get("PROCESS_ENGINE_HOST", "127.0.0.1"),
                port=int(os.environ.get("PROCESS_ENGINE_PORT", "8000")))


if __name__ == "__main__":
    main()
