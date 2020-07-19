import discord
from . import models
from . import es_models
from . import config
from . import timers
from . import stats
from .regions import REGIONS
import pytz
import asyncio
import datetime
from shapely.geometry import Point
from geoalchemy2.shape import from_shape, to_shape
from sqlalchemy import func, and_, or_
from sqlalchemy.orm.exc import NoResultFound
import json
import gettext
import re
import random
RE_EMOJI = re.compile("\<\:(.+):(\d+)>")

_ = gettext.gettext

HATCH_TIME = datetime.timedelta(minutes=60)
DESPAWN_TIME = datetime.timedelta(minutes=45)

EMBED_RAID = 1
EMBED_HATCH = 2

def prepare_gym_embed(gym):
    es_gym, sql_gym = gym
    title = sql_gym.title
    if sql_gym.ex:
        description = _("This gym is EX Eligible")
    else:
        description = _("This gym is not EX Eligible")
    embed=discord.Embed(title=title, url="https://www.google.com/maps/dir/Current+Location/{},{}".format(es_gym.location['lat'], es_gym.location['lon']), description=description)
    embed.set_image(url='https://api.mapbox.com/styles/v1/{3}/static/pin-s+97F0F9({1},{0})/{1},{0},14,0,0/250x125@2x?access_token={2}'.format(es_gym.location['lat'], es_gym.location['lon'], 'pk.eyJ1IjoiamF5dHVybnIiLCJhIjoiY2pxaTM0YjN6MGdvcjQ4bm0za25ucGpmbCJ9.qJmqwYw24tq_5WaKlOCzVg', 'jayturnr/cjqi34t5walqo2rmwu032ra0a'))
    embed.set_footer(text="Gym ID {}.".format(es_gym.meta["id"]))
    return embed

def add_gym(session, id, latitude, longitude, ex, title):
    gym = models.Gym(
        id=id,
        title=title,
        location=from_shape(Point(longitude, latitude), srid=4326),
        ex=ex,
    )
    session.add(gym)
    session.commit()

    gymdoc = es_models.Gym(
        meta={'id': gym.id},
        title=title,
        location={"lat": latitude, "lon": longitude},
    )
    gymdoc.save()
    return gym, gymdoc

def get_raid_at_time(session, gym, time):
    spawn_time = time - HATCH_TIME - DESPAWN_TIME
    raid = session.query(models.Raid).filter(
        models.Raid.despawned == False,
        models.Raid.gym == gym,
        models.Raid.despawn_time >= spawn_time,
        models.Raid.despawn_time <= time + HATCH_TIME + DESPAWN_TIME
    ).first()
    return raid

def get_display_name(channel, member, extra=0):
    team_emoji = None
    for role in member.roles:
        if role.name.lower() == "mystic":
            team_emoji = get_emoji_by_name(channel.guild, "mystic")
            break
        elif role.name.lower() == "valor":
            team_emoji = get_emoji_by_name(channel.guild, "valor")
            break
        elif role.name.lower() == "instinct":
            team_emoji = get_emoji_by_name(channel.guild, "instinct")
            break

    result = member.display_name
    if team_emoji:
        result = str(team_emoji) + result
    if extra > 0:
        result = result + " (+{})".format(extra)
    return result

def get_emoji_by_name(guild, name):
    for emoji in guild.emojis:
        if emoji.name.lower() == name.lower():
            return emoji

def format_time(cog, channel, t):
    tz = pytz.timezone(config.get(cog.session, "timezone", channel))
    loc_dt = pytz.utc.localize(t).astimezone(tz)
    if t - datetime.datetime.utcnow() > datetime.timedelta(days=1):
        return loc_dt.strftime("%Y-%m-%d %H:%M")
    return loc_dt.strftime("%H:%M")

async def wait_for_tasks(tasks):
    """
        Collect the task results, it doesn't
        serve any purpose apart from raising exceptions
        which is useful
    """
    if len(tasks) == 0:
        return
    done, pending = await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)
    for task in done:
        task.result()

