"""Validate a tar archive and publish its regular files to Cloud Storage.

The publication contract is intentionally conservative: every archive member is
validated before extraction, objects are create-only, and the manifest is
written last. A manifest therefore marks a complete publication.
"""

from __future__ import annotations

import argparse
import bz2
import gzip
import hashlib
import json
import lzma
import sys
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud import storage

DEFAULT_MAX_MEMBERS = 10_000
DEFAULT_MAX_BYTES = 1_073_741_824
MANIFEST_NAME = "_manifest.json"
RESERVED_MEMBER_PATHS = frozenset({MANIFEST_NAME})
READ_CHUNK_SIZE = 1024 * 1024
MAX_CONSECUTIVE_METADATA_HEADERS = 64


class ArchiveValidationError(ValueError):
    """The archive does not satisfy the bounded extraction contract."""


class PublicationConflict(RuntimeError):
    """An object already exists with content different from this publication."""


def _bounded_raw_header_scan(path: Path, *, max_members: int) -> None:
    """Bound headers tarfile consumes internally before it yields a member."""

    with path.open("rb") as raw:
        magic = raw.read(6)
    opener = (
        gzip.open
        if magic.startswith(b"\x1f\x8b")
        else bz2.open
        if magic.startswith(b"BZh")
        else lzma.open
        if magic.startswith(b"\xfd7zXZ\x00")
        else open
    )
    count = 0
    metadata_chain = 0
    with opener(path, "rb") as source:
        while True:
            header = source.read(512)
            if not header or header == b"\0" * 512:
                return
            if len(header) != 512:
                raise ArchiveValidationError("archive ends inside a tar header")
            count += 1
            if count > max_members:
                raise ArchiveValidationError(
                    f"archive exceeds the {max_members:,} member limit"
                )
            type_flag = header[156:157]
            metadata_types = {
                tarfile.XHDTYPE,
                tarfile.XGLTYPE,
                tarfile.GNUTYPE_LONGNAME,
                tarfile.GNUTYPE_LONGLINK,
            }
            if type_flag in metadata_types:
                metadata_chain += 1
                if metadata_chain > MAX_CONSECUTIVE_METADATA_HEADERS:
                    raise ArchiveValidationError(
                        "archive contains too many consecutive metadata headers"
                    )
            else:
                metadata_chain = 0
            try:
                size = tarfile.nti(header[124:136])
            except ValueError as error:
                raise ArchiveValidationError(
                    "archive contains an invalid member size"
                ) from error
            if size < 0:
                raise ArchiveValidationError("archive contains a negative member size")
            padded_size = ((size + 511) // 512) * 512
            if len(source.read(padded_size)) != padded_size:
                raise ArchiveValidationError("archive ends inside a member payload")


@dataclass(frozen=True)
class PreparedFile:
    """A validated, extracted regular file and its immutable lineage."""

    path: str
    local_path: Path
    size: int
    sha256: str


@dataclass(frozen=True)
class PreparedArchive:
    """The extracted files and deterministic archive manifest."""

    archive_path: Path
    archive_size: int
    archive_sha256: str
    files: tuple[PreparedFile, ...]

    @property
    def total_uncompressed_bytes(self) -> int:
        return sum(item.size for item in self.files)

    def manifest(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "archive": {
                "name": self.archive_path.name,
                "sha256": self.archive_sha256,
                "size": self.archive_size,
            },
            "file_count": len(self.files),
            "total_uncompressed_bytes": self.total_uncompressed_bytes,
            "files": [
                {"path": item.path, "sha256": item.sha256, "size": item.size}
                for item in self.files
            ],
        }

    def manifest_bytes(self) -> bytes:
        payload = json.dumps(
            self.manifest(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        return f"{payload}\n".encode()


@dataclass(frozen=True)
class PublicationResult:
    """The object-level result of a completed publication."""

    bucket: str
    prefix: str
    uploaded: tuple[str, ...]
    existing: tuple[str, ...]
    manifest_object: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "prefix": self.prefix,
            "uploaded": list(self.uploaded),
            "existing": list(self.existing),
            "manifest_object": self.manifest_object,
        }


@dataclass(frozen=True)
class _Member:
    member: tarfile.TarInfo
    path: str


def _snapshot_archive(source_path: Path, snapshot_path: Path) -> tuple[int, str]:
    """Copy and hash the exact source bytes that the validator will inspect."""

    digest = hashlib.sha256()
    size = 0
    with source_path.open("rb") as source, snapshot_path.open("xb") as snapshot:
        for chunk in iter(lambda: source.read(READ_CHUNK_SIZE), b""):
            snapshot.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _normalise_member_path(name: str) -> str | None:
    if "\x00" in name:
        raise ArchiveValidationError("archive member names cannot contain NUL bytes")
    if "\\" in name:
        raise ArchiveValidationError(f"archive member uses a backslash: {name!r}")

    raw = PurePosixPath(name)
    if raw.is_absolute():
        raise ArchiveValidationError(f"archive member is absolute: {name!r}")

    parts = tuple(part for part in raw.parts if part not in ("", "."))
    if any(part == ".." for part in parts):
        raise ArchiveValidationError(f"archive member escapes the root: {name!r}")
    if not parts:
        return None
    return PurePosixPath(*parts).as_posix()


def _inspect_members(
    archive: tarfile.TarFile, *, max_members: int, max_bytes: int
) -> tuple[_Member, ...]:
    if max_members <= 0:
        raise ArchiveValidationError("max_members must be greater than zero")
    if max_bytes <= 0:
        raise ArchiveValidationError("max_bytes must be greater than zero")

    accepted: list[_Member] = []
    seen: set[str] = set()
    total_bytes = 0

    # Iterate lazily so the member ceiling stops header parsing instead of first
    # materializing an unbounded list with TarFile.getmembers().
    for member_count, member in enumerate(archive, start=1):
        if member_count > max_members:
            raise ArchiveValidationError(
                f"archive exceeds the {max_members:,} member limit"
            )
        path = _normalise_member_path(member.name)
        if path is None:
            if member.isdir():
                continue
            raise ArchiveValidationError("the archive root must be a directory")

        if path in RESERVED_MEMBER_PATHS:
            raise ArchiveValidationError(
                f"archive member uses a reserved publication path: {path!r}"
            )

        if not (member.isdir() or member.isreg()):
            raise ArchiveValidationError(
                f"archive member is not a regular file or directory: {member.name!r}"
            )
        if path in seen:
            raise ArchiveValidationError(
                f"archive contains a duplicate normalized path: {path!r}"
            )

        seen.add(path)
        accepted.append(_Member(member=member, path=path))

        if member.isreg():
            if member.size < 0:
                raise ArchiveValidationError(
                    f"archive member has a negative size: {member.name!r}"
                )
            total_bytes += member.size
            if total_bytes > max_bytes:
                raise ArchiveValidationError(
                    f"archive exceeds the {max_bytes:,} byte limit"
                )

    file_paths = {item.path for item in accepted if item.member.isreg()}
    if not file_paths:
        raise ArchiveValidationError("archive contains no regular files")

    for file_path in file_paths:
        prefix = f"{file_path}/"
        if any(other.startswith(prefix) for other in seen if other != file_path):
            raise ArchiveValidationError(
                f"regular file is also used as a parent path: {file_path!r}"
            )

    return tuple(accepted)


def _extract_files(
    archive: tarfile.TarFile, members: tuple[_Member, ...], destination: Path
) -> tuple[PreparedFile, ...]:
    prepared: list[PreparedFile] = []
    for item in sorted(members, key=lambda value: value.path):
        if item.member.isdir():
            continue

        local_path = destination.joinpath(*PurePosixPath(item.path).parts)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        source = archive.extractfile(item.member)
        if source is None:
            raise ArchiveValidationError(
                f"could not read regular file: {item.member.name!r}"
            )

        digest = hashlib.sha256()
        bytes_written = 0
        with source, local_path.open("xb") as target:
            while chunk := source.read(READ_CHUNK_SIZE):
                target.write(chunk)
                digest.update(chunk)
                bytes_written += len(chunk)

        if bytes_written != item.member.size:
            raise ArchiveValidationError(
                f"archive member size changed while reading: {item.member.name!r}"
            )
        prepared.append(
            PreparedFile(
                path=item.path,
                local_path=local_path,
                size=bytes_written,
                sha256=digest.hexdigest(),
            )
        )

    return tuple(prepared)


@contextmanager
def prepare_archive(
    archive_path: str | Path,
    *,
    max_members: int = DEFAULT_MAX_MEMBERS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> Iterator[PreparedArchive]:
    """Validate and extract an archive into a self-cleaning temporary directory."""

    path = Path(archive_path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ArchiveValidationError(f"archive is not a regular file: {path}")

    with tempfile.TemporaryDirectory(prefix="data-playbook-") as temporary:
        temporary_root = Path(temporary)
        snapshot_path = temporary_root / "archive.snapshot"
        destination = temporary_root / "files"
        try:
            destination.mkdir()
            archive_size, archive_sha256 = _snapshot_archive(path, snapshot_path)
            _bounded_raw_header_scan(snapshot_path, max_members=max_members)
            with tarfile.open(snapshot_path, "r:*") as archive:
                members = _inspect_members(
                    archive, max_members=max_members, max_bytes=max_bytes
                )
                files = _extract_files(archive, members, destination)
        except (tarfile.TarError, OSError, RecursionError) as error:
            raise ArchiveValidationError(f"could not read archive: {error}") from error

        yield PreparedArchive(
            archive_path=path,
            archive_size=archive_size,
            archive_sha256=archive_sha256,
            files=files,
        )


def _normalise_prefix(prefix: str) -> str:
    if "\x00" in prefix or "\\" in prefix:
        raise ValueError("prefix cannot contain NUL bytes or backslashes")
    value = prefix.strip("/")
    parts = tuple(part for part in PurePosixPath(value).parts if part not in ("", "."))
    if any(part == ".." for part in parts):
        raise ValueError("prefix cannot contain parent traversal")
    return PurePosixPath(*parts).as_posix() if parts else ""


def _object_name(prefix: str, relative_path: str) -> str:
    name = f"{prefix}/{relative_path}" if prefix else relative_path
    if len(name.encode()) > 1_024:
        raise ValueError(f"Cloud Storage object name exceeds 1,024 bytes: {name!r}")
    return name


def _matches_existing(blob: Any, *, sha256: str, size: int) -> bool:
    blob.reload()
    metadata = blob.metadata or {}
    if (
        blob.size is None
        or int(blob.size) != size
        or metadata.get("sha256") != sha256
        or blob.generation is None
    ):
        return False
    # Custom SHA metadata is caller-writable. Verify the bytes of the loaded
    # generation, with bounded reads, before treating a collision as reusable.
    digest = hashlib.sha256()
    consumed = 0
    try:
        with blob.open(
            "rb",
            chunk_size=READ_CHUNK_SIZE,
            if_generation_match=blob.generation,
            raw_download=True,
            timeout=60,
        ) as source:
            while chunk := source.read(min(READ_CHUNK_SIZE, size - consumed + 1)):
                consumed += len(chunk)
                if consumed > size:
                    return False
                digest.update(chunk)
    except NotFound, PreconditionFailed:
        return False
    return consumed == size and digest.hexdigest() == sha256


def _upload_file(blob: Any, item: PreparedFile) -> str:
    blob.metadata = {"sha256": item.sha256}
    try:
        blob.upload_from_filename(
            str(item.local_path),
            if_generation_match=0,
            checksum="auto",
            timeout=60,
        )
    except PreconditionFailed as error:
        if _matches_existing(blob, sha256=item.sha256, size=item.size):
            return "existing"
        raise PublicationConflict(
            f"gs://{blob.bucket.name}/{blob.name} already exists with different content"
        ) from error
    return "uploaded"


def _upload_manifest(blob: Any, payload: bytes) -> str:
    sha256 = hashlib.sha256(payload).hexdigest()
    blob.metadata = {"sha256": sha256}
    try:
        blob.upload_from_string(
            payload,
            content_type="application/json; charset=utf-8",
            if_generation_match=0,
            checksum="auto",
            timeout=60,
        )
    except PreconditionFailed as error:
        if _matches_existing(blob, sha256=sha256, size=len(payload)):
            return "existing"
        raise PublicationConflict(
            f"gs://{blob.bucket.name}/{blob.name} already exists with different content"
        ) from error
    return "uploaded"


def publish_prepared_archive(
    prepared: PreparedArchive,
    *,
    bucket_name: str,
    prefix: str = "",
    project: str | None = None,
    client: Any | None = None,
) -> PublicationResult:
    """Publish validated files create-only and write the manifest last."""

    normalized_prefix = _normalise_prefix(prefix)
    storage_client = client or storage.Client(project=project)
    bucket = storage_client.bucket(bucket_name)
    uploaded: list[str] = []
    existing: list[str] = []

    for item in prepared.files:
        object_name = _object_name(normalized_prefix, item.path)
        status = _upload_file(bucket.blob(object_name), item)
        (uploaded if status == "uploaded" else existing).append(object_name)

    manifest_object = _object_name(normalized_prefix, MANIFEST_NAME)
    manifest_status = _upload_manifest(
        bucket.blob(manifest_object), prepared.manifest_bytes()
    )
    (uploaded if manifest_status == "uploaded" else existing).append(manifest_object)

    return PublicationResult(
        bucket=bucket_name,
        prefix=normalized_prefix,
        uploaded=tuple(uploaded),
        existing=tuple(existing),
        manifest_object=manifest_object,
    )


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a tar archive and publish its files create-only."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_archive_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("archive", type=Path)
        command.add_argument(
            "--max-members", type=_positive_integer, default=DEFAULT_MAX_MEMBERS
        )
        command.add_argument(
            "--max-bytes", type=_positive_integer, default=DEFAULT_MAX_BYTES
        )

    validate = subparsers.add_parser(
        "validate", help="validate locally and print the deterministic manifest"
    )
    add_archive_arguments(validate)

    publish = subparsers.add_parser(
        "publish", help="publish files to Cloud Storage and write the manifest last"
    )
    add_archive_arguments(publish)
    publish.add_argument("bucket")
    publish.add_argument("--prefix", default="")
    publish.add_argument("--project")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        with prepare_archive(
            args.archive, max_members=args.max_members, max_bytes=args.max_bytes
        ) as prepared:
            if args.command == "validate":
                print(json.dumps(prepared.manifest(), indent=2, sort_keys=True))
                return 0

            result = publish_prepared_archive(
                prepared,
                bucket_name=args.bucket,
                prefix=args.prefix,
                project=args.project,
            )
            print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
            return 0
    except (ArchiveValidationError, PublicationConflict, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
