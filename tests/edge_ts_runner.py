"""Shared runner for edge TypeScript behavior tests.

The edge tests execute Cloudflare Pages functions directly in Node. Keep the
Python -> Node boundary intentionally small: CI can run after Sentry has
patched ``subprocess.Popen``, and that patch records argv/env metadata for
every child process.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EDGE_TS_LOADER = REPO_ROOT / "tests" / "edge_ts_loader.mjs"
NODE_CRASH_SIGNALS = {
    sig
    for sig in (
        getattr(signal, "SIGABRT", None),
        getattr(signal, "SIGBUS", None),
        getattr(signal, "SIGSEGV", None),
    )
    if sig is not None
}


def run_edge_node(script: str, *, timeout: float = 20) -> subprocess.CompletedProcess[str]:
    """Run an ESM edge test script through the repo TS loader.

    The script is written to a temporary repo-root ``.mjs`` file instead of
    passed via ``node -e``. That keeps Sentry's subprocess span name small when
    its stdlib integration has patched ``Popen`` and also keeps large JS test
    bodies out of inherited process metadata.
    """
    node_path = shutil.which("node")
    if node_path is None:
        pytest.skip("node is required for edge TypeScript behavior tests")

    attempts: list[subprocess.CompletedProcess[str]] = []
    for attempt in range(2):
        script_path = _write_temp_script(script)
        try:
            proc = _run_node_script(node_path, script_path, timeout=timeout)
        finally:
            script_path.unlink(missing_ok=True)
        attempts.append(proc)
        if not _should_retry_node_crash(proc.returncode):
            break
        if attempt == 0:
            continue

    final = attempts[-1]
    if _should_skip_repeated_node_crash(attempts):
        pytest.skip(
            "Darwin-only skip: edge Node subprocess crashed repeatedly with "
            "a child-process signal; treating this as transient macOS runner "
            "instability.\n" + _format_failure(attempts)
        )
    assert final.returncode == 0, _format_failure(attempts)
    return final


def _write_temp_script(script: str) -> Path:
    fd, raw_path = tempfile.mkstemp(
        prefix=".edge-node-",
        suffix=".mjs",
        dir=REPO_ROOT,
        text=True,
    )
    path = Path(raw_path)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        body = textwrap.dedent(script)
        fh.write(body)
        if not body.endswith("\n"):
            fh.write("\n")
    return path


def _run_node_script(
    node_path: str,
    script_path: Path,
    *,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        node_path,
        "--loader",
        str(EDGE_TS_LOADER),
        str(script_path),
    ]
    with _without_sentry_subprocess_patch():
        return subprocess.run(
            cmd,
            capture_output=True,
            close_fds=False,
            text=True,
            timeout=timeout,
            check=False,
            env=_node_env(),
        )


def _node_env() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("SENTRY_") and not key.startswith("SUBPROCESS_")
    }
    # Keep unrelated parent-process loaders/tracers out of the child. The test
    # supplies the only loader it needs explicitly via ``--loader``.
    env.pop("NODE_OPTIONS", None)
    env.setdefault("NO_COLOR", "1")
    env.setdefault("NODE_DISABLE_COLORS", "1")
    return env


@contextlib.contextmanager
def _without_sentry_subprocess_patch():
    """Temporarily unwrap Sentry's stdlib ``Popen`` hooks for this local probe.

    Sentry stores the original functions on ``__wrapped__``. If some other
    wrapper is present we still restore exactly what we found.
    """
    patched: list[tuple[str, object]] = []
    for attr_name in ("__init__", "wait", "communicate"):
        current = getattr(subprocess.Popen, attr_name)
        original = current
        while True:
            wrapped = getattr(original, "__wrapped__", None)
            if wrapped is None:
                break
            original = wrapped
        if original is current:
            continue
        patched.append((attr_name, current))
        setattr(subprocess.Popen, attr_name, original)
    try:
        yield
    finally:
        for attr_name, current in reversed(patched):
            setattr(subprocess.Popen, attr_name, current)


def _is_node_crash(returncode: int) -> bool:
    if returncode >= 0:
        return False
    try:
        sig = signal.Signals(-returncode)
    except ValueError:
        return False
    return sig in NODE_CRASH_SIGNALS


def _should_retry_node_crash(returncode: int) -> bool:
    return sys.platform == "darwin" and _is_node_crash(returncode)


def _should_skip_repeated_node_crash(
    attempts: list[subprocess.CompletedProcess[str]],
) -> bool:
    return (
        sys.platform == "darwin"
        and len(attempts) > 1
        and all(_is_node_crash(proc.returncode) for proc in attempts)
    )


def _signal_name(returncode: int) -> str:
    if returncode >= 0:
        return str(returncode)
    try:
        return signal.Signals(-returncode).name
    except ValueError:
        return f"signal {-returncode}"


def _format_failure(attempts: list[subprocess.CompletedProcess[str]]) -> str:
    chunks: list[str] = []
    for index, proc in enumerate(attempts, start=1):
        chunks.append(
            f"edge node attempt {index} exited rc={proc.returncode} "
            f"({_signal_name(proc.returncode)})"
        )
        if proc.stderr:
            chunks.append("stderr:\n" + proc.stderr)
        if proc.stdout:
            chunks.append("stdout:\n" + proc.stdout)
    return "\n".join(chunks)