def get_pokemon_image_url(dex, form=0, shiny=False):
    DOMAIN = "https://www.trainerdex.co.uk/"
    BASE = "pokemon/pokemon_icon_{dex:03}_{form:02}.png".format(dex=dex, form=form)
    BASE_SHINY = "pokemon/pokemon_icon_{dex:03}_{form:02}_shiny.png".format(dex=dex, form=form)
    if shiny and random.randrange(1,11) == 1:
        return DOMAIN+BASE_SHINY
    return DOMAIN+SHINY
        
def format_raid(cog, channel, raid):
    title = raid.gym.title
    title = "{} (#{})".format(title, raid.id)
    if raid.ex:
        title = "EX: "+title

    going = cog.session.query(models.RaidGoing).filter_by(raid=raid)

    users = []
    num_extra = 0
    if going.count():
        for g in going:
            guild = cog.bot.get_guild(g.guild_id)
            if guild is None:
                continue
            member = guild.get_member(g.user_id)
            if member is None:
                continue
            num_extra += g.extra
            display_name = get_display_name(channel, member, g.extra)
            users.append(display_name)
        users.sort()

    if raid.pokemon is None:
        description = _("**Level**: {}").format(raid.level) + "\n"
        image = "https://www.trainerdex.co.uk/egg/{}.png".format(raid.level)
    else:
        image = get_pokemon_image_url(raid.pokemon.id, 0, raid.pokemon.shiny)
        name = raid.pokemon.name
        if raid.pokemon.shiny:
            name += ":sparkles:"
        if raid.pokemon.raid_level:
            description = _("**Pokemon**: {} (Level {})").format(name, raid.pokemon.raid_level) + "\n"
        else:
            description = _("**Pokemon**: {}").format(name, raid.pokemon.raid_level) + "\n"

    description += _("**Start Time**: {}").format(format_time(cog, channel, raid.start_time)) + "\n"
    if datetime.datetime.utcnow() < raid.despawn_time - DESPAWN_TIME:
        description += _("**Hatches at**: {}").format(format_time(cog, channel, raid.despawn_time - DESPAWN_TIME)) + "\n"
    description += _("**Despawns at**: {}").format(format_time(cog, channel, raid.despawn_time)) + "\n"

    if raid.pokemon is not None:
        if None not in [raid.pokemon.perfect_cp, raid.pokemon.perfect_cp_boosted]:
            description += _("**Perfect CP**: {} / {}").format(raid.pokemon.perfect_cp, raid.pokemon.perfect_cp_boosted) + "\n"
        if raid.pokemon.types is not None:
            counters_int = stats.get_counter_types(raid.pokemon.types)
            counters = stats.from_int(counters_int)
            description += _("**Weak against**: {}").format(", ".join([_(counter) for counter in counters])) + "\n"

    if datetime.datetime.utcnow() < raid.despawn_time - DESPAWN_TIME:
        description += _("**Interested ({})**").format(going.count()+num_extra) + "\n"
    else:
        description += _("**Going ({})**").format(going.count()+num_extra) + "\n"

    description += "\n".join(users) + "\n"
    emoji_going = config.get(cog.session, "emoji_going", channel)
    if not raid.ex and raid.gym.ex:
        description += _("This raid has the possibility of giving you an EX raid pass") + "\n"
    description += _("Press the {} below if you want to do this raid").format(emoji_going)

    location = to_shape(raid.gym.location)
    kwargs = {
        "title": title,
        "url": "https://www.google.com/maps/dir/Current+Location/{},{}".format(location.y, location.x),
        "description": description
    }

    embed=discord.Embed(**kwargs)

    embed.set_thumbnail(url=image)
    embed.set_footer(text=_("Raid ID {}. Ignore emoji counts, they are inaccurate.").format(raid.id))

    subscriptions = config.get(cog.session, "subscriptions", channel)
    if subscriptions and not raid.ex:
        roles = []
        if raid.pokemon:
            pokemon_role = find_role(channel.guild, raid.pokemon.name)
            if pokemon_role:
                roles.append(pokemon_role)
        else:
            egg_role = find_role(channel.guild, _("Level {} egg").format(raid.level))
            if egg_role:
                roles.append(egg_role)
        gym_role = find_role(channel.guild, raid.gym.title)
        if gym_role:
            roles.append(gym_role)
        if raid.gym.ex:
            ex_role = find_role(channel.guild, _("EX Eligible"))
            if ex_role:
                roles.append(ex_role)
        content = " ".join([role.mention for role in roles])
    else:
        content = None
    return {"embed": embed, "content": content}

