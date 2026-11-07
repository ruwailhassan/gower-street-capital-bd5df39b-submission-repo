#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Read-only file/secret preflight. No project commands or network requests."""

from __future__ import annotations

import argparse
import contextvars
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath

MAX_FILE_BYTES = 10 * 1024 * 1024
DEADLINE = contextvars.ContextVar("review_deadline", default=None)
GENERATED = {"node_modules", ".venv", "venv", "__pycache__"}
ARCHIVES = (".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar")
ASSET_SUFFIXES = ARCHIVES + (
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".mp3",
    ".mp4",
    ".woff",
    ".woff2",
    ".bin",
)
EXAMPLES = {".env.example", ".env.sample", ".env.template", ".env.dist"}
PRIVATE_NAMES = {
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "credentials.json",
    "service-account.json",
    "service_account.json",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "credentials",
}


class Incomplete(Exception):
    """A check could not safely finish. Its message must contain no source values."""


def remaining(timeout: float) -> float:
    deadline = DEADLINE.get()
    if deadline is not None:
        timeout = min(timeout, deadline - time.monotonic())
    if timeout <= 0:
        raise Incomplete(
            "Time limit reached. Secret scanning is unfinished; rerun before pushing."
        )
    return timeout


def command(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    data: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            input=data,
            capture_output=True,
            timeout=remaining(timeout),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        # Never forward process output or an exception containing command arguments.
        raise Incomplete(
            "Tool unavailable or time limit reached. Secret scanning is unfinished."
        ) from exc


def git_env() -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "GITLEAKS_"))
    }
    env.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_COUNT": "5",
            "GIT_CONFIG_KEY_0": "core.fsmonitor",
            "GIT_CONFIG_VALUE_0": "false",
            "GIT_CONFIG_KEY_1": "core.hooksPath",
            "GIT_CONFIG_VALUE_1": os.devnull,
            "GIT_CONFIG_KEY_2": "diff.external",
            "GIT_CONFIG_VALUE_2": "",
            "GIT_CONFIG_KEY_3": "core.pager",
            "GIT_CONFIG_VALUE_3": "cat",
            "GIT_CONFIG_KEY_4": "core.attributesFile",
            "GIT_CONFIG_VALUE_4": os.devnull,
        }
    )
    return env


def git(repo: Path, *args: str, timeout: int = 30) -> bytes:
    result = command(
        ["git", "--no-pager", *args], cwd=repo, env=git_env(), timeout=timeout
    )
    if result.returncode:
        raise Incomplete(
            "Git inspection failed; inspect locally without printing credentials."
        )
    return result.stdout


def split_paths(raw: bytes) -> list[str]:
    return [os.fsdecode(item) for item in raw.split(b"\0") if item]


