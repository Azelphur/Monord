from aiohttp import web


class Webhook:
    def __init__(self, bot):
        self.bot = bot

    async def mad_handler(self, request):
        #[{'message': {'latitude': 51.359126, 'longitude': 1.445414, 'level': 5, 'team_id': 1, 'start': 1553340120, 'end': 1553342820, 'gym_id': '48eefa6527344ef282c74181a7074399.16', 'name': 'The Scotsman', 'url': 'http://lh5.ggpht.com/YfMW7LqOgdcPigk06UWbYqLYm6VY2wQ9I6l_lVTkaeeoCDWEFQ3wItFZj3-f_CPtcYrf-5q6sVuvsfhNNlA', 'pokemon_id': 0, 'sponsor': '0', 'weather': '0', 'park': 'None'}, 'type': 'raid'}]
        #print(request)
        #print(dir(request))
        #print(await request.json())
        events = await request.json()
        for event in events:
            if event['type'] == 'raid':
                pass
        return web.Response()

    async def webserver(self):
        app = web.Application()
        app.router.add_post('/wh/mad', self.mad_handler)
        runner = web.AppRunner(app)
        await runner.setup()
        self.site = web.TCPSite(runner, '0.0.0.0', 8999)
        await self.bot.wait_until_ready()
        await self.site.start()
