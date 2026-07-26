# Source Review and Approval Checklist

All 15 documents begin as:

`review_status: "draft_requires_source_review"`

They are substantive production candidates with authoritative references, but
they must not be used by learner-facing RAG until a human review approves them.

## Review each document independently

1. Read the entire document for factual accuracy and beginner clarity.
2. Open every URL under `References and Further Reading`.
3. Confirm the source title, publisher, and topic match the statement.
4. Remove or rewrite any unsupported statement.
5. Confirm each hypothetical amount, company, or outcome is clearly labeled.
6. Confirm there is no current-security recommendation, return guarantee,
   personalized advice, fabricated statistic, or fabricated citation.
7. Confirm formulas define variables, rate periods, and units.
8. Confirm every Knowledge Check answer matches the teaching text.
9. Confirm time-sensitive material has a date and requires periodic review.
10. Change only the reviewed document's front matter:

```yaml
review_status: "approved_seed"
reviewed_at: "YYYY-MM-DD"
```

11. Refresh the manifest:

```powershell
python scripts\validate_seed_knowledge.py --update-hashes
```

12. Re-run normal validation.

Do not perform a global search-and-replace to approve all documents.

## Review order

- C2.1: documents 01–05
- C2.2: documents 06–10
- C2.3: documents 11–15

The default validator permits a collection containing both drafts and approved
documents. Before learner-facing C3 ingestion, every document must pass:

```powershell
python scripts\validate_seed_knowledge.py --require-approved
```
