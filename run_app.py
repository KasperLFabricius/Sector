"""Launch the Sector Streamlit app.

Run with ``python run_app.py`` (or ``streamlit run app/sector_app.py``). Sector
serves on port 8502 (Streamlit's default 8501 is used by BriCoS) so both can be
open at once; override with the ``SECTOR_PORT`` environment variable.
"""

import os
import pathlib
import sys

from streamlit.web import cli as stcli

APP = pathlib.Path(__file__).resolve().parent / "app" / "sector_app.py"


def _port() -> str:
    return os.environ.get("SECTOR_PORT") or "8502"


def _streamlit_argv(app_path, port) -> list:
    """Return the local-only development launcher arguments."""
    return [
        "streamlit", "run", str(app_path),
        "--server.port", port,
        "--server.address", "127.0.0.1",
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
        "--client.toolbarMode", "viewer",
        "--client.showErrorDetails", "type",
    ]


def main():
    sys.argv = _streamlit_argv(APP, _port())
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
