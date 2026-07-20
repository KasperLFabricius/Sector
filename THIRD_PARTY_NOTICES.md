# Third-party notices

Sector is proprietary software; see `LICENSE`. Third-party components retain
their own licence terms.

The Windows build creates `THIRD_PARTY_NOTICES.txt` from the installed,
hash-locked build environment. It records each Python distribution, version,
declared licence, source URL and packaged licence/notice text. The inventory is
intentionally conservative and may include build-only packages. The generated
file and Sector's proprietary notice are copied beside `Sector.exe` and checked
by CI before the package is uploaded.

The embedded point-grid uses Tabulator under the MIT licence. Its original text
is retained at `app/point_grid_frontend/LICENSE` and is also copied into the
generated consolidated notice.
