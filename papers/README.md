# Paper ID Allowlists

Put one Coalescence paper ID per line in a text file.

Example `papers/bigbangtest.txt`:

```text
paper_123
paper_456
paper_789
```

Blank lines and lines starting with `#` are ignored.

Use with:

```bash
coalescence-reviewer review-feed --paper-ids-file papers/bigbangtest.txt
```
