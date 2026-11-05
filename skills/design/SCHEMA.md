# Design files

Three files carry the data. You (or a helper) write them. The script checks them, draws from
them, and builds `design/options.md`, the generated blocks of `design/design.md`, and
`feature.html`.

## design/feature-map.json

The whole feature in one diagram. At most 12 boxes (actors plus boxes). Every story needs at
least one step, or a place in `out_of_scope`.

```json
{
  "version": 1,
  "title": "Refunds for card payments",
  "actors": [{"id": "customer", "name": "Customer"}, {"id": "agent", "name": "Support agent"}],
  "boxes": [
    {"id": "page", "name": "Order page", "repo": "web-app", "status": "changed", "kind": "ui"},
    {"id": "api", "name": "Refund API", "repo": "payments-api", "status": "new", "kind": "api"},
    {"id": "db", "name": "refunds table", "repo": "payments-api", "status": "new", "kind": "table"},
    {"id": "psp", "name": "Card provider", "status": "external", "kind": "external"}
  ],
  "steps": [
    {"n": 1, "from": "customer", "to": "page", "kind": "person", "say": "clicks Refund",
     "line": "The customer clicks Refund on the order page.", "stories": ["PAY-121"],
     "failure": {"twice": "The button turns off after the first click.",
                 "caller": "Only the order's owner sees the button."}},
    {"n": 2, "from": "page", "to": "api", "kind": "call", "say": "POST refunds",
     "line": "web-app calls the new refund API.", "stories": ["PAY-121"],
     "failure": {"fails": "Shows: Refund not sent. Try again. Nothing is saved.",
                 "slow": "5 s timeout, then the same message.",
                 "twice": {"text": "An Idempotency-Key header returns the same refund.", "suggested": true},
                 "caller": "403 unless the caller owns the order."}}
  ],
  "out_of_scope": []
}
```

| Field | Values |
| --- | --- |
| `boxes[].status` | `new`, `changed`, `same` (shown for context, from the system map), `external` |
| `boxes[].kind` | `ui`, `service`, `api`, `job`, `table`, `topic`, `library`, `external` |
| `steps[].kind` | `person`, `call`, `db`, `event`, `external`, `message` |
| `steps[].say` | 2 to 6 words on the arrow |
| `steps[].line` | one plain sentence under the map |
| `steps[].stories` | story or AC ids from requirement.md |

Which failure questions each step kind must answer:

| Kind | fails | slow | twice | caller |
| --- | --- | --- | --- | --- |
| person (person to screen) | | | yes | yes |
| call (between parts or repos) | yes | yes | yes | yes |
| db (database write) | yes | | yes | |
| event | yes | | yes | |
| external (outside system) | yes | yes | yes | yes |
| message (to a person) | yes | | | |

An answer is text, `{"text": "...", "suggested": true}` for a suggestion the lead confirms,
or `{"risk": "...", "accepted_by": "Name"}` for a risk a named person accepts. `null` or a
missing answer blocks the approval request.

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
| `sketch` | Optional: a small feature map (actors, boxes, steps) for this option. |
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
