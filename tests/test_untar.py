from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path
from typing import Any

import pytest
from google.api_core.exceptions import PreconditionFailed

import untar


def make_archive(
    tmp_path: Path,
    members: list[tuple[str, bytes | None, bytes | None]],
) -> Path:
    archive_path = tmp_path / "input.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, content, link_type in members:
            info = tarfile.TarInfo(name)
            if link_type is not None:
                info.type = link_type
                info.linkname = "target"
                archive.addfile(info)
            elif content is None:
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            else:
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
    return archive_path


class FakeBlob:
    def __init__(self, bucket: FakeBucket, name: str) -> None:
        self.bucket = bucket
        self.name = name
        self.metadata: dict[str, str] | None = None
        self.size: int | None = None
        self.generation: int | None = None

    def upload_from_filename(self, filename: str, **kwargs: Any) -> None:
        self.bucket.calls.append((self.name, "file", kwargs))
        self._store(Path(filename).read_bytes())

    def upload_from_string(self, payload: bytes, **kwargs: Any) -> None:
        self.bucket.calls.append((self.name, "manifest", kwargs))
        self._store(payload)

    def _store(self, payload: bytes) -> None:
        if self.name in self.bucket.objects:
            raise PreconditionFailed("already exists")
        self.bucket.objects[self.name] = {
            "payload": payload,
            "metadata": dict(self.metadata or {}),
        }

    def reload(self) -> None:
        existing = self.bucket.objects[self.name]
        payload = existing["payload"]
        assert isinstance(payload, bytes)
        self.size = len(payload)
        metadata = existing["metadata"]
        assert isinstance(metadata, dict)
        self.metadata = metadata
        self.generation = 1

    def open(self, mode: str, **kwargs: Any) -> io.BytesIO:
        assert mode == "rb"
        assert kwargs["if_generation_match"] == self.generation
        assert kwargs["chunk_size"] == untar.READ_CHUNK_SIZE
        assert kwargs["raw_download"] is True
        payload = self.bucket.objects[self.name]["payload"]
        assert isinstance(payload, bytes)
        return io.BytesIO(payload)


class FakeBucket:
    def __init__(self, name: str) -> None:
        self.name = name
        self.objects: dict[str, dict[str, object]] = {}
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)


class FakeClient:
    def __init__(self) -> None:
        self.buckets: dict[str, FakeBucket] = {}

    def bucket(self, name: str) -> FakeBucket:
        return self.buckets.setdefault(name, FakeBucket(name))


def test_prepare_archive_preserves_nested_paths_and_builds_manifest(
    tmp_path: Path,
) -> None:
    archive_path = make_archive(
        tmp_path,
        [
            ("folder/", None, None),
            ("folder/two.txt", b"two", None),
            ("one.txt", b"one", None),
        ],
    )

    with untar.prepare_archive(archive_path) as prepared:
        assert [item.path for item in prepared.files] == [
            "folder/two.txt",
            "one.txt",
        ]
        assert prepared.files[0].local_path.read_bytes() == b"two"
        assert prepared.manifest()["total_uncompressed_bytes"] == 6
        assert prepared.manifest()["file_count"] == 2
        assert prepared.manifest_bytes().endswith(b"\n")


@pytest.mark.parametrize("name", ["../escape.txt", "/absolute.txt", "a\\b.txt"])
def test_prepare_archive_rejects_unsafe_paths(tmp_path: Path, name: str) -> None:
    archive_path = make_archive(tmp_path, [(name, b"bad", None)])

    with (
        pytest.raises(untar.ArchiveValidationError),
        untar.prepare_archive(archive_path),
    ):
        pass


@pytest.mark.parametrize(
    "link_type",
    [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE],
)
def test_prepare_archive_rejects_links(tmp_path: Path, link_type: bytes) -> None:
    archive_path = make_archive(tmp_path, [("link", None, link_type)])

    with (
        pytest.raises(untar.ArchiveValidationError, match="not a regular file"),
        untar.prepare_archive(archive_path),
    ):
        pass


def test_prepare_archive_rejects_duplicate_normalized_paths(tmp_path: Path) -> None:
    archive_path = make_archive(
        tmp_path,
        [
            ("folder/file.txt", b"one", None),
            ("folder/./file.txt", b"two", None),
        ],
    )

    with (
        pytest.raises(untar.ArchiveValidationError, match="duplicate"),
        untar.prepare_archive(archive_path),
    ):
        pass


