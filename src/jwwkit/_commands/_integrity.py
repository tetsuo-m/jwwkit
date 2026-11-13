"""Offline checks for package data and the installed wheel's RECORD."""
import base64
import hashlib
from importlib import metadata
from pathlib import Path

from jwwkit import template_path


_TEMPLATE_SHA256 = "0913d5f6755b7038c11cda8be75c2502511ce85a007f9bcc2f10df049f6eff1e"
_DRAWINGS = {".jww", ".jws", ".jwc", ".jwk", ".jwf", ".dxf", ".pdf"}


def check_installed_files() -> int:
    template = template_path()
    package_root = template.parent.parent
    if hashlib.sha256(template.read_bytes()).hexdigest() != _TEMPLATE_SHA256:
        raise ValueError("Installed empty template hash mismatch")

    files = set()
    for path in package_root.rglob("*"):
        if "__pycache__" in path.parts:
            continue
        if path.is_symlink() or getattr(path.stat(), "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Link or reparse point in jwwkit: {path}")
        if not path.is_file():
            continue
        if path.name.casefold() in {"desktop.ini", "thumbs.db"} or path.suffix == ".pyc":
            continue
        if path.name.casefold() == "ai_settings_summary.json":
            raise ValueError(f"Personal JWF summary in jwwkit: {path}")
        if path.suffix.casefold() in _DRAWINGS and path != template:
            raise ValueError(f"Unexpected drawing in jwwkit: {path}")
        files.add(path)

    distribution = metadata.distribution("jwwkit")
    records = {
        Path(item.locate()): item
        for item in distribution.files or ()
        if item.parts[0] == "jwwkit" and "__pycache__" not in item.parts
    }
    # Editable installations record the path hook and metadata, not package files.
    if records:
        if set(records) != files:
            extra = sorted(str(path.relative_to(package_root)) for path in files - records.keys())
            missing = sorted(str(path.relative_to(package_root)) for path in records.keys() - files)
            raise ValueError(f"Unexpected or missing installed jwwkit files: extra={extra}, missing={missing}")
        for path, record in records.items():
            data = path.read_bytes()
            if record.hash is None or record.size != len(data):
                raise ValueError(f"Installed jwwkit file size or RECORD mismatch: {path.name}")
            digest = hashlib.new(record.hash.mode, data).digest()
            if base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii") != record.hash.value:
                raise ValueError(f"Installed jwwkit file hash mismatch: {path.name}")
    return len(files)
