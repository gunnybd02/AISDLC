"""The MCP server that follows the release in force without a restart (docs: blue/green release). Before each line it
reads state/live/current; a release it does not run yet is checked first by that release's own doctor (in a process of
its own: loader, names, argument types, ports, effects, rules, nets) and only a clean one is swapped in: the harness
modules are dropped and imported again from the new release. A release that fails the check is never taken (the one in
force goes on answering) and is not checked again. Run without boot (no HARNESS_CODE), it serves the work tree as is."""
import importlib
import os
import subprocess
import sys
from pathlib import Path

from harness.assemble.engine.build import CODE_ENV
from harness.utils.gateway.release import current, release_dir

CHECK_TIMEOUT = 120


def healthy(home, code):
    """Whether the release's own doctor finds no problem, for the home."""
    env = {**os.environ, "HARNESS_HOME": str(home), CODE_ENV: str(code)}
    try:
        p = subprocess.run([sys.executable, str(Path(code) / "entry" / "doctor.py")], env=env, capture_output=True,
                           timeout=CHECK_TIMEOUT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return p.returncode == 0


def load(home, code):
    """The MCP server of the code folder, imported afresh: every harness module is dropped and read again from it."""
    old = os.environ.get(CODE_ENV)
    for name in [m for m in sys.modules if m == "harness" or m.startswith("harness.")]:
        del sys.modules[name]
    sys.path[:] = [p for p in sys.path if p != old]
    sys.path.insert(0, str(code))
    os.environ[CODE_ENV] = str(code)
    return importlib.import_module("harness.assemble.engine.wire_mcp").build_server(home)


def serve_live(instream, outstream, home):
    home = Path(home)
    live = bool(os.environ.get(CODE_ENV))  # started by entry/boot.py: it follows the releases
    from harness.assemble.engine.wire_mcp import build_server
    server, running, refused = build_server(home), current(home) if live else None, set()
    for line in instream:
        sha = current(home) if live else None
        if sha and sha != running and sha not in refused:
            code = release_dir(home, sha)
            if healthy(home, code):
                server, running = load(home, code), sha
            else:
                refused.add(sha)
        server.serve_line(line, outstream)
