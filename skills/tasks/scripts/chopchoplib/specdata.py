"""The spec: spec/spec.json holds the facts, spec/spec.md holds the words.

chopchop writes spec.json and the prose sections of spec.md. This module checks spec.json, writes
the generated sections of spec.md from it, cuts tasks from it, and works out the done status.

spec.json, version 1 (every list may be empty unless it says otherwise):

  {"version": 1, "title": "Refunds for card payments",
   "rules": [{"id": "R-1", "text": "...", "stories": ["PAY-121"], "met": "what shows it was met",
              "examples": [{"given": "...", "when": "...", "then": "..."}]}],
   "out_of_scope": ["PAY-130"],
   "repos": {"payments-api": {"language": "java",
                              "folders": [{"path": "src/refunds/", "like": "src/orders/cancel/", "why": "..."}],
                              "naming": [{"today": "OrderCancelService", "new": "RefundService"}],
                              "test_example": "cancels_only_paid_orders",
                              "style": ["one rule of the team's style, quoted"],
                              "do_not": ["No `ProblemDetail` in refunds: only payouts use it."]}},
   "contracts": [{"id": "C-1", "name": "POST /refunds", "kind": "api", "repo": "payments-api",
                  "lang": "http", "example": "POST /refunds ..."}],
   "packages": [{"id": "P2", "repo": "payments-api", "title": "Refund service", "wave": 1, "size": "M",
                 "goal": "...", "rules": ["R-3"], "depends_on": ["P1"],
                 "files": [{"path": "src/refunds/RefundService.java", "change": "new", "what": "..."}],
                 "uses": ["C-2"], "gives": ["C-1"], "makes": ["RefundService.request"],
                 "copy": [{"cite": "payments-api/src/orders/cancel/OrderCancelService.java:12-17@e5d83f4",
                           "why": "the closest feature", "change": "add the 30 day check"}],
                 "reuse": [{"name": "orders.findOwned(orderId, by)", "does": "checks the owner",
                            "cite": "payments-api/src/orders/cancel/OrderCancelService.java:13@e5d83f4"}],
                 "sketch": [{"file": "src/refunds/RefundService.java", "code": "..."}],
                 "tests": [{"name": "refuses_refund_after_30_days", "level": "unit",
                            "file": "test/refunds/RefundServiceTest.java", "proves": "...",
                            "rules": ["R-3"], "failures": ["2.twice"]}],
                 "run": {"command": "./gradlew test --tests '*Refund*'", "expect": "all pass"},
                 "do_not": ["Do not touch src/payouts/**"]}],
   "journeys": [{"id": "J1", "title": "...", "stories": ["PAY-121"], "rules": ["R-1"], "repo": "web-app",
                 "file": "e2e/refund.spec.ts", "run": {"command": "npm run e2e -- refund", "found_in": "..."},
                 "manual": null, "data": "...", "steps": [{"do": "...", "see": "..."}]}],
   "checks": [{"id": "M1", "title": "...", "who": "Asha", "rules": ["R-5"], "steps": ["..."]}],
   "questions": [{"text": "...", "owner": "...", "blocking": false, "answer": null}],
   "assumptions": ["..."]}

A failure reference such as "2.twice" means message 2 of design/flow.json, question "twice".
"""

import posixpath
import re

from . import cite, designdoc, diagrams

SPEC_DIR = "spec"
SPEC_MD = "spec.md"
SPEC_JSON = "spec.json"
PROOF_FILE = "proof.json"
VERIFY_DIR = "verify"

PARTS = [("A", "Understand", 1), ("B", "Build", 6), ("C", "Prove", 15), ("D", "Ship and track", 19)]
HEADINGS = [
    "Summary", "Words we use", "What changes", "Rules and examples", "How it works today",
    "Repos and files", "Fit the existing code", "Flows, step by step", "Contracts", "Data",
    "Errors and failure cases", "Security, speed and running it", "Shared rules", "Work packages",
    "Unit tests", "Integration tests", "End-to-end journeys", "Manual checks",
    "Rollout and undo", "Done status", "Decisions, assumptions and open questions",
]
APPENDIX = "Trace"
BLOCKS = {"rules": 4, "files": 6, "fit": 7, "contracts": 9, "failures": 11, "packages": 14, "unit": 15,
          "integration": 16, "journeys": 17, "checks": 18, "done": 20, "decisions": 21, "trace": None}
PROSE = [n for n in range(1, len(HEADINGS) + 1) if n not in BLOCKS.values()]
STATUSES = ["draft", "ready", "building", "done"]
STATUS_TEXT = {"draft": "Draft.", "ready": "Ready to cut tasks.", "building": "Being built.", "done": "Done."}

CHANGES = ["new", "change", "delete"]
SIZES = ["S", "M"]
LEVELS = ["unit", "integration"]
MAX_WAVE = 2
PROVE_WAVE = 3
SPLIT_PACKAGES, SPLIT_REPOS, BIG_PACKAGE = 12, 4, 12
ID_RES = {"rules": r"R-\d+", "contracts": r"C-\d+", "packages": r"P\d+", "journeys": r"J\d+", "checks": r"M\d+"}
TICKED = re.compile(r"`([A-Za-z_][\w.]*)`")
EXT_LANG = {".java": "java", ".kt": "kotlin", ".ts": "ts", ".tsx": "tsx", ".js": "js", ".jsx": "jsx", ".py": "python",
            ".go": "go", ".rb": "ruby", ".cs": "csharp", ".rs": "rust", ".sql": "sql", ".php": "php", ".swift": "swift",
            ".scala": "scala", ".yaml": "yaml", ".yml": "yaml", ".json": "json", ".sh": "bash", ".md": "markdown"}

STATE_TEXT = {"planned": "Planned", "built": "Built", "proved": "Proved", "waiting": "Waiting", "failing": "Failing"}


# --------------------------------------------------------------------------- small helpers


def _list(v):
    return v if isinstance(v, list) else []


def _items(spec, key):
    return [x for x in _list((spec or {}).get(key)) if isinstance(x, dict)]


def by_id(spec, key):
    return {x.get("id"): x for x in _items(spec, key)}


def lang_of(path):
    return EXT_LANG.get(posixpath.splitext(str(path))[1].lower(), "")


def _walk_strings(value, where=""):
    if isinstance(value, str):
        yield where, value
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk_strings(v, "%s[%d]" % (where, i))
    elif isinstance(value, dict):
        for k, v in value.items():
            if k in ("code", "example"):
                continue
            yield from _walk_strings(v, "%s.%s" % (where, k) if where else k)


def _id_num(x):
    m = re.search(r"\d+", str(x))
    return int(m.group(0)) if m else 0


def ordered_packages(spec):
    return sorted(_items(spec, "packages"), key=lambda p: (p.get("wave") if isinstance(p.get("wave"), int) else 9,
                                                             _id_num(p.get("id"))))


def test_style(name):
    name = str(name)
    if "_" in name and name.lower() == name:
        return "snake_case"
    if " " in name:
        return "sentence"
    if re.match(r"^[a-z]+[A-Z]", name):
        return "camelCase"
    return ""


