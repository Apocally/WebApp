import asyncio
import aiomysql
import logging

logging.basicConfig(filename='example.log',level=logging.DEBUG)

# 异步
# 创建数据库连接池
async def create_pool(loop,**kw):
    print('create database connection pool...')
    # 全局变量__pool作为连接池
    global __pool
    __pool = await aiomysql.create_pool(
        host=kw.get('host', 'localhost'),
        port=kw.get('port', 3306),
        user=kw['user'],
        password=kw['password'],
        db=kw['db'],
        charset=kw.get('charset', 'utf8'),
        autocommit=kw.get('autocommit', True),
        maxsize=kw.get('maxsize', 10),          # 最多10个链接对象
        minsize=kw.get('minsize', 1),
        loop=loop                               # 是否多余？
    )


# 封装SELECT方法
async def select(sql, args, size=None):                 # sql语句，参数，size表示取几条
    global __pool
    with (await __pool) as conn:
        cur = await conn.cursor(aiomysql.DictCursor)    # 以字典形式返回的Cursor
        await cur.execute(sql.replace('?', '%s'), args)   # SQL占位符是?，而MySQL的占位符是%s。用参数替换而非字符串拼接可以防止sql注入
        # 如果传入size参数，就通过fetchmany()获取最多指定数量的记录，否则，通过fetchall()获取所有记录。
        if size:
            rs = await cur.fetchmany(size)
        else:
            rs = await cur.fetchall()
        await cur.close()
        logging.info('rows returned: %s' % len(rs))
        return rs


# 定义一个通用的execute()函数，执行INSERT、UPDATE、DELETE语句
async def execute(sql, args):
    global __pool
    with (await __pool) as conn:
        try:
            cur = await conn.cursor()
            await cur.execute(sql.replace('?', '%s'), args)
            affected = cur.rowcount                     # 返回结果数
            await cur.close()
        except BaseException as e:
            raise e
        return affected

# 'metaclass'必须是可调用(callable)的，并且返回一个'type'。当我们想要动态地创建类时，利用type是一个很合适的解决方案。
class ModelMetaClass(type):

    # 元类必须实现__new__方法，当一个类指定通过某元类来创建，那么就会调用该元类的__new__方法
    # 该方法接收4个参数
    # cls为当前准备创建的类的对象
    # name为类的名字，创建User类，则name便是User
    # bases类继承的父类集合,创建User类，则base便是Model
    # attrs为类的属性/方法集合，创建User类，则attrs便是一个包含User类属性的dict
    def __new__(cls, name, bases, attrs):
        # 排除Model类本身
        if name == 'Model':
            return type.__new__(cls, name, bases, attrs)
        # 取出表名，默认与类的名字相同
        tableName = attrs.get('__table__', None) or name
        logging.info('found model: %s (table: %s)' % (name, tableName))

        # 获取所有的Field和主键名:
        # 用于存储所有的字段，以及字段值
        mappings = dict()

        # 仅用来存储非主键意外的其它字段，而且只存key
        fields = []

        # 仅保存主键的key
        primaryKey = None

        # 注意这里attrs的key是字段名，value是字段实例，不是字段的具体值
        # 比如User类的id=StringField(...) 这个value就是这个StringField的一个实例，而不是实例化的时候传进去的具体id值
        for k, v in attrs.items():
            # attrs同时还会拿到一些其它系统提供的类属性，我们只处理自定义的类属性，所以判断一下
            # isinstance 方法用于判断v是否是一个Field
            if isinstance(v, Field):
                mappings[k] = v
                if v.primary_key:
                    if primaryKey:
                        raise RuntimeError("Duplicate primary key for field :%s" % k)
                    primaryKey = k
                else:
                    fields.append(k)

        # 保证了必须有一个主键
        if not primaryKey:
            raise RuntimeError("Primary key not found")

        # 这里的目的是去除类属性，为什么要去除呢，因为我想知道的信息已经记录下来了。去除之后，就访问不到类属性了
        # 记录到了mappings,fields，等变量里，而我们实例化的时候，如
        # user=User(id='10001') ，为了防止这个实例变量与类属性冲突，所以将其去掉
        for k in mappings.keys():
            attrs.pop(k)
        escaped_fields = list(map(lambda f: '`%s`' % f, fields))

        # 以下都是要返回的东西了，刚刚记录下的东西，如果不返回给这个类，又谈得上什么动态创建呢？
        # 到此，动态创建便比较清晰了，各个子类根据自己的字段名不同，动态创建了自己
        # 下面通过attrs返回的东西，在子类里都能通过实例拿到，如self
        attrs['__mappings__'] = mappings  # 保存属性和列的映射关系
        attrs['__table__'] = tableName
        attrs['__primary_key__'] = primaryKey  # 主键属性名
        attrs['__fields__'] = fields  # 除主键外的属性名

        # 构造默认的SELECT, INSERT, UPDATE和DELETE语句:
        attrs['__select__'] = "select %s, %s from %s" % (primaryKey, ', '.join(escaped_fields), tableName)
        attrs['__insert__'] = "insert into %s (%s, %s) values (%s)" % (
            tableName, primaryKey, ', '.join(escaped_fields), create_args_string(len(escaped_fields) + 1))
        attrs['__update__'] = "update %s set %s where %s=?" % (
            tableName, ', '.join(map(lambda f: '%s=?' % (mappings.get(f).name or f), fields)), primaryKey)
        attrs['__delete__'] = "delete from %s where %s=?" % (tableName, primaryKey)
        return type.__new__(cls, name, bases, attrs)


