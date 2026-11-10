"""Download and safely extract the two exact, sealed evidence archives.

This script downloads saved observations. It never runs a native application.
Only Python's standard library is needed. Downloads are pinned by SHA-256.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import urllib.request
import zipfile

RELEASE = "https://github.com/narimanmani/budgeted-ai-regression-testing/releases/download/v1.0.0"
ARCHIVES = {
    "v8": ("development_v8_evidence.zip", "99e7167f3b77bb1729bca020f38aba446a79d6dcbf8227a9dfaff32afa8cfbd3"),
    "v9": ("transfer_v9_evidence.zip", "5928f3a9eabf7d846f9488a3a2c99878b62bcc2babff8d7559cc0cec7300765f"),
}
MAX_FILE = 512 * 1024 * 1024
MAX_TOTAL = 2 * 1024 * 1024 * 1024
MAX_MEMBERS = 50002
FORBIDDEN = {".exe", ".dll", ".gguf", ".safetensors", ".pyc", ".pyo", ".db", ".sqlite", ".sqlite3", ".pkl", ".pickle", ".bin", ".npz", ".npy"}


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def safe_member(name):
    reserved = {"con", "prn", "aux", "nul"} | {f"{p}{n}" for p in ("com", "lpt") for n in range(1, 10)}
    if not name or "\\" in name or ":" in name or name.startswith("/"):
        raise ValueError("Unsafe ZIP path")
    for part in name.split("/"):
        if (part in {"", ".", ".."} or part.endswith((" ", ".")) or
                any(c in part for c in '<>"|?*\x00') or part.split(".")[0].lower() in reserved):
            raise ValueError("Unsafe or nonportable ZIP path")
    if Path(name).suffix.lower() in FORBIDDEN:
        raise ValueError("Unexpected runtime/model/database binary in evidence archive")
    return name


def checked_inventory(path, study):
    """Check the external archive commitment before trusting its manifest."""
    if sha256(path) != ARCHIVES[study][1]:
        raise ValueError("Archive SHA-256 differs from the sealed study commitment")
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        names = [safe_member(item.filename) for item in members]
        if len(names) > MAX_MEMBERS or len(set(n.casefold() for n in names)) != len(names):
            raise ValueError("Duplicate, case-colliding or oversized ZIP inventory")
        if any(item.is_dir() or stat.S_ISLNK(item.external_attr >> 16) or item.file_size > MAX_FILE for item in members):
            raise ValueError("Unsafe ZIP member type or size")
        if sum(item.file_size for item in members) > MAX_TOTAL:
            raise ValueError("Uncompressed evidence exceeds the 2-GiB safety limit")
        manifest = json.loads(archive.read("ARTIFACT_MANIFEST.json"))
        entries = manifest["files"]
        if isinstance(entries, list):
            entries = {row["path"]: row for row in entries}
        if not isinstance(entries, dict):
            raise ValueError("Unknown evidence manifest structure")
        extras = {"ARTIFACT_MANIFEST.json"} | ({"ARTIFACT_README.md"} if study == "v8" else set())
        if set(names) != set(entries) | extras:
            raise ValueError("ZIP inventory differs from the sealed manifest")
        for name, row in entries.items():
            safe_member(name)
            if not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
                raise ValueError("Invalid file hash in manifest")
            data = archive.read(name)  # Reading every member also validates its CRC.
            if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("Manifest-bound evidence file differs: " + name)
        # Metadata bytes are covered by the pinned whole-ZIP hash as well.
        if archive.testzip() is not None:
            raise ValueError("Evidence ZIP failed CRC verification")
    return names


def download(study, directory):
    filename, expected = ARCHIVES[study]
    target = directory / filename
    directory.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha256(target) != expected:
            raise ValueError(f"Existing {target} has the wrong hash; preserve or move it before retrying")
        return target
    partial = target.with_suffix(target.suffix + ".partial")
    if partial.exists():
        raise FileExistsError(f"A previous partial download exists: {partial}; inspect it before retrying")
    request = urllib.request.Request(RELEASE + "/" + filename, headers={"User-Agent": "budgeted-ai-regression-testing/1.0.0"})
    with urllib.request.urlopen(request, timeout=60) as response, partial.open("xb") as stream:
        if not response.geturl().lower().startswith("https://"):
            raise ValueError("Refusing a non-HTTPS release redirect")
        size = 0
        for block in iter(lambda: response.read(1024 * 1024), b""):
            size += len(block)
            if size > MAX_FILE:
                raise ValueError("Compressed archive exceeds the download safety limit")
            stream.write(block)
    if sha256(partial) != expected:
        raise ValueError(f"Download hash mismatch; retained for inspection: {partial}")
    partial.replace(target)
    return target


def extract(path, destination, study):
    names = checked_inventory(path, study)
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"Use a new extraction directory; refusing to mix or overwrite evidence: {destination}")
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(path) as archive:
        for name in names:
            target = destination.joinpath(*name.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as source, target.open("xb") as stream:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    stream.write(block)
    return {"study": study, "archive": str(path), "sha256": ARCHIVES[study][1],
            "extraction": str(destination), "files": len(names), "new_native_or_model_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", choices=["v8", "v9", "all"], default="all")
    repository = Path(__file__).resolve().parents[1]
    parser.add_argument("--archives-dir", type=Path, default=repository / "downloads" / "archives", help="Directory for pinned ZIP downloads")
    parser.add_argument("--extract-dir", type=Path, default=repository / "extracted", help="Parent of separate new v8/v9 extraction directories")
    parser.add_argument("--download-only", action="store_true", help="Download and check hashes without extracting")
    args = parser.parse_args()
    for study in (["v8", "v9"] if args.study == "all" else [args.study]):
        path = download(study, args.archives_dir.resolve())
        if args.download_only:
            names = checked_inventory(path, study)
            result = {"study": study, "archive": str(path), "sha256": ARCHIVES[study][1], "verified_zip_files": len(names)}
        else:
            result = extract(path, args.extract_dir.resolve() / study, study)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
