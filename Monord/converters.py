from . import es_models
from . import config
from . import utils
from . import models
from elasticsearch_dsl import Search
from sqlalchemy.orm.exc import NoResultFound
from redbot.core import commands
from geoalchemy2.shape import to_shape
import elasticsearch
import re
import datetime
import logging
import sys
import pytz
import gettext
_ = gettext.gettext

logger = logging.getLogger()
logger.setLevel(logging.ERROR)

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)

RE_MINUTESAFTER = re.compile("^(\d+)@(.+)$")
RE_DISCORD_MENTION = re.compile("\<@(?:\!|)(\d+)\>")

def get_es_gym_by_id(ctx, argument):
    try:
        gym = es_models.Gym.get(id=argument)
        return gym
    except elasticsearch.exceptions.NotFoundError:
        raise commands.ConversionFailure(ctx, argument, _("Gym with id {} not found").format(argument))


class Gym(commands.Converter):
    async def convert(self, ctx, argument):
        try:
            if not argument.isnumeric():
                try:
                    alias = ctx.cog.session.query(models.GymAlias).filter_by(
                        guild_id=ctx.message.channel.guild.id,
                        title=argument.lower()
                    ).one()
                    return get_es_gym_by_id(ctx, alias.gym.id)
                except NoResultFound:
                    pass
            if argument.isnumeric():
                return get_es_gym_by_id(ctx, argument)

            region = config.get(ctx.cog.session, "region", ctx.message.channel)
            if region is None:
                raise commands.ConversionFailure(ctx, argument, _("This guild/channel does not have a region set"))

            region = to_shape(region)
            points = []
            for point in region.exterior.coords:
                points.append({"lat": point[1], "lon": point[0]})
            s = Search(index="gym").query("match", title={'query': argument, 'fuzziness': 2})
            s = s.filter("geo_polygon", location={"points": points})
            response = s.execute()
            if response.hits.total == 0:
                raise commands.ConversionFailure(ctx, argument, _("Gym \"{}\" not found").format(argument))
            return response[0]
        except (commands.ConversionFailure, commands.BadArgument):
            raise
        except Exception as e:
            logger.exception("Exception in Gym converter")
            await ctx.send(_("Error in Gym converter. Check your console or logs for details"))
            raise


class GymWithSQL(Gym):
    async def convert(self, ctx, argument):
        try:
            es_gym = await super(GymWithSQL, self).convert(ctx, argument)
            sql_gym = ctx.cog.session.query(models.Gym).get(es_gym.meta["id"])
            if sql_gym is None:
                raise commands.ConversionFailure(ctx, argument, _("Gym \"{}\" not found").format(argument))
            return (es_gym, sql_gym)
        except (commands.ConversionFailure, commands.BadArgument):
            raise
        except Exception as e:
            logger.exception("Exception in GymWithSQL converter")
            await ctx.send(_("Error in GymWithSQL converter. Check your console or logs for details"))
            raise
            

class Time(commands.Converter):
    def hours_minutes_to_dt(self, ctx, start_time, fmt):
        try:
            tz = pytz.timezone(config.get(ctx.cog.session, "timezone", ctx.message.channel))
            now = datetime.datetime.utcnow().astimezone(tz)
            start_dt = tz.localize(datetime.datetime.strptime(start_time, fmt))
            start_dt = now.replace(
                hour=start_dt.hour,
                minute=start_dt.minute,
                second=0
            )
            if start_dt < now:
                start_dt = start_dt + datetime.timedelta(days=1)
            start_dt = start_dt.astimezone(pytz.utc)
            return start_dt
        except ValueError:
            return None

    async def convert(self, ctx, argument):
        try:
            start_dt = None

            match = RE_MINUTESAFTER.match(argument)
            if match:
                start_dt = await self.convert(ctx, match.group(2))
                start_dt += datetime.timedelta(minutes=int(match.group(1)))
                return start_dt

            cleaned_start_time = argument.rstrip("m")
            cleaned_start_time = cleaned_start_time.rstrip("mins")
            if cleaned_start_time.isnumeric() and int(cleaned_start_time) <= 60:
                return datetime.datetime.utcnow().replace(tzinfo=pytz.utc) + datetime.timedelta(minutes=int(cleaned_start_time))

            for t_format_24h, t_format_12h in [("%H:%M", "%I:%M%p"), ("%H%M", "%I%M%p"), ("%H.%M", "%I.%M:%p")]:
                start_dt = self.hours_minutes_to_dt(ctx, argument, t_format_24h)
                if start_dt is None:
                    continue
                if start_dt - pytz.utc.localize(datetime.datetime.utcnow()) > utils.HATCH_TIME + utils.DESPAWN_TIME:
                    new_start_dt = self.hours_minutes_to_dt(ctx, argument+"pm", t_format_12h)
                    start_dt = start_dt if new_start_dt is None else new_start_dt
                if start_dt is not None:
                    return start_dt
            try:
                tz = pytz.timezone(config.get(ctx.cog.session, "timezone", ctx.message.channel))
                start_dt = datetime.datetime.strptime(argument, "%Y-%m-%d.%H:%M")
                start_dt = tz.localize(start_dt)
                start_dt = start_dt.astimezone(pytz.utc)
            except ValueError:
                pass
            if start_dt is None:
                raise commands.ConversionFailure(ctx, argument, _("\"{}\" is not a known time format").format(argument))
            return start_dt
        except (commands.ConversionFailure, commands.BadArgument):
            raise
        except Exception as e:
            logger.exception("Exception in Time converter")
            await ctx.send(_("Error in Time converter. Check your console or logs for details"))
            raise