def failure_refs(flow):
    """{"2.twice": row} for every failure question of flow.json."""
    return {"%s.%s" % (r["n"], r["question"]): r for r in diagrams.failures(flow or {})}


# --------------------------------------------------------------------------- checks


def validate(spec, stories=None, known=None, repos=None, flow=None):
    """Returns (errors, warnings) for spec.json. stories: top-level story ids; known: every story and AC id;
    repos: repo names from chopchop.yaml; flow: design/flow.json."""
    errors, warnings = [], []
    if not isinstance(spec, dict):
        return ["spec.json must be an object"], []
    if not spec.get("title"):
        errors.append("title is missing")

    for key, pat in ID_RES.items():
        seen = set()
        for i, x in enumerate(_list(spec.get(key)), 1):
            if not isinstance(x, dict):
                errors.append("%s %d must be an object" % (key, i))
                continue
            xid = x.get("id")
            if not isinstance(xid, str) or not re.fullmatch(pat, xid):
                errors.append("%s %d: id %r must look like %s" % (key, i, xid, pat.replace("\\d+", "1")))
            elif xid in seen:
                errors.append("%s: id %s is used twice" % (key, xid))
            seen.add(xid)

    rules = by_id(spec, "rules")
    contracts = by_id(spec, "contracts")
    packages = by_id(spec, "packages")
    repos_info = spec.get("repos") if isinstance(spec.get("repos"), dict) else {}

    def known_ids(ids, where):
        for sid in _list(ids):
            if known and sid not in known:
                errors.append("%s: %s is not a story or AC id in requirement.md" % (where, sid))

    def rule_ids(ids, where):
        for rid in _list(ids):
            if rid not in rules:
                errors.append("%s: rule %s does not exist" % (where, rid))

    # rules
    for rid, r in rules.items():
        if not r.get("text"):
            errors.append("%s needs text: the rule in one or two plain sentences" % rid)
        if not r.get("met"):
            errors.append("%s needs met: what shows the rule was met" % rid)
        if not _list(r.get("stories")):
            errors.append("%s needs the story or AC ids it serves" % rid)
        known_ids(r.get("stories"), rid)
        ex = [e for e in _list(r.get("examples")) if isinstance(e, dict)]
        if not ex:
            errors.append("%s needs at least one example (given, when, then)" % rid)
        for j, e in enumerate(ex, 1):
            gone = [k for k in ("given", "when", "then") if not e.get(k)]
            if gone:
                errors.append("%s example %d is missing %s" % (rid, j, ", ".join(gone)))
    out = set(_list(spec.get("out_of_scope")))
    for sid in stories or []:
        if sid in out:
            continue
        if not any(sid == s or str(s).startswith(sid + ".") for r in rules.values() for s in _list(r.get("stories"))):
            errors.append("story %s has no rule. Add one, or put it in out_of_scope." % sid)

    # contracts
    givers = {}
    for p in packages.values():
        for c in _list(p.get("gives")):
            givers.setdefault(c, []).append(p.get("id"))
    for cid, c in contracts.items():
        if not c.get("name"):
            errors.append("%s needs a name, such as POST /refunds or refund.done" % cid)
        if not c.get("example"):
            errors.append("%s needs an example: the exact request, response, event or type" % cid)
        if cid not in givers:
            errors.append("%s is given by no package. Put it in the gives of the package that builds it." % cid)
        elif len(givers[cid]) > 1:
            errors.append("%s is given by %s. Only one package may build a contract." % (cid, ", ".join(givers[cid])))

    # repos
    used_repos = sorted({p.get("repo") for p in packages.values() if p.get("repo")} |
                        {j.get("repo") for j in _items(spec, "journeys") if j.get("repo")})
    for name in used_repos:
        if repos and name not in repos:
            errors.append("repo %s is not in chopchop.yaml" % name)
        if name not in repos_info:
            warnings.append("repos.%s is missing: say where files go, the names to copy, the style and what not to do"
                            % name)
    if len(used_repos) > SPLIT_REPOS or len(packages) > SPLIT_PACKAGES:
        warnings.append("%d packages in %d repos. That is a big feature: offer the user to split it."
                        % (len(packages), len(used_repos)))

    # packages
    refs = failure_refs(flow) if flow else {}
    makes = {}
    tests_by_rule, test_names = {}, {}
    for pid, p in packages.items():
        where = pid
        repo = p.get("repo")
        if not repo or not isinstance(repo, str):
            errors.append("%s needs one repo" % where)
        if not p.get("title"):
            errors.append("%s needs a title" % where)
        if not p.get("goal"):
            errors.append("%s needs a goal: what works when it is merged" % where)
        wave = p.get("wave")
        if not isinstance(wave, int) or not 0 <= wave <= MAX_WAVE:
            errors.append("%s: wave must be 0 (contracts), 1 (slices) or 2 (wiring)" % where)
        if p.get("size") not in SIZES:
            errors.append("%s: size must be S or M. Split anything bigger." % where)
        rule_ids(p.get("rules"), where)
        files = [f for f in _list(p.get("files")) if isinstance(f, dict)]
        if not files:
            errors.append("%s lists no files" % where)
        if len(files) > BIG_PACKAGE:
            warnings.append("%s has %d files. It may be too big to review in one sitting." % (where, len(files)))
        paths = []
        for f in files:
            fp = str(f.get("path") or "")
            if not fp or fp.startswith("/") or ".." in fp.split("/"):
                errors.append("%s: file path %r must be relative to the repo" % (where, fp))
            if f.get("change") not in CHANGES:
                errors.append("%s: %s change must be new, change or delete" % (where, fp))
            if not f.get("what"):
                errors.append("%s: say what changes in %s" % (where, fp))
            paths.append(fp)
        for dep in _list(p.get("depends_on")):
            d = packages.get(dep)
            if d is None:
                errors.append("%s depends on %s, which does not exist" % (where, dep))
            elif isinstance(d.get("wave"), int) and isinstance(wave, int) and d["wave"] >= wave:
                errors.append("%s (wave %s) depends on %s (wave %s). Depend only on an earlier wave."
                              % (where, wave, dep, d["wave"]))
        for cid in _list(p.get("uses")):
            if cid not in contracts:
                errors.append("%s uses %s, which is not in contracts" % (where, cid))
            for g in givers.get(cid, []):
                gw = packages[g].get("wave")
                same_repo = packages[g].get("repo") == repo
                if g != pid and same_repo and isinstance(gw, int) and isinstance(wave, int) and gw >= wave:
                    errors.append("%s uses %s from %s in the same repo, so %s must be in an earlier wave. (Another "
                                  "repo may code against a contract in the same wave, with a mock.)" % (where, cid, g, g))
        for cid in _list(p.get("gives")):
            if cid not in contracts:
                errors.append("%s gives %s, which is not in contracts" % (where, cid))
        for name in _list(p.get("makes")):
            if name in makes:
                errors.append("%s and %s both make %s" % (makes[name], pid, name))
            makes[name] = pid
        for j, c in enumerate(_list(p.get("copy")), 1):
            if not isinstance(c, dict) or len(cite.find(str(c.get("cite") or ""))) != 1:
                errors.append("%s copy %d needs a cite such as repo/path:12-17@abc1234" % (where, j))
            elif not c.get("why"):
                errors.append("%s copy %d: say why this code is the one to copy" % (where, j))
        for j, r in enumerate(_list(p.get("reuse")), 1):
            if not isinstance(r, dict) or not r.get("name") or len(cite.find(str(r.get("cite") or ""))) != 1:
                errors.append("%s reuse %d needs a name and a cite where it lives" % (where, j))
        banned = {w for d in _list(p.get("do_not")) + _list((repos_info.get(repo) or {}).get("do_not"))
                  for w in TICKED.findall(str(d))}
        for j, s in enumerate(_list(p.get("sketch")), 1):
            if not isinstance(s, dict) or not s.get("code"):
                errors.append("%s sketch %d needs code" % (where, j))
                continue
            if s.get("file") not in paths:
                errors.append("%s sketch %d: file %r is not one of the package's files" % (where, j, s.get("file")))
            hit = sorted(w for w in banned if re.search(r"(?<![\w.])%s(?!\w)" % re.escape(w), s["code"]))
            if hit:
                errors.append("%s sketch for %s uses %s, which its do-not list forbids" % (where, s.get("file"), ", ".join(hit)))
        tests = [t for t in _list(p.get("tests")) if isinstance(t, dict)]
        if not tests:
            errors.append("%s has no tests. Name each unit test, its values and what it proves." % where)
        style = test_style((repos_info.get(repo) or {}).get("test_example") or "")
        for t in tests:
            name = t.get("name")
            if not name:
                errors.append("%s: a test has no name" % where)
                continue
            key = (repo, name)
            if key in test_names:
                errors.append("%s: test %s is also in %s" % (where, name, test_names[key]))
            test_names[key] = pid
            if t.get("level", "unit") not in LEVELS:
                errors.append("%s: test %s level must be unit or integration" % (where, name))
            if not t.get("proves"):
                errors.append("%s: test %s needs proves: the values and the result" % (where, name))
            rule_ids(t.get("rules"), "%s test %s" % (where, name))
            for rid in _list(t.get("rules")):
                tests_by_rule.setdefault(rid, []).append(name)
            for ref in _list(t.get("failures")):
                if refs and ref not in refs:
                    errors.append("%s test %s: failure %s is not a question in flow.json (use message.question, "
                                  "such as 2.twice)" % (where, name, ref))
            if style and test_style(name) and test_style(name) != style:
                warnings.append("%s: test %s is %s, but this repo names tests in %s (like %s)"
                                % (where, name, test_style(name), style, repos_info[repo]["test_example"]))
        run = p.get("run") if isinstance(p.get("run"), dict) else {}
        if not run.get("command"):
            errors.append("%s needs run.command: how to run its tests" % where)

    for i, a in enumerate(ordered_packages(spec)):
        for b in ordered_packages(spec)[i + 1:]:
            if a.get("wave") != b.get("wave") or a.get("repo") != b.get("repo"):
                continue
            shared = {f.get("path") for f in _list(a.get("files")) if isinstance(f, dict)} & \
                     {f.get("path") for f in _list(b.get("files")) if isinstance(f, dict)}
            for fp in sorted(x for x in shared if x):
                errors.append("%s and %s are both in wave %s and both touch %s. Move one to another wave."
                              % (a.get("id"), b.get("id"), a.get("wave"), fp))

    # journeys and manual checks
    for j in _items(spec, "journeys"):
        jid = j.get("id")
        if not j.get("title"):
            errors.append("%s needs a title" % jid)
        known_ids(j.get("stories"), jid)
        rule_ids(j.get("rules"), jid)
        for rid in _list(j.get("rules")):
            tests_by_rule.setdefault(rid, []).append(jid)
        steps = [s for s in _list(j.get("steps")) if isinstance(s, dict)]
        if not steps or any(not s.get("do") or not s.get("see") for s in steps):
            errors.append("%s needs steps, each with do and see" % jid)
        if not j.get("data"):
            errors.append("%s needs data: the test data it starts from" % jid)
        manual = j.get("manual") if isinstance(j.get("manual"), dict) else None
        run = j.get("run") if isinstance(j.get("run"), dict) else {}
        if manual:
            if not manual.get("who"):
                errors.append("%s is manual, so it needs manual.who: the person who signs it" % jid)
        else:
            if not j.get("repo"):
                errors.append("%s needs the repo whose e2e suite runs it" % jid)
            if not run.get("command"):
                errors.append("%s needs run.command (how this repo runs e2e), or manual.who when the repo has no "
                              "e2e suite" % jid)
            if not j.get("file"):
                errors.append("%s needs file: where its e2e test lives" % jid)
    for m in _items(spec, "checks"):
        mid = m.get("id")
        if not m.get("title") or not _list(m.get("steps")):
            errors.append("%s needs a title and steps" % mid)
        if not m.get("who"):
            errors.append("%s needs who: the person who signs it" % mid)
        rule_ids(m.get("rules"), mid)
        for rid in _list(m.get("rules")):
            tests_by_rule.setdefault(rid, []).append(mid)

    for rid in rules:
        if rid not in tests_by_rule:
            errors.append("%s has no test, journey or manual check. Every rule needs proof." % rid)

    if refs:
        covered = {ref for p in packages.values() for t in _list(p.get("tests")) if isinstance(t, dict)
                   for ref in _list(t.get("failures"))}
        covered |= {ref for key in ("journeys", "checks") for x in _items(spec, key) for ref in _list(x.get("failures"))}
        for ref, row in refs.items():
            if row["state"] in ("answered", "suggested") and ref not in covered:
                errors.append("failure %s (message %s, %s: %s) has no test. Add it to a test's failures."
                              % (ref, row["n"], row["question"], (row["answer"] or "")[:60]))

    for q in _items(spec, "questions"):
        if q.get("blocking") and not q.get("answer"):
            errors.append("open question blocks the build: %s (owner: %s)" % (q.get("text"), q.get("owner") or "nobody"))

    for where, text in _walk_strings(spec):
        if designdoc.PLACEHOLDER.search(text):
            errors.append("%s still has placeholder text: %s" % (where, text[:60]))
        if designdoc.DASHES.search(text):
            errors.append("%s has a long dash. Use a comma, a full stop or a colon." % where)
    return errors, warnings


