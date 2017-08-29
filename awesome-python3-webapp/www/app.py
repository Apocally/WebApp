import logging; logging.basicConfig(level=logging.INFO)
import asyncio,os,json,time
from datetime import datetime
from aiohttp import web

def index(request):
    return web.Response(content_type='text/html', body=b'<h1>Awesome</h1>')


# 异步IO，协程
async def init(loop):
    app = web.Application(loop=loop)
    app.router.add_route('GET','/',index)                                      # 设置路由
    srv = await loop.create_server(app.make_handler(),'127.0.0.1',9000)   # 创建服务器
    logging.info('server started at http://127.0.0.1:9000...')                 # 写日志
    return


loop = asyncio.get_event_loop()
loop.run_until_complete(init(loop))
loop.run_forever()