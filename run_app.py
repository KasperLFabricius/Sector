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


def main():
    sys.argv = ["streamlit", "run", str(APP), "--server.port", _port(),
                "--server.headless", "true"]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
