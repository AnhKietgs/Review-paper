# Grounded author questions

1. Add harness tests for a grounded question and an invalid question after its bounded repair. The latter must be absent from completed findings but present in the run trace.
2. Give questions a distinct `grounded` outcome after evidence verification. Omit questions that remain ungrounded at completion. Keep claim findings unchanged.
3. Render grounded questions in a separate report section with source quotes and locations. Keep them out of supported and unsupported claim totals.
4. Split questions from scientific findings in the review page; show a source-linked author-question section.
5. Run focused backend tests, frontend checks, and the existing backend suite. Rebuild Docker services if available.
