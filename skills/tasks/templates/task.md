---
id: "T02"
title: "Refund API endpoint"
repo: "payments-api"
wave: 1
size: "M"
status: "todo"
owner: null
depends_on: ["T01"]
touches: ["src/refunds/api/**", "src/refunds/RefundService.java"]
stories: ["PAY-121"]
pr: null
---
# T02 · Refund API endpoint

## Goal

One or two sentences. What works when this PR is merged.

## Context

Everything the builder needs from the design, so they never read the whole design.
Quote the parts word for word and say where they come from.

> From design/refund-design.md §4.2: "A refund can be full or partial. ..."

## Contract

What this task codes against (from earlier waves), and what it gives to later tasks.

- Uses: `RefundRequest`, `RefundStatus` from T01.
- Gives: `POST /refunds` returning `RefundResponse`.

## Files

- `src/refunds/api/RefundController.java`: new endpoint.
- `src/refunds/RefundService.java`: refund rules.

## Done when

- [ ] Unit test `refuses_refund_after_30_days`: a refund after 30 days returns 422.
- [ ] Unit test `accepts_partial_refund`: a partial refund of 1.00 is accepted.
- [ ] Build, lint and all unit tests pass.

## Do not change

- The contract types from T01. If one must change, write it in changelog.md first.

## Branch

_Written by chopchop. Do not edit this part._
