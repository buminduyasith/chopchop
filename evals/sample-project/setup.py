#!/usr/bin/env python3
"""Build the refunds sample project: 4 tiny git repos and a chopchop workspace.

Usage
  setup.py --to DIR          build it in DIR (must be empty or missing)
  setup.py --to DIR --json   also print the commits of each repo

Traps for chopchop to catch:
  - payments-api returns errors two ways: ApiError (order cancel) and ProblemDetail (payouts).
  - ledger-service listens to payment events. No story mentions it.
  - A second commit moves PayoutJob down 4 lines, changes the CardClient timeout from 10 s
    to 15 s, and deletes LegacyRefundNote.java, so citations made at the first commit are
    moved, changed and gone.
  - The language, the test tool and the database are all in the code. Asking about them is wrong.

The tests and the eval cases use it. A new user can try chopchop on it in a few minutes.
Standard library only. Python 3.8+.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parents[1]
STORIES = PLUGIN / "skills" / "stories" / "scripts" / "chopchop_stories.py"

REPOS = {
    "payments-api": {
        "CODEOWNERS": "* @pay-team\n/db/ @pay-team @dba-team\n",
        "README.md": "# payments-api\n\nPayments, order cancel and payouts. Java 17, Spring Boot, PostgreSQL.\n"
                     "Build and test with `./gradlew test`.\n",
        "build.gradle": "plugins { id 'java' }\ndependencies { testImplementation 'org.junit.jupiter:junit-jupiter:5.10.0' }\n",
        "openapi.yaml": "openapi: 3.0.0\ninfo: {title: payments-api, version: '1'}\npaths:\n"
                        "  /payments: {post: {summary: Pay}}\n  /orders/{id}/cancel: {post: {summary: Cancel an order}}\n",
        "docs/adr/0001-events-through-outbox.md": "# ADR 1: Events go out through the outbox table\n\n"
                                                  "Status: Accepted\n\nEvery event is written to the outbox in the same "
                                                  "transaction, then sent. A consumer can get an event twice.\n",
        "db/migration/V40__payments.sql": "CREATE TABLE payments (id BIGINT PRIMARY KEY, order_id BIGINT NOT NULL,\n"
                                          "  amount NUMERIC(12,2) NOT NULL, paid_at TIMESTAMP NOT NULL);\n",
        "db/migration/V41__order_cancellations.sql": "CREATE TABLE order_cancellations (id BIGINT PRIMARY KEY,\n"
                                                     "  order_id BIGINT NOT NULL, status VARCHAR(20) NOT NULL);\n",
        "src/errors/ApiError.java": "package pay.errors;\n\n/** The error body order and payment endpoints return. */\n"
                                    "public record ApiError(String code, String message) {}\n",
        "src/orders/cancel/OrderCancelService.java": (
            "package pay.orders.cancel;\n\n"
            "public class OrderCancelService {\n"
            "    private final Orders orders;\n"
            "    private final Cancellations cancellations;\n\n"
            "    public OrderCancelService(Orders orders, Cancellations cancellations) {\n"
            "        this.orders = orders;\n"
            "        this.cancellations = cancellations;\n"
            "    }\n\n"
            "    public OrderCancel cancel(long orderId, User by) {\n"
            "        Order order = orders.findOwned(orderId, by);\n"
            "        order.requireStatus(OrderStatus.PAID);\n"
            "        OrderCancel c = OrderCancel.pending(order);\n"
            "        return cancellations.save(c);\n"
            "    }\n"
            "}\n"),
        "src/orders/Order.java": (
            "package pay.orders;\n\n"
            "import java.time.Instant;\n\n"
            "public class Order {\n"
            "    private final long id;\n"
            "    private OrderStatus status;\n"
            "    private Instant paidAt;\n\n"
            "    public Instant paidAt() { return paidAt; }\n\n"
            "    public void requireStatus(OrderStatus wanted) {\n"
            "        if (status != wanted) throw new IllegalStateException(\"order \" + id + \" is \" + status);\n"
            "    }\n"
            "}\n"),
        "src/payouts/PayoutJob.java": (
            "package pay.payouts;\n\n"
            "public class PayoutJob {\n"
            "    private static final int MAX_TRIES = 5;\n\n"
            "    @Scheduled(fixedDelay = 60_000)\n"
            "    public void run() {\n"
            "        for (Payout p : payouts.findPending(50)) {\n"
            "            retry.run(p, MAX_TRIES, () -> card.payout(p));\n"
            "        }\n"
            "    }\n"
            "}\n"),
        "src/payouts/PayoutErrors.java": "package pay.payouts;\n\n/** Payout endpoints return RFC 7807 problem details. */\n"
                                         "public class PayoutErrors { ProblemDetail notFound() { return ProblemDetail.forStatus(404); } }\n",
        "src/provider/CardClient.java": (
            "package pay.provider;\n\n"
            "public class CardClient {\n"
            "    private static final Duration TIMEOUT = Duration.ofSeconds(10);\n\n"
            "    public PayoutResult payout(Payout p) {\n"
            "        return http.post(\"/payouts\", p, TIMEOUT);\n"
            "    }\n"
            "}\n"),
        "src/events/EventPublisher.java": "package pay.events;\n\n/** Writes events to the outbox table. A sender job publishes them. */\n"
                                          "public class EventPublisher { void publish(String topic, Object body) { outbox.add(topic, body); } }\n",
        "src/legacy/LegacyRefundNote.java": "package pay.legacy;\n\n/** Refunds are done by hand in the provider's portal. */\n"
                                            "public class LegacyRefundNote {}\n",
        "test/orders/OrderCancelServiceTest.java": "class OrderCancelServiceTest { @Test void cancels_only_paid_orders() {} }\n",
    },
    "web-app": {
        "CODEOWNERS": "* @web-team\n",
        "README.md": "# web-app\n\nThe customer site. React and TypeScript. Test with `npm test` (Jest).\n",
        "package.json": "{\"name\": \"web-app\", \"scripts\": {\"test\": \"jest\", \"build\": \"tsc\"}}\n",
        "src/orders/OrderPage.tsx": (
            "import React from 'react';\nimport { cancelOrder } from '../api/paymentsApi';\n\n"
            "export class OrderPage extends React.Component<Props> {\n"
            "  render() {\n"
            "    return <button onClick={() => cancelOrder(this.props.orderId)}>Cancel order</button>;\n"
            "  }\n"
            "}\n"),
        "src/api/paymentsApi.ts": "export async function cancelOrder(id: string) {\n"
                                  "  return fetch(`/api/orders/${id}/cancel`, { method: 'POST' });\n}\n",
    },
    "notify-service": {
        "CODEOWNERS": "* @notify-team\n",
        "README.md": "# notify-service\n\nSends every customer email from payment events. Node and TypeScript.\n",
        "src/handlers/payoutSent.ts": (
            "import { seen, markSeen } from '../store';\n\n"
            "export async function payoutSent(event: PaymentEvent) {\n"
            "  if (await seen(event.id)) return; // the outbox can send an event twice\n"
            "  await sendEmail(event.customerId, 'payout-sent', event);\n"
            "  await markSeen(event.id);\n"
            "}\n"),
        "src/templates/index.ts": "export const templates = { 'payout-sent': 'Your payout is on its way.' };\n",
    },
    "ledger-service": {
        "CODEOWNERS": "* @ledger-team\n",
        "README.md": "# ledger-service\n\nRecords every money movement. Kotlin.\n",
        "src/listeners/PaymentEventsListener.kt": (
            "package ledger.listeners\n\n"
            "@KafkaListener(topicPattern = \"payment\\\\..*\")\n"
            "fun on(event: PaymentEvent) {\n"
            "    ledger.record(event.movement())\n"
            "}\n"),
    },
}

SECOND_COMMIT = {
    "payments-api": {
        "src/payouts/PayoutJob.java": (
            "package pay.payouts;\n\n"
            "import pay.retry.Retry;\n"
            "import pay.provider.CardClient;\n"
            "import java.util.List;\n"
            "import org.springframework.scheduling.annotation.Scheduled;\n\n"
            "public class PayoutJob {\n"
            "    private static final int MAX_TRIES = 5;\n\n"
            "    @Scheduled(fixedDelay = 60_000)\n"
            "    public void run() {\n"
            "        for (Payout p : payouts.findPending(50)) {\n"
            "            retry.run(p, MAX_TRIES, () -> card.payout(p));\n"
            "        }\n"
            "    }\n"
            "}\n"),
        "src/provider/CardClient.java": (
            "package pay.provider;\n\n"
            "public class CardClient {\n"
            "    private static final Duration TIMEOUT = Duration.ofSeconds(15);\n\n"
            "    public PayoutResult payout(Payout p) {\n"
            "        return http.post(\"/payouts\", p, TIMEOUT);\n"
            "    }\n"
            "}\n"),
        "src/legacy/LegacyRefundNote.java": None,
    },
}

STORIES_JSON = {
    "epic": {"id": "PAY-120", "title": "Refunds for card payments",
             "description": "Customers can get their money back for a card payment."},
    "stories": [
        {"id": "PAY-121", "title": "Customer requests a refund",
         "description": "As a customer, I want to ask for a refund of a card payment from my order page.",
         "acceptance_criteria": "- A refund can be asked for within 30 days of the payment.\n"
                                "- The smallest refund is 0.01.\n"
                                "- The customer sees the refund as pending right away."},
        {"id": "PAY-122", "title": "Support agent cancels a refund",
         "description": "As a support agent, I want to cancel a refund while it is still pending.",
         "acceptance_criteria": "- A refund can be cancelled only while it is pending.\n"
                                "- The customer gets one email when the refund is done."},
    ],
}

ENV = dict(os.environ, GIT_AUTHOR_NAME="Sample", GIT_AUTHOR_EMAIL="sample@example.com",
           GIT_COMMITTER_NAME="Sample", GIT_COMMITTER_EMAIL="sample@example.com")


def git(path, *args):
    out = subprocess.run(["git"] + list(args), cwd=str(path), capture_output=True, text=True, env=ENV)
    if out.returncode != 0:
        raise RuntimeError("git %s failed in %s: %s" % (" ".join(args), path, out.stderr.strip()))
    return out.stdout.strip()


def write_files(root, files):
    for rel, text in files.items():
        f = root / rel
        if text is None:
            if f.exists():
                f.unlink()
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")


def build(target):
    target = Path(target).resolve()
    if target.exists() and any(target.iterdir()):
        raise SystemExit("Error: %s is not empty." % target)
    target.mkdir(parents=True, exist_ok=True)
    commits = {}
    for name, files in REPOS.items():
        root = target / name
        root.mkdir()
        git(root, "init", "-q", "-b", "main")
        write_files(root, files)
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "first version")
        commits[name] = {"first": git(root, "rev-parse", "HEAD")}
    for name, files in SECOND_COMMIT.items():
        root = target / name
        write_files(root, files)
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "payout imports, slower card timeout, drop legacy note")
        commits[name]["second"] = git(root, "rev-parse", "HEAD")
    for name in REPOS:
        commits[name]["head"] = git(target / name, "rev-parse", "HEAD")
    ws = target / "_chopchop"
    ws.mkdir()
    (ws / "chopchop.yaml").write_text(
        "team: payments\nbase_branch: main\n\nrepos:\n" +
        "".join("  %s: %s\n" % (n, n) for n in REPOS) +
        "\nbranches:\n  feature: \"feature/{key}-{slug}\"\n  task: \"feature/{key}/{task}-{slug}\"\n", encoding="utf-8")
    stories = target / "stories.json"
    stories.write_text(json.dumps(STORIES_JSON, indent=2), encoding="utf-8")
    out = subprocess.run([sys.executable, str(STORIES), "--ingest", str(stories), "--workspace", str(ws)],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError("stories ingest failed: %s" % out.stderr)
    stories.unlink()
    info = {"root": str(target), "workspace": str(ws), "commits": commits}
    (ws / "sample.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


def main(argv=None):
    p = argparse.ArgumentParser(prog="setup.py", description=__doc__.split("\n")[0])
    p.add_argument("--to", required=True, help="folder to build the sample in")
    p.add_argument("--json", action="store_true", help="print the commits as JSON")
    args = p.parse_args(argv)
    info = build(args.to)
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        print("Sample:   %s" % info["root"])
        print("Next:     cd %s and run /chopchop:learn, then /chopchop:design refunds for card payments" % info["root"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
