"""Optional Kafka source (`STREAM_SOURCE=kafka`, `pip install -e ".[kafka]"`, `docker compose up -d`).

Consumes JSON alerts from `KAFKA_ALERTS_TOPIC` and feeds them to the pipeline exactly like the
REST endpoint does. Publishing decisions to `KAFKA_DECISIONS_TOPIC` is a stretch goal.
"""

from __future__ import annotations

import asyncio
import json
import logging

from gateway.config import Settings
from gateway.logs import log_event
from gateway.stream.normalise import NormalisationError, normalise

logger = logging.getLogger("gateway.kafka")


class KafkaAlertSource:
    def __init__(self, pipeline, settings: Settings) -> None:
        self.pipeline = pipeline
        self.settings = settings
        self._consumer = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        try:
            from aiokafka import AIOKafkaConsumer
        except ImportError as exc:
            raise RuntimeError("STREAM_SOURCE=kafka requires `pip install -e '.[kafka]'`") from exc
        self._consumer = AIOKafkaConsumer(
            self.settings.kafka_alerts_topic,
            bootstrap_servers=self.settings.kafka_bootstrap,
            group_id="triage-gateway",
            enable_auto_commit=True,
            value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        )
        await self._consumer.start()
        self._task = asyncio.create_task(self._run(), name="kafka-consumer")
        log_event(
            logger, "kafka_started", topic=self.settings.kafka_alerts_topic, bootstrap=self.settings.kafka_bootstrap
        )

    async def _run(self) -> None:
        assert self._consumer is not None
        async for msg in self._consumer:
            try:
                alerts = normalise(msg.value)
            except (NormalisationError, ValueError) as exc:
                log_event(logger, "kafka_bad_message", logging.WARNING, error=str(exc)[:200], offset=msg.offset)
                continue
            self.pipeline.submit(alerts)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        if self._consumer:
            await self._consumer.stop()
