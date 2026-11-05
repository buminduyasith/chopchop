---
status: "draft"
---
# Design · {{title}}

<!-- For leads. About 10 minutes to read. Keep the 12 headings, in this order. A section with
nothing to say keeps its heading and says "None." Comments like this one never show. Write
speaker notes for a slide as a talk comment inside the section. -->

## 1. Summary and the ask

<!-- 3 to 5 lines: what we build, for whom, why now. Then these two lines, exactly. -->

**The ask:** 
**Size:** 

<!-- talk: Start with the ask. Then the size. -->

## 2. High-level design

<!-- One picture of the parts, not the steps. chopchop draws it from design/architecture.json,
which you write with the diagram skill. Do not draw it by hand here. -->

<!-- chopchop:architecture -->
<!-- /chopchop:architecture -->

## 3. Why

<!-- 3 to 6 bullets. Facts only. A fact about today's code ends with its citation, such as
`payments-api/src/payouts/PayoutJob.java:35-40@a1f9c2e`. -->

## 4. Scope

<!-- Two lists. In scope, with story ids. Out of scope, with the parked ideas from options.md.
Every story id appears in one of the two lists. -->

## 5. Main flow and errors

<!-- One or two sentences on the main path. chopchop draws the sequence and the failure table
from design/flow.json, which you write with the diagram skill. -->

<!-- chopchop:flow -->
<!-- /chopchop:flow -->

## 6. Data changes

<!-- One table: table, change, columns, migration. Or "None." -->

## 7. Contract changes

<!-- One table: API or event, between which repos, new or changed, breaking or not. Or "None." -->

## 8. Key decisions

<!-- chopchop:decisions -->
<!-- /chopchop:decisions -->

## 9. Impact and rollout

<!-- Bullets. Who else is affected (from the system map), flags, release order, how to roll back. -->

## 10. Risks

<!-- Up to 5 rows: risk, and what we do about it. Accepted risks from the failure answers, with the name. -->

## 11. How we prove it

<!-- One table: unit, integration, e2e and manual tests, with a count each. Then the e2e journeys by name. -->

## 12. Questions, assumptions, approval

<!-- Open questions with an owner, or "None." The block below lists who must approve, the
questions for the lead, the assumptions and the approval. -->

<!-- chopchop:approval -->
<!-- /chopchop:approval -->

## Likely questions

<!-- From the mock lead review. One ### heading per question, then a one or two line answer.
Add a "Why not ...?" question for each option not picked. -->