def sensitive_name(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    if name in EXAMPLES:
        return False
    return (
        name == ".env"
        or name.startswith(".env.")
        or name in PRIVATE_NAMES
        or name.endswith((".pem", ".key", ".p12", ".pfx", ".keystore", ".jks"))
    )


def safe_path(root: Path, name: str) -> Path:
    parts = PurePosixPath(name).parts
    if (
        not parts
        or PurePosixPath(name).is_absolute()
        or any(p in {"..", ".git"} for p in parts)
    ):
        raise Incomplete("Unsafe candidate path; inspect locally.")
    candidate = root.joinpath(*parts)
    if not candidate.absolute().is_relative_to(root.absolute()):
        raise Incomplete("Candidate path leaves the repository; inspect locally.")
    return candidate


def read_working(root: Path, name: str) -> bytes | None:
    path = safe_path(root, name)
    # Check every component: never follow a tracked or untracked symlink.
    current = root
    for part in PurePosixPath(name).parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            return None  # Deleted working file; the index/history is still checked.
        if stat.S_ISLNK(mode):
            if current == path:
                # Git uploads the link text, never the linked file's contents.
                return os.fsencode(os.readlink(path))
            raise Incomplete("A parent folder is a symlink; inspect it separately.")
    if not stat.S_ISREG(path.stat().st_mode):
        raise Incomplete("Non-regular file or submodule needs separate inspection.")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise Incomplete("File exceeds the 10 MiB inspection limit.")
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise Incomplete("File grew beyond the inspection limit.")
    return data


def tree_check(repo: Path, report: dict, snapshot: Path, scope: str) -> dict:
    locations = {}
    if scope == "index":
        entries = []
        for raw in git(repo, "ls-files", "--stage", "-z").split(b"\0"):
            if not raw:
                continue
            header, name = raw.split(b"\t", 1)
            mode, oid, stage = header.decode("ascii").split()
            entries.append((os.fsdecode(name), mode, oid, stage))
    else:
        entries = [
            (name, None, None, None)
            for name in split_paths(
                git(
                    repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z"
                )
            )
        ]

    for name, mode, oid, stage in entries:
        remaining(30)
        try:
            safe_path(snapshot, name)
            if scope == "index":
                if stage != "0":
                    raise Incomplete("Unmerged index entry needs resolution.")
                if mode not in {"100644", "100755", "120000"}:
                    raise Incomplete(
                        "Submodule needs its own secret scan before pushing."
                    )
                size = int(git(repo, "cat-file", "-s", oid))
                if size > MAX_FILE_BYTES:
                    raise Incomplete("Staged file exceeds the 10 MiB inspection limit.")
                data = git(repo, "cat-file", "blob", oid)
            else:
                data = read_working(repo, name)
            if data is None:
                continue
            if sensitive_name(name):
                report["findings"].append(
                    {
                        "scope": scope,
                        "file": name,
                        "reason": "sensitive filename; investigate",
                    }
                )
            if needs_separate_review(name, data):
                report["needs_review"].append(
                    review_item(
                        scope,
                        name,
                        data,
                        "Inspect this asset and any embedded content, or leave it out of the upload. For LFS inspect the referenced payload.",
                    )
                )
            key = hashlib.sha256(data).hexdigest()
            locations.setdefault(key, []).append(name)
            # Do not let built-in filename allowlists hide project files.
            destination = snapshot / key
            destination.write_bytes(data)
            destination.chmod(0o600)
        except (Incomplete, OSError, ValueError) as exc:
            reason = (
                str(exc)
                if isinstance(exc, Incomplete)
                else "File could not be inspected."
            )
            report["incomplete"].append(
                {"scope": scope, "file": name, "reason": reason}
            )
    report["coverage"][scope] = {"candidate_entries": len(entries)}
    return locations


def needs_separate_review(name: str, data: bytes) -> bool:
    return (
        name.lower().endswith(ASSET_SUFFIXES)
        or b"\x00" in data[:8192]
        or data.startswith(
            (
                b"%PDF-",
                b"PK\x03\x04",
                b"SQLite format 3\x00",
                b"version https://git-lfs.github.com/spec/v1",
            )
        )
    )


def review_item(scope: str, name: str, data: bytes, reason: str) -> dict:
    return {
        "scope": scope,
        "file": name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "reason": reason,
    }


def housekeeping(repo: Path) -> list[dict]:
    """Group unignored dependency folders before reading thousands of their files."""
    untracked = split_paths(
        git(repo, "ls-files", "--others", "--exclude-standard", "-z")
    )
    folders = set()
    for name in untracked:
        parts = PurePosixPath(name).parts
        for index, part in enumerate(parts):
            if part in GENERATED:
                folders.add(PurePosixPath(*parts[: index + 1]).as_posix() + "/")
                break
    return [
        {
            "folder": name,
            "reason": "Add an appropriate .gitignore rule, then rerun. Do not upload dependencies or local environments.",
        }
        for name in sorted(folders)
    ]


def history_check(repo: Path, report: dict, snapshot: Path) -> None:
    """Scan full reachable blobs as files too, including files hidden by Git attributes."""
    raw = git(
        repo,
        "log",
        "--raw",
        "-z",
        "--format=",
        "--no-renames",
        "--root",
        "--no-ext-diff",
        "--no-textconv",
        "--full-history",
        "-m",
        "HEAD",
    )
    tokens = raw.split(b"\0")
    seen = set()
    entries = []
    cursor = 0
    while cursor < len(tokens):
        remaining(30)
        header = tokens[cursor].strip(b"\n")
        cursor += 1
        if not header:
            continue
        if not header.startswith(b":") or cursor >= len(tokens):
            raise Incomplete("Historical file inventory could not be parsed.")
        name = os.fsdecode(tokens[cursor])
        cursor += 1
        fields = header[1:].split()
        if len(fields) != 5:
            raise Incomplete("Historical file inventory is incomplete.")
        _, mode, _, oid, _ = (field.decode("ascii") for field in fields)
        if (
            mode == "000000"
        ):  # Deletion; the earlier added blob is enumerated separately.
            continue
        if sensitive_name(name):
            report["findings"].append(
                {
                    "scope": "history",
                    "file": name,
                    "reason": "sensitive filename in history; investigate",
                }
            )
        try:
            if mode not in {"100644", "100755", "120000"}:
                raise Incomplete(
                    "Historical symlink or submodule needs separate inspection."
                )
            if oid in seen:
                continue
            seen.add(oid)
            size = int(git(repo, "cat-file", "-s", oid))
            if size > MAX_FILE_BYTES:
                raise Incomplete("Historical file exceeds the 10 MiB inspection limit.")
            data = git(repo, "cat-file", "blob", oid)
            if needs_separate_review(name, data):
                report["needs_review"].append(
                    review_item(
                        "history",
                        name,
                        data,
                        "This asset is still in the commits being uploaded. Inspect that version and any embedded content, or arrange authorised history cleanup. For LFS inspect the referenced payload.",
                    )
                )
            destination = snapshot / oid
            destination.write_bytes(data)
            destination.chmod(0o600)
            entries.append({"blob": oid, "file": name})
        except (Incomplete, OSError, ValueError) as exc:
            reason = (
                str(exc)
                if isinstance(exc, Incomplete)
                else "Historical file could not be inspected."
            )
            report["incomplete"].append(
                {"scope": "history", "file": name, "reason": reason}
            )
    report["coverage"]["historical_blobs"] = {"candidate_entries": len(seen)}
    report["historical_blob_locations"] = entries


def scan(
    scanner: str,
    target: Path,
    scope: str,
    temp: Path,
    report: dict,
    timeout: int,
    locations: dict | None = None,
) -> None:
    report_path = temp / (scope + "-findings.json")
    args = [
        scanner,
        "git" if scope == "history" else "dir",
        str(target),
        "--config",
        str(temp / "gitleaks.toml"),
        "--gitleaks-ignore-path",
        str(temp / "empty.ignore"),
        "--ignore-gitleaks-allow",
        "--redact=100",
        "--no-banner",
        "--no-color",
        "--log-level",
        "debug",
        "--exit-code",
        "42",
        "--report-format",
        "json",
        "--report-path",
        str(report_path),
        "--timeout",
        str(timeout),
    ]
    if scope == "history":
        args += ["--log-opts=--full-history -m --no-ext-diff --no-textconv HEAD"]
    result = command(args, cwd=temp, env=git_env(), timeout=timeout + 5)
    if result.returncode not in {0, 42}:
        raise Incomplete(
            "Gitleaks failed. Raw output withheld to avoid credential exposure."
        )
    for line in (result.stdout + result.stderr).splitlines():
        if b"skipping binary file" not in line:
            continue
        try:
            raw_path = line.split(b"path=", 1)[1].decode("utf-8").strip()
            path = Path(json.loads(raw_path) if raw_path.startswith('"') else raw_path)
            name = path.relative_to(target).as_posix()
            originals = locations.get(name, [name]) if locations is not None else [name]
            for original in originals:
                report["needs_review"].append(
                    review_item(
                        scope,
                        original,
                        path.read_bytes(),
                        "The scanner cannot read this file format. Inspect its contents and attachments, or leave it out of the upload.",
                    )
                )
        except (IndexError, ValueError, OSError):
            raise Incomplete(
                "A skipped file could not be identified. Inspect scanner coverage locally."
            )
    if not report_path.is_file():
        raise Incomplete("Gitleaks did not produce a coverage report.")
    try:
        findings = json.loads(report_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise Incomplete("Gitleaks produced an unreadable report.") from exc
    if not isinstance(findings, list) or (result.returncode == 42 and not findings):
        raise Incomplete("Gitleaks exit status and report disagree.")
    for item in findings:
        if (
            not isinstance(item, dict)
            or not {"RuleID", "File", "StartLine"} <= item.keys()
        ):
            raise Incomplete("Gitleaks produced an incomplete finding.")
        name = str(item["File"])
        # Directory scans may return either a relative path or an absolute one.
        try:
            name = (
                str(Path(name).relative_to(target))
                if Path(name).is_absolute()
                else name
            )
        except ValueError:
            name = "<location outside snapshot; inspect locally>"
        originals = locations.get(name, [name]) if locations is not None else [name]
        for original in originals:
            report["findings"].append(
                {
                    "scope": scope,
                    "rule": item["RuleID"],
                    "file": original,
                    "line": item["StartLine"],
                    "commit": item.get("Commit", ""),
                }
            )
    report["coverage"].setdefault(scope, {})["scanner"] = "completed"


def _preflight(repo: Path, scanner: str, timeout: int) -> dict:
    report: dict = {
        "status": "INCOMPLETE",
        "head": None,
        "scanner_version": None,
        "coverage": {},
        "findings": [],
        "incomplete": [],
        "needs_review": [],
        "setup_needed": [],
        "readme_candidates": [],
        "note": "This checks files/secrets only; code, tests and README need review.",
    }
    try:
        repo = Path(
            os.fsdecode(git(repo, "rev-parse", "--show-toplevel")).strip()
        ).resolve()
        report["setup_needed"] = housekeeping(repo)
        if report["setup_needed"]:
            report["status"] = "SETUP_NEEDED"
            report["next_action"] = (
                "Ignore the listed dependency/environment folders, then rerun. No secret scan has run yet."
            )
            return compact(report)
        if git(repo, "rev-parse", "--is-shallow-repository").strip() == b"true":
            report["incomplete"].append(
                {"scope": "history", "reason": "Shallow history."}
            )
        head = command(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=repo,
            env=git_env(),
            timeout=30,
        )
        if head.returncode == 0:
            report["head"] = head.stdout.decode("ascii").strip()
        elif not git(repo, "symbolic-ref", "-q", "HEAD").strip():
            raise Incomplete("Cannot determine HEAD state.")

        version = command([scanner, "version"], cwd=repo, env=git_env(), timeout=10)
        match = re.fullmatch(rb"v?(\d+)\.(\d+)\.(\d+)\s*", version.stdout)
        if version.returncode or not match:
            raise Incomplete(
                "Gitleaks version unavailable; install official Gitleaks v8.30.1+."
            )
        number = tuple(int(part) for part in match.groups())
        if number < (8, 30, 1) or number[0] != 8:
            raise Incomplete(
                "Unsupported Gitleaks version; use v8.30.1+ in the v8 series."
            )
        report["scanner_version"] = ".".join(str(part) for part in number)

        with tempfile.TemporaryDirectory(prefix="review-preflight-") as directory:
            temp = Path(directory)
            temp.chmod(0o700)
            (temp / "gitleaks.toml").write_text(
                "[extend]\nuseDefault = true\n", encoding="utf-8"
            )
            (temp / "empty.ignore").write_text("", encoding="utf-8")
            for scope in ("index", "working"):
                snapshot = temp / scope
                snapshot.mkdir(mode=0o700)
                locations = tree_check(repo, report, snapshot, scope)
                scan(scanner, snapshot, scope, temp, report, timeout, locations)
            if report["head"]:
                scan(scanner, repo, "history", temp, report, timeout)
                history_snapshot = temp / "historical_blobs"
                history_snapshot.mkdir(mode=0o700)
                history_check(repo, report, history_snapshot)
                scan(
                    scanner, history_snapshot, "historical_blobs", temp, report, timeout
                )
                locations = {
                    entry["blob"]: entry["file"]
                    for entry in report.pop("historical_blob_locations")
                }
                for finding in report["findings"] + report["needs_review"]:
                    if finding["scope"] == "historical_blobs":
                        blob = Path(finding["file"]).name
                        finding["blob"] = blob
                        finding["file"] = locations.get(blob, finding["file"])
            else:
                report["coverage"]["history"] = {
                    "scanner": "not applicable: no commits yet"
                }

        candidates = split_paths(
            git(repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        )
        for name in sorted(set(candidates)):
            path = PurePosixPath(name)
            if path.parent.as_posix() in {
                ".",
                ".github",
                "docs",
            } and path.name.lower().startswith("readme"):
                report["readme_candidates"].append(name)
    except (Incomplete, OSError, ValueError) as exc:
        reason = (
            str(exc)
            if isinstance(exc, Incomplete)
            else "Preflight could not complete safely."
        )
        report["incomplete"].append({"scope": "preflight", "reason": reason})

    report["status"] = (
        "INCOMPLETE"
        if report["incomplete"]
        else "FINDINGS"
        if report["findings"]
        else "MANUAL_REVIEW"
        if report["needs_review"]
        else "PASS"
    )
    report["next_action"] = {
        "PASS": "No secrets detected in the scanned files. Continue with README/tests and the requested GitHub push.",
        "FINDINGS": "Resolve the suspected credentials before pushing. Never print the values.",
        "INCOMPLETE": "Finish the secret scan before pushing; see the incomplete checks.",
        "MANUAL_REVIEW": "Inspect the listed files separately and record evidence for their SHA-256 contents, or exclude them. They have not passed secret scanning.",
    }[report["status"]]
    return compact(report)


def compact(report: dict) -> dict:
    """Keep the report small. Missing details can never look like a clean result."""
    report.pop("historical_blob_locations", None)
    for key in ("findings", "incomplete", "needs_review", "setup_needed"):
        entries = report.get(key, [])
        unique = []
        seen = set()
        for entry in entries:
            signature = json.dumps(
                {
                    key: value
                    for key, value in entry.items()
                    if not (key == "reason" and "sha256" in entry)
                },
                sort_keys=True,
            )
            if signature not in seen:
                seen.add(signature)
                unique.append(entry)
        report[key + "_count"] = len(unique)
        report[key] = unique[:20]
        if len(unique) > 20:
            report[key + "_omitted"] = len(unique) - 20
    return report


def preflight(
    repo: Path, scanner: str, timeout: int, total_timeout: float = 180
) -> dict:
    token = DEADLINE.set(time.monotonic() + total_timeout)
    try:
        return _preflight(repo, scanner, timeout)
    finally:
        DEADLINE.reset(token)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path.cwd(), help="Project directory"
    )
    parser.add_argument(
        "--scanner", default="gitleaks", help="Official Gitleaks executable"
    )
    parser.add_argument(
        "--timeout", type=int, default=45, help="Seconds per Gitleaks scope"
    )
    parser.add_argument(
        "--total-timeout",
        type=int,
        default=180,
        help="Overall preflight time limit in seconds",
    )
    args = parser.parse_args()
    if args.timeout < 1 or args.total_timeout < 1:
        parser.error("Time limits must be positive")
    scanner = shutil.which(args.scanner)
    if not scanner:
        print(
            json.dumps(
                {
                    "status": "INCOMPLETE",
                    "reason": "Gitleaks unavailable; install it first.",
                }
            )
        )
        return 2
    report = preflight(args.repo.resolve(), scanner, args.timeout, args.total_timeout)
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return {
        "PASS": 0,
        "FINDINGS": 1,
        "INCOMPLETE": 2,
        "SETUP_NEEDED": 2,
        "MANUAL_REVIEW": 3,
    }[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