class Pokemon(commands.Converter):
    async def convert(self, ctx, argument):
        try:
            if argument.isnumeric():
                if not 0 < int(argument) < 6:
                    raise commands.ConversionFailure(ctx, argument, _("{} is not a valid egg level, must be between 1 and 5").format(argument))
                return int(argument)
            s = Search(index="pokemon").query("match", name={'query': argument, 'fuzziness': 2})
            response = s.execute()
            if response.hits.total == 0:
                raise commands.ConversionFailure(ctx, argument, _("Pokemon \"{}\" not found").format(argument))
            return response[0]
        except (commands.ConversionFailure, commands.BadArgument):
            raise
        except Exception as e:
            logger.exception("Exception in Pokemon converter")
            await ctx.send(_("Error in Pokemon converter. Check your console or logs for details"))
            raise


class PokemonWithSQL(Pokemon):
    async def convert(self, ctx, argument):
        try:
            es_pokemon = await super(PokemonWithSQL, self).convert(ctx, argument)
            if isinstance(es_pokemon, int):
                return (es_pokemon, es_pokemon)
            sql_pokemon = ctx.cog.session.query(models.Pokemon).get(es_pokemon.meta["id"])
            if sql_pokemon is None:
                raise commands.ConversionFailure(ctx, argument, _("Pokemon \"{}\" not found").format(argument))
            return (es_pokemon, sql_pokemon)
        except (commands.ConversionFailure, commands.BadArgument):
            raise
        except Exception as e:
            logger.exception("Exception in PokemonWithSQL converter")
            await ctx.send(_("Error in PokemonWithSQL converter. Check your console or logs for details"))
            raise


class Raid(commands.Converter):
    async def convert(self, ctx, argument):
        try:
            if argument.isnumeric():
                try:
                    return ctx.cog.session.query(models.Raid).get(argument)
                except NoResultFound:
                    raise commands.ConversionFailure(ctx, argument, _("Raid with ID \"{}\" not found").format(argument))

            gym = await GymWithSQL().convert(ctx, argument)
            raid = utils.get_raid_at_time(ctx.cog.session, gym[1], datetime.datetime.utcnow())
            if raid is None:
                raise commands.ConversionFailure(ctx, argument, _("There is no raid on \"{}\".").format(gym.title))
            return raid
        except (commands.ConversionFailure, commands.BadArgument):
            raise
        except Exception as e:
            logger.exception("Exception in Raid converter")
            await ctx.send(_("Error in Raid converter. Check your console or logs for details"))
            raise

class MembersWithExtra(commands.Converter):
    async def convert(self, ctx, argument):
        try:
            args = argument.split()
            if len(args) < 1:
                raise commands.BadArgument(_("Not enough arguments").format(argument))

            members = []
            member = None
            skip_next = False
            for i in range(0, len(args)):
                if skip_next:
                    skip_next = False
                    continue
                match = RE_DISCORD_MENTION.match(args[i])
                if match:
                    member = ctx.message.channel.guild.get_member(int(match.group(1)))
                    extra = 0
                    if i+1 < len(args) and args[i+1].isnumeric():
                        extra = int(args[i+1])
                        skip_next = True
                    members.append((member, extra))
                else:
                    raise commands.ConversionFailure(ctx, argument, _("\"{}\" is not a member").format(argument))
            return members
        except (commands.ConversionFailure, commands.BadArgument):
            raise
        except Exception as e:
            logger.exception("Exception in MembersWithExtra")
            await ctx.send(_("Error in MembersWithExtrar converter. Check your console or logs for details"))
            raise