def cites(spec):
    """Every citation in spec.json, as cite.find dicts."""
    out, seen = [], set()
    for p in _items(spec, "packages"):
        for key in ("copy", "reuse"):
            for x in _list(p.get(key)):
                if isinstance(x, dict):
                    for c in cite.find(str(x.get("cite") or "")):
                        if c["raw"] not in seen:
                            seen.add(c["raw"])
                            out.append(c)
    return out


def reuse_problems(spec, results):
    """Each reused name must be in the lines it cites. results: cite.check results."""
    found = {r["raw"]: r for r in results}
    errors = []
    for p in _items(spec, "packages"):
        for r in _list(p.get("reuse")):
            if not isinstance(r, dict):
                continue
            c = cite.find(str(r.get("cite") or ""))
            res = found.get(c[0]["raw"]) if c else None
            lines = (res or {}).get("now") or (res or {}).get("old")
            if not lines:
                continue
            words = re.findall(r"[A-Za-z_]\w*", str(r.get("name") or "").split("(")[0])
            word = words[-1] if words else ""
            if word and not re.search(r"(?<!\w)%s(?!\w)" % re.escape(word), "\n".join(lines)):
                errors.append("%s reuses %s, but %s is not in the lines it cites (%s). Cite where it really is."
                              % (p.get("id"), r.get("name"), word, r.get("cite")))
    return errors


