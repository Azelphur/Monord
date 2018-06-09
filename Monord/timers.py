import datetime
import logging
import sys
import asyncio
from sqlalchemy import or_
from . import models
from . import utils
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
            while cog.time_stale == False and datetime.datetime.utcnow() < t:
                await asyncio.sleep(1)

            # If a raids time was changed, restart the loop to check for new times
            if cog.time_stale:
                cog.time_stale = False
                continue

            if not raid.hatched:
                raid.hatched = True
                await utils.notify_hatch(cog, raid)
            else:
                raid.despawned = True
            cog.session.add(raid)
            cog.session.commit()
        except Exception as e:
            logger.exception("Error in raid_timers")

def reschedule(cog):
    if cog.raid_timers_task is None or cog.raid_timers_task.done():
        cog.raid_timers_task = cog.bot.loop.create_task(raid_timers(cog))
    else:
        cog.time_stale = True
