# Contribution and whole-document omission handling

## Intent

Resolve two recurring review findings automatically. A contribution claim with a bad quotation gets one bounded revision using the original source chunk. A claim that a detail is absent from a paper is evaluated only after the full main document has been processed.

## Contribution branch

- Keep the existing exact-quote and locator gate and semantic Evidence Verifier.
- In a repair, constrain the Scientific Review Agent to the original contribution claim and allowed source chunks. The revised claim must match what the author actually states; a proposed or possible benefit cannot become a proven contribution.
- If the one revision still fails, retain an unverified finding with its reason; never manufacture supporting evidence.

## Omission branch

- Scientific Review emits `kind=omission` for document-wide claims of missing or unreported information. It may cite a related passage, but that passage is context rather than proof of absence.
- The harness defers each omission until every main-paper chunk is processed. Evidence Verifier then audits the omission against the full extracted text in bounded chunk groups, sequentially. A finding is refuted if any group shows the detail is present. An ambiguous group prevents a conclusive omission result.
- Only when all chunks were examined and no group shows the detail is the result `not_reported`. The wording must limit the claim to the extracted version of the uploaded paper. The trace records the audited chunk IDs and outcome.
- A run that stops before full coverage cannot label an omission `not_reported`.
- The report and UI show `not_reported` separately from evidence-supported claims. They disclose that this is a bounded search over extracted text, not proof that the authors never discussed the detail elsewhere.

## Limits

- No new external search, database migration, or human approval step.
- Keep the four logical agents and one worker per harness turn.
