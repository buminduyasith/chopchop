# Diagram file format

## design/architecture.json

```json
{
  "version": 2,
  "title": "Refunds for card payments",
  "nodes": [
    {"id": "agent", "name": "Support agent", "kind": "person", "row": 0, "col": 0},
    {"id": "psp", "name": "Card provider", "kind": "external", "status": "external", "row": 0, "col": 3},
    {"id": "customer", "name": "Customer", "kind": "person", "row": 1, "col": 0},
    {"id": "page", "name": "Order page", "kind": "ui", "repo": "web-app", "status": "changed",
     "note": "Refund button", "row": 1, "col": 1},
    {"id": "api", "name": "Refund API", "kind": "api", "repo": "payments-api", "status": "new",
     "note": "POST /refunds", "row": 1, "col": 2},
    {"id": "job", "name": "Refund job", "kind": "job", "repo": "payments-api", "status": "new",
     "note": "every minute", "row": 1, "col": 3},
    {"id": "db", "name": "refunds table", "kind": "table", "repo": "payments-api", "status": "new",
     "row": 2, "col": 2},
    {"id": "outbox", "name": "Event outbox", "kind": "topic", "repo": "payments-api", "status": "same",
     "row": 2, "col": 3},
    {"id": "mail", "name": "Refund email", "kind": "service", "repo": "notify-service", "status": "new",
     "row": 3, "col": 3}
  ],
  "links": [
    {"from": "customer", "to": "page", "label": "asks for refund", "kind": "call"},
    {"from": "page", "to": "api", "label": "POST refunds", "kind": "call"},
    {"from": "api", "to": "db", "label": "saves pending", "kind": "data"},
    {"from": "job", "to": "db", "label": "reads pending", "kind": "data"},
    {"from": "job", "to": "psp", "label": "sends refund", "kind": "external"},
    {"from": "job", "to": "outbox", "label": "refund.done", "kind": "event"},
    {"from": "outbox", "to": "mail", "label": "delivers event", "kind": "event"},
    {"from": "mail", "to": "customer", "label": "email", "kind": "call"},
    {"from": "agent", "to": "api", "label": "cancels refund", "kind": "call"}
  ]
}
```

Why it is placed this way: the customer's path runs left to right on row 1. The table sits
under the API that writes it, and the job reads it from the next cell. The card provider is
top right, next to the job that calls it. The email service gets its own block under
payments-api, and column 0 to 2 of row 3 stays empty so the email can travel back to the
customer.

| Field | Values |
| --- | --- |
| `nodes[].id` | letters, numbers, `-` and `_`, starting with a letter |
| `nodes[].kind` | `person`, `ui`, `api`, `service`, `job`, `table`, `topic`, `library`, `external` |
| `nodes[].status` | `new` (green), `changed` (amber), `same` (white, context), `external` (dashed). People have none. |
| `nodes[].repo` | the repo it lives in, as named in chopchop.yaml. People and outside systems have none. |
| `nodes[].note` | optional, 1 to 4 words, under 40 characters |
| `nodes[].row`, `col` | whole numbers from 0. `col` at most 4. Left out: the script places it, badly. Always place. |
| `links[].label` | what moves along it, 1 to 4 words. Never a step number. |
| `links[].kind` | `call`, `data`, `event`, `external` |

Limits: 14 parts, 5 columns, about 1240 px wide (5 columns).

## design/flow.json

```json
{
  "version": 2,
  "title": "Request a refund",
  "participants": ["customer", "page", "api", "db", "job", "psp", "outbox", "mail"],
  "messages": [
    {"n": 1, "from": "customer", "to": "page", "kind": "person", "say": "clicks Refund",
     "line": "The customer clicks Refund on the order page.", "stories": ["PAY-121"],
     "failure": {"twice": "The button turns off after the first click.",
                 "caller": "Only the order's owner sees the button."}},
    {"n": 2, "from": "page", "to": "api", "kind": "call", "say": "POST refunds",
     "line": "web-app calls the new refund API.", "stories": ["PAY-121"],
     "failure": {"fails": "Shows: Refund not sent. Try again. Nothing is saved.",
                 "slow": "5 s timeout, then the same message.",
                 "twice": {"text": "An Idempotency-Key header returns the same refund.", "suggested": true},
                 "caller": "403 unless the caller owns the order."}},
    {"n": 3, "from": "api", "to": "page", "kind": "reply", "say": "422 window closed",
     "line": "Orders older than 30 days are refused.", "if": "older than 30 days"},
    {"n": 4, "from": "api", "to": "db", "kind": "db", "say": "save pending",
     "line": "The API saves the refund as pending.", "stories": ["PAY-121"],
     "failure": {"fails": "500, nothing sent, the page says try again.",
                 "twice": "A unique key on the order id keeps one refund."}}
  ],
  "out_of_scope": []
}
```

| Field | Values |
| --- | --- |
| `participants` | architecture ids, left to right in the same order as the high-level design. At most 8. |
| `messages[].n` | 1, 2, 3 with no gaps |
| `messages[].kind` | `person`, `call`, `db`, `event`, `external`, `message`, `reply` |
| `messages[].say` | 2 to 6 words on the arrow |
| `messages[].line` | one plain sentence, read out on the slide |
| `messages[].if` | optional: the condition for an error path. Drawn in amber. |
| `messages[].stories` | story or AC ids from requirement.md |
| `out_of_scope` | story ids this flow does not cover on purpose |

Which failure questions each message kind must answer:

| Kind | fails | slow | twice | caller |
| --- | --- | --- | --- | --- |
| person (person to screen) | | | yes | yes |
| call (between parts or repos) | yes | yes | yes | yes |
| db (database write) | yes | | yes | |
| event | yes | | yes | |
| external (outside system) | yes | yes | yes | yes |
| message (to a person) | yes | | | |
| reply | | | | |

An answer is text, `{"text": "...", "suggested": true}` for a suggestion the lead confirms,
or `{"risk": "...", "accepted_by": "Name"}` for a risk a named person accepts. `null` or a
missing answer blocks the approval request.
