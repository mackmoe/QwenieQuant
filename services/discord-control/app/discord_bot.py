"""
Discord bot setup and slash command registration.

This module is intentionally thin: it wires Discord interactions to the
handler functions in commands.py. All logic (authorization, formatting,
client calls) stays in commands.py so it can be tested without Discord.

Slash commands are registered as guild-specific (instant propagation)
using the DISCORD_GUILD_ID setting.
"""

import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands as dc_commands

from app.commands import (
    UNAUTHORIZED_MESSAGE,
    handle_analyze,
    handle_predict,
    handle_reflect,
    handle_status,
    is_authorized,
)
from app.config import Settings

logger = logging.getLogger(__name__)


def create_bot(
    prediction_client,
    learning_client,
    reflection_client,
    http,
    settings: Settings,
) -> dc_commands.Bot:
    intents = discord.Intents.default()
    bot = dc_commands.Bot(command_prefix="!", intents=intents)
    tree = bot.tree
    guild = discord.Object(id=settings.discord_guild_id)

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

    return bot
