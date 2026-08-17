# Data Playbook knowledge index

Data Playbook combines working reference notes with one bounded executable
archive publisher. The root [`README.md`](../README.md) is authoritative for the
publisher's current safety and validation contract. The other root documents are
working references, not deployable modules.

## Current map

| Material | Purpose | Authority boundary |
| --- | --- | --- |
| [`README.md`](../README.md) | Archive validation and create-only Cloud Storage publication | Current executable contract |
| [`application-patterns.md`](../application-patterns.md) | Application and data-flow patterns | Working reference; review for the target system |
| [`auditing-bigquery.md`](../auditing-bigquery.md) | BigQuery audit notes | Working reference; not a production runbook |
| [`filling-bigquery.md`](../filling-bigquery.md) | BigQuery loading notes | Working reference; not a deployment module |
| [`ba.sql`](../ba.sql) | SQL reference material | Query example; validate schema, cost, and permissions before use |

## Knowledge lifecycle

Use [`note-template.md`](note-template.md) when a scratch note is worth sharing.
A committed note must identify its status, scope, owner, dates, sources,
evidence, and promotion target.

```text
draft note -> sourced research -> tested procedure or accepted decision
          \-> superseded, rejected, or retained as dated evidence
```

- **Draft** means useful for review, not approved or validated.
- **Observed** means supported by named evidence at a stated time.
- **Verified** means the documented validation passed on an exact revision and
  environment; it is not a claim about another environment.
- **Accepted** means a decision owner chose the documented option.
- **Superseded** preserves history while pointing to the replacement.

Do not store credentials, customer data, proprietary source material, or raw
provider payloads in notes. Public availability is not evidence of permitted
bulk collection or redistribution.

## Maintenance

- Prefer updating a current contract over adding a contradictory note.
- Preserve dated evidence rather than silently rewriting what an old run proved.
- Link relative files and exact commits where possible; record retrieval and
  review dates for external sources.
- Move existing root notes only as a separate, link-audited change. This index
  intentionally does not rename established paths.