@pytest.mark.parametrize("name", ["_manifest.json", "./_manifest.json"])
def test_prepare_archive_rejects_reserved_completion_marker(
    tmp_path: Path, name: str
) -> None:
    archive_path = make_archive(tmp_path, [(name, b"not-a-publication-manifest", None)])

    with (
        pytest.raises(untar.ArchiveValidationError, match="reserved publication path"),
        untar.prepare_archive(archive_path),
    ):
        pass


def test_prepare_archive_manifest_describes_the_validated_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_path = make_archive(tmp_path, [("one.txt", b"one", None)])
    source_bytes = archive_path.read_bytes()
    extract_files = untar._extract_files

    def mutate_source_after_extract(*args: object, **kwargs: object):
        prepared = extract_files(*args, **kwargs)
        archive_path.write_bytes(b"source changed after the snapshot")
        return prepared

    monkeypatch.setattr(untar, "_extract_files", mutate_source_after_extract)
    with untar.prepare_archive(archive_path) as prepared:
        assert prepared.archive_size == len(source_bytes)
        assert prepared.archive_sha256 == hashlib.sha256(source_bytes).hexdigest()
        assert prepared.files[0].local_path.read_bytes() == b"one"


def test_prepare_archive_rejects_file_parent_collision(tmp_path: Path) -> None:
    archive_path = make_archive(
        tmp_path, [("folder", b"one", None), ("folder/file.txt", b"two", None)]
    )

    with (
        pytest.raises(untar.ArchiveValidationError, match="parent path"),
        untar.prepare_archive(archive_path),
    ):
        pass


def test_prepare_archive_enforces_member_and_byte_limits(tmp_path: Path) -> None:
    archive_path = make_archive(
        tmp_path, [("one.txt", b"one", None), ("two.txt", b"two", None)]
    )

    with (
        pytest.raises(untar.ArchiveValidationError, match="member limit"),
        untar.prepare_archive(archive_path, max_members=1),
    ):
        pass
    with (
        pytest.raises(untar.ArchiveValidationError, match="byte limit"),
        untar.prepare_archive(archive_path, max_bytes=5),
    ):
        pass


@pytest.mark.parametrize("root_name", [".", "./"])
def test_prepare_archive_counts_ignored_root_directories(
    tmp_path: Path, root_name: str
) -> None:
    archive_path = make_archive(
        tmp_path,
        [(root_name, None, None), (root_name, None, None), ("file.txt", b"ok", None)],
    )

    with (
        pytest.raises(untar.ArchiveValidationError, match="member limit"),
        untar.prepare_archive(archive_path, max_members=2),
    ):
        pass

    with untar.prepare_archive(archive_path, max_members=3) as prepared:
        assert [item.path for item in prepared.files] == ["file.txt"]


