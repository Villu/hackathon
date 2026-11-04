"""Synthetic workload for the live-Azure track. Prints log lines that tell one incident story
per app, so `query_logs` against Log Analytics returns something worth triaging.

Runs inside a stock python:3.12-alpine Container App (no image build): azure_bootstrap.sh
passes this file base64-encoded. PROFILE picks the story; APP_VERSION marks the revision.
Synthetic data only.
"""

import os
import random
import sys
import time

PROFILE = os.environ.get("PROFILE", "orders-api")
VERSION = os.environ.get("APP_VERSION", "1.0.0")
BAD_VERSIONS = set(os.environ.get("BAD_VERSIONS", "2.14.0").split(","))

STORIES = {
    "orders-api": {
        "bad": [
            (6, "ERROR HTTP 500 GET /api/orders/{id} NullReferenceException at OrderMapper.MapV2 (OrderMapper.cs:88)"),
            (3, "ERROR HTTP 500 POST /api/orders ArgumentNullException: discountCode"),
            (2, "WARN Retrying downstream call to pricing-svc (attempt 2)"),
            (1, "INFO HTTP 200 GET /health"),
        ],
        "good": [
            (8, "INFO HTTP 200 GET /api/orders/{id} 41ms"),
            (2, "INFO HTTP 201 POST /api/orders 88ms"),
            (1, "WARN slow request 900ms GET /api/orders/search"),
        ],
    },
    "payments-worker": {
        "bad": [
            (5, "ERROR connection refused: inventory-db-proxy:5432 (psycopg.OperationalError) after 3 retries"),
            (3, "ERROR job payments.settle failed: could not connect to inventory-db-proxy"),
            (2, "WARN circuit open for inventory-db-proxy, sleeping 5s"),
            (1, "INFO heartbeat ok"),
        ],
    },
    "checkout-frontend": {
        "bad": [
            (3, "ERROR container killed: OOMKilled (exit 137), memory limit 512Mi"),
            (4, "WARN GC pressure: heap 498Mi / 512Mi"),
            (2, "WARN image cache size 310Mi exceeds soft limit"),
            (2, "INFO served /checkout in 210ms"),
        ],
    },
    "search-indexer": {
        "bad": [
            (5, "INFO indexed batch of 5000 docs in 1.9s"),
            (3, "INFO queue depth 12000 (autoscaling to 7 replicas)"),
            (2, "WARN p95 latency 850ms above SLO 500ms"),
        ],
    },
}


def lines_for(profile: str, version: str) -> list[tuple[int, str]]:
    story = STORIES.get(profile, {"bad": [(1, "INFO ok")]})
    if "good" in story and version not in BAD_VERSIONS:
        return story["good"]
    return story["bad"]


def main() -> None:
    lines = lines_for(PROFILE, VERSION)
    weights = [w for w, _ in lines]
    print(f"INFO {PROFILE} {VERSION} starting", flush=True)
    while True:
        _, msg = random.choices(lines, weights=weights)[0]
        print(
            f"{msg} [app={PROFILE} version={VERSION}]",
            file=sys.stderr if msg.startswith("ERROR") else sys.stdout,
            flush=True,
        )
        time.sleep(random.uniform(1.0, 4.0))


if __name__ == "__main__":
    main()
