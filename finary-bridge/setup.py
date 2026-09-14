"""Stage the authoritative repository notice; extracted sdists carry their own copy."""

from pathlib import Path

from setuptools import setup

package = Path(__file__).resolve().parent
source = package.parent / "LICENSE"
notice = package / "LICENSE"
if source.is_file():
    notice.write_bytes(source.read_bytes())
if not notice.is_file():
    raise RuntimeError("Build from the repository or a complete source distribution with LICENSE")

setup()
