"""The server, run the way python -m app runs it, but on a scripted LLM whose replies never finish and with no
database. tests/test_shutdown.py starts it as a separate process and interrupts it mid-turn:

    python tests/serve_fake.py <port> <log file>
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # mika/server, for `app`

from fakes import HANG, FakeEngine, fake_settings, open_fake_services  # noqa: E402

from app.__main__ import serve  # noqa: E402
from app.logs import setup_logging  # noqa: E402
from app.main import create_app  # noqa: E402


def main() -> None:
    port, log_file = int(sys.argv[1]), Path(sys.argv[2])
    setup_logging(log_file)
    engine = FakeEngine(replies=[["[happy] Hi", HANG] for _ in range(3)])
    settings = fake_settings(host="127.0.0.1", port=port)
    serve(create_app(settings, services=lambda s: open_fake_services(s, engine)), settings)


if __name__ == "__main__":
    main()