def create_args_string(num):
    # 用来计算需要拼接多少个占位符
    L = []
    for n in range(num):
        L.append('?')
    return ', '.join(L)


# ORM
# Model, 所有ORM映射的基类
class Model(dict, metaclass=ModelMetaClass):

    # 继承自dict
    def __init__(self, **kw):
        super(Model, self).__init__(**kw)

    def __getattr__(self, key):                         # user.id = user['id']
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Model' object has no attribute '%s'" % key)

    def __setattr__(self, key, value):
        self[key] = value

    def get_value(self, key):
        return getattr(self, key, None)

    def getValueOrDefault(self, key):
        value = getattr(self, key, None)
        if value is None:
            field = self.__mappings__[key]
            if field.default is not None:               # value 可以是函数(callable,可调用对象)
                value = field.default() if callable(field.default) else field.default
                logging.debug('using default value for %s: %s' % (key, str(value)))
                setattr(self, key, value)
        return value

    # 一步异步，处处异步，所以这些方法都必须是一个协程
    # 下面 self.__mappings__,self.__insert__等变量据是根据对应表的字段不同，而动态创建
    async def save(self):
        args = list(map(self.getValueOrDefault, self.__mappings__))   # 遍历__mappings__中的key,映射到getValueOrDefault
        await execute(self.__insert__, args)

    async def remove(self):
        args = []
        args.append(self[self.__primaryKey__])
        print(self.__delete__)
        await execute(self.__delete__, args)

    async def update(self, **kw):
        print("enter update")
        args = []
        for key in kw:
            if key not in self.__fields__:
                raise RuntimeError("field not found")
        for key in self.__fields__:
            if key in kw:
                args.append(kw[key])
            else:
                args.append(getattr(self, key, None))
        args.append(getattr(self, self.__primaryKey__))
        await execute(self.__update__, args)

    # 类方法
    @classmethod
    async def find(cls, pk):
        rs = await select('%s where `%s`=?' % (cls.__select__, cls.__primaryKey__), [pk], 1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])  # 返回的是一个实例对象引用

    @classmethod
    async def findAll(cls, where=None, args=None):
        sql = [cls.__select__]
        if where:
            sql.append('where')
            sql.append(where)
        if args is None:
            args = []
        rs = await select(' '.join(sql), args)
        return [cls(**r) for r in rs]





# Field和各种Field子类
class Field():

    def  __init__(self, name, column_type, primary_key, default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default

    def __str__(self):
        return '<%s, %s:%s>' % (self.__class__.__name__, self.column_type, self.name)


class StringField(Field):
    def __init__(self, name=None, primary_key=False, default=None, ddl='varchar(100)'):
      super(StringField,self).__init__(name,ddl, primary_key, default)

# Bool在MYSQL中自动识别为Tinyint(1). true,false,TRUE,FALSE,它们分别代表1,0,1,0.
class BooleanField(Field):
    def __init__(self, name=None, default=0):
      super(BooleanField,self).__init__(name, 'boolean', False, default)


class IntegerField(Field):
    def __init__(self, name=None, primary_key=False, default=0):
      super(IntegerField,self).__init__(name, 'bigint', primary_key, default)

# Real在MYSQL中自动识别为Double.
class FloatField(Field):
    def __init__(self, name=None, primary_key=False, default=0.0):
      super(FloatField,self).__init__(name, 'real', primary_key, default)


class TextField(Field):
    def __init__(self, name=None, primary_key=False, default=None):
      super(TextField,self).__init__(name, 'text', primary_key, default)
