# Diagrams

Both design diagrams come from the diagram skill (`../diagram/SKILL.md`):

- **Section 2, high-level design** from `design/architecture.json`: the parts, the repo each
  lives in, and what talks to what. A structure, never steps.
- **Section 5, main flow** from `design/flow.json`: the numbered messages in time order, the
  error paths, and a failure answer for every message.

The build writes both as Mermaid in design.md, so GitHub and editors show them. The dashboard
draws the same two files as pictures. Do not write either one by hand.

## Other diagrams

Most designs need no third diagram. When one really helps (a state machine, a data shape),
write it as Mermaid in its section, and keep these rules:

- Node ids: letters, numbers and `_` only.
- Labels in plain words. No `( ) [ ] { } " / | # ;` inside a label.
- No styling.
- At most 4 diagrams in design.md, the two generated ones included.
