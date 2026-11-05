# System map update

An explorer writes one update per repo it read, then `chopchop_learn.py --write` checks it and
merges it into `_chopchop/system/system-map.json`. The script adds the commit, owners
(CODEOWNERS), hotspots (git log) and ADR list by itself.

```json
{
  "repos": {
    "payments-api": {
      "kind": "service",
      "summary": "Payments, order cancel and payouts. Java 17, Spring Boot, PostgreSQL.",
      "layers": ["controller", "service", "repository", "job"],
      "patterns": [
        {"text": "Status changes go through one service method that checks the old status first.",
         "cite": "payments-api/src/orders/cancel/OrderCancelService.java:12-17@a1f9c2e"},
        {"text": "Events go out through the outbox table, so a consumer can get one twice.",
         "cite": "payments-api/src/events/EventPublisher.java:3-4@a1f9c2e"}
      ]
    }
  },
  "nodes": [
    {"id": "payments-api:api", "name": "Payments API", "kind": "api", "repo": "payments-api",
     "cite": "payments-api/openapi.yaml:3-5@a1f9c2e"},
    {"id": "payments-api:payments", "name": "payments", "kind": "table", "repo": "payments-api",
     "cite": "payments-api/db/migration/V40__payments.sql:1@a1f9c2e"},
    {"id": "payments-api:payout-job", "name": "Payout job", "kind": "job", "repo": "payments-api",
     "cite": "payments-api/src/payouts/PayoutJob.java:6-11@a1f9c2e"},
    {"id": "payment-events", "name": "payment events", "kind": "topic"},
    {"id": "card-provider", "name": "Card provider", "kind": "external"}
  ],
  "links": [
    {"from": "payments-api:api", "to": "payments-api:payments", "kind": "db", "say": "writes payments",
     "found_in": "payments-api", "cite": "payments-api/src/orders/cancel/OrderCancelService.java:16@a1f9c2e"},
    {"from": "payments-api:payout-job", "to": "card-provider", "kind": "external", "say": "sends payouts",
     "found_in": "payments-api", "cite": "payments-api/src/payouts/PayoutJob.java:9@a1f9c2e"}
  ]
}
```

| Field | Rule |
| --- | --- |
| `repos` | The repos this update covers. The merge replaces their parts and links. |
| `kind` (repo) | service, web, mobile, library, job, infra, data or other. |
| `layers` | The layers code passes through in this repo, in call order. spec draws its flow lanes from them. |
| `patterns` | What the code always does, one line each, with a citation. design lists them as "Patterns we follow". |
| `nodes[].id` | Unique, stable. Use `repo:name` for parts inside a repo. Letters, numbers, `.`, `-`, `_`, `:`. |
| `nodes[].kind` | service, api, ui, job, table, topic, external, library or person. |
| `links[].kind` | call, event, db, external, person or message. |
| `links[].found_in` | The repo where you saw the code for this link. It must be a repo this update covers. |
| `cite` | `repo/path:line@commit` or `repo/path:start-end@commit`, with the commit you read. |
| `source` | Leave it out. A person sets `"person"` on an entry they fixed, and the merge never touches it. |

A link to a part in another repo is fine when that part is already in the map, or in this
update. Topics and outside systems have no repo.
