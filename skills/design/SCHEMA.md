# Design files

Four files carry the data. You (or a helper) write them. The script checks them, draws from
them, and builds `design/options.md`, the generated blocks of `design/design.md`, and
`feature.html`.

## design/architecture.json and design/flow.json

The two diagrams. Their format, with a full example and the failure questions each message
kind must answer, is in the diagram skill: `../diagram/references/format.md`.

## work/options.json

The real choices, written before the design and kept after the picks.

```json
{
  "understood": {"text": "3 to 5 lines: the idea said back.", "confidence": "high"},
  "follow": [{"text": "Refund status changes copy order cancel.",
              "cite": "payments-api/src/orders/cancel/OrderCancelService.java:12-17@a1f9c2e"}],
  "leave": [{"text": "CardClient has no retry wrapper. We add refund() the same way as payout().",
             "why": "Refactoring it is a separate change.",
             "cite": "payments-api/src/provider/CardClient.java:4@a1f9c2e"}],
  "choices": [
    {"kind": "conflict", "question": "Which error shape do refunds use?",
     "why": "payments-api returns errors two ways.",
     "options": [
       {"key": "A", "title": "ApiError", "fit": "follows", "fit_note": "Follows order cancel",
        "rows": {"Used in": "orders and payments", "web-app": "already reads it"}},
       {"key": "B", "title": "ProblemDetail", "fit": "bends", "fit_note": "Only payouts use it",
        "rows": {"Used in": "payouts", "web-app": "needs a second error reader"}}],
     "recommended": "A", "reason": "Refunds sit next to order cancel.",
     "picked": "A", "picked_by": "you", "concern": null}
  ],
  "for_lead": [{"text": "Should the ledger hear refund.done in this release?", "owner": "@ledger-team"}],
  "parked": [{"text": "One error shape for all of payments-api.", "why": "A separate refactor."}]
}
```

| Field | Rule |
| --- | --- |
| `follow`, `leave` | Each item needs a citation. |
| `choices` | At most 4. Conflicts are shown first. Choices are numbered in the order shown. |
| `kind` | `conflict` (the code does one thing two ways) or `decision` (a real fork). |
| `question` | A full question that ends with `?`. |
| `options` | 2 or 3. Keys `A`, `B`, `C`. |
| `fit` | `follows`, `bends` or `breaks` the existing code. Bends and breaks need `fit_note`. A picked option that breaks a pattern goes to "For the lead" by itself. |
| `rows` | Short facts to compare: touches, risk, undo, later work. The same row names on each option. |
| `sketch` | Optional: a small high-level design (nodes and links, as in architecture.json) for this option. |
| `picked_by` | `you`, `lead`, or `chopchop` (nobody picked: an assumption to confirm). |
| `concern` | chopchop's one-line concern when the pick differs from its own. |

## work/answers.json

Every question asked, and the answer.

```json
{"rounds": [
  {"round": 1, "questions": [
    {"q": "What matters most for this feature?", "a": "Ship soon, smallest change", "assumed": false}]}
]}
```

`assumed: true` means nobody answered (`--auto`). The design lists it as an assumption.
