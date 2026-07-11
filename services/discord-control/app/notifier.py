"""
WorkflowNotifier: posts an operational summary to a Discord channel after each
autonomous workflow cycle completes.

Detection: polls OE /health every POLL_INTERVAL_SECONDS for a changed
last_scan timestamp. When the timestamp changes, waits CYCLE_GRACE_PERIOD_SECONDS
(to allow downstream services — prediction queue, risk manager, learning engine,
reflection engine — to finish processing), then gathers current state from all
services and posts exactly one message.

Discord failures are logged and silently absorbed. Workflow execution is
completely independent of Discord availability: a notification failure never
interrupts, delays, or retries the workflow.

Trigger types:
  "Scheduled" — scan was triggered by the OE background scheduler.
  "Manual"    — scan was initiated via the Discord /scan slash command.
                Call signal_manual_trigger() before invoking /scan.
"""

import asyncio
import logging

from app.clients import (
    LearningClient,
    OpportunityClient,
    PredictionClient,
    PredictionQueueClient,
    ReflectionClient,
    RiskManagerClient,
)
from app.formatter import format_notification

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 60
_CYCLE_GRACE_PERIOD_SECONDS = 120


class WorkflowNotifier:
    def __init__(
        self,
        channel_id: int,
        bot,
        opportunity_client: OpportunityClient,
        queue_client: PredictionQueueClient,
        learning_client: LearningClient,
        reflection_client: ReflectionClient,
        prediction_client: PredictionClient,
        risk_manager_client: RiskManagerClient,
        settings,
    ) -> None:
        self._channel_id = channel_id
        self._bot = bot
        self._oe = opportunity_client
        self._pq = queue_client
        self._le = learning_client
        self._re = reflection_client
        self._pred = prediction_client
        self._rm = risk_manager_client
        self._settings = settings
        self._workflow_count: int = 0
        self._pending_trigger: str = "Scheduled"

    def signal_manual_trigger(self) -> None:
        """Mark the next notification as manually triggered (called by /scan handler)."""
        self._pending_trigger = "Manual"

    async def start(self) -> None:
        """
        Background polling loop. Seeds last_scan on startup so the first poll
        does not generate a spurious notification.
        """
        logger.info(
            "WorkflowNotifier starting; channel=%d poll=%ds grace=%ds",
            self._channel_id,
            _POLL_INTERVAL_SECONDS,
            _CYCLE_GRACE_PERIOD_SECONDS,
        )
        last_scan_ts = await self._get_last_scan()
        logger.info("WorkflowNotifier seeded; last_scan=%s", last_scan_ts)

        while True:
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            try:
                current_ts = await self._get_last_scan()
                if current_ts and current_ts != last_scan_ts:
                    trigger = self._pending_trigger
                    self._pending_trigger = "Scheduled"
                    last_scan_ts = current_ts
                    self._workflow_count += 1
                    workflow_num = self._workflow_count
                    logger.info(
                        "WorkflowNotifier: new scan detected; workflow=#%d trigger=%s; "
                        "waiting %ds for cycle to complete",
                        workflow_num,
                        trigger,
                        _CYCLE_GRACE_PERIOD_SECONDS,
                    )
                    await asyncio.sleep(_CYCLE_GRACE_PERIOD_SECONDS)
                    await self._post_notification(workflow_num, trigger, current_ts)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("WorkflowNotifier poll error; continuing")

    async def _get_last_scan(self) -> str | None:
        try:
            health = await self._oe.health()
            v = health.get("last_scan")
            return str(v) if v is not None else None
        except Exception:
            return None

    async def _post_notification(
        self,
        workflow_num: int,
        trigger: str,
        completed_at: str | None,
    ) -> None:
        channel = self._bot.get_channel(self._channel_id)
        if channel is None:
            logger.error(
                "WorkflowNotifier: channel %d not found — "
                "check DISCORD_NOTIFICATION_CHANNEL_ID",
                self._channel_id,
            )
            return
        try:
            message = await self._build_message(workflow_num, trigger, completed_at)
            await channel.send(message)
            logger.info(
                "WorkflowNotifier: notification posted; workflow=#%d channel=%d",
                workflow_num,
                self._channel_id,
            )
        except Exception:
            logger.exception(
                "WorkflowNotifier: failed to post to channel %d; "
                "workflow execution unaffected",
                self._channel_id,
            )

    async def _build_message(
        self,
        workflow_num: int,
        trigger: str,
        completed_at: str | None,
    ) -> str:
        results = await asyncio.gather(
            self._oe.health(),
            self._pq.health(),
            self._pq.get_stats(),
            self._le.analyze(),
            self._pred.health(),
            self._rm.health(),
            self._oe.get_opportunities(limit=1),
            self._pq.get_activity_stats(),
            self._oe.get_best_by_category(),
            return_exceptions=True,
        )

        def _safe(r):
            return r if isinstance(r, dict) else {"error": str(r)}

        (oe_health, pq_health, pq_stats, analysis,
         pred_health, rm_health, top_opps, activity, by_category) = [_safe(r) for r in results]

        reflection: dict = {"error": "no analysis available"}
        if "error" not in analysis and analysis.get("analysis_id"):
            try:
                reflection = await self._re.reflect(analysis["analysis_id"])
                if not isinstance(reflection, dict):
                    reflection = {"error": "unexpected response"}
            except Exception as exc:
                reflection = {"error": str(exc)}

        return format_notification(
            oe_health=oe_health,
            pq_health=pq_health,
            pq_stats=pq_stats,
            analysis=analysis,
            pred_health=pred_health,
            rm_health=rm_health,
            top_opps=top_opps,
            reflection=reflection,
            settings=self._settings,
            workflow_num=workflow_num,
            trigger=trigger,
            completed_at=completed_at,
            activity=activity,
            by_category=by_category,
        )
