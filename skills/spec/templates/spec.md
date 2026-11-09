# Spec · {{title}}

<!-- How to read this spec: Part A explains the feature to anyone in about 10 minutes. Part B is
for the people and agents who build it. Part C says how we prove it works. Part D says how it
ships and where it stands. Sections marked "generated" come from spec/spec.json: do not edit
them here, change spec.json and build again. -->

# Part A · Understand

## 1. Summary

<!-- "**In short:**" and one or two lines. Then what we build, for whom, and what done looks
like, in plain words. Link the approved design: design/design.md. -->

## 2. Words we use

<!-- "**In short:**" and one line. Then a short table: Word | What it means here. One name per
thing, and use only that name everywhere. Explain every term a new developer would not know. -->

## 3. What changes

<!-- "**In short:**" and one line. Then three lists compared with today: Added, Changed,
Removed. Behavior only, in plain words. -->

## 4. Rules and examples

<!-- Generated from rules in spec.json. -->

<!-- chopchop:rules -->
<!-- /chopchop:rules -->

## 5. How it works today

<!-- "**In short:**" and one or two lines. Then how today's code does the nearest thing, step by
step, each fact with a citation such as payments-api/src/orders/cancel/OrderCancelService.java:12-17@e5d83f4.
End with the closest feature to copy. -->

# Part B · Build

## 6. Repos and files

<!-- Generated: every file, by repo, with the file map. -->

<!-- chopchop:files -->
<!-- /chopchop:files -->

## 7. Fit the existing code

<!-- Generated from repos and each package's copy and reuse in spec.json. -->

<!-- chopchop:fit -->
<!-- /chopchop:fit -->

## 8. Flows, step by step

<!-- "**In short:**" and one line. Then each message of the main flow (design/flow.json), in
order: what happens, and the file and function that handles it. For example:
"2. web-app calls POST /refunds. `RefundController.create` in payments-api/src/refunds/api/
reads the body and calls `RefundService.request`." -->

## 9. Contracts

<!-- Generated from contracts in spec.json. -->

<!-- chopchop:contracts -->
<!-- /chopchop:contracts -->

## 10. Data

<!-- "**In short:**" and one line. Then the schema change (in the repo's migration style, with
the next migration number), how existing rows are filled, indexes, and how to undo it.
Write "None." if no data changes. -->

## 11. Errors and failure cases

<!-- Generated: every failure answer from the main flow, and the test that proves it. -->

<!-- chopchop:failures -->
<!-- /chopchop:failures -->

## 12. Security, speed and running it

<!-- "**In short:**" and one line. Then who may do what and where it is checked, limits and
timeouts with real numbers, logs and metrics to add (named like the repo names them), flags
and config. -->

## 13. Shared rules

<!-- "**In short:**" and one line. Then what every task must agree on: names, ids, error shape,
formats, time zones, money. Then three lists: Always, Ask first, Never. -->

## 14. Work packages

<!-- Generated: the build order. Each package becomes one task. -->

<!-- chopchop:packages -->
<!-- /chopchop:packages -->

# Part C · Prove

## 15. Unit tests

<!-- chopchop:unit -->
<!-- /chopchop:unit -->

## 16. Integration tests

<!-- chopchop:integration -->
<!-- /chopchop:integration -->

## 17. End-to-end journeys

<!-- chopchop:journeys -->
<!-- /chopchop:journeys -->

## 18. Manual checks

<!-- chopchop:checks -->
<!-- /chopchop:checks -->

# Part D · Ship and track

## 19. Rollout and undo

<!-- "**In short:**" and one line. Then the release order across repos (contracts and data
first), flags and their defaults, what to watch after release, and how to roll back each step. -->

## 20. Done status

<!-- chopchop:done -->
<!-- /chopchop:done -->

## 21. Decisions, assumptions and open questions

<!-- chopchop:decisions -->
<!-- /chopchop:decisions -->

## Trace

<!-- chopchop:trace -->
<!-- /chopchop:trace -->
