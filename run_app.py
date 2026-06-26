"""Launch the Sector Streamlit app.

Run with ``python run_app.py`` (or ``streamlit run app/sector_app.py``).
"""

import pathlib
import sys

from streamlit.web import cli as stcli

APP = pathlib.Path(__file__).resolve().parent / "app" / "sector_app.py"


def main():
    sys.argv = ["streamlit", "run", str(APP), "--server.port", "8501",
                "--server.headless", "true"]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
