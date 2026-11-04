"""Emit synthetic alerts to the gateway (REST), to Kafka, or to stdout.

python -m simulator.alert_generator --scenario cpu_spike --count 1
python -m simulator.alert_generator --scenario mixed --rate 5 --count 100 --shape prometheus
python -m simulator.alert_generator --sink kafka --scenario mixed --rate 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time

import httpx

from simulator.scenarios import SCENARIOS, SHAPES, build


async def run(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed)
    shape = SHAPES[args.shape]
    interval = 1.0 / args.rate if args.rate > 0 else 0.0
    sent = 0
    failed = 0

    producer = None
    if args.sink == "kafka":
        from aiokafka import AIOKafkaProducer

        producer = AIOKafkaProducer(bootstrap_servers=args.bootstrap)
        await producer.start()

    async with httpx.AsyncClient(timeout=5.0) as http:
        count = args.count if args.count > 0 else sys.maxsize
        for _ in range(count):
            alert = build(args.scenario, rng, args.env)
            payload = shape(alert)
            try:
                if args.sink == "stdout":
                    print(json.dumps(payload))
                elif args.sink == "rest":
                    t0 = time.perf_counter()
                    resp = await http.post(f"{args.gateway}/alerts", json=payload)
                    ms = int((time.perf_counter() - t0) * 1000)
                    print(
                        f"{resp.status_code} {alert['name']:<26} {alert['resource']['name']:<18} {alert['alert_id']}  ack={ms}ms",  # noqa: E501
                        file=sys.stderr,
                    )
                    resp.raise_for_status()
                else:
                    await producer.send_and_wait(args.topic, json.dumps(payload).encode())
                    print(f"kafka {alert['name']} {alert['alert_id']}", file=sys.stderr)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"send failed: {exc}", file=sys.stderr)
            if interval:
                await asyncio.sleep(interval)
    if producer:
        await producer.stop()
    print(f"sent={sent} failed={failed}", file=sys.stderr)
    return 0 if failed == 0 else 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default="mixed", choices=[*SCENARIOS, "mixed"])
    ap.add_argument("--count", type=int, default=1, help="0 = forever")
    ap.add_argument("--rate", type=float, default=1.0, help="alerts per second (0 = as fast as possible)")
    ap.add_argument("--shape", default="normalised", choices=list(SHAPES))
    ap.add_argument("--sink", default="rest", choices=["rest", "kafka", "stdout"])
    ap.add_argument("--gateway", default="http://localhost:8080")
    ap.add_argument("--bootstrap", default="localhost:19092")
    ap.add_argument("--topic", default="alerts")
    ap.add_argument("--env", default=None, choices=[None, "prod", "staging", "dev"])
    ap.add_argument("--seed", type=int, default=None)
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
