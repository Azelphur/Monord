from . import models
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy import and_, or_
import pytz
import discord
from shapely.geometry import shape, Polygon
from geoalchemy2.shape import from_shape
import json
import gettext
_ = gettext.gettext

class ValidationError(Exception):
    pass

class InvalidSettingError(Exception):
    pass

def boolean_validator(value, is_channel):
    if value.lower() in ["yes", "true", "1"]:
        return True
    if value.lower() in ["no", "false", "0"]:
        return False
    raise ValidationError(_("Must be yes or no"))

def channel_only_validator(value, is_channel):
    if not is_channel:
        raise ValidationError(_("You can only set this setting per-channel"))
    return value

def timezone_validator(value, is_channel):
    if value not in pytz.all_timezones:
        raise ValidationError(_("Must be a valid time zone"))
    return value

def region_validator(value, is_channel):
    if value is None:
        return value
    try:
        j = json.loads(value)
    except json.decoder.JSONDecodeError:
        raise ValidationError(_("Invalid JSON provided"))
    s = shape({"type": "Polygon", "coordinates": j})
    return from_shape(s, srid=4326)

def emoji_validator(value, is_channel):
    # This could definitely be better, TODO
    return str(value) if value is not None else None

def integer_validator(value, is_channel):
    if value is None:
        return None
    try:
        value = int(value)
    except ValueError:
        raise ValidationiError(_("Value must be a number"))
    return value

SETTINGS = {
    "mirror": {
        "validators": [channel_only_validator, boolean_validator],
        "help": _("Mirror raids within this channel (or servers) geopoints, yes or no"),
        "default": False,
    },
    "timezone": {
        "validators": [timezone_validator],
        "help": _("Set the server (or channels) time zone. See https://en.wikipedia.org/wiki/List_of_tz_database_time_zones for a list of time zones"),
        "default": "Europe/London"
    },
    "region": {
        "validators": [region_validator],
        "help": "A list of coordinates in JSON format, specifying a polygon around your area",
        "default": None
    },
    "subscriptions": {
        "validators": [channel_only_validator, boolean_validator],
        "help": _("Mention subscription roles in this channel"),
        "default": False
    },
    "delete_after_despawn": {
        "validators": [integer_validator],
        "help": _("Delete raids this many minutes after despawn"),
        "default": None
    },
    "emoji_going": {
        "validators": [emoji_validator],
        "help": _("The emoji used for the going button reaction"),
        "default": "\U0001F44D"
    },
    "emoji_add_person": {
        "validators": [emoji_validator],
        "help": _("The emoji used for the add person button reaction"),
        "default": "\U00002B06"
    },
    "emoji_remove_person": {
        "validators": [emoji_validator],
        "help": _("The emoji used for the add person button reaction"),
        "default": "\U00002B07"
    },
    "emoji_add_time": {
        "validators": [emoji_validator],
        "help": _("The emoji used for the add time button reaction"),
        "default": "\U000023E9"
    },
    "emoji_remove_time": {
        "validators": [emoji_validator],
        "help": _("The emoji used for the remove time button reaction"),
        "default": "\U000023EA"
    }
}

async def list_settings(ctx):
    msg = []
    for setting, d in SETTINGS.items():
        msg.append("**{}** - {}.".format(setting, d["help"]))
    embed=discord.Embed(title=_("Settings"), description="\n".join(msg))
    await ctx.send(embed=embed)

def get(session, keys, channel, allow_fallback=True, server_only=False, return_default=True):
    if isinstance(keys, str):
        keys = [keys]

    if allow_fallback:
        cfg = session.query(models.GuildConfig).filter(
            or_(
                models.GuildConfig.channel_id == channel.id,
                and_(models.GuildConfig.guild_id == channel.guild.id, models.GuildConfig.channel_id == None)
            )
        )
    elif server_only:
        cfg = session.query(models.GuildConfig).filter(
            models.GuildConfig.guild_id == channel.guild.id,
            models.GuildConfig.channel_id == None
        )
    else:
        cfg = session.query(models.GuildConfig).filter(models.GuildConfig.channel_id == channel.id)

    result = []
    server_cfg = None
    channel_cfg = None
    if cfg.count() == 1: # One config, use what we have
        server_cfg = cfg[0] if cfg[0].channel_id is None else None
        channel_cfg = None if cfg[0].channel_id is None else cfg[0]
    elif cfg.count() == 2: # Both configs, use best
        server_cfg = cfg[0] if cfg[0].channel_id is None else cfg[1]
        channel_cfg = cfg[1] if cfg[0].channel_id is None else cfg[0]

    for key in keys:
        if channel_cfg is not None and getattr(channel_cfg, key) is not None:
            result.append(getattr(channel_cfg, key))
            continue
        if server_cfg is not None and getattr(server_cfg, key) is not None:
            result.append(getattr(server_cfg, key))
            continue
        if return_default:
            result.append(SETTINGS[key]["default"])
        else:
            result.append(None)
    return result if len(result) > 1 else result[0]

def set_guild_config(session, guild, key, value):
    _set_config(session, key, value, False, **{"guild_id": guild.id, "channel_id": None})

def set_channel_config(session, channel, key, value):
    _set_config(session, key, value, True, **{"guild_id": channel.guild.id, "channel_id": channel.id})

def _set_config(session, key, value, is_channel, **kwargs):
    if key not in SETTINGS:
        raise InvalidSettingError()
    validators = SETTINGS[key]["validators"]
    for validator in validators:
        value = validator(value, is_channel)

    try:
        config = session.query(models.GuildConfig).filter_by(**kwargs).one()
    except NoResultFound:
        config = models.GuildConfig(**kwargs)
    setattr(config, key, value)
    session.add(config)
    session.commit()
