"""
Discord bot setup and slash command registration.

This module is intentionally thin: it wires Discord interactions to the
handler functions in commands.py. All logic (authorization, formatting,
client calls) stays in commands.py so it can be tested without Discord.

Slash commands are registered as guild-specific (instant propagation)
using the DISCORD_GUILD_ID setting.
"""

import asyncio
import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands as dc_commands

from app.commands import (
    UNAUTHORIZED_MESSAGE,
    handle_activity,
    handle_analyze,
    handle_brief,
    handle_markets,
    handle_performance,
    handle_predict,
    handle_reflect,
    handle_run,
    handle_scan,
    handle_status,
    handle_workflow,
    is_authorized,
)
from app.config import Settings

logger = logging.getLogger(__name__)


def create_bot(
    prediction_client,
    learning_client,
    reflection_client,
    opportunity_client,
    queue_client,
    risk_manager_client,
    http,
    settings: Settings,
    bot_start_time,
) -> dc_commands.Bot:
    intents = discord.Intents.default()
    bot = dc_commands.Bot(command_prefix=[], intents=intents)
    tree = bot.tree
    guild = discord.Object(id=settings.discord_guild_id)

    # Mutable reference so /scan can signal the notifier before it exists.
    _notifier_ref: list = [None]

    # --- Authorization guard (reused across all commands) -----------------

    async def _deny(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(UNAUTHORIZED_MESSAGE, ephemeral=True)

    def _auth(user_id: int) -> bool:
        return is_authorized(user_id, settings.allowed_user_ids)

    # --- /status ----------------------------------------------------------

    @tree.command(
        name="status",
        description="Show the health of all platform services.",
        guild=guild,
    )
    async def status_cmd(interaction: discord.Interaction) -> None:
        if not _auth(interaction.user.id):
            await _deny(interaction)
            return
        await interaction.response.defer()
        result = await handle_status(
            prediction_client, learning_client, reflection_client, http, settings
        )
        await interaction.followup.send(result)

    # --- /predict ---------------------------------------------------------

    @tree.command(
        name="predict",
        description="Make a binary prediction using the AI core.",
        guild=guild,
    )
    @app_commands.describe(
        question="The prediction question (10–500 characters).",
        category="Prediction category (default: finance).",
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="Finance", value="finance"),
        app_commands.Choice(name="Politics", value="politics"),
        app_commands.Choice(name="Sports", value="sports"),
        app_commands.Choice(name="Weather", value="weather"),
    ])
    async def predict_cmd(
        interaction: discord.Interaction,
        question: str,
        category: app_commands.Choice[str] | None = None,
    ) -> None:
        if not _auth(interaction.user.id):
            await _deny(interaction)
            return
        await interaction.response.defer()
        cat_value = category.value if category else "finance"
        result = await handle_predict(
            question, cat_value, interaction.user.id, prediction_client
        )
        await interaction.followup.send(result)

    # --- /analyze ---------------------------------------------------------

    @tree.command(
        name="analyze",
        description="Run a learning analysis on recent prediction history.",
        guild=guild,
    )
    async def analyze_cmd(interaction: discord.Interaction) -> None:
        if not _auth(interaction.user.id):
            await _deny(interaction)
            return
        await interaction.response.defer()
        result = await handle_analyze(interaction.user.id, learning_client)
        await interaction.followup.send(result)

    # --- /reflect ---------------------------------------------------------

    @tree.command(
        name="reflect",
        description="Run a reflection on the latest learning analysis.",
        guild=guild,
    )
    async def reflect_cmd(interaction: discord.Interaction) -> None:
        if not _auth(interaction.user.id):
            await _deny(interaction)
            return
        await interaction.response.defer()
        result = await handle_reflect(
            interaction.user.id, learning_client, reflection_client
        )
        await interaction.followup.send(result)

    # --- /markets ---------------------------------------------------------

    @tree.command(
        name="markets",
        description="Show current Kalshi market opportunities (read-only diagnostics).",
        guild=guild,
    )
    @app_commands.describe(
        category="Filter by category (default: All).",
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="Finance", value="finance"),
        app_commands.Choice(name="Politics", value="politics"),
        app_commands.Choice(name="Sports", value="sports"),
        app_commands.Choice(name="Weather", value="weather"),
    ])
    async def markets_cmd(
        interaction: discord.Interaction,
        category: app_commands.Choice[str] | None = None,
    ) -> None:
        if not _auth(interaction.user.id):
            await _deny(interaction)
            return
        await interaction.response.defer()
        cat_value = category.value if category else None
        result = await handle_markets(
            interaction.user.id, opportunity_client, category=cat_value
        )
        await interaction.followup.send(result)

    # --- /brief -----------------------------------------------------------

    @tree.command(
        name="brief",
        description="Executive summary: platform status, activity, performance, and best opportunity.",
        guild=guild,
    )
    async def brief_cmd(interaction: discord.Interaction) -> None:
        if not _auth(interaction.user.id):
            await _deny(interaction)
            return
        await interaction.response.defer()
        from datetime import datetime, timezone
        uptime_seconds = (datetime.now(timezone.utc) - bot_start_time).total_seconds()
        result = await handle_brief(
            interaction.user.id,
            opportunity_client,
            queue_client,
            learning_client,
            reflection_client,
            prediction_client,
            risk_manager_client,
            settings,
            uptime_seconds,
        )
        await interaction.followup.send(result)

    # --- /scan ------------------------------------------------------------

    @tree.command(
        name="scan",
        description="Trigger an immediate Opportunity Engine market scan.",
        guild=guild,
    )
    async def scan_cmd(interaction: discord.Interaction) -> None:
        if not _auth(interaction.user.id):
            await _deny(interaction)
            return
        await interaction.response.defer()
        if _notifier_ref[0] is not None:
            _notifier_ref[0].signal_manual_trigger()
        result = await handle_scan(interaction.user.id, opportunity_client)
        await interaction.followup.send(result)

    # --- /workflow --------------------------------------------------------

    @tree.command(
        name="workflow",
        description="Show platform activity summary: markets, queue, predictions, and service health.",
        guild=guild,
    )
    async def workflow_cmd(interaction: discord.Interaction) -> None:
        if not _auth(interaction.user.id):
            await _deny(interaction)
            return
        await interaction.response.defer()
        result = await handle_workflow(
            interaction.user.id,
            opportunity_client,
            queue_client,
            learning_client,
            reflection_client,
            prediction_client,
        )
        await interaction.followup.send(result)

    # --- /performance -----------------------------------------------------

    @tree.command(
        name="performance",
        description="Show prediction accuracy, confidence, and calibration metrics.",
        guild=guild,
    )
    async def performance_cmd(interaction: discord.Interaction) -> None:
        if not _auth(interaction.user.id):
            await _deny(interaction)
            return
        await interaction.response.defer()
        result = await handle_performance(
            interaction.user.id, learning_client, settings
        )
        await interaction.followup.send(result)

    # --- /activity --------------------------------------------------------

    @tree.command(
        name="activity",
        description="Show the most recent platform events: predictions and opportunity scans.",
        guild=guild,
    )
    async def activity_cmd(interaction: discord.Interaction) -> None:
        if not _auth(interaction.user.id):
            await _deny(interaction)
            return
        await interaction.response.defer()
        result = await handle_activity(
            interaction.user.id, queue_client, opportunity_client
        )
        await interaction.followup.send(result)

    # --- /run -------------------------------------------------------------

    @tree.command(
        name="run",
        description="Manually execute one workflow iteration (predict → risk → trade).",
        guild=guild,
    )
    async def run_cmd(interaction: discord.Interaction) -> None:
        if not _auth(interaction.user.id):
            await _deny(interaction)
            return
        await interaction.response.defer()
        result = await handle_run(interaction.user.id, queue_client)
        await interaction.followup.send(result)

    # --- Lifecycle --------------------------------------------------------

    @bot.event
    async def on_ready() -> None:
        synced = await tree.sync(guild=guild)
        logger.info(
            "Logged in as %s — synced %d command(s) to guild %d",
            bot.user,
            len(synced),
            settings.discord_guild_id,
        )
        # Signal file checked by the Docker healthcheck.
        Path("/tmp/bot_ready").touch()

        # Start workflow notifier if configured.
        if settings.discord_notifications_enabled and settings.discord_notification_channel_id:
            from app.notifier import WorkflowNotifier
            notifier = WorkflowNotifier(
                channel_id=settings.discord_notification_channel_id,
                bot=bot,
                opportunity_client=opportunity_client,
                queue_client=queue_client,
                learning_client=learning_client,
                reflection_client=reflection_client,
                prediction_client=prediction_client,
                risk_manager_client=risk_manager_client,
                settings=settings,
            )
            _notifier_ref[0] = notifier
            asyncio.create_task(notifier.start())
            logger.info(
                "WorkflowNotifier started; channel=%d",
                settings.discord_notification_channel_id,
            )
        else:
            logger.info(
                "WorkflowNotifier disabled; "
                "DISCORD_NOTIFICATIONS_ENABLED=%s DISCORD_NOTIFICATION_CHANNEL_ID=%s",
                settings.discord_notifications_enabled,
                settings.discord_notification_channel_id,
            )

    return bot