def file_problems(spec, repo_dirs):
    """New files go in folders that exist; changed files must exist. Needs the repos on disk."""
    errors, warnings = [], []
    for p in _items(spec, "packages"):
        root = repo_dirs.get(p.get("repo"))
        if not root or not root.is_dir():
            continue
        for f in _list(p.get("files")):
            if not isinstance(f, dict) or not f.get("path"):
                continue
            target = root / f["path"]
            if f.get("change") in ("change", "delete") and not target.exists():
                errors.append("%s: %s is marked %s, but it is not in %s" % (p.get("id"), f["path"], f["change"], p.get("repo")))
            elif f.get("change") == "new":
                if target.exists():
                    errors.append("%s: %s is marked new, but it already exists. Mark it change." % (p.get("id"), f["path"]))
                top = f["path"].split("/")[0]
                if "/" in f["path"] and not (root / top).exists():
                    warnings.append("%s: %s starts a new top-level folder %s/. Keep new files next to similar ones."
                                    % (p.get("id"), f["path"], top))
    return errors, warnings


# --------------------------------------------------------------------------- spec.md


def block_re(name):
    return designdoc.block_re(name)


def without_blocks(text):
    for name in BLOCKS:
        text = block_re(name).sub("", text)
    return text


def _prose(text):
    text = re.sub(r"(?s)<!--.*?-->", "", without_blocks(text))
    text = re.sub(r"(?ms)^```.*?^```", "", text)
    return "\n".join(l for l in text.split("\n") if not l.lstrip().startswith(("|", "#")))


def lint(body):
    """Returns (errors, warnings) for spec.md (without its front matter). No word cap."""
    errors, warnings = [], []
    found = [(n, t) for n, t, _ in designdoc.sections(body) if n is not None]
    want = list(enumerate(HEADINGS, 1))
    if found != want:
        missing = ["%d. %s" % w for w in want if w not in found]
        extra = ["%d. %s" % f for f in found if f not in want]
        errors.append("headings must be the %d fixed ones, in order. Missing: %s. Not expected: %s."
                      % (len(HEADINGS), ", ".join(missing) or "none", ", ".join(extra) or "none"))
    for name, n in BLOCKS.items():
        if not block_re(name).search(body):
            errors.append("the generated block chopchop:%s is missing%s. Put back:\n<!-- chopchop:%s -->\n<!-- /chopchop:%s -->"
                          % (name, " from section %d" % n if n else " (## %s)" % APPENDIX, name, name))
    for n, title, text in designdoc.sections(body):
        if n in PROSE:
            clean = _prose(text).strip()
            if not clean:
                errors.append('section %d (%s) is empty. Write "None." if there is nothing to say.' % (n, title))
            elif clean != "None." and not re.match(r"\*\*In short:\*\*", clean):
                warnings.append('section %d (%s) should start with "**In short:**" and one or two lines.' % (n, title))

    def blank(m):
        return "\n" * m.group(0).count("\n")
    plain = body
    for name in BLOCKS:
        plain = block_re(name).sub(blank, plain)
    plain = re.sub(r"(?ms)^```.*?^```", blank, plain)
    plain = re.sub(r"(?s)<!--.*?-->", blank, plain)
    for i, line in enumerate(plain.split("\n"), 1):
        if designdoc.PLACEHOLDER.search(line):
            errors.append("line %d still has placeholder text: %s" % (i, line.strip()[:60]))
    for i, line in enumerate(body.split("\n"), 1):
        if designdoc.DASHES.search(line):
            errors.append("line %d has a long dash. Use a comma, a full stop or a colon." % i)
    low = _prose(body).lower()
    for word, use in designdoc.BANNED.items():
        if re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(word), low):
            warnings.append('"%s": use "%s"' % (word, use))
    flat = re.sub(r"\s+", " ", re.sub(r"(?m)^\s*([-*+]|\d+[.)])\s+", "\n", _prose(body)))
    for s in re.split(r"(?<=[.!?])\s+|\n", flat):
        s = re.sub(r"`[^`]*`", "x", s).strip()
        if len(s.split()) > designdoc.LONG_SENTENCE:
            warnings.append("long sentence, %d words: %s..." % (len(s.split()), " ".join(s.split()[:8])))
    return errors, warnings


def _cell(s):
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def _fence(code, lang=""):
    code = str(code or "").rstrip("\n")
    ticks = "````" if "```" in code else "```"
    return "%s%s\n%s\n%s" % (ticks, lang, code, ticks)


def _short(text):
    return "**In short:** %s" % text


def _snippet(results, raw):
    r = next((x for x in results if x["raw"] == raw), None)
    if not r:
        return None
    lines = r.get("now") or r.get("old")
    if not lines:
        return None
    out = []
    for line in lines[:cite.MAX_LINES]:
        out.append(cite.mask(line)[0])
    return "\n".join(out)


def render_rules(spec):
    rules = _items(spec, "rules")
    if not rules:
        return "None."
    out = [_short("%d rules. Each says what is possible, what shows it was met, and examples." % len(rules)), ""]
    for r in rules:
        out.append("**%s** %s _(%s)_" % (r.get("id"), r.get("text"), ", ".join(_list(r.get("stories")))))
        out.append("")
        out.append("- Shows it was met: %s" % r.get("met"))
        for j, e in enumerate(_list(r.get("examples")), 1):
            if isinstance(e, dict):
                out.append("- Example %d. Given %s, when %s, then %s." % (j, str(e.get("given", "")).rstrip("."),
                                                                         str(e.get("when", "")).rstrip("."),
                                                                         str(e.get("then", "")).rstrip(".")))
        out.append("")
    if _list(spec.get("out_of_scope")):
        out.append("Out of scope: %s." % ", ".join(spec["out_of_scope"]))
    return "\n".join(out).rstrip()