def emoji_from_string(guild, emoji):
    match = RE_EMOJI.match(emoji)
    if match:
        return get_emoji_by_name(guild, match.group(1))
    return emoji

async def add_raid_reactions(session, message):
    emoji_going, emoji_add_person, emoji_remove_person, emoji_add_time, emoji_remove_time = config.get(
        session,
        ['emoji_going', 'emoji_add_person', 'emoji_remove_person', 'emoji_add_time', 'emoji_remove_time'],
        message.channel
    )
    try:
        await message.add_reaction(emoji_from_string(message.channel.guild, emoji_going))
        await message.add_reaction(emoji_from_string(message.channel.guild, emoji_add_person))
        await message.add_reaction(emoji_from_string(message.channel.guild, emoji_remove_person))
        await message.add_reaction(emoji_from_string(message.channel.guild, emoji_add_time))
        await message.add_reaction(emoji_from_string(message.channel.guild, emoji_remove_time))
    except discord.errors.NotFound:
        pass

async def send_raid(cog, channel, raid, extra_content=None):
    embeds = list(cog.session.query(models.Embed).filter_by(channel_id=channel.id, raid=raid, embed_type=EMBED_RAID))
    cog.session.query(models.Embed).filter_by(channel_id=channel.id, raid=raid).delete()
    for embed in embeds:
        try:
            message = await channel.get_message(embed.message_id)
            await message.delete()
        except discord.errors.NotFound:
            pass

    formatted_raid = format_raid(cog, channel, raid)
    if extra_content != None:
        if formatted_raid["content"] is not None:
            formatted_raid["content"] = extra_content + "\n" + formatted_raid["content"]
        else:
            formatted_raid["content"] = extra_content
    message = await channel.send(**formatted_raid)
    embed = models.Embed(channel_id=channel.id, message_id=message.id, raid_id=raid.id, embed_type=EMBED_RAID)
    delete_after_despawn = config.get(cog.session, "delete_after_despawn", channel)
    if delete_after_despawn is not None:
        embed.delete_at = raid.despawn_time + datetime.timedelta(minutes=delete_after_despawn)
    cog.session.add(embed)
    cog.session.commit()
    timers.embed_reschedule(cog)
    await add_raid_reactions(cog.session, message)

async def update_raid(cog, raid, exclude_channels=[]):
    cog.session.commit()
    embeds = list(cog.session.query(models.Embed).filter_by(raid=raid, embed_type=EMBED_RAID))
    tasks = []
    for embed in embeds:
        channel = cog.bot.get_channel(embed.channel_id)
        if channel in exclude_channels:
            continue
        try:
            message = await channel.get_message(embed.message_id)
        except discord.errors.NotFound:
            cog.session.query(models.Embed).filter_by(message_id=embed.message_id).delete()
            continue
        tasks.append(message.edit(**format_raid(cog, channel, raid)))
    delete_after_despawn = config.get(cog.session, "delete_after_despawn", channel)
    if delete_after_despawn is not None:
        delete_at = raid.despawn_time + datetime.timedelta(minutes=delete_after_despawn)
        if embed.delete_at != delete_at:
            embed.delete_at = delete_at
            cog.session.add(embed)
            cog.session.commit()
    await wait_for_tasks(tasks)

