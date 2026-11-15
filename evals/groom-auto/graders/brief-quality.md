---
type: llm
focus: {source: file, path: "_chopchop/001-PAY-120-refunds-for-card-payments/requirements/brief.md"}
weight: 2
---

These are the BA's stories the brief must stay true to:
PAY-121 Customer requests a refund: within 30 days of the payment; the smallest refund is 0.01; the customer sees the refund as pending right away.
PAY-122 Support agent cancels a refund: only while it is pending; the customer gets one email when the refund is done.

Ignore the YAML front matter and the HTML comment markers: chopchop writes those.
PASS if: the brief has a Summary of a few short lines; it says what will be built and for whom; PAY-121 and PAY-122 are each under In scope or Out of scope; the five limits above appear with the same numbers and meaning (30 days, 0.01, pending right away, cancel only while pending, one email when done); and the sentences are short and plain.
FAIL if a story is missing from the scope, a limit is changed, softened or dropped, the Summary is missing, or the text is long, vague or full of jargon. Extra assumptions listed under Assumptions or Open questions are fine.