def render_files(spec):
    pk = ordered_packages(spec)
    if not pk:
        return "None."
    n = sum(len(_list(p.get("files"))) for p in pk)
    repos = sorted({p.get("repo") for p in pk})
    out = [_short("%d files in %d repo%s. Green is new, amber is changed." % (n, len(repos), "" if len(repos) == 1 else "s")),
           "", "```mermaid", diagrams.file_map_mermaid(spec), "```", ""]
    for repo in repos:
        out += ["**%s**" % repo, "", "| Change | File | What | Package |", "| --- | --- | --- | --- |"]
        for p in pk:
            if p.get("repo") != repo:
                continue
            for f in _list(p.get("files")):
                if isinstance(f, dict):
                    out.append("| %s | `%s` | %s | %s |" % (f.get("change"), _cell(f.get("path")), _cell(f.get("what")), p.get("id")))
        out.append("")
    return "\n".join(out).rstrip()


def render_fit(spec, results):
    repos = spec.get("repos") if isinstance(spec.get("repos"), dict) else {}
    pk = ordered_packages(spec)
    names = sorted(set(repos) | {p.get("repo") for p in pk if p.get("repo")})
    if not names:
        return "None."
    out = [_short("New code follows what each repo already does: its folders, names, methods and style."), ""]
    for repo in names:
        info = repos.get(repo) or {}
        out += ["### %s" % repo, ""]
        if _list(info.get("folders")):
            out += ["Where new files go:", ""]
            for f in info["folders"]:
                if isinstance(f, dict):
                    out.append("- `%s`%s%s" % (f.get("path"), ", like `%s`" % f["like"] if f.get("like") else "",
                                               ": %s" % f["why"] if f.get("why") else ""))
            out.append("")
        if _list(info.get("naming")):
            out += ["Names, copied from the neighbors:", "", "| Today | New, same pattern |", "| --- | --- |"]
            out += ["| `%s` | `%s` |" % (_cell(x.get("today")), _cell(x.get("new"))) for x in info["naming"] if isinstance(x, dict)]
            out.append("")
        if info.get("test_example"):
            out += ["Test names look like `%s`." % info["test_example"], ""]
        if _list(info.get("style")):
            out += ["Style rules that apply:", ""] + ["- %s" % s for s in info["style"]] + [""]
        copies = [(p, c) for p in pk if p.get("repo") == repo for c in _list(p.get("copy")) if isinstance(c, dict)]
        for p, c in copies:
            out.append("Code to copy for %s: `%s`. %s%s" % (p.get("id"), c.get("cite"), c.get("why", ""),
                                                            " Change: %s" % c["change"] if c.get("change") else ""))
            snip = _snippet(results, c.get("cite"))
            out += ["", _fence(snip, lang_of(cite.find(c["cite"])[0]["path"]) if cite.find(c["cite"]) else "")] if snip else []
            out.append("")
        reuse = [(p, r) for p in pk if p.get("repo") == repo for r in _list(p.get("reuse")) if isinstance(r, dict)]
        if reuse:
            out += ["Reuse, do not rewrite:", "", "| Use | It does | Where | In |", "| --- | --- | --- | --- |"]
            seen = set()
            for p, r in reuse:
                key = (r.get("name"), r.get("cite"))
                if key in seen:
                    continue
                seen.add(key)
                out.append("| `%s` | %s | `%s` | %s |" % (_cell(r.get("name")), _cell(r.get("does")), _cell(r.get("cite")), p.get("id")))
            out.append("")
        if _list(info.get("do_not")):
            out += ["Do not:", ""] + ["- %s" % d for d in info["do_not"]] + [""]
    return "\n".join(out).rstrip()


def render_contracts(spec):
    cs = _items(spec, "contracts")
    if not cs:
        return "None."
    givers = {c: p.get("id") for p in _items(spec, "packages") for c in _list(p.get("gives"))}
    users = {}
    for p in _items(spec, "packages"):
        for c in _list(p.get("uses")):
            users.setdefault(c, []).append(p.get("id"))
    out = [_short("%d contracts. Each is built by one package and used by others." % len(cs)), ""]
    for c in cs:
        out.append("**%s · %s** (%s, %s). Built by %s%s." % (c.get("id"), c.get("name"), c.get("kind", "contract"),
                                                             c.get("repo", ""), givers.get(c.get("id"), "nobody"),
                                                             ", used by %s" % ", ".join(users[c["id"]]) if users.get(c.get("id")) else ""))
        out += ["", _fence(c.get("example"), c.get("lang", "")), ""]
    return "\n".join(out).rstrip()


def render_failures(spec, flow):
    rows = diagrams.failures(flow or {})
    if not rows:
        return "None."
    tests = {}
    for p in _items(spec, "packages"):
        for t in _list(p.get("tests")):
            if isinstance(t, dict):
                for ref in _list(t.get("failures")):
                    tests.setdefault(ref, []).append("`%s` (%s)" % (t.get("name"), p.get("id")))
    for key in ("journeys", "checks"):
        for x in _items(spec, key):
            for ref in _list(x.get("failures")):
                tests.setdefault(ref, []).append("%s %s" % (x.get("id"), x.get("title")))
    out = [_short("Every failure answer from the main flow, and the test that proves it."), "",
           "| # | Message | Case | What happens | Proved by |", "| --- | --- | --- | --- | --- |"]
    names = {"fails": "Fails", "slow": "Slow", "twice": "Runs twice", "caller": "Wrong caller"}
    for r in rows:
        ref = "%s.%s" % (r["n"], r["question"])
        if r["state"] == "risk":
            proof = "Accepted risk"
        else:
            proof = ", ".join(tests.get(ref, [])) or "**No test yet**"
        out.append("| %s | %s | %s | %s | %s |" % (r["n"], _cell(r["say"]), names.get(r["question"], r["question"]),
                                                  _cell(r["answer"] or "No answer yet"), proof))
    return "\n".join(out)


