# Data Playbook

Data Playbook is a collection of working notes and utilities for Google Cloud data
work. The executable part of the repository is a bounded tar archive publisher:
it validates an archive locally, extracts only regular files into a temporary
directory, and can publish those files create-only to Cloud Storage.

The Markdown and SQL files remain reference notes. They are not packaged,
tested deployment modules and should be reviewed for the target project before
use.

The repository knowledge map and shareable-note lifecycle are documented in
[`docs/README.md`](docs/README.md).

## Archive publication contract

`untar.py` separates local validation from cloud mutation:

1. Inspect every member before extracting anything.
2. Accept directories and regular files only.
3. Reject absolute paths, parent traversal, backslashes, links, devices,
   duplicate normalized paths, and file/directory hierarchy collisions.
4. Enforce member-count and total-uncompressed-byte limits.
5. Copy and hash an exact, automatically cleaned local snapshot, then inspect and
   extract only that snapshot so the archive lineage and extracted bytes cannot
   come from different source revisions.
6. Reserve `_manifest.json` for the publisher; an archive cannot supply its own
   completion marker.
7. Stream accepted files into an automatically cleaned temporary directory while
   calculating SHA-256 hashes.
8. Upload every object with `if_generation_match=0`; an existing object is
   accepted only when its size, stored SHA-256 metadata, and a bounded SHA-256
   readback of its loaded generation all match.
9. Write `_manifest.json` last. Its presence marks a complete publication.

The default limits are 10,000 members, including ignored root directories, and
1 GiB of uncompressed regular-file content. Use lower limits when the expected dataset permits it.

## Set up

Python 3.14 and [uv](https://docs.astral.sh/uv/) are required.

```bash
python -m pip install uv==0.12.5
uv sync --all-groups --frozen
```

Runtime and development dependencies are exact-pinned in `pyproject.toml` and
fully resolved in `uv.lock`. Renovate monitors Python packages, the uv workflow,
and digest-pinned GitHub Actions.

## Validate locally

Validation does not create a Cloud Storage client and does not require Google
credentials:

```bash
uv run python untar.py validate ./source.tar.gz
uv run python untar.py validate ./source.tar.gz \
  --max-members 2_000 \
  --max-bytes 536870912
```

Successful validation prints the deterministic manifest that would accompany a
publication, including the archive digest and each file's normalized path,
size, and SHA-256 digest.

## Publish to Cloud Storage

Authenticate with [Application Default Credentials](https://cloud.google.com/docs/authentication/provide-credentials-adc)
and choose a new, immutable prefix for each dataset or run:

```bash
uv run python untar.py publish ./source.tar.gz example-bucket \
  --project example-project \
  --prefix imports/2026-08-12/source-a
```

The caller needs permission to create objects and read object bytes and metadata in the
target bucket. This tool does not create buckets, change IAM, delete objects, or
overwrite an existing generation.

If a publish stops partway through, `_manifest.json` is absent. Rerun the same
command to verify and reuse exact objects, then continue. Any existing object
with different content stops the run before the manifest is written. Prefer a
new prefix over cleanup; if rollback is required, the bucket owner should review
and remove the exact generations intentionally.

The manifest is a publication-completeness and lineage record. It does not prove
that a downstream load, query, or business workflow succeeded.

## Quality gate

```bash
./scripts/check.sh
```

The gate verifies the lockfile, syncs the frozen environment, runs Ruff lint and
format checks, executes the isolated test suite, and audits the resolved Python
environment for known vulnerabilities. Tests use an in-memory Cloud Storage fake
and never contact Google Cloud.

## Why the safeguards exist

Python warns that extracting untrusted archives without inspection can be
dangerous even with modern extraction filters. Cloud Storage uploads overwrite
live objects unless callers supply preconditions. This utility snapshots and
hashes the exact bytes it inspects, rejects a source-supplied completion marker,
performs its own bounded member inspection, and uses the create-only generation
precondition on every write.

- [Python `tarfile` security guidance](https://docs.python.org/3.14/library/tarfile.html)
- [Cloud Storage request preconditions](https://cloud.google.com/storage/docs/request-preconditions)
- [Cloud Storage Python `Blob` API](https://cloud.google.com/python/docs/reference/storage/latest/google.cloud.storage.blob.Blob)
