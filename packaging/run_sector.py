"""Entry point for the packaged (PyInstaller) Sector build.

Launches the Streamlit app the same way ``streamlit run app/sector_app.py`` does,
but resolves the app path inside the frozen bundle and points the writable state
(autosave, the numba compile cache) at a per-user folder so a read-only install
location (e.g. Program Files) does not break startup.
"""

from __future__ import annotations

import os
import pathlib
import sys


def _bundle_base() -> pathlib.Path:
    """Folder that holds the bundled ``app`` and ``sector`` trees.

    Frozen: PyInstaller unpacks data next to the executable (``sys._MEIPASS``);
    from source: the repository root (the parent of this ``packaging`` folder).
    """
    if getattr(sys, "frozen", False):
        return pathlib.Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    return pathlib.Path(__file__).resolve().parent.parent


def _user_data_dir() -> pathlib.Path:
    """A writable per-user folder for autosave and the numba cache."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    root = pathlib.Path(base) if base else (pathlib.Path.home() / ".sector")
    return (root / "Sector") if base else root


def main() -> None:
    app = _bundle_base() / "app" / "sector_app.py"
    data = _user_data_dir()
    try:
        data.mkdir(parents=True, exist_ok=True)
    except OSError:
        data = pathlib.Path.home()          # last resort; never block startup
    # Writable locations for the autosave file and numba's on-disk compile cache
    # (both default next to read-only bundled code in a frozen build).
    os.environ.setdefault("SECTOR_AUTOSAVE_DIR", str(data))
    os.environ.setdefault("NUMBA_CACHE_DIR", str(data / "numba_cache"))

    sys.argv = [
        "streamlit", "run", str(app),
        "--global.developmentMode=false",
        "--server.headless=false",          # open the browser on launch
        "--browser.gatherUsageStats=false",
    ]
    from streamlit.web import cli as stcli
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
