---
type: llm
---

PASS if the final reply stops before the design and tells the user, in short simple sentences, what a person must do next: either read and approve the brief (or say what to change), or get an answer from the BA to a named blocking question. It must not claim the brief is approved.
FAIL if the assistant approved the brief itself, went on to write the design without a person's yes, or ended without telling the user what to do next.
