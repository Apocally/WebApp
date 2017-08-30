import functools, asyncio, inspect, logging


def get(path):
    '''
    define decorator @get('/path')
    :param path: url
    :return:decorator
    '''
    def decorator(func):
        # functools.wraps(wrapped[, assigned][, updated])
        # wraps函数，它将update_wrapper也封装了进来
        ## functools.update_wrapper(wrapper, wrapped[, assigned][, updated])
        ## update_wrapper函数，它可以把被封装函数的__name__、__module__、__doc__和 __dict__都复制到封装函数去：
        @functools.wraps(func)
        def wrapper(*args,**kw):
            return func(*args,**kw)
        wrapper.__method__ = 'GET'
        wrapper.__route__ = path
        return wrapper
    return decorator


def post(path):
    '''
    define decorator @post('/path')
    :param path:
    :return: decorator
    '''
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args,**kw):
            return func(*args,**kw)
        wrapper.__method__ = 'POST'
        wrapper.__route__ = path

        return wrapper
    return decorator

# URL处理函数不一定是一个coroutine，因此我们用RequestHandler()来封装一个URL处理函数。
# RequestHandler是一个类，由于定义了__call__()方法，因此可以将其实例视为函数。
# RequestHandler目的就是从URL函数中分析其需要接收的参数，从request中获取必要的参数，调用URL函数，然后把结果转换为web.Response对象，这样，就完全符合aiohttp框架的要求：
class RequestHandler():
    def __init__(self, app, fn):
        self._app = app
        self._func = fn

    async def __call__(self, request):
        kw = '' # 获取参数
        r = await self._func(**kw)
        return r


# 用来注册一个URL处理函数
def add_route(app, fn):
    method = getattr(fn, '__method__', None)
    path = getattr(fn, '__route__', None)
    if path is None or method is None:
        raise ValueError('@get or @post not defined in %s.' % str(fn))
    if not asyncio.iscoroutinefunction(fn) and not inspect.isgeneratorfunction(fn):
        fn = asyncio.coroutine(fn)
    logging.info('add route %s %s => %s(%s)' % (method, path, fn.__name__, ', '.join(inspect.signature(fn).parameters.keys())))
    app.router.add_route(method, path, RequestHandler(app, fn))


#
def add_routes(app, module_name):
    '''
    :param app:
    :param module_name: handles.index, handles.blog, handles.create_comment等
    :return:
    '''
    # rfind() 返回字符串最后一次出现的位置(从右向左查询)，如果没有匹配项则返回-1
    n = module_name.rfind('.')
    if n == (-1):
        # 等价于import module_name
        mod = __import__(module_name, globals(), locals())
    else:
        name = module_name[n+1:]
        # 等价于from module_name[:n] import [name], 若[name]有多个，则依次导入
        mod = getattr(__import__(module_name[:n], globals(), locals(), [name]), name)
    for attr in dir(mod):
        if attr.startswith('_'):
            continue
        fn = getattr(mod, attr)
        if callable(fn):
            method = getattr(fn, '__method__', None)
            path = getattr(fn, '__route__', None)
            if method and path:
                add_route(app, fn)