async def create_raid(cog, time, pokemon, gym, ex, triggered_by=None, triggered_channel=None):
    # Calculate a sensible start time.
    start_time = time - DESPAWN_TIME # Set proposed start time to hatch.
    if start_time < pytz.utc.localize(datetime.datetime.utcnow()): # If the time is in the past, fix it.
        start_time = pytz.utc.localize(datetime.datetime.utcnow()) + datetime.timedelta(minutes=10)
    if start_time > time: # Is the start time we selected after the raid ends?
        start_time = start_time - datetime.timedelta(minutes=2)

    if isinstance(pokemon, int):
        pokemons = get_possible_pokemon(cog, gym.location, time - DESPAWN_TIME - HATCH_TIME, pokemon, ex)
        if len(pokemons) == 1:
            pokemon = pokemons[0]


    raid = models.Raid(
        pokemon=pokemon if not isinstance(pokemon, int) else None,
        gym=gym,
        despawn_time=time,
        start_time=start_time,
        ex=ex,
        level=pokemon if isinstance(pokemon, int) else pokemon.raid_level,
        hatched=False if isinstance(pokemon, int) else True
    )
    cog.session.add(raid)
    cog.session.commit() # Required as we need raids ID in the embed

    timers.raid_reschedule(cog)

    tasks = []
    if triggered_channel is not None:
        tasks.append(send_raid(cog, triggered_channel, raid))

    guilds = cog.session.query(models.GuildConfig).filter(
        models.GuildConfig.channel_id == None,
        models.GuildConfig.region != None,
        func.ST_Contains(models.GuildConfig.region, gym.location)
    )
    channels = cog.session.query(models.GuildConfig).filter(
        or_(
            and_(
                models.GuildConfig.guild_id.in_([guild.guild_id for guild in guilds]),
                models.GuildConfig.mirror == True,
                models.GuildConfig.region == None
            ),
            and_(
                models.GuildConfig.channel_id != None,
                models.GuildConfig.mirror == True,
                func.ST_Contains(models.GuildConfig.region, gym.location)
            )
        )
    )

    for cfg in channels:
        channel = cog.bot.get_channel(cfg.channel_id)
        if channel == triggered_channel:
            continue # Don't broadcast twice in the same channel
        if channel == None:
            continue # Channel is missing, don't broadcast to it.
        tasks.append(send_raid(cog, channel, raid))

    await wait_for_tasks(tasks)

def check_availability(pokemon, location, time, level):
    location = to_shape(location)
    availability_rules = json.loads(pokemon.availability_rules)
    if level != pokemon.raid_level:
        return False
    if availability_rules is None:
        if pokemon.raid_level:
            return True
        return False
    for ruleset in availability_rules:
        available = True
        for rule in ruleset:
            if rule["type"] == "time":
                start_time = pytz.utc.localize(datetime.datetime.strptime(rule["start"], "%Y-%m-%dT%H:%M:%SZ"))
                end_time = pytz.utc.localize(datetime.datetime.strptime(rule["end"], "%Y-%m-%dT%H:%M:%SZ"))
                if not start_time <= time <= end_time:
                    available = False
                    break
            elif rule["type"] == "region":
                if "region" not in rule or \
                        rule["region"] not in REGIONS or \
                        not REGIONS[rule["region"].lower()].contains(location):
                    available = False
                    break                    
        if available:
            return True
    return False

def get_possible_pokemon(cog, location, time, level, ex):
    pokemons = cog.session.query(models.Pokemon).filter_by(
        raid_level=level,
        ex=ex
    ).order_by("name")
    filtered_pokemons = []
    for pokemon in pokemons:
        if check_availability(pokemon, location, time, level):
            filtered_pokemons.append(pokemon)
    return filtered_pokemons

