"""Create and publish a workspace-owned ib-suite virtual environment."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform as platform_module
import shutil
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass


SKILL_ROOT = Path(__file__).resolve().parent.parent
READY_FILE = ".ready"
OWNER_FILE = "owner.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_digest(source_root: Path) -> str:
    """Hash packaged ib-common sources without timestamps or cache files."""
    files = [source_root / "pyproject.toml"]
    package_root = source_root / "ib_common"
    files.extend(
        path
        for path in package_root.rglob("*")
        if path.is_file() and path.suffix == ".py" and "__pycache__" not in path.parts
    )
    digest = hashlib.sha256()
    for path in sorted(files):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"ib-common source is missing or unsafe: {path}")
        relative = path.relative_to(source_root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def runtime_fingerprint(
    lock_file: str | Path,
    source_root: str | Path,
    runtime: Mapping[str, str],
) -> str:
    """Return a stable fingerprint for one runtime and packaged source revision."""
    lock_path = Path(lock_file)
    payload = {
        "runtime": dict(sorted(runtime.items())),
        "runtime_lock_sha256": _sha256_file(lock_path),
        "ib_common_source_sha256": _source_digest(Path(source_root)),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def validate_roots(
    skill_root: str | Path, workspace_root: str | Path
) -> tuple[Path, Path]:
    """Resolve and validate separate, existing skill and workspace roots."""
    skill = Path(skill_root).expanduser().resolve(strict=True)
    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    if not skill.is_dir() or not workspace.is_dir():
        raise ValueError("skill root and workspace root must be directories")
    if (
        workspace == Path(workspace.anchor)
        or workspace == skill
        or _is_relative_to(workspace, skill)
    ):
        raise ValueError("workspace root must be a writable directory outside the skill root")
    if not os.access(workspace, os.W_OK | os.X_OK):
        raise ValueError(f"workspace root is not writable: {workspace}")
    return skill, workspace


def _ensure_real_directory(path: Path) -> None:
    if path.exists() or os.path.lexists(path):
        if path.is_symlink() or not path.is_dir():
            raise ValueError(f"managed state path must be a real directory: {path}")
        return
    path.mkdir(mode=0o700)


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass
class BootstrapLock:
    """Directory lock with owner metadata and conservative stale recovery."""

    path: Path
    fingerprint: str
    timeout: float = 120.0
    stale_after: float = 1800.0
    poll_interval: float = 0.2

    def __post_init__(self) -> None:
        self.token = uuid.uuid4().hex
        self._acquired = False

    def _owner_payload(self) -> dict[str, object]:
        return {
            "token": self.token,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "started_at": time.time(),
            "fingerprint": self.fingerprint,
        }

    def _read_owner(self) -> dict[str, object] | None:
        try:
            raw = (self.path / OWNER_FILE).read_text(encoding="utf-8")
            data = json.loads(raw)
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _is_stale(self, owner: dict[str, object] | None) -> bool:
        if owner is not None and owner.get("hostname") == socket.gethostname():
            pid = owner.get("pid")
            if isinstance(pid, int) and _pid_is_alive(pid):
                return False
            return True
        try:
            age = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return False
        return age > self.stale_after

    def _reclaim(self) -> None:
        stale = self.path.with_name(f"{self.path.name}.stale.{self.token}")
        try:
            os.replace(self.path, stale)
        except FileNotFoundError:
            return
        except OSError:
            return
        shutil.rmtree(stale, ignore_errors=True)

    def __enter__(self) -> "BootstrapLock":
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self.path.mkdir(mode=0o700)
            except FileExistsError:
                owner = self._read_owner()
                if self._is_stale(owner):
                    self._reclaim()
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"timed out waiting for bootstrap lock {self.path}; owner={owner}"
                    )
                time.sleep(self.poll_interval)
                continue
            (self.path / OWNER_FILE).write_text(
                json.dumps(self._owner_payload(), sort_keys=True), encoding="utf-8"
            )
            self._acquired = True
            return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if not self._acquired:
            return
        owner = self._read_owner()
        if owner is not None and owner.get("token") == self.token:
            shutil.rmtree(self.path, ignore_errors=True)


def publish_venv(state_root: str | Path, target: str | Path, token: str) -> None:
    """Atomically make an already-ready versioned environment the stable entry."""
    state = Path(state_root)
    target_path = Path(target).resolve(strict=True)
    venvs = (state / "venvs").resolve(strict=True)
    if not _is_relative_to(target_path, venvs) or not (target_path / READY_FILE).is_file():
        raise ValueError("ready venv target must be inside the managed venvs directory")

    stable = state / "venv"
    if os.path.lexists(stable) and not stable.is_symlink():
        raise ValueError(f"refusing to replace non-symlink venv entry: {stable}")
    temporary = state / f".venv.link.{token}"
    if os.path.lexists(temporary):
        temporary.unlink()
    temporary.symlink_to(target_path)
    os.replace(temporary, stable)


def validate_wheelhouse(
    wheelhouse: str | Path,
    *,
    platform: str,
    machine: str,
    abi: str,
    runtime_lock_sha256: str,
    ib_common_source_sha256: str,
) -> Path:
    """Validate an offline wheelhouse manifest and return the one ib-common wheel."""
    root = Path(wheelhouse).resolve(strict=True)
    manifest_path = root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise ValueError("wheelhouse manifest is missing or malformed") from error
    expected = {
        "platform": platform,
        "machine": machine,
        "abi": abi,
        "runtime_lock_sha256": runtime_lock_sha256,
        "ib_common_source_sha256": ib_common_source_sha256,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"wheelhouse {key} does not match this runtime")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("wheelhouse manifest files must be a mapping")
    for name, expected_hash in files.items():
        path = root / name
        if not isinstance(name, str) or path.is_symlink() or not path.is_file():
            raise ValueError(f"wheelhouse file is missing or unsafe: {name}")
        if _sha256_file(path) != expected_hash:
            raise ValueError(f"wheelhouse hash mismatch: {name}")
    ib_common = sorted(root.glob("ib_common-*.whl"))
    if len(ib_common) != 1:
        raise ValueError("wheelhouse must contain exactly one ib-common wheel")
    return ib_common[0]


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def copy_build_source(source_root: str | Path, temporary_root: str | Path) -> Path:
    """Copy package sources to owned temporary storage before wheel building."""
    source = Path(source_root)
    destination = Path(temporary_root) / "ib-common-source"
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("build", "*.egg-info", "__pycache__", "*.pyc"),
    )
    return destination


def _runtime_identity() -> dict[str, str]:
    return {
        "implementation": platform_module.python_implementation().lower(),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "abi": getattr(sys, "abiflags", "") or f"cp{sys.version_info.major}{sys.version_info.minor}",
        "platform": sys.platform,
        "machine": platform_module.machine().lower(),
    }


def _ready_matches(path: Path, fingerprint: str) -> bool:
    try:
        payload = json.loads((path / READY_FILE).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    return payload.get("fingerprint") == fingerprint


def bootstrap(
    workspace_root: str | Path,
    *,
    offline: bool = False,
    wheelhouse: str | Path | None = None,
    lock_timeout: float = 120.0,
    stale_after: float = 1800.0,
) -> Path:
    """Build or reuse a managed environment and return its stable Python path."""
    previous_umask = os.umask(0o077)
    try:
        skill_root, workspace = validate_roots(SKILL_ROOT, workspace_root)
        state = workspace / ".ib-suite"
        _ensure_real_directory(state)
        venvs = state / "venvs"
        temporary_root = state / "tmp"
        _ensure_real_directory(venvs)
        _ensure_real_directory(temporary_root)

        lock_file = skill_root / "requirements-runtime.lock"
        build_lock = skill_root / "requirements-build.lock"
        source_root = skill_root / "ib-common"
        identity = _runtime_identity()
        fingerprint = runtime_fingerprint(lock_file, source_root, identity)
        target = venvs / fingerprint

        with BootstrapLock(state / "bootstrap.lock", fingerprint, lock_timeout, stale_after) as lock:
            if _ready_matches(target, fingerprint):
                publish_venv(state, target, lock.token)
                return state / "venv" / "bin" / "python"
            if target.exists() or os.path.lexists(target):
                if target.is_symlink() or not target.is_dir():
                    raise ValueError(f"unsafe incomplete venv path: {target}")
                shutil.rmtree(target)

            _run([sys.executable, "-m", "venv", str(target)])
            target_python = target / "bin" / "python"
            lock_hash = _sha256_file(lock_file)
            source_hash = _source_digest(source_root)
            owner_tmp = temporary_root / lock.token
            owner_tmp.mkdir(mode=0o700)
            try:
                if offline:
                    if wheelhouse is None:
                        raise ValueError("--offline requires --wheelhouse")
                    ib_common_wheel = validate_wheelhouse(
                        wheelhouse,
                        platform=identity["platform"],
                        machine=identity["machine"],
                        abi=identity["abi"],
                        runtime_lock_sha256=lock_hash,
                        ib_common_source_sha256=source_hash,
                    )
                    pip_options = ["--no-index", "--find-links", str(Path(wheelhouse).resolve())]
                else:
                    pip_options = ["--only-binary=:all:"]
                    build_venv = owner_tmp / "build-venv"
                    _run([sys.executable, "-m", "venv", str(build_venv)])
                    build_python = build_venv / "bin" / "python"
                    _run(
                        [
                            str(build_python),
                            "-m",
                            "pip",
                            "install",
                            "--require-hashes",
                            "-r",
                            str(build_lock),
                        ]
                    )
                    wheel_dir = owner_tmp / "wheelhouse"
                    wheel_dir.mkdir()
                    build_source = copy_build_source(source_root, owner_tmp)
                    _run(
                        [
                            str(build_python),
                            "-m",
                            "build",
                            "--wheel",
                            "--no-isolation",
                            "--outdir",
                            str(wheel_dir),
                            str(build_source),
                        ]
                    )
                    wheels = sorted(wheel_dir.glob("ib_common-*.whl"))
                    if len(wheels) != 1:
                        raise ValueError("local ib-common build did not produce exactly one wheel")
                    ib_common_wheel = wheels[0]

                _run(
                    [
                        str(target_python),
                        "-m",
                        "pip",
                        "install",
                        *pip_options,
                        "--require-hashes",
                        "-r",
                        str(lock_file),
                    ]
                )
                _run(
                    [
                        str(target_python),
                        "-m",
                        "pip",
                        "install",
                        *pip_options,
                        "--no-deps",
                        str(ib_common_wheel),
                    ]
                )
                _run([str(target_python), "-m", "pip", "check"])
                _run([str(target_python), "-c", "import ib_common"])
                (target / READY_FILE).write_text(
                    json.dumps(
                        {
                            "fingerprint": fingerprint,
                            "runtime_lock_sha256": lock_hash,
                            "ib_common_source_sha256": source_hash,
                        },
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                publish_venv(state, target, lock.token)
            finally:
                shutil.rmtree(owner_tmp, ignore_errors=True)
        return state / "venv" / "bin" / "python"
    finally:
        os.umask(previous_umask)


def main() -> None:
    """Run the workspace bootstrap command-line interface."""
    parser = argparse.ArgumentParser(description="Create the ib-suite workspace environment")
    parser.add_argument("--workspace-root", required=True, help="existing writable consumer workspace")
    parser.add_argument("--offline", action="store_true", help="forbid package-index access")
    parser.add_argument("--wheelhouse", help="verified wheelhouse for --offline")
    parser.add_argument("--lock-timeout", type=float, default=120.0)
    parser.add_argument("--stale-after", type=float, default=1800.0)
    args = parser.parse_args()
    python = bootstrap(
        args.workspace_root,
        offline=args.offline,
        wheelhouse=args.wheelhouse,
        lock_timeout=args.lock_timeout,
        stale_after=args.stale_after,
    )
    print(f"venv ready: {python}")


if __name__ == "__main__":
    main()
