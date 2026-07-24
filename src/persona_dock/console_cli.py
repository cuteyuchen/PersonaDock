from __future__ import annotations

import sys
from typing import Any

from persona_dock import stable_cli


def configure_console_streams() -> None:
    """Use one UTF-8 CLI contract across Windows, macOS, and Linux.

    Windows standalone executables otherwise inherit a legacy console code page.
    JSON containing non-ASCII Persona fields can then raise UnicodeEncodeError.
    Reconfiguration is skipped for StringIO/test wrappers that do not expose it.
    """

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            # Embedded hosts may lock their standard streams. Commands can still
            # run; only direct non-ASCII console rendering may be constrained.
            continue


def main(argv: list[str] | None = None) -> int:
    configure_console_streams()
    return stable_cli.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["configure_console_streams", "main"]
