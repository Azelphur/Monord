from . import es_models
from . import models
from . import utils
from . import converters
from . import config
from . import timers
from . import stats
from redbot.core import checks, commands
from elasticsearch import Elasticsearch
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.orm.exc import NoResultFound
from os.path import exists as path_exists
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
import time as time_module
import discord
import json
import datetime
import pytz
import re
import gettext
_ = gettext.gettext

class Monord:
    """
        Find gyms, report raids, get notifications, and more!
    """
    def __init__(self, bot):
        self.bot = bot
        engine = create_engine('postgresql://pokemongo:pokemongo@localhost/pokemongo', connect_args={"options": "-c timezone=utc"})
        models.Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine)()
        self.raid_timers_task = None
        self.time_stale = False
        timers.reschedule(self)

    @commands.group(name="gym", invoke_without_command=True)
    async def gym(self, ctx):
        """
            Add, find and remove gyms
        """
        await ctx.send_help()

    @gym.command()
    async def find(self, ctx, *, gym: converters.GymWithSQL):
        """
            Find a gym, and show its location
            
            <gym> - The title or ID of the gym
        """
        embed = utils.prepare_gym_embed(gym)
        await ctx.send(embed=embed)

    @checks.mod_or_permissions(manage_guild=True)
    @gym.command()
    async def add(self, ctx, latitude: float, longitude: float, ex: bool, *, title: str):
        """
            Add a gym to the database
            
            <latitude> - Latitude of the gym
            <longitude> - Longitude of the gym
            <ex> - Is the gym an EX location (yes/no)
            <title> - The title of the gym
        """
        gym, gymdoc = utils.add_gym(self.session, latitude, longitude, ex, title)
        await ctx.send("Gym created", embed=utils.prepare_gym_embed((gymdoc, gym)))

    @checks.mod_or_permissions(manage_guild=True)
    @gym.group(name="alias", invoke_without_command=True)
    async def alias(self, ctx):
        """
            Manage aliases on gyms
        """
        await ctx.send_help()

    @checks.mod_or_permissions(manage_guild=True)
    @alias.command(name="add")
    async def add_alias(self, ctx, title: str, *, gym: converters.GymWithSQL):
        """
            Add an alias for a gym
            
            <latitude> - Latitude of the gym
            <longitude> - Longitude of the gym
            <ex> - Is the gym an EX location (yes/no)
            <title> - The title of the gym
        """
        es_gym, sql_gym = gym

        title = title.lower()

        alias = self.session.query(models.GymAlias).filter_by(
            title=title,
            gym=sql_gym,
            guild_id=ctx.message.channel.guild.id
        )
        if alias.count() > 0:
            await ctx.send(_("Alias already exists"))
            return

        alias = models.GymAlias(
            title=title,
            gym=sql_gym,
            guild_id=ctx.message.channel.guild.id
        )
        self.session.add(alias)
        self.session.commit()
        await ctx.send(_("Alias \"{}\" added for {}").format(title, sql_gym.title))

    @alias.command(name="list")
    async def list_(self, ctx, *, gym: converters.GymWithSQL):
        """
            List aliases for a gym
            
            <title> - The title of the gym
        """
        es_gym, sql_gym = gym

        aliases = self.session.query(models.GymAlias).filter_by(
            gym=sql_gym,
            guild_id=ctx.message.channel.guild.id
        )
        if aliases.count() == 0:
            await ctx.send(_("{} has no aliases").format(sql_gym.title))
        alias_list = []
        for alias in aliases:
            alias_list.append(alias.title)
        await ctx.send(_("{} has the following aliases: {}").format(sql_gym.title, ", ".join(alias_list)))

    @checks.mod_or_permissions(manage_guild=True)
    @alias.command(name="remove")
    async def remove_alias(self, ctx, title, *, gym: converters.GymWithSQL):
        es_gym, sql_gym = gym

        title = title.lower()

        alias = self.session.query(models.GymAlias).filter_by(
            title=title,
            gym=sql_gym,
            guild_id=ctx.message.channel.guild.id
        )
        if alias.count() == 0:
            await ctx.send(_("Alias \"{}\" on {} does not exist").format(title, sql_gym.title))
            return
        alias.delete()
        await ctx.send(_("Alias \"{}\" on {} removed").format(title, sql_gym.title))

    @checks.mod_or_permissions(manage_guild=True)
    @gym.command()
    async def remove(self, ctx, *, gym: converters.Gym):
        """
            Remove a gym from the database
            
            <gym> - The title or ID of the gym
        """
        title = gym.title
        self.session.query(models.Gym).filter_by(id=gym.meta["id"]).delete()
        es_models.Gym.get(id=gym.meta["id"]).delete()
        await ctx.send(_("Gym \"{}\" removed").format(title))

    @checks.mod_or_permissions(manage_guild=True)
    @gym.group(name="set", invoke_without_command=True)
    async def set_(self, ctx):
        """
            Change details on a gym
        """
        await ctx.send_help()

    @checks.mod_or_permissions(manage_guild=True)
    @set_.group(name="ex")
    async def gym_set_ex(self, ctx, ex: bool, *, gym: converters.GymWithSQL):
        es_gym, sql_gym = gym
        sql_gym.ex = ex
        self.session.add(sql_gym)
        self.session.commit()
        await ctx.tick()

    @commands.group(name="raid", invoke_without_command=True)
    async def raid(self, ctx):
        """
            Report raids
        """
        await ctx.send_help()

    @raid.command()
    async def report(self, ctx, time: converters.Time, pokemon: converters.PokemonWithSQL, *, gym: converters.GymWithSQL):
        """
            Report a raid
            
            <time> Can be minutes left on the timer, or a HH:MM time
            <pokemon> Either the name of the pokemon, or the eggs level
            <gym> The title of the gym
        """
        es_gym, sql_gym = gym
        es_pokemon, sql_pokemon = pokemon
        if isinstance(sql_pokemon, int): # User reported an egg
            time += utils.DESPAWN_TIME

        if not isinstance(sql_pokemon, int) and utils.check_availability(sql_pokemon, sql_gym.location, time - utils.DESPAWN_TIME - utils.HATCH_TIME, sql_pokemon.raid_level) == False:
            await ctx.send(_("{} is not currently available in raids").format(sql_pokemon.name))
            return

        raid = utils.get_raid_at_time(self.session, sql_gym, time)
        if raid:
            if not isinstance(sql_pokemon, int) and raid.pokemon != sql_pokemon:
                raid.pokemon = sql_pokemon
                self.session.add(raid)
                self.session.commit()
                return
            await ctx.send(_("That raid has already been reported"))
            return

        await utils.create_raid(self, time, sql_pokemon, sql_gym, False, ctx.message.author, ctx.message.channel)

    @raid.command()
    async def ex(self, ctx, time: converters.Time, *, gym: converters.GymWithSQL):
        """
            Report an EX raid
            
            <time> Start time of the EX raid in YYYY-MM-DD.HH:MM format
            <gym> The title of the gym
        """
        es_gym, sql_gym = gym

        time += utils.DESPAWN_TIME

        raid = utils.get_raid_at_time(self.session, sql_gym, time)
        if raid:
            await ctx.send(_("That raid has already been reported (#{})").format(raid.id))
            return

        await utils.create_raid(self, time, 5, sql_gym, True, ctx.message.author, ctx.message.channel)

    @raid.command()
    async def hide(self, ctx, channel: discord.TextChannel, *, raid: converters.Raid):
        """
            Hide a raid from a channel

            <channel> Channel to hide the raid from.
            <raid> Either the title of a gym, or a raid ID.
        """
        await utils.hide_raid(self, channel, raid)
        await ctx.tick()

    @raid.command()
    async def show(self, ctx, channel: discord.TextChannel, *, raid: converters.Raid):
        """
            Show a raid in a channel

            <channel> Channel to hide the raid from.
            <raid> Either the title of a gym, or a raid ID.
        """
        await utils.send_raid(self, channel, raid)

    @raid.command(name="gym")
    async def raid_gym(self, ctx, raid: converters.Raid, *, gym: converters.GymWithSQL):
        """
            Correct a raids gym

            <channel> Channel to hide the raid from.
            <gym> Either the title of a gym, or a raid ID.
        """
        es_gym, sql_gym = gym
        raid.gym = sql_gym
        self.session.add(raid)
        self.session.commit()
        await utils.update_raid(self, raid)
        await ctx.tick()

    @raid.group(invoke_without_command=True)
    async def going(self, ctx):
        """
            Add or remove people as going to a raid
        """
        await ctx.send_help()

    @going.group(name="add")
    async def add_person(self, ctx, raid: converters.Raid, *, members: converters.MembersWithExtra):
        """
            Add people as going to a raid
        """
        await utils.add_raid_going(self, ctx.message.author, raid, members)
        await utils.update_raid(self, raid)
        await ctx.tick()

    @going.group(name="remove")
    async def remove_person(self, ctx, raid: converters.Raid, *members: discord.Member):
        """
            Remove people from going to a raid
        """
        await utils.remove_raid_going(self, ctx.message.author, raid, members)
        await utils.update_raid(self, raid)
        await ctx.tick()

    @raid.command()
    async def start(self, ctx, time: converters.Time, *, raid: converters.Raid):
        """
            Set the start time of a raid
            
            <time> - Can be minutes (in the future), or a HH:MM time
            <raid> Either the title of a gym, or a raid ID
        """
        despawn_time = pytz.utc.localize(raid.despawn_time)
        if time > despawn_time:
            await ctx.send(_("You can't set the start time to after the raid despawns"))
            return
        if time < despawn_time - utils.DESPAWN_TIME - utils.HATCH_TIME:
            await ctx.send(_("You can't set the start time to before the raid starts"))
            return
        raid.start_time = time
        self.session.add(raid)
        await utils.update_raid(self, raid)
        await ctx.tick()

    @raid.command()
    async def despawn(self, ctx, time: converters.Time, *, raid: converters.Raid):
        """
            Set the despawn time of a raid
            
            <time> - Can be minutes (in the future), or a HH:MM time
            <raid> Either the title of a gym, or a raid ID
        """
        despawn_time = pytz.utc.localize(raid.despawn_time)
        raid.despawn_time = time
        self.session.add(raid)
        await utils.update_raid(self, raid)
        timers.reschedule(self)
        await ctx.tick()

    @raid.command()
    async def pokemon(self, ctx, pokemon: converters.PokemonWithSQL, *, raid: converters.Raid):
        """
            Set the pokemon on a raid.
            
            <pokemon> - The name of the pokemon
            <raid> Either the title of a gym, or a raid ID
        """
        es_pokemon, sql_pokemon = pokemon
        if isinstance(sql_pokemon, int):
            pokemons = utils.get_possible_pokemon(self, raid.gym.location, pytz.utc.localize(raid.despawn_time), sql_pokemon, raid.ex)
            if len(pokemons) == 1:
                sql_pokemon = pokemons[0]
        raid.pokemon = sql_pokemon if not isinstance(sql_pokemon, int) else None,
        raid.level = sql_pokemon if isinstance(sql_pokemon, int) else sql_pokemon.raid_level
        self.session.add(raid)
        await utils.update_raid(self, raid)
        await ctx.tick()

    @checks.mod_or_permissions(manage_guild=True)
    @commands.group(name="config", invoke_without_command=True)
    async def config(self, ctx):
        """
            Change configuration settings
        """
        await ctx.send_help()

    async def set_config(self, ctx, is_channel, key: str = None, value: str = None, channel: discord.TextChannel = None):
        if isinstance(ctx.message.channel, discord.abc.PrivateChannel):
            await ctx.send(_("This command is not available in DMs."))
            return
        if key == None:
            await config.list_settings(ctx)
            return

        if value == None:
            if key in config.SETTINGS:
                cfg = config.get(self.session, key, channel, False, not is_channel, False)
                await ctx.send(_("{} is set to {}").format(key, cfg))
                return
            else:
                await ctx.send(_("{} is not a valid setting").format(key))
                return

        if value.lower() in ["none", "null"]:
            value = None
        try:
            if is_channel:
                config.set_channel_config(self.session, channel, key, value)
                await ctx.send(_("Setting {} to \"{}\" on {}").format(key, value, channel.mention))
            else:
                config.set_guild_config(self.session, channel.guild, key, value)
                await ctx.send(_("Setting {} to \"{}\"").format(key, value))
        except config.InvalidSettingError:
            await ctx.send(_("{} is not a valid setting").format(key))
        except config.ValidationError as e:
            await ctx.send(e)

    @checks.mod_or_permissions(manage_guild=True)
    @config.command()
    async def channel(self, ctx, key: str = None, value: str = None, channel: discord.TextChannel = None):
        """
            Sets config setting for a channel
            
            <channel> a discord channel
            <key> the key to set, or nothing to see a list of keys
            <value> the value to set, or nothing to see the value of <key>
        """
        if channel == None:
            channel = ctx.message.channel
        await self.set_config(ctx, True, key, value, channel)

    @checks.mod_or_permissions(manage_guild=True)
    @config.command()
    async def guild(self, ctx, key: str = None, *, value: str = None):
        """
            Sets config setting for this guild
            
            <key> the key to set, or nothing to see a list of keys
            <value> the value to set, or nothing to see the value of <key>
        """
        await self.set_config(ctx, False, key, value, ctx.message.channel)

    @commands.group(name="subscribe", invoke_without_command=True)
    async def subscribe(self, ctx):
        """
            Subscribe to notifications
        """
        await ctx.send_help()

    @subscribe.group(name="pokemon")
    async def pokemon_subscribe(self, ctx, *, pokemon: converters.Pokemon):
        """
            Subscribe to notifications for a pokemon
            
            <pokemon> the name of the pokemon
        """
        await utils.subscribe_with_message(ctx, ctx.message.author, pokemon.name)

    @subscribe.group(name="ex")
    async def ex_subscribe(self, ctx):
        """
            Subscribe to notifications for raids on EX Eligible gyms
        """
        await utils.subscribe_with_message(ctx, ctx.message.author, _("EX Eligible"))

    @subscribe.group(name="gym")
    async def gym_subscribe(self, ctx, *, gym: converters.Gym):
        """
            Subscribe to notifications for raids on a gym
        """
        await utils.subscribe_with_message(ctx, ctx.message.author, gym.title)

    @commands.group(name="unsubscribe", invoke_without_command=True)
    async def unsubscribe(self, ctx):
        """
            Unsubscribe from notifications
        """
        await ctx.send_help()

    @unsubscribe.group(name="pokemon")
    async def pokemon_unsubscribe(self, ctx, pokemon: converters.Pokemon):
        """
            Unsubscribe from notifications for a pokemon
            
            <pokemon> the name of the pokemon
        """
        await utils.unsubscribe_with_message(ctx, ctx.message.author, pokemon.name)

    @unsubscribe.group(name="ex")
    async def ex_unsubscribe(self, ctx):
        """
            Unsubscribe from notifications for raids on EX Eligible gyms
        """
        await utils.unsubscribe_with_message(ctx, ctx.message.author, _("EX Eligible"))

    @unsubscribe.group(name="gym")
    async def gym_unsubscribe(self, ctx, *, gym: converters.Gym):
        """
            Unsubscribe from notifications for raids on a gym
        """
        await utils.unsubscribe_with_message(ctx, ctx.message.author, gym.title)

    @commands.group(invoke_without_command=True)
    async def party(self, ctx):
        """
            Manage your party, members of your party will be automatically added to raids when you sign up
        """
        await ctx.send_help()

    @party.command(name="create")
    async def party_create(self, ctx, *, members: converters.MembersWithExtra):
        # Disband existing party, if there is one.
        self.session.query(models.Party).filter_by(creator_user_id=ctx.message.author.id).delete()
        for member, extra in members:
            p = models.Party(
                creator_user_id=ctx.message.author.id,
                user_id=member.id,
                guild_id=member.guild.id,
                extra=extra
            )
            self.session.add(p)
        self.session.commit()
        await ctx.tick()

    @party.command(name="add")
    async def party_add(self, ctx, *, members: converters.MembersWithExtra):
        for member, extra in members:
            if self.session.query(models.Party).filter_by(creator_user_id=ctx.message.author.id, user_id=member.id).count() > 0:
                continue
            p = models.Party(
                creator_user_id=ctx.message.author.id,
                user_id=member.id,
                guild_id=member.guild.id,
                extra=extra
            )
            self.session.add(p)
        self.session.commit()
        await ctx.tick()

    @party.command(name="remove")
    async def party_remove(self, ctx, *members: discord.Member):
        self.session.query(models.Party).filter(
            models.Party.creator_user_id == ctx.message.author.id,
            models.Party.user_id.in_([member.id for member in members])
        ).delete(synchronize_session=False)
        self.session.expire_all()
        await ctx.tick()

    @party.command(name="disband")
    async def party_disband(self, ctx):
        self.session.query(models.Party).filter(
            models.Party.creator_user_id == ctx.message.author.id
        ).delete(synchronize_session=False)
        self.session.expire_all()
        await ctx.tick()

    @party.command(name="list")
    async def party_list(self, ctx):
        party_members = self.session.query(models.Party).filter_by(creator_user_id=ctx.message.author.id)
        member_names = []
        for party_member in party_members:
            guild = self.bot.get_guild(party_member.guild_id)
            member = guild.get_member(party_member.user_id)
            if not member:
                continue
            member_names.append(member.display_name)
        await ctx.send(_("You are in a party with: {}").format(", ".join(member_names)))

    @checks.is_owner()
    @commands.command()
    async def loaddata(self, ctx, *, csv_path="pokemongodata.json"):
        """
            Load pokemon and gyms from json file
        """
        if not path_exists(csv_path):
            await ctx.send(_("{} File not found").format(csv_path))
            return
        with open(csv_path, "r") as f:
            try:
                data = json.loads(f.read())
            except json.decoder.JSONDecodeError as e:
                await ctx.send(e)
                return
            message = await ctx.send("Importing data, this will take a second... (0 / {})".format(len(data)))
            last_time = time_module.time()
            count_gyms = 0
            count_pokemon = 0
            for i, entry in enumerate(data):
                now = time_module.time()
                if now - last_time > 5 or i == len(data)-1:
                    await message.edit(content="Importing data, this will take a second... ({} / {})".format(i+1, len(data)))
                    last_time = now
                if entry["type"] == "gym":
                    count_gyms += 1
                    try:
                        gym = self.session.query(models.Gym).filter_by(
                            location=from_shape(Point(entry["data"]["longitude"], entry["data"]["latitude"]), srid=4326)
                        ).one()
                        if gym.title != entry["data"]["title"]:
                            gym.title = entry["data"]["title"]
                            self.session.add(gym)
                    except NoResultFound:
                        utils.add_gym(
                            self.session,
                            entry["data"]["latitude"],
                            entry["data"]["longitude"],
                            entry["data"].get("ex", False),
                            entry["data"]["title"],
                        )
                elif entry["type"] == "pokemon":
                    count_pokemon += 1
                    try:
                        p = self.session.query(models.Pokemon).filter_by(name=entry["data"]["name"]).one()
                    except NoResultFound:
                        p = models.Pokemon(name=entry["data"]["name"])
                    p.id = entry["data"]["id"]
                    p.raid_level = entry["data"].get("raid_level", None)
                    p.ex = entry["data"].get("ex", False)
                    p.availability_rules = json.dumps(entry["data"].get("availability_rules", None))
                    p.perfect_cp = entry["data"].get("perfect_cp", None)
                    p.perfect_cp_boosted = entry["data"].get("perfect_cp_boosted", None)
                    p.shiny = entry["data"].get("shiny", False)
                    if entry["data"].get("types", None) is not None:
                        p.types = stats.to_int(entry["data"]["types"])
                    self.session.add(p)
                    es_models.Pokemon(meta={'id': entry["data"]["id"]}, name=entry["data"]["name"]).save()
            self.session.commit()
            await ctx.send("Imported {} gyms and {} pokemon".format(count_gyms, count_pokemon))

    async def on_raw_reaction(self, payload):
        guild = self.bot.get_guild(payload.guild_id)
        channel = guild.get_channel(payload.channel_id)
        member = guild.get_member(payload.user_id)
        message = await channel.get_message(payload.message_id)

        if member == self.bot.user:
            # Ignore reactions that we add
            return
        
        if message.author != self.bot.user:
            # Ignore reactions on any messages that weren't created by us
            return

        # Find the Embed associated with our message.
        try:
            embed = self.session.query(models.Embed).filter_by(channel_id=channel.id, message_id=message.id).one()
        except NoResultFound:
            return

        if embed.embed_type == utils.EMBED_RAID:
            emoji_going, emoji_add_person, emoji_remove_person, emoji_add_time, emoji_remove_time = config.get(
                self.session,
                ['emoji_going', 'emoji_add_person', 'emoji_remove_person', 'emoji_add_time', 'emoji_remove_time'],
                channel
            )

            if str(payload.emoji) == emoji_going:
                await utils.toggle_going(self, member, embed.raid, [member])
            elif str(payload.emoji) == emoji_add_person:
                await utils.add_person(self, member, embed.raid, member)
            elif str(payload.emoji) == emoji_remove_person:
                await utils.add_person(self, member, embed.raid, member, -1)
            elif str(payload.emoji) == emoji_add_time or str(payload.emoji) == emoji_remove_time:
                if str(payload.emoji) == emoji_add_time:
                    new_start_time = min(embed.raid.despawn_time, embed.raid.start_time + datetime.timedelta(minutes=5))
                else:
                    new_start_time = max(embed.raid.despawn_time - utils.DESPAWN_TIME, embed.raid.start_time - datetime.timedelta(minutes=5))
                if new_start_time == embed.raid.start_time:
                    # No point doing a embed update if nothing is changing.
                    return
                embed.raid.start_time = new_start_time
                self.session.add(embed.raid)
            else:
                emojis = [emoji_going, emoji_add_person, emoji_remove_person, emoji_add_time, emoji_remove_time]
                for reaction in message.reactions:
                    if str(reaction) in emojis:
                        emojis.remove(str(reaction))
                if emojis != []:
                    await message.clear_reactions()
                    await utils.add_raid_reactions(self.session, message)
                else:
                    await message.remove_reaction(payload.emoji, member)
        elif embed.embed_type == utils.EMBED_HATCH:
            pokemons = utils.get_possible_pokemon(self, embed.raid.gym.location, pytz.utc.localize(embed.raid.despawn_time - utils.DESPAWN_TIME - utils.HATCH_TIME), embed.raid.level, embed.raid.ex)
            num = int(str(payload.emoji)[0]) if str(payload.emoji)[0].isnumeric() else None
            if num is not None:
                if num > len(pokemons):
                    return
                pokemon = pokemons[num]
                await utils.hatch_raid(self, embed.raid, pokemon)
                return
        await utils.update_raid(self, embed.raid)

    async def on_raw_reaction_add(self, payload):
        await self.on_raw_reaction(payload)

    async def on_raw_reaction_remove(self, payload):
        await self.on_raw_reaction(payload)

    async def on_raw_message_delete(self, payload):
        try:
            deleted_embed = self.session.query(models.Embed).filter_by(channel_id=payload.channel_id, message_id=payload.message_id).one()
        except NoResultFound:
            return

        embeds = self.session.query(models.Embed).filter_by(raid=deleted_embed.raid)
        for embed in embeds:
            if embed.channel_id == payload.channel_id and embed.message_id == payload.message_id:
                continue
            try:
                channel = self.bot.get_channel(embed.channel_id)
                message = await channel.get_message(embed.message_id)
                await message.delete()
            except discord.errors.NotFound:
                pass

        
        self.session.query(models.RaidGoing).filter_by(raid=deleted_embed.raid).delete()
        self.session.query(models.Embed).filter_by(raid=deleted_embed.raid).delete()
        self.session.query(models.Raid).filter_by(id=deleted_embed.raid_id).delete()
        timers.reschedule(self)

