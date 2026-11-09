# spec/spec.json

The facts of the spec. You write it. The script checks it, writes 13 sections of spec.md from
it, and `/chopchop:tasks` cuts the tasks from it. A full, real example is
`examples/refunds.spec.json`. Every list may be empty unless a row says otherwise.

```json
{
  "version": 1,
  "title": "Refunds for card payments",
  "rules": [], "out_of_scope": [], "repos": {}, "contracts": [],
  "packages": [], "journeys": [], "checks": [], "questions": [], "assumptions": []
}
```

Ids never change once written: `R-1`, `C-1`, `P1`, `J1`, `M1`. A removed item keeps its id
retired; a new one takes the next number.

## rules

| Field | Rule |
| --- | --- |
| `id` | `R-1`, `R-2` ... |
| `text` | The rule in one or two plain sentences. What is possible, not how. |
| `stories` | Story or AC ids from requirement.md (`PAY-121.AC1`). Every story needs a rule, or goes in `out_of_scope`. |
| `met` | What shows the rule was met, with a real value. |
| `examples` | At least one `{"given", "when", "then"}`. Put the error cases here too. |

## repos

One entry per repo the feature changes. See `references/code.md`.

| Field | Rule |
| --- | --- |
| `language` | The main language, for the sketches. |
| `folders` | `[{"path", "like", "why"}]`: where new files go, next to which existing code. |
| `naming` | `[{"today", "new"}]`: new names made the way the neighbors are named. |
| `test_example` | One real test name from the repo. New test names must look the same. |
| `style` | The rules from the team's style file this feature touches. |
| `do_not` | Traps. Code names in backticks are checked: no sketch may use them. |

## contracts

What two packages share: an API, an event, a table or a type.

| Field | Rule |
| --- | --- |
| `id`, `name`, `kind`, `repo` | `C-1`, `POST /refunds`, `api` (or `event`, `table`, `type`), the repo that owns it. |
| `example` | The exact shape: request and responses, the event body, the SQL, the type. |
| `lang` | The code fence language: `http`, `json`, `sql`, `ts` ... |

Exactly one package `gives` each contract. A package in the same repo that `uses` it must be in
a later wave. A package in another repo may use it in the same wave, coding against the
example with a mock.

## packages

Each package becomes one task: one repo, one PR.

| Field | Rule |
| --- | --- |
| `id`, `repo`, `title` | `P1`, one repo, a short title. |
| `wave` | 0 contracts, 1 slices (in parallel), 2 wiring (only if needed). |
| `size` | `S` (about half a day) or `M` (about a day). Split anything bigger. |
| `goal` | What works when it is merged. |
| `rules`, `depends_on` | The rules it builds. Packages it needs, from earlier waves only. |
| `files` | `[{"path", "change", "what"}]`. `change` is `new`, `change` or `delete`. A changed file must exist; a new one must not. Two packages in the same wave and repo never share a file. |
| `uses`, `gives`, `makes` | Contracts it codes against, contracts it builds, new names it creates. |
| `copy` | `[{"cite", "why", "change"}]`: the closest existing code, as `repo/path:12-17@abc1234`. |
| `reuse` | `[{"name", "does", "cite"}]`: existing methods and types to call. The name must be in the cited lines. |
| `sketch` | `[{"file", "code"}]`: new code in the repo's style. `file` is one of the package's files. |
| `tests` | At least one: `{"name", "level", "file", "proves", "rules", "failures"}`. `level` is `unit` or `integration`. `failures` names failure answers of design/flow.json, such as `2.twice`. |
| `run` | `{"command", "expect"}`: how to run this package's tests. |
| `do_not` | What this package must not touch. |

Every failure answer in design/flow.json needs a test, a journey or a manual check that names
it in `failures`, unless a person accepted it as a risk.

## journeys

End-to-end paths a user takes. A journey that runs becomes a prove task in wave 3.

| Field | Rule |
| --- | --- |
| `id`, `title`, `stories`, `rules` | `J1`, a short title, what it proves. |
| `repo`, `file` | The repo whose e2e suite runs it, and the test file to write. |
| `run` | `{"command", "found_in"}`: how this repo runs e2e, and where you found it. |
| `manual` | `{"who": "Asha"}` instead of `run` when the repo has no e2e suite. A person signs it. |
| `data` | The test data it starts from. |
| `steps` | `[{"do", "see"}]`, in plain words. |
| `failures` | Optional: failure answers this journey proves. |

## checks

Manual checks, only for what no test can do: `{"id": "M1", "title", "who", "rules", "steps", "failures"}`.
A person signs each one with `--sign M1 --by NAME`.

## questions and assumptions

`questions`: `[{"text", "owner", "blocking", "answer"}]`. A blocking question with no answer
stops the build. `assumptions`: plain lines, each a guess someone should confirm.

## What the script writes

| spec.md section | From |
| --- | --- |
| 4 Rules and examples | `rules` |
| 6 Repos and files | `packages[].files`, with the file map |
| 7 Fit the existing code | `repos`, `packages[].copy` (with the real lines), `packages[].reuse` |
| 9 Contracts | `contracts` |
| 11 Errors and failure cases | design/flow.json and the tests that name each failure |
| 14 Work packages | `packages` |
| 15, 16 Unit and integration tests | `packages[].tests` |
| 17 End-to-end journeys | `journeys` |
| 18 Manual checks | `checks` |
| 20 Done status | the tasks, work/verify/ and work/proof.json |
| 21 Decisions, assumptions and open questions | work/options.json, `assumptions`, `questions` |
| Trace | everything above |