def render_packages(spec, results, task_of=None):
    pk = ordered_packages(spec)
    if not pk:
        return "None."
    contracts = by_id(spec, "contracts")
    waves = sorted({p.get("wave") for p in pk if isinstance(p.get("wave"), int)})
    out = [_short("%d packages in %d wave%s. Wave 0 is contracts, wave 1 runs in parallel, wave 2 joins them. "
                  "Each package becomes one task." % (len(pk), len(waves), "" if len(waves) == 1 else "s")), ""]
    for p in pk:
        task = (task_of or {}).get(p.get("id"))
        out += ["### %s · %s · %s" % (p.get("id"), p.get("repo"), p.get("title")), "",
                "Wave %s, size %s%s%s. Rules: %s." % (p.get("wave"), p.get("size"),
                                                     ", depends on %s" % ", ".join(p["depends_on"]) if _list(p.get("depends_on")) else "",
                                                     ", task %s" % task if task else "",
                                                     ", ".join(_list(p.get("rules"))) or "none"),
                "", p.get("goal", ""), "", "| Change | File | What |", "| --- | --- | --- |"]
        out += ["| %s | `%s` | %s |" % (f.get("change"), _cell(f.get("path")), _cell(f.get("what")))
                for f in _list(p.get("files")) if isinstance(f, dict)]
        out.append("")
        bullets = []
        if _list(p.get("uses")):
            bullets.append("- **Uses:** %s." % ", ".join("%s %s" % (c, contracts.get(c, {}).get("name", "")) for c in p["uses"]))
        if _list(p.get("gives")):
            bullets.append("- **Gives:** %s." % ", ".join("%s %s" % (c, contracts.get(c, {}).get("name", "")) for c in p["gives"]))
        if _list(p.get("makes")):
            bullets.append("- **New names:** %s." % ", ".join("`%s`" % m for m in p["makes"]))
        for c in _list(p.get("copy")):
            if isinstance(c, dict):
                bullets.append("- **Copy** `%s`: %s%s" % (c.get("cite"), c.get("why", ""), " Change: %s" % c["change"] if c.get("change") else ""))
        if _list(p.get("reuse")):
            bullets.append("- **Reuse:** %s." % ", ".join("`%s`" % r.get("name") for r in p["reuse"] if isinstance(r, dict)))
        if bullets:
            out += bullets + [""]
        for s in _list(p.get("sketch")):
            if isinstance(s, dict):
                out += ["Sketch of `%s`, in this repo's style:" % s.get("file"), "", _fence(s.get("code"), lang_of(s.get("file"))), ""]
        run = p.get("run") if isinstance(p.get("run"), dict) else {}
        out.append("Tests: %s. Run `%s`%s." % (", ".join("`%s`" % t.get("name") for t in _list(p.get("tests")) if isinstance(t, dict)),
                                              run.get("command", ""), ", expect %s" % run["expect"] if run.get("expect") else ""))
        if _list(p.get("do_not")):
            out += ["", "Do not:", ""] + ["- %s" % d for d in p["do_not"]]
        out.append("")
    return "\n".join(out).rstrip()


def render_tests(spec, level):
    rows = []
    for p in ordered_packages(spec):
        for t in _list(p.get("tests")):
            if isinstance(t, dict) and t.get("level", "unit") == level:
                rows.append("| `%s` | %s · %s | %s | %s |" % (_cell(t.get("name")), p.get("repo"), p.get("id"),
                                                               _cell(t.get("proves")),
                                                               ", ".join(_list(t.get("rules")) + _list(t.get("failures")))))
    if not rows:
        return "None."
    head = _short("%d %s tests. Each names its values and what it proves." % (len(rows), level))
    return "\n".join([head, "", "| Test | Repo · package | Proves | Rules and failures |", "| --- | --- | --- | --- |"] + rows)


def render_journeys(spec, task_of=None):
    js = _items(spec, "journeys")
    if not js:
        return "None."
    out = [_short("%d end-to-end journeys. Each runs the repo's own way, or is signed by a person." % len(js)), ""]
    for j in js:
        manual = j.get("manual") if isinstance(j.get("manual"), dict) else None
        run = j.get("run") if isinstance(j.get("run"), dict) else {}
        task = (task_of or {}).get(j.get("id"))
        out += ["### %s · %s" % (j.get("id"), j.get("title")), ""]
        out.append("Stories: %s. Proves: %s.%s" % (", ".join(_list(j.get("stories"))) or "none",
                                                   ", ".join(_list(j.get("rules"))) or "none", " Task %s." % task if task else ""))
        if manual:
            out.append("Manual: signed by %s, because the repo has no e2e suite." % manual.get("who"))
        else:
            out.append("Runs in %s with `%s`%s. Test file `%s`." % (j.get("repo"), run.get("command"),
                                                                    " (found in %s)" % run["found_in"] if run.get("found_in") else "",
                                                                    j.get("file")))
        out += ["", "Data: %s" % j.get("data"), "", "| # | Do | See |", "| --- | --- | --- |"]
        out += ["| %d | %s | %s |" % (i, _cell(s.get("do")), _cell(s.get("see")))
                for i, s in enumerate(_list(j.get("steps")), 1) if isinstance(s, dict)]
        out.append("")
    return "\n".join(out).rstrip()


def render_checks(spec):
    ms = _items(spec, "checks")
    if not ms:
        return "None."
    out = [_short("%d manual checks. Each is signed by a named person." % len(ms)), ""]
    for m in ms:
        out += ["**%s · %s.** Signed by %s. Proves: %s." % (m.get("id"), m.get("title"), m.get("who"),
                                                            ", ".join(_list(m.get("rules"))) or "none"), ""]
        out += ["%d. %s" % (i, s) for i, s in enumerate(_list(m.get("steps")), 1)]
        out.append("")
    return "\n".join(out).rstrip()


def render_decisions(spec, opts=None):
    out = [_short("The choices behind this spec, what we assumed, and what is still open."), ""]
    picked = []
    for c in _list((opts or {}).get("choices")):
        if isinstance(c, dict) and c.get("picked"):
            o = next((x for x in _list(c.get("options")) if isinstance(x, dict) and x.get("key") == c["picked"]), {})
            picked.append("- %s **%s: %s** (picked by %s)" % (c.get("question"), c["picked"], o.get("title", ""),
                                                              c.get("picked_by") or "you"))
    out += ["Decisions from options.md:", ""] + (picked or ["- None."]) + [""]
    out += ["Assumptions:", ""] + (["- %s" % a for a in _list(spec.get("assumptions"))] or ["- None."]) + [""]
    qs = _items(spec, "questions")
    out += ["Open questions:", ""]
    for q in qs:
        state = "answered: %s" % q["answer"] if q.get("answer") else ("**blocks the build**" if q.get("blocking") else "open")
        out.append("- %s Owner: %s. %s." % (q.get("text"), q.get("owner") or "nobody", state))
    if not qs:
        out.append("- None.")
    return "\n".join(out)


# --------------------------------------------------------------------------- tasks from the spec


def _slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return s[:40].rstrip("-") or "task"


def task_plan(spec):
    """Task ids for every package (in wave order) and every journey that runs in a repo."""
    out, n = [], 0
    for p in ordered_packages(spec):
        n += 1
        out.append({"id": "T%02d" % n, "package": p["id"], "slug": _slug(p.get("title"))})
    for j in _items(spec, "journeys"):
        if isinstance(j.get("manual"), dict):
            continue
        n += 1
        out.append({"id": "T%02d" % n, "journey": j["id"], "slug": "prove-" + _slug(j.get("title"))})
    return out


def _quote_rules(spec, ids):
    rules = by_id(spec, "rules")
    out = []
    for rid in ids:
        r = rules.get(rid)
        if r:
            out.append('> From spec/spec.md §4, %s: "%s" Shows it was met: %s' % (rid, r.get("text"), r.get("met")))
            for j, e in enumerate(_list(r.get("examples")), 1):
                if isinstance(e, dict):
                    out.append(">\n> Example %d. Given %s, when %s, then %s." % (j, str(e.get("given")).rstrip("."),
                                                                               str(e.get("when")).rstrip("."),
                                                                               str(e.get("then")).rstrip(".")))
            out.append("")
    return out


