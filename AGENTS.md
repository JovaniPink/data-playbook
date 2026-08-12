# Repository guidance

- Treat `application-patterns.md`, `auditing-bigquery.md`, `filling-bigquery.md`, and `ba.sql` as working reference material. Do not imply that they are deployable modules.
- Keep archive validation local and deterministic. Tests must not use live Google Cloud credentials or mutate a bucket.
- Preserve create-only publication semantics. Every write uses a generation-match precondition, and `_manifest.json` is written last.
- Stage explicit files only and preserve unrelated work.
- Before a handoff, run `./scripts/check.sh` with Python 3.14 and the locked environment.