async def send_hatch(cog, channel, raid):
    role = find_role(channel.guild, _("Raid {} (#{})").format(raid.gym.title, raid.id))
    if role:
        content = role.mention
    else:
        content = None

    description = _("This raid has hatched, can you see what it is?") + "\n"
    pokemons = get_possible_pokemon(cog, raid.gym.location, pytz.utc.localize(raid.despawn_time - DESPAWN_TIME - HATCH_TIME), raid.level, raid.ex)
    for i, pokemon in enumerate(pokemons):
        if i > 9:
            break
        description += "{}\u20E3 - {}\n".format(i, pokemon.name)
    location = to_shape(raid.gym.location)
    embed=discord.Embed(
        title=raid.gym.title,
        url="https://www.google.com/maps/dir/Current+Location/{},{}".format(location.y, location.x),
        description=description
    )
    embed.set_footer(text="Raid ID {}.".format(raid.id))

    message = await channel.send(content, embed=embed)

    embed = models.Embed(channel_id=channel.id, message_id=message.id, raid=raid, embed_type=EMBED_HATCH)
    delete_after_despawn = config.get(cog.session, "delete_after_despawn", channel)
    if delete_after_despawn is not None:
        embed.delete_at = raid.despawn_time + datetime.timedelta(minutes=delete_after_despawn)
    cog.session.add(embed)
    cog.session.commit()

    for i in range(0, min(len(pokemons), 10)):
        await message.add_reaction(str(i)+"\u20E3")

def get_subscription_channels(cog, raid):
    guilds = cog.session.query(models.GuildConfig).filter(
        models.GuildConfig.channel_id == None,
        models.GuildConfig.region != None,
        func.ST_Contains(models.GuildConfig.region, raid.gym.location)
    )
    channels = cog.session.query(models.GuildConfig).filter(
        or_(
            and_(
                models.GuildConfig.guild_id.in_([guild.guild_id for guild in guilds]),
                models.GuildConfig.subscriptions == True,
                models.GuildConfig.region == None
            ),
            and_(
                models.GuildConfig.channel_id != None,
                models.GuildConfig.subscriptions == True,
                func.ST_Contains(models.GuildConfig.region, raid.gym.location)
            )
        )
    )
    return channels

async def notify_hatch(cog, raid):
    channels = get_subscription_channels(cog, raid)
    tasks = []
    for cfg in channels:
        channel = cog.bot.get_channel(cfg.channel_id)
        tasks.append(send_hatch(cog, channel, raid))

    await wait_for_tasks(tasks)

async def hatch_raid(cog, raid, pokemon):
    raid.pokemon = pokemon
    cog.session.add(raid)
    cog.session.commit()
    channels = get_subscription_channels(cog, raid)
    tasks = []

    await update_raid(cog, raid, exclude_channels=channels)
    for cfg in channels:
        channel = cog.bot.get_channel(cfg.channel_id)
        role = find_role(channel.guild, _("Raid {} (#{})").format(raid.gym.title, raid.id))
        if role:
            title = role.mention
        else:
            title = raid.gym.title
        message = _("{} is a {}").format(title, pokemon.name)
        tasks.append(send_raid(cog, channel, raid, message))

    embeds = list(cog.session.query(models.Embed).filter_by(raid=raid, embed_type=EMBED_HATCH))
    cog.session.query(models.Embed).filter_by(raid=raid, embed_type=EMBED_HATCH).delete()
    for embed in embeds:
        message = await channel.get_message(embed.message_id)
        tasks.append(message.delete())

    await wait_for_tasks(tasks)

async def add_raid_going(cog, triggered_by, raid, members):
    members_list = [(member.guild.id, member.id, extra) for member, extra in members]
    # If the user is adding themselves, include their party
    if triggered_by.id in [member.id for member, extra in members]:
        party_members = cog.session.query(models.Party).filter_by(creator_user_id=triggered_by.id)
        for i, party_member in enumerate(party_members):
            members_list.append((party_member.guild_id, party_member.user_id, party_member.extra))

    for guild_id, member_id, extra in members_list:
        count = cog.session.query(models.RaidGoing).filter_by(raid=raid, user_id=member_id).count()
        if count != 0:
            return
        going = models.RaidGoing(
            user_id=member_id,
            guild_id=guild_id,
            extra=extra,
            raid=raid
        )
        guild = cog.bot.get_guild(guild_id)
        member = guild.get_member(member_id)
        await subscribe(member, _("Raid {} (#{})").format(raid.gym.title, raid.id))
        cog.session.add(going)

