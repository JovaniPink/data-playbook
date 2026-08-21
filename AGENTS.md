# Repository guidance

- Treat `application-patterns.md`, `auditing-bigquery.md`, `filling-bigquery.md`, and `ba.sql` as working reference material. Do not imply that they are deployable modules.
- Keep archive validation local and deterministic. Tests must not use live Google Cloud credentials or mutate a bucket.
- Preserve exact-byte custody: snapshot and hash the source once, then inspect and extract only that snapshot.
- Preserve create-only publication semantics. Every write uses a generation-match precondition, `_manifest.json` is a reserved input path, and the publisher writes it last.
- Use uv 0.12.5 through the immutable `astral-sh/setup-uv` action in CI. Do not bootstrap executable tooling through an unverified runtime `pip install` step.
- Stage explicit files only and preserve unrelated work.
- Before a handoff, run `./scripts/check.sh` with Python 3.14 and the locked environment.
