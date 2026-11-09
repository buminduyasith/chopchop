# Code that fits the repo

We build inside code that already exists. The spec shows the code, it does not describe it:
real code to copy, the methods to reuse, where files go, and a sketch of the new code written
the way the repo already writes code.

## Per repo (spec.json `repos`)

- **folders**: where new files go, and the existing folder each one copies (`like`). New code
  sits next to similar code. Never invent a layout the repo does not use.
- **naming**: today's names and the new ones made the same way. `OrderCancelService` gives
  `RefundService`. `V41__order_cancellations.sql` gives `V42__refunds.sql`.
- **test_example**: one real test name from the repo, so new tests are named the same way.
- **style**: the rules from the team's style file that this feature touches, quoted.
- **do_not**: the traps. Put code names in backticks: the script checks no sketch uses them.

## Per package

- **copy**: the closest existing code, as a citation (at most about 20 lines), with why it is
  the one to copy and what to change. The page and the task show the real lines.
- **reuse**: every existing method or type the new code calls, with the citation where it
  lives. The script checks the name is in the cited lines.
- **makes**: the new names this package creates, so later packages and sketches can use them.
- **sketch**: the new code, in the repo's language and style:
  - Signatures, the key lines, and the error handling, exactly as the repo does them.
  - The full body only where the logic is the point: rules, money, dates, retries, things
    that run at the same time.
  - Boilerplate says "same as" a real file: `// constructor: same as OrderCancelService.java:7-10`.
  - Mark names in comments: `// existing` for reused ones, `// new in P1` for ones a package
    makes. Every name is one of the two.
- **tests**: named the way the repo names them, with the values in `proves`.

## Follow the repo as it is

- If the repo uses class components, an old error shape, or a hand-rolled helper, follow it.
  A newer pattern is a design choice for the lead, never a quiet change in a spec.
- When the repo does one thing two ways, show only the way options.md picked, and put the
  other way in `do_not`.
- Never add a dependency the repo does not have. If one is truly needed, it is a question.

## Example

```json
{"id": "P2", "repo": "payments-api", "title": "Refund service", "wave": 1, "size": "M",
 "copy": [{"cite": "payments-api/src/orders/cancel/OrderCancelService.java:12-17@e5d83f4",
           "why": "Order cancel is the closest feature: same owner check, same pending state.",
           "change": "Add the 30 day check after requireStatus."}],
 "reuse": [{"name": "orders.findOwned(orderId, by)", "does": "Finds the order and checks the caller owns it.",
            "cite": "payments-api/src/orders/cancel/OrderCancelService.java:13@e5d83f4"}],
 "sketch": [{"file": "src/refunds/RefundService.java",
             "code": "public Refund request(long orderId, User by) {\n    Order order = orders.findOwned(orderId, by);   // existing\n    order.requireStatus(OrderStatus.PAID);          // existing\n    if (order.paidAt().plus(WINDOW).isBefore(clock.instant())) {   // new in P1: Order.paidAt()\n        throw RefundErrors.windowClosed();          // new: ApiError REFUND_WINDOW_CLOSED\n    }\n    return refunds.save(Refund.pending(order));\n}"}]}
```
