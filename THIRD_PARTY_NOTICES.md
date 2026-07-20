# Third-party notices

Sector is proprietary software; see `LICENSE`. Third-party components retain
their own licence terms.

The Windows build creates `THIRD_PARTY_NOTICES.txt` from the exact package names
and versions selected by `requirements-build.txt`. Runner-only or locally
installed packages are excluded; a missing or mismatched locked distribution
fails the build. The file records each selected distribution, version, declared
licence, source URL and packaged licence/notice text. The inventory includes
build-only packages intentionally. The generated file and Sector's proprietary
notice are copied beside `Sector.exe` and checked by CI before upload.

The embedded point-grid uses Tabulator under the MIT licence. Its original text
is retained at `app/point_grid_frontend/LICENSE` and is also copied into the
generated consolidated notice.
