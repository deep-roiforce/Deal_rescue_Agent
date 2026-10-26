"""Build the deployable metadata archives.

Why Python and not Compress-Archive: PowerShell's Compress-Archive omits
explicit directory entries, and Salesforce's deploy unzipper can reject the
result with a misleading "No package.xml found". This writes directory entries,
forward-slash paths and fixed timestamps, so the same inputs always produce a
byte-identical archive.

The Metadata API reads a deployment two ways, and Workbench exposes the choice
as a "Single Package" checkbox:

    Single Package TICKED   -> package.xml at the ROOT of the zip
    Single Package UNTICKED -> a package FOLDER; a root manifest reports
                               "No package.xml found"

Both shapes are written so either setting works.

    python salesforce/build_zip.py
"""

from __future__ import annotations

import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"

SOURCES = ["package.xml", "objects", "permissionsets"]
FIXED_DATE = (1980, 1, 1, 0, 0, 0)  # reproducible archives


def collect() -> list[tuple[str, bytes]]:
    """(archive path, bytes) for every file, forward slashes, sorted."""
    files: list[tuple[str, bytes]] = []
    for name in SOURCES:
        source = HERE / name
        if not source.exists():
            raise SystemExit(f"missing: {source}")
        if source.is_file():
            files.append((source.name, source.read_bytes()))
            continue
        for path in sorted(source.rglob("*")):
            if path.is_file():
                files.append((path.relative_to(HERE).as_posix(), path.read_bytes()))
    return sorted(files)


def write_zip(target: Path, files: list[tuple[str, bytes]], prefix: str = "") -> None:
    """Write the archive, including explicit directory entries."""
    entries = [(f"{prefix}{name}", data) for name, data in files]

    directories: set[str] = set()
    for name, _ in entries:
        parts = name.split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            directories.add("/".join(parts[:depth]) + "/")

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for directory in sorted(directories):
            info = zipfile.ZipInfo(directory, date_time=FIXED_DATE)
            info.external_attr = (0o40755 << 16) | 0x10  # directory bit
            archive.writestr(info, b"")
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=FIXED_DATE)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)


def main() -> None:
    files = collect()
    DIST.mkdir(parents=True, exist_ok=True)

    targets = [
        (DIST / "deal-rescue-package-unpackaged.zip", "unpackaged/", "Single Package UNTICKED"),
        (DIST / "deal-rescue-package.zip", "", "Single Package TICKED"),
    ]

    for target, prefix, note in targets:
        write_zip(target, files, prefix)
        size = target.stat().st_size / 1024
        print(f"{target.name:42s} {size:5.1f} KB   {note}")

    print(f"\n{len(files)} metadata files:")
    for name, _ in files:
        print(f"  {name}")
    print("\nWorkbench -> migration -> Deploy")
    print("  use the -unpackaged archive, tick Rollback On Error, leave Single Package unticked")


if __name__ == "__main__":
    main()
