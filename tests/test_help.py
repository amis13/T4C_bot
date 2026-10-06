import discord

from bot.help import COMMANDS, build_help


def test_help_includes_ia_and_ia_reset_commands():
    """Assert that /ia and /ia-reset are registered in COMMANDS."""
    command_names = [name for name, _ in COMMANDS]
    assert "/ia" in command_names
    assert "/ia-reset" in command_names


def test_no_stale_independiente_description():
    """Assert that no description contains 'independiente' (case-insensitive)."""
    for name, description in COMMANDS:
        assert "independiente" not in description.lower(), (
            f"Command {name} still has stale description claiming questions are independent"
        )


def test_build_help_fields_match_commands():
    """Assert that build_help() returns an Embed with fields for every COMMANDS entry."""
    embed = build_help()
    assert isinstance(embed, discord.Embed)
    assert len(embed.fields) == len(COMMANDS)

    # Verify the field names match command names in order
    field_names = [field.name for field in embed.fields]
    command_names = [name for name, _ in COMMANDS]
    assert field_names == command_names

    # Verify all fields have descriptions
    for field in embed.fields:
        assert field.value, f"Field {field.name} has no description"
