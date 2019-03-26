from Monord.main import Monord
from discord.ext import commands
from os import environ
import traceback

class Bot(commands.Bot):
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send_help(ctx.command)
        elif isinstance(error, commands.CommandError):
            await ctx.send(error)
        else:
            await ctx.send('Error executing {}, see logs for more details'.format(ctx.command))
            traceback.print_tb(error.__traceback__)

bot = Bot(command_prefix='!', description='Monord')
bot.add_cog(Monord(bot))
bot.run(environ['DISCORD_TOKEN'], bot=True, reconnect=True)