def to_tasks(spec, snippets=None):
    """[{"meta": {...}, "body": "...", "file": "T01-slug.md"}] for every package and runnable journey.
    snippets: {citation: code} so each task carries the real code to copy."""
    plan = task_plan(spec)
    task_of = {x.get("package") or x.get("journey"): x["id"] for x in plan}
    packages = by_id(spec, "packages")
    contracts = by_id(spec, "contracts")
    rules = by_id(spec, "rules")
    repos_info = spec.get("repos") if isinstance(spec.get("repos"), dict) else {}
    givers = {c: p.get("id") for p in packages.values() for c in _list(p.get("gives"))}
    out = []
    for x in plan:
        if x.get("package"):
            p = packages[x["package"]]
            deps = set(_list(p.get("depends_on"))) | {
                givers[c] for c in _list(p.get("uses")) if givers.get(c) and givers[c] != p["id"]
                and isinstance(packages[givers[c]].get("wave"), int) and isinstance(p.get("wave"), int)
                and packages[givers[c]]["wave"] < p["wave"]}
            stories = sorted({s for rid in _list(p.get("rules")) for s in _list(rules.get(rid, {}).get("stories"))})
            meta = {"id": x["id"], "title": p.get("title"), "repo": p.get("repo"), "wave": p.get("wave"),
                    "size": p.get("size"), "status": "todo", "owner": None,
                    "depends_on": sorted(task_of[d] for d in deps if d in task_of),
                    "touches": [f.get("path") for f in _list(p.get("files")) if isinstance(f, dict)],
                    "stories": stories, "package": p["id"], "pr": None}
            body = ["# %s · %s" % (x["id"], p.get("title")), "", "## Goal", "", p.get("goal", ""), "", "## Context", ""]
            body += _quote_rules(spec, _list(p.get("rules"))) or ["None."]
            body += ["## Contract", ""]
            for c in _list(p.get("uses")):
                g = packages.get(givers.get(c), {})
                if g.get("repo") != p.get("repo"):
                    body += ["- Uses: %s %s, built by %s in %s. Code against this exact shape, with a mock:"
                             % (c, contracts.get(c, {}).get("name", ""), task_of.get(givers.get(c), "another task"), g.get("repo")),
                             "", _fence(contracts.get(c, {}).get("example"), contracts.get(c, {}).get("lang", "")), ""]
                else:
                    body.append("- Uses: %s %s, from %s." % (c, contracts.get(c, {}).get("name", ""), task_of.get(givers.get(c), "an earlier task")))
            for c in _list(p.get("gives")):
                body += ["- Gives: %s %s. Later tasks code against it exactly:" % (c, contracts.get(c, {}).get("name", "")), "",
                         _fence(contracts.get(c, {}).get("example"), contracts.get(c, {}).get("lang", "")), ""]
            if not _list(p.get("uses")) and not _list(p.get("gives")):
                body.append("None.")
            body += ["", "## Code", "", "Follow the code that is there. From spec/spec.md §7 and §14.", ""]
            info = repos_info.get(p.get("repo")) or {}
            for f in _list(info.get("folders")):
                if isinstance(f, dict):
                    body.append("- New files go in `%s`%s." % (f.get("path"), ", like `%s`" % f["like"] if f.get("like") else ""))
            for nm in _list(info.get("naming")):
                if isinstance(nm, dict):
                    body.append("- Name: `%s` like `%s`." % (nm.get("new"), nm.get("today")))
            if info.get("test_example"):
                body.append("- Test names look like `%s`." % info["test_example"])
            for c in _list(p.get("copy")):
                if isinstance(c, dict):
                    body.append("- Copy `%s`: %s%s" % (c.get("cite"), c.get("why", ""), " Change: %s" % c["change"] if c.get("change") else ""))
                    code = (snippets or {}).get(c.get("cite"))
                    if code:
                        found = cite.find(c["cite"])
                        body += ["", _fence(code, lang_of(found[0]["path"]) if found else ""), ""]
            for r in _list(p.get("reuse")):
                if isinstance(r, dict):
                    body.append("- Reuse `%s` (`%s`): %s" % (r.get("name"), r.get("cite"), r.get("does", "")))
            for s in _list(p.get("sketch")):
                if isinstance(s, dict):
                    body += ["", "Sketch of `%s`:" % s.get("file"), "", _fence(s.get("code"), lang_of(s.get("file")))]
            body += ["", "## Files", ""]
            body += ["- `%s` (%s): %s" % (f.get("path"), f.get("change"), f.get("what")) for f in _list(p.get("files")) if isinstance(f, dict)]
            body += ["", "## Done when", ""]
            for t in _list(p.get("tests")):
                if isinstance(t, dict):
                    body.append("- [ ] %s test `%s`: %s" % ("Unit" if t.get("level", "unit") == "unit" else "Integration",
                                                            t.get("name"), t.get("proves")))
            run = p.get("run") if isinstance(p.get("run"), dict) else {}
            body.append("- [ ] Build, lint and all tests pass. These tests run with `%s`." % run.get("command", ""))
            body += ["", "## Do not change", ""]
            body += ["- %s" % d for d in _list(p.get("do_not")) + _list(info.get("do_not"))]
            body.append("- Contracts from earlier tasks. If one must change, log it in changelog.md first.")
        else:
            j = by_id(spec, "journeys")[x["journey"]]
            run = j.get("run") if isinstance(j.get("run"), dict) else {}
            needs = {task_of[p["id"]] for p in packages.values()
                     if set(_list(p.get("rules"))) & set(_list(j.get("rules"))) and p["id"] in task_of}
            meta = {"id": x["id"], "title": "Prove: %s" % j.get("title"), "repo": j.get("repo"), "wave": PROVE_WAVE,
                    "size": "S", "status": "todo", "owner": None, "depends_on": sorted(needs),
                    "touches": [j.get("file")], "stories": _list(j.get("stories")), "kind": "prove",
                    "journey": j["id"], "e2e": run.get("command"), "pr": None}
            body = ["# %s · Prove: %s" % (x["id"], j.get("title")), "", "## Goal", "",
                    "The end-to-end journey %s passes, run the way %s runs e2e tests." % (j["id"], j.get("repo")), "",
                    "## Context", ""]
            body += _quote_rules(spec, _list(j.get("rules")))
            body += ["Test data: %s" % j.get("data"), "", "| # | Do | See |", "| --- | --- | --- |"]
            body += ["| %d | %s | %s |" % (i, _cell(s.get("do")), _cell(s.get("see"))) for i, s in enumerate(_list(j.get("steps")), 1)
                     if isinstance(s, dict)]
            body += ["", "## Files", "", "- `%s` (new): the e2e test for %s" % (j.get("file"), j["id"]), "",
                     "## Done when", "",
                     "- [ ] E2E test `%s` passes with `%s`." % (j.get("file"), run.get("command")),
                     "- [ ] Each step's \"See\" is checked by the test.", "",
                     "## Do not change", "", "- App code. If the journey fails, log the bug in changelog.md and tell the owner of the task that built it."]
        body += ["", "## Branch", "", "_Written by chopchop. Do not edit this part._", ""]
        out.append({"meta": meta, "body": "\n".join(body), "file": "%s-%s.md" % (x["id"], x["slug"])})
    return out


# --------------------------------------------------------------------------- done status