async def remove_raid_going(cog, triggered_by, raid, members):
    members_list = [member.id for member in members]
    # If the user is adding themselves, include their party
    if triggered_by.id in members_list:
        party_members = cog.session.query(models.Party).filter_by(creator_user_id=triggered_by.id)
        for party_member in party_members:
            members_list.append(party_member.user_id)

    cog.session.query(models.RaidGoing).filter(
        models.RaidGoing.raid == raid,
        models.RaidGoing.user_id.in_(members_list)
    ).delete(synchronize_session=False)
    cog.session.expire_all()
    for member in members:
        await unsubscribe(member, _("Raid {} (#{})").format(raid.gym.title, raid.id))

async def add_person(cog, triggered_by, raid, member, extra=1):
    try:
        going = cog.session.query(models.RaidGoing).filter_by(raid=raid, user_id=member.id).one()
        going.extra = max(going.extra + extra, 0)
        cog.session.add(going)
    except NoResultFound:
        return

async def toggle_going(cog, triggered_by, raid, members):
    members_to_add = []
    members_to_remove = []
    for member in members:
        try:
            going = cog.session.query(models.RaidGoing).filter_by(raid=raid, user_id=member.id).one()
            members_to_remove.append(member)
        except NoResultFound:
            members_to_add.append((member, 0))
    await add_raid_going(cog, triggered_by, raid, members_to_add)
    await remove_raid_going(cog, triggered_by, raid, members_to_remove)

def find_role(guild, role_name):
    for role in guild.roles:
        if role.name == role_name:
            return role
    return None

def member_in_role(member, role):
    for role_ in member.roles:
        if role_ == role:
            return True
    return False

async def subscribe(member, role_name):
    role = find_role(member.guild, role_name)
    if role is None:
        role = await member.guild.create_role(name=role_name, mentionable=True)
    if member_in_role(member, role):
        return False
    await member.add_roles(role, reason=_("Added by Monord"))
    return True

async def subscribe_with_message(ctx, member, role_name):
    subscribed = await subscribe(member, role_name)
    if subscribed:
        await ctx.send(_("You are now subscribed to {}").format(role_name))
    else:
        await ctx.send(_("You are already subscribed to {}").format(role_name))

async def unsubscribe(member, role_name):
    role = find_role(member.guild, role_name)
    if role is None:
        return False
    for role_ in member.roles:
        if role_ == role:
            await member.remove_roles(role, reason=_("Removed by Monord"))
            if not role.members:
                await role.delete(reason=_("Removed by Monord, role is empty"))
            return True
    return False

async def unsubscribe_with_message(ctx, member, role_name):
    unsubscribed = await unsubscribe(member, role_name)
    if unsubscribed:
        await ctx.send(_("You have been unsubscribed from {}").format(role_name))
    else:
        await ctx.send(_("You are not subscribed to {}").format(role_name))

async def hide_raid(cog, channel, raid):
    embeds = list(cog.session.query(models.Embed).filter_by(channel_id=channel.id, raid=raid))
    cog.session.query(models.Embed).filter_by(channel_id=channel.id, raid=raid).delete()
    for embed in embeds:
        try:
            message = await channel.get_message(embed.message_id)
            await message.delete()
        except discord.errors.NotFound:
            pass

async def mark_raid_despawned(cog, raid):
    raid.despawned = True

    tasks = []

    for guild in cog.bot.guilds:
        role = find_role(guild, _("Raid {} (#{})").format(raid.gym.title, raid.id))
        if role is not None:
            tasks.append(role.delete(reason=_("Removed by Monord")))
    await wait_for_tasks(tasks)
