"""Install the pinned experimental host into an isolated workspace environment.

Run explicitly; application startup never downloads or installs dependencies.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
import venv
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive",
        type=Path,
        help="Use a previously downloaded archive; its checksum is still verified",
    )
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    manifest = json.loads((project / "config/hermes.lock.json").read_text())
    runtime = project / ".hermes-runtime"
    runtime.mkdir(exist_ok=True)
    archive = args.archive.resolve() if args.archive else runtime / "source.zip"
    url = f"https://codeload.github.com/NousResearch/hermes-agent/zip/{manifest['commit']}"
    if not args.archive:
        with (
            urllib.request.urlopen(url, timeout=60) as response,
            archive.open("wb") as output,
        ):
            total = 0
            while chunk := response.read(65536):
                total += len(chunk)
                if total > 64 * 1024 * 1024:
                    raise ValueError("Hermes source archive exceeds download limit")
                output.write(chunk)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest["archive_sha256"]:
        raise ValueError("Hermes source archive checksum mismatch")
    source_parent = runtime / "source"
    source_parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        if any(
            name.startswith(("/", "\\")) or ".." in Path(name).parts
            for name in bundle.namelist()
        ):
            raise ValueError("Unsafe source archive path")
        bundle.extractall(source_parent)
    environment = runtime / "venv"
    venv.create(environment, with_pip=True)
    python = environment / (
        "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    )
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "-r",
            str(project / "config/hermes-requirements.lock"),
        ],
        check=True,
    )
    source = source_parent / f"hermes-agent-{manifest['commit']}"
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-build-isolation",
            "-e",
            str(source),
        ],
        check=True,
    )
    print("Isolated Hermes installation prepared. It remains disabled.")
    print("MEMORY_HERMES_PYTHON=" + str(python))
    print("MEMORY_HERMES_SOURCE=" + str(source))


if __name__ == "__main__":
    main()
