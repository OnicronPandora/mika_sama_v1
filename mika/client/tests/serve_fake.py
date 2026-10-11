"""The client, run the way python -m app runs it, but with a fake voice and no microphone.
tests/test_shutdown.py starts it as a separate process and interrupts it while a sentence never finishes:

    python tests/serve_fake.py <port> <log file> <Mac URL>
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # mika/client, for `app`

from fakes import FakeTranscriber, FakeVoice, fast_settings, open_fake_client  # noqa: E402

from app.__main__ import serve  # noqa: E402
from app.logs import setup_logging  # noqa: E402
from app.main import create_app  # noqa: E402


def main() -> None:
    port, log_file, mac_url = int(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    setup_logging(log_file)
    settings = fast_settings(mac_url).model_copy(update={"port": port})
    serve(create_app(settings, services=open_fake_client(FakeVoice(), FakeTranscriber())), settings)


if __name__ == "__main__":
    main()
