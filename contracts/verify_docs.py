"""Run and type-check every Python and TypeScript code block in the documentation.

Blocks fenced as ```python run under the current interpreter and are checked
with mypy. Blocks fenced as ```ts run under Node with type stripping and are
checked with tsc; ```js and ```javascript blocks run under Node as ES modules.
Each block runs as its own program, twice, against the local contract fixture
with CAURA_URL and CAURA_API_KEY set. With --live, blocks run instead against
the backend named by the CAURA_URL, CAURA_API_KEY, and CAURA_TENANT already in
the environment. Add `no-run` to a fence's info string to skip a block that is
intentionally partial.

Usage: python contracts/verify_docs.py [--workdir DIR] [--live] [FILE ...]
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fixture import API_KEY, serve

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
FENCE = re.compile(r"^```([a-zA-Z]+)([^\n]*)\n(.*?)^```", re.MULTILINE | re.DOTALL)


def blocks(path: Path) -> list[tuple[str, str, str]]:
    return [(lang, info, code) for lang, info, code in FENCE.findall(path.read_text())]


def run(command: list[str], cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        command, cwd=cwd, env=env, capture_output=True, text=True, timeout=120, check=False
    )
    if result.returncode != 0:
        summary = " ".join(command[:2]) + " failed"
        raise RuntimeError(f"{summary}\n--- stdout\n{result.stdout}\n--- stderr\n{result.stderr}")
    return result.stdout


@contextmanager
def backend(live: bool) -> Iterator[dict[str, str]]:
    """Environment for one block: the shared live backend, or a fresh fixture."""
    if live:
        if "CAURA_URL" not in os.environ:
            raise SystemExit("--live needs CAURA_URL and CAURA_API_KEY in the environment")
        yield dict(os.environ)
        return
    with serve() as (url, _):
        env = {**os.environ, "CAURA_URL": url, "CAURA_API_KEY": API_KEY}
        env.pop("CAURA_TENANT", None)
        yield env


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workdir", type=Path, help="directory whose node_modules provides @caura/rail"
    )
    parser.add_argument("--live", action="store_true", help="use the backend from the environment")
    parser.add_argument("files", nargs="*", type=Path)
    args = parser.parse_args()
    files = [f.resolve() for f in args.files] or DEFAULT_FILES
    workdir = args.workdir or ROOT
    tsc = shutil.which("tsc", path=str(workdir / "node_modules" / ".bin")) or shutil.which("tsc")
    if not tsc:
        raise SystemExit("tsc not found: run npm ci or install typescript in the workdir")
    counts = {"python": 0, "ts": 0, "js": 0, "skipped": 0}
    runnable = {"python": "python", "ts": "ts", "js": "js", "javascript": "js"}
    with tempfile.TemporaryDirectory(dir=workdir, prefix=".docs-") as tmp:
        scratch = Path(tmp)
        (scratch / "package.json").write_text('{"type": "module"}\n')
        for path in files:
            for index, (lang, info, code) in enumerate(blocks(path), start=1):
                label = f"{path.name} block {index} ({lang})"
                kind = runnable.get(lang)
                if kind is None or "no-run" in info:
                    counts["skipped"] += kind is not None
                    continue
                ext = {"python": "py", "ts": "ts", "js": "mjs"}[kind]
                snippet = scratch / f"{path.stem}_{index}.{ext}"
                snippet.write_text(code)
                # Each block gets an empty backend so blocks cannot depend on each other,
                # and runs twice against it: memory persists, so a block must also hold
                # when the facts it writes already exist.
                with backend(args.live) as env:
                    try:
                        if kind == "python":
                            for _ in range(2):
                                run([sys.executable, str(snippet)], scratch, env)
                            run(
                                [
                                    sys.executable,
                                    "-m",
                                    "mypy",
                                    "--strict",
                                    "--allow-untyped-defs",
                                    "--allow-untyped-calls",
                                    str(snippet),
                                ],
                                scratch,
                                env,
                            )
                        elif kind == "js":
                            for _ in range(2):
                                run(["node", str(snippet)], scratch, env)
                        else:
                            for _ in range(2):
                                run(
                                    [
                                        "node",
                                        "--experimental-strip-types",
                                        "--no-warnings",
                                        str(snippet),
                                    ],
                                    scratch,
                                    env,
                                )
                            run(
                                [
                                    tsc,
                                    "--noEmit",
                                    "--strict",
                                    "--module",
                                    "nodenext",
                                    "--target",
                                    "es2022",
                                    "--allowImportingTsExtensions",
                                    "--types",
                                    "node",
                                    str(snippet),
                                ],
                                scratch,
                                env,
                            )
                        counts[kind] += 1
                        print("ok  ", label)
                    except RuntimeError as exc:
                        raise SystemExit(f"FAIL {label}\n{exc}") from None
    print(
        f"Documentation verified: {counts['python']} Python, {counts['ts']} TypeScript, and "
        f"{counts['js']} JavaScript blocks ran twice each"
        f"{' against ' + os.environ['CAURA_URL'] if args.live else ''}; "
        f"{counts['skipped']} marked no-run."
    )


if __name__ == "__main__":
    main()
