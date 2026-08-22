"""Run the engine: ``python -m process_engine`` (or ``process-engine-worker``).

No server, no port — it talks to the database and nothing else, which is why it
can sit on a Windows host with no inbound HTTP at all. The designer's API is a
separate package (``python -m process_engine_api``).
"""

from .worker import main

if __name__ == "__main__":
    main()
