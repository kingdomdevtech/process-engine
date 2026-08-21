"""Run the API server: ``python -m process_engine`` (or ``process-engine``)."""

import logging

import uvicorn

from .api import create_app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