def test_prepare_archive_counts_pax_headers_before_tarfile_filters_them(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "pax.tar"
    with tarfile.open(archive_path, "w") as archive:
        for index in range(2):
            header = tarfile.TarInfo(f"pax-{index}")
            header.type = tarfile.XHDTYPE
            archive.addfile(header)
        content = b"ok"
        file_info = tarfile.TarInfo("file.txt")
        file_info.size = len(content)
        archive.addfile(file_info, io.BytesIO(content))

    with (
        pytest.raises(untar.ArchiveValidationError, match="member limit"),
        untar.prepare_archive(archive_path, max_members=2),
    ):
        pass


def test_prepare_archive_rejects_unbounded_metadata_header_chains(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "pax-chain.tar"
    with tarfile.open(archive_path, "w") as archive:
        for index in range(untar.MAX_CONSECUTIVE_METADATA_HEADERS + 1):
            header = tarfile.TarInfo(f"pax-{index}")
            header.type = tarfile.XHDTYPE
            archive.addfile(header)

    with (
        pytest.raises(
            untar.ArchiveValidationError,
            match="too many consecutive metadata headers",
        ),
        untar.prepare_archive(archive_path),
    ):
        pass


def test_publish_is_create_only_nested_and_manifest_last(tmp_path: Path) -> None:
    archive_path = make_archive(
        tmp_path, [("folder/two.txt", b"two", None), ("one.txt", b"one", None)]
    )
    client = FakeClient()

    with untar.prepare_archive(archive_path) as prepared:
        result = untar.publish_prepared_archive(
            prepared,
            bucket_name="example",
            prefix="imports/run-1",
            client=client,
        )

    bucket = client.bucket("example")
    assert result.uploaded == (
        "imports/run-1/folder/two.txt",
        "imports/run-1/one.txt",
        "imports/run-1/_manifest.json",
    )
    assert [call[0] for call in bucket.calls][-1] == result.manifest_object
    assert [call[1] for call in bucket.calls][-1] == "manifest"
    assert all(call[2]["if_generation_match"] == 0 for call in bucket.calls)
    assert all(call[2]["checksum"] == "auto" for call in bucket.calls)
    manifest = json.loads(bucket.objects[result.manifest_object]["payload"])
    assert manifest["file_count"] == 2


def test_publish_rerun_accepts_exact_objects(tmp_path: Path) -> None:
    archive_path = make_archive(tmp_path, [("one.txt", b"one", None)])
    client = FakeClient()

    with untar.prepare_archive(archive_path) as prepared:
        untar.publish_prepared_archive(
            prepared, bucket_name="example", prefix="run", client=client
        )
        result = untar.publish_prepared_archive(
            prepared, bucket_name="example", prefix="run", client=client
        )

    assert result.uploaded == ()
    assert result.existing == ("run/one.txt", "run/_manifest.json")


def test_publish_rejects_mismatched_existing_object(tmp_path: Path) -> None:
    archive_path = make_archive(tmp_path, [("one.txt", b"one", None)])
    client = FakeClient()
    bucket = client.bucket("example")
    bucket.objects["run/one.txt"] = {
        "payload": b"different",
        "metadata": {"sha256": "not-the-source-digest"},
    }

    with (
        untar.prepare_archive(archive_path) as prepared,
        pytest.raises(untar.PublicationConflict, match="different content"),
    ):
        untar.publish_prepared_archive(
            prepared, bucket_name="example", prefix="run", client=client
        )

    assert "run/_manifest.json" not in bucket.objects


def test_validate_cli_does_not_construct_storage_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archive_path = make_archive(tmp_path, [("one.txt", b"one", None)])

    def fail_client(*args: object, **kwargs: object) -> None:
        raise AssertionError("validate must not construct a Cloud Storage client")

    monkeypatch.setattr(untar.storage, "Client", fail_client)
    assert untar.main(["validate", str(archive_path)]) == 0
    assert json.loads(capsys.readouterr().out)["file_count"] == 1


def test_publish_rejects_same_size_bytes_with_matching_metadata(tmp_path: Path) -> None:
    archive_path = make_archive(tmp_path, [("one.txt", b"one", None)])
    client = FakeClient()
    bucket = client.bucket("example")
    bucket.objects["run/one.txt"] = {
        "payload": b"two",
        "metadata": {"sha256": hashlib.sha256(b"one").hexdigest()},
    }
    with (
        untar.prepare_archive(archive_path) as prepared,
        pytest.raises(untar.PublicationConflict, match="different content"),
    ):
        untar.publish_prepared_archive(
            prepared, bucket_name="example", prefix="run", client=client
        )
    assert "run/_manifest.json" not in bucket.objects


def test_publish_rejects_corrupt_completion_marker_with_matching_metadata(
    tmp_path: Path,
) -> None:
    archive_path = make_archive(tmp_path, [("one.txt", b"one", None)])
    client = FakeClient()
    with untar.prepare_archive(archive_path) as prepared:
        untar.publish_prepared_archive(
            prepared, bucket_name="example", prefix="run", client=client
        )
        marker = client.bucket("example").objects["run/_manifest.json"]
        payload = marker["payload"]
        assert isinstance(payload, bytes)
        marker["payload"] = b"x" + payload[1:]
        with pytest.raises(untar.PublicationConflict, match="different content"):
            untar.publish_prepared_archive(
                prepared, bucket_name="example", prefix="run", client=client
            )


def test_publish_stops_when_existing_generation_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = make_archive(tmp_path, [("one.txt", b"one", None)])
    client = FakeClient()
    client.bucket("example").objects["run/one.txt"] = {
        "payload": b"one",
        "metadata": {"sha256": hashlib.sha256(b"one").hexdigest()},
    }

    def changed_generation(self: FakeBlob, mode: str, **kwargs: Any) -> io.BytesIO:
        assert kwargs["if_generation_match"] == 1
        raise PreconditionFailed("generation changed")

    monkeypatch.setattr(FakeBlob, "open", changed_generation)
    with (
        untar.prepare_archive(archive_path) as prepared,
        pytest.raises(untar.PublicationConflict),
    ):
        untar.publish_prepared_archive(
            prepared, bucket_name="example", prefix="run", client=client
        )
    assert "run/_manifest.json" not in client.bucket("example").objects
