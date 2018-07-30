import datetime
import logging
import sys
import asyncio
from sqlalchemy import or_
from . import models
from . import utils
import discord
logger = logging.getLogger()
logger.setLevel(logging.ERROR)

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)


async def raid_timers(cog):
    while True:
        try:
            # Find the soonest raid that hasn't hatched or despawned.
            raids = cog.session.query(models.Raid).filter(
                or_(
                    models.Raid.despawned == False,
                    models.Raid.hatched == False
                )
            ).order_by('despawn_time')

            # If there are no raids found, stop the loop.
            if raids.count() == 0:
                return

            soonest_hatch = raids.filter_by(hatched=False).order_by('despawn_time').first()
            soonest_despawn = raids.first()
            if soonest_hatch is not None:
                raid = soonest_hatch if soonest_hatch.despawn_time - utils.DESPAWN_TIME < soonest_despawn.despawn_time else soonest_despawn
            else:
                raid = soonest_despawn

            # If it's hatched use the despawn time.
            t = raid.despawn_time
            if raid.hatched == False:
                t = t - utils.DESPAWN_TIME

            # Wait until hatch / despawn, or until a raid time is changed
            while cog.raid_time_stale == False and datetime.datetime.utcnow() < t:
                await asyncio.sleep(1)

            # If a raids time was changed, restart the loop to check for new times
            if cog.raid_time_stale:
                cog.raid_time_stale = False
                continue

            if not raid.hatched:
                raid.hatched = True
                await utils.notify_hatch(cog, raid)
            else:
                raid.despawned = True
                await utils.mark_raid_despawned(cog, raid)
            cog.session.add(raid)
            cog.session.commit()
        except Exception as e:
            logger.exception("Error in raid_timers")
            await asyncio.sleep(5)

async def embed_timers(cog):
    while True:
        try:
            # Find the embed that needs deleting.
            embed = cog.session.query(models.Embed).filter(models.Embed.delete_at != None).order_by('delete_at').first()
            # If there are no raids found, stop the loop.
            if embed is None:
                return
            # Wait until hatch / despawn, or until a raid time is changed
            while cog.embed_time_stale == False and datetime.datetime.utcnow() < embed.delete_at:
                await asyncio.sleep(1)

            try:
                channel = cog.bot.get_channel(embed.channel_id)
                message = await channel.get_message(embed.message_id)
                await message.delete()
            except discord.errors.NotFound as e:
                logging.exception("Delete failed")
                pass
            cog.session.query(models.Embed).filter_by(message_id=embed.message_id).delete()

        except Exception as e:
            logger.exception("Error in embed_timers")
            await asyncio.sleep(5)

def raid_reschedule(cog):
    if cog.raid_timers_task is None or cog.raid_timers_task.done():
        cog.raid_timers_task = cog.bot.loop.create_task(raid_timers(cog))
    else:
        cog.raid_time_stale = True

def embed_reschedule(cog):
    if cog.embed_timers_task is None or cog.embed_timers_task.done():
        cog.embed_timers_task = cog.bot.loop.create_task(embed_timers(cog))
    else:
        cog.embed_time_stale = True
    