def status(spec, tasks, verify=None, proof=None):
    """The state of every item. tasks: [Task]; verify: {task id: {"ok", "when", "commit"}}; proof: work/proof.json."""
    verify = verify or {}
    signs = ((proof or {}).get("signed") or {}) if isinstance(proof, dict) else {}
    plan = task_plan(spec)
    task_of = {x.get("package") or x.get("journey"): x["id"] for x in plan}
    tmap = {t.id: t for t in tasks or []}
    for t in tasks or []:
        key = t.get("package") or t.get("journey")
        if key:
            task_of[key] = t.id

    def task_state(tid):
        t = tmap.get(tid)
        v = verify.get(tid) or {}
        if t is None:
            return "planned", "no task yet"
        if v and v.get("ok") is False:
            return "failing", "%s: last check failed %s" % (tid, (v.get("when") or "")[:10])
        if t.get("status") == "done":
            if v.get("ok"):
                return "proved", "%s merged, checks passed %s" % (tid, (v.get("when") or "")[:10])
            return "built", "%s merged, no passing check saved" % tid
        return "planned", "%s is %s" % (tid, t.get("status"))

    items = []
    for p in ordered_packages(spec):
        st, note = task_state(task_of.get(p["id"]))
        for t in _list(p.get("tests")):
            if isinstance(t, dict):
                items.append({"kind": t.get("level", "unit"), "id": t.get("name"), "title": t.get("proves"),
                              "rules": _list(t.get("rules")), "state": st, "how": note, "package": p["id"]})
    for j in _items(spec, "journeys"):
        if isinstance(j.get("manual"), dict):
            s = signs.get(j["id"])
            items.append({"kind": "journey", "id": j["id"], "title": j.get("title"), "rules": _list(j.get("rules")),
                          "state": "proved" if s else "waiting",
                          "how": "signed by %s on %s" % (s["by"], s["on"]) if s else "to be signed by %s" % j["manual"].get("who")})
        else:
            st, note = task_state(task_of.get(j["id"]))
            items.append({"kind": "journey", "id": j["id"], "title": j.get("title"), "rules": _list(j.get("rules")),
                          "state": st, "how": note})
    for m in _items(spec, "checks"):
        s = signs.get(m["id"])
        items.append({"kind": "manual", "id": m["id"], "title": m.get("title"), "rules": _list(m.get("rules")),
                      "state": "proved" if s else "waiting",
                      "how": "signed by %s on %s" % (s["by"], s["on"]) if s else "to be signed by %s" % m.get("who")})
    rules = []
    for r in _items(spec, "rules"):
        mine = [i for i in items if r["id"] in i["rules"]]
        states = {i["state"] for i in mine}
        st = ("failing" if "failing" in states else "proved" if mine and states == {"proved"} else
              "built" if mine and states <= {"proved", "built"} else "planned")
        rules.append({"id": r["id"], "title": r.get("text"), "stories": _list(r.get("stories")), "state": st,
                      "how": "%d of %d proofs passed" % (sum(1 for i in mine if i["state"] == "proved"), len(mine))})
    open_q = [q for q in _items(spec, "questions") if not q.get("answer")]
    proved = sum(1 for i in items if i["state"] == "proved")
    all_done = bool(items) and proved == len(items) and all(r["state"] == "proved" for r in rules) and \
        not [q for q in open_q if q.get("blocking")]
    return {"items": items, "rules": rules, "proved": proved, "total": len(items),
            "tasks": {"total": len(tasks or []), "done": sum(1 for t in tasks or [] if t.get("status") == "done")},
            "open_questions": len(open_q), "ready_for_done": all_done, "task_of": task_of}


def render_done(st, meta=None):
    meta = meta or {}
    if meta.get("status") == "done":
        head = "**Done.** Set by %s on %s." % (meta.get("done_by"), meta.get("done_on"))
    else:
        head = _short("%d of %d proofs passed, %d of %d tasks done. Only a person sets Done, when everything is Proved."
                      % (st["proved"], st["total"], st["tasks"]["done"], st["tasks"]["total"]))
    out = [head, "", "| Proof | Kind | State | How we know |", "| --- | --- | --- | --- |"]
    for i in st["items"]:
        out.append("| `%s` | %s | %s | %s |" % (_cell(i["id"]), i["kind"], STATE_TEXT[i["state"]], _cell(i["how"])))
    out += ["", "| Rule | State | Proofs |", "| --- | --- | --- |"]
    out += ["| %s | %s | %s |" % (r["id"], STATE_TEXT[r["state"]], r["how"]) for r in st["rules"]]
    out += ["", "The feature checklist:", ""]
    checks = [
        (all(r["state"] == "proved" for r in st["rules"]) and st["rules"], "Every rule, and so every story and AC, is proved."),
        (st["tasks"]["total"] and st["tasks"]["done"] == st["tasks"]["total"], "Every task PR is merged by a person."),
        (all(i["state"] == "proved" for i in st["items"] if i["kind"] in ("unit", "integration")),
         "Each repo builds, lint passes, and all unit and integration tests pass."),
        (all(i["state"] == "proved" for i in st["items"] if i["kind"] == "journey"), "Every end-to-end journey passes."),
        (all(i["state"] == "proved" for i in st["items"] if i["kind"] == "manual"), "Every manual check is signed."),
        (not st["open_questions"], "No open question is left."),
    ]
    out += ["- [%s] %s" % ("x" if ok else " ", text) for ok, text in checks]
    return "\n".join(out)


def render_trace(spec, st):
    task_of = st.get("task_of") or {}
    out = ["| Story | Rule | Packages | Tests | Tasks |", "| --- | --- | --- | --- | --- |"]
    for r in _items(spec, "rules"):
        pk = [p for p in ordered_packages(spec) if r["id"] in _list(p.get("rules"))]
        tests = [t.get("name") for p in _items(spec, "packages") for t in _list(p.get("tests"))
                 if isinstance(t, dict) and r["id"] in _list(t.get("rules"))]
        tests += [j["id"] for j in _items(spec, "journeys") if r["id"] in _list(j.get("rules"))]
        tests += [m["id"] for m in _items(spec, "checks") if r["id"] in _list(m.get("rules"))]
        tasks = sorted({task_of[p["id"]] for p in pk if p["id"] in task_of})
        out.append("| %s | %s | %s | %s | %s |" % (", ".join(_list(r.get("stories"))), r["id"], ", ".join(p["id"] for p in pk) or "none",
                                                   ", ".join("`%s`" % t for t in tests) or "none", ", ".join(tasks) or "not cut yet"))
    return "\n".join(out)


def counts(spec):
    pk = _items(spec, "packages")
    return {"rules": len(_items(spec, "rules")), "packages": len(pk),
            "files": sum(len(_list(p.get("files"))) for p in pk),
            "tests": sum(len(_list(p.get("tests"))) for p in pk),
            "journeys": len(_items(spec, "journeys")), "checks": len(_items(spec, "checks")),
            "repos": len({p.get("repo") for p in pk})}

