from __future__ import annotations

import argparse
import os
import subprocess
import time
from pathlib import Path

from verify_binary import _free_port, _http_get, _stop_process_tree


def _require(port: int, path: str, markers: tuple[bytes, ...] = ()) -> bytes:
    status, body = _http_get(port, path)
    if status != 200:
        raise AssertionError(f"unexpected status for {path}: {status}")
    for marker in markers:
        if marker not in body:
            raise AssertionError(f"missing Vue marker for {path}: {marker!r}")
    return body


def verify(binary: Path) -> None:
    port = _free_port()
    environment = dict(os.environ)
    process = subprocess.Popen(
        [
            str(binary),
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-browser",
        ],
        cwd=binary.parent,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 30
        last_error: BaseException | None = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                raise RuntimeError(
                    f"Web process exited before Vue verification ({process.returncode}):\n{output}"
                )
            try:
                index = _require(
                    port,
                    "/vue",
                    (b'id="app"', b'/assets/vue/app.js', b'/assets/vue/app.css'),
                )
                javascript = _require(port, "/assets/vue/app.js")
                stylesheet = _require(port, "/assets/vue/app.css")
                if len(index) < 200 or len(javascript) < 20_000 or len(stylesheet) < 2_000:
                    raise AssertionError(
                        {
                            "index_bytes": len(index),
                            "javascript_bytes": len(javascript),
                            "stylesheet_bytes": len(stylesheet),
                        }
                    )
                if b"PersonaDock" not in javascript:
                    raise AssertionError("Vue JavaScript bundle is missing the PersonaDock marker")
                if b"--sidebar" not in stylesheet:
                    raise AssertionError("Vue stylesheet is missing PersonaDock design tokens")
                return
            except BaseException as error:
                last_error = error
                time.sleep(0.5)
        raise RuntimeError(f"Vue frontend did not become ready: {last_error}")
    finally:
        _stop_process_tree(process)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify embedded Vue assets in PersonaDock binary.")
    parser.add_argument("--binary", required=True, type=Path)
    arguments = parser.parse_args()
    binary = arguments.binary.expanduser().resolve()
    if not binary.is_file():
        raise FileNotFoundError(binary)
    verify(binary)
    print(f"Verified embedded Vue frontend: {binary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
