"""Stage the authoritative notice for repository and distribution build layouts."""

from pathlib import Path

from setuptools import setup

package = Path(__file__).resolve().parent
source_marker = package / ".repository-source"
source = package.parent / "LICENSE"
notice = package / "LICENSE"

if source_marker.is_file():
    if not source.is_file():
        raise RuntimeError("Repository source build requires the authoritative root LICENSE")
    notice.write_bytes(source.read_bytes())
elif not notice.is_file():
    raise RuntimeError("Complete source distribution requires its bundled LICENSE")

setup()
