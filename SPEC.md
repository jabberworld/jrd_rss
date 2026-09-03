# JRSS — Спецификация проекта

## 1. Назначение

**JRSS** (Jabber RSS Transport) — XMPP-компонент-транспорт, доставляющий RSS-ленты пользователям Jabber/XMPP в виде индивидуальных ботов-контактов. Каждая RSS-лента представляется как JID `feedname@transport.domain` в ростере пользователя. Новые статьи доставляются как сообщения в чат.

Проект реализован как **компонент** XMPP-сервера (не MUC, не публичный сервис), подключаемый через protocolsjabberd2/ejabberd и протокол `jabber:component:accept`.

## 2. Системные требования

- **Python**: 3.9+ (используется `asyncio.to_thread`, появился в 3.9)
- **MySQL/MariaDB**: 5.7+ / 10.2+ (поддержка `utf8mb4`, `TEXT`, `DATETIME`)
- **XMPP-сервер**: jabberd2, ejabberd или совместимый компонент-хост
- **Операционная система**: Linux (тестировано на Debian 12/13)

## 3. Зависимости

### Обязательные

| Пакет      | Минимальная версия | Назначение                              |
|------------|--------------------|-----------------------------------------|
| slixmpp    | 1.10               | XMPP-клиент/компонент, XEP-0030, XEP-0050, XEP-0004 |
| feedparser |любая               | Парсинг RSS/Atom XML                    |
| pymysql    | любая              | MySQL-драйвер纯 Python                   |

### Опциональные

| Пакет  | Назначение                                              |
|--------|---------------------------------------------------------|
| Pillow | Конвертация favicon.ico в PNG для vCard-фото            |
| lxml   | Парсинг HTML-страницы для поиска тега `<link rel="icon">` |

## 4. Конфигурация

### Файл `config.xml`

Формат XML. Загружается при импорте `jrdrss_config.py`. Порядок поиска:

1. Переменная окружения `$JRSS_CONFIG`
2. `py3/config.xml` (относительно рабочей директории)
3. `../config.xml` (относительно рабочей директории)

Элементы XML и соответствующие переменные модуля:

| Элемент XML | Переменная     | Тип    | По умолч. | Описание                                           |
|-------------|----------------|--------|-----------|----------------------------------------------------|
| `dbhost`    | `DB_HOST`      | string | 127.0.0.1 | Хост MySQL                                         |
| `dbuser`    | `DB_USER`      | string | (пусто)   | Пользователь MySQL                                 |
| `dbpass`    | `DB_PASS`      | string | (пусто)   | Пароль MySQL                                       |
| `dbname`    | `DB_NAME`      | string | jrdrss    | Имя базы данных                                    |
| `name`      | `NAME`         | string | (пусто)   | XMPP-домен компонента                              |
| `host`      | `HOST`         | string | 127.0.0.1 | IP XMPP-сервера (jabberd2)                         |
| `port`      | `PORT`         | string | 5555      | Порт XMPP-сервера                                  |
| `password`  | `PASSWORD`     | string | (пусто)   | Пароль компонента                                  |
| `adaptive`  | `ADAPTIVE`     | string | 0         | Адаптивные интервалы: 0=выкл, 1=вкл                |
| `regallow`  | `REGALLOW`     | string | 1         | Публичная регистрация: 0=выкл, 1=вкл               |
| `iconlogo`  | `ICONLOGO`     | string | 0         | favicon → vCard: 0=выкл, 1=вкл                     |
| `sentsize`  | `SENTSIZE`     | string | 3         | Архив в днях ( clamp: 3..365 )                     |
| `admin`     | `admins`       | list[] | (пусто)   | JID администратора. Можно повторять.                |

### Пример

```xml
<config>
    <dbhost>127.0.0.1</dbhost>
    <dbuser>jrdrss</dbuser>
    <dbpass>secret</dbpass>
    <dbname>jrdrss</dbname>
    <name>rss.example.com</name>
    <host>127.0.0.1</host>
    <port>5555</port>
    <password>componentpass</password>
    <adaptive>1</adaptive>
    <regallow>1</regallow>
    <iconlogo>0</iconlogo>
    <sentsize>30</sentsize>
    <admin>admin@example.com</admin>
</config>
```

### Модуль `jrdrss_config.py`

- Загружает конфигурацию при импорте модуля (`load_config()` на уровне модуля)
- Устанавливает глобальный таймаут сокета: `socket.setdefaulttimeout(10)`
- Если `ICONLOGO=1`, импортирует `PIL.Image` и `lxml.html`
- Содержит base64-кодированный PNG RSS-иконки (`rsslogo`) как дефолтное vCard-фото
- Версия: `programmVersion = "2.1.0"`

## 5. База данных

### Подключение

PyMySQL, charset `utf8mb4`, autocommit `False`. Соединение ленивое (`conn=None`, `cursor=None`), создаётся при первом запросе.

### Таблица `feeds`

```sql
CREATE TABLE IF NOT EXISTS feeds (
    feedname    VARCHAR(255) NOT NULL,
    url         VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    tags        VARCHAR(255) DEFAULT NULL,
    subscribers INT NOT NULL DEFAULT 0,
    timeout     INT NOT NULL DEFAULT 3600,
    private     BOOLEAN DEFAULT false,
    checktype   INT DEFAULT 0,
    registrar   VARCHAR(128) DEFAULT NULL,
    regdate     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (feedname),
    UNIQUE KEY (url),
    KEY (registrar)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE utf8mb4_unicode_ci;
```

| Поле         | Тип      | Описание                                                      |
|--------------|----------|---------------------------------------------------------------|
| feedname     | PK       | Уникальное имя ленты (используется как XMPP-нода)            |
| url          | UNIQUE   | URL RSS/Atom-ленты                                            |
| description  | TEXT     | Текстовое описание                                            |
| tags         | VARCHAR  | Теги через запятую (категории)                                |
| subscribers  | INT      | Счётчик подписчиков (денормализованный)                       |
| timeout      | INT      | Интервал обновления в секундах (мин. 60)                      |
| private      | BOOLEAN  | Скрыта от поиска/бrowsing (только для registrar)              |
| checktype    | INT      | Тип дедупликации: 0=link, 1=link+title, 2=link+title+content |
| registrar    | VARCHAR  | JID пользователя, зарегистрировавшего ленту                   |
| regdate      | DATETIME | Дата регистрации                                              |

### Таблица `subscribers`

```sql
CREATE TABLE IF NOT EXISTS subscribers (
    id          INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    jid         VARCHAR(128),
    feedname    VARCHAR(255),
    posfilter   VARCHAR(255) DEFAULT NULL,
    negfilter   VARCHAR(255) DEFAULT NULL,
    short       INT DEFAULT 0,
    mute        BOOLEAN DEFAULT false,
    UNIQUE KEY (jid, feedname),
    KEY (feedname)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE utf8mb4_unicode_ci;
```

| Поле      | Тип      | Описание                                                        |
|-----------|----------|-----------------------------------------------------------------|
| id        | PK       | Автоинкремент                                                   |
| jid       | VARCHAR  | JID подписчика                                                  |
| feedname  | VARCHAR  | Имя ленты (FK-подобный → feeds.feedname)                       |
| posfilter | VARCHAR  | Позитивный regex-фильтр (только совпадающие статьи)             |
| negfilter | VARCHAR  | Негативный regex-фильтр (исключить совпадающие)                 |
| short     | INT      | Режим обрезки: 0=полный, 1=заголовок, 2=предложение, 3=абзац  |
| mute      | BOOLEAN  | Заглушён (статьи не приходят, но ручной fetch работает)         |

### Таблица `sent`

```sql
CREATE TABLE IF NOT EXISTS sent (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    feedname    VARCHAR(255),
    title       VARCHAR(255) DEFAULT NULL,
    author      VARCHAR(127) DEFAULT NULL,
    link        VARCHAR(255) DEFAULT NULL,
    content     TEXT DEFAULT NULL,
    datetime    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    income      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY (feedname, income),
    KEY (income),
    KEY (link),
    KEY (datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE utf8mb4_unicode_ci;
```

| Поле     | Тип      | Описание                                              |
|----------|----------|-------------------------------------------------------|
| id       | PK       | Автоинкремент                                         |
| feedname | VARCHAR  | Имя ленты                                             |
| title    | VARCHAR  | Заголовок статьи                                      |
| author   | VARCHAR  | Автор статьи                                           |
| link     | VARCHAR  | URL статьи                                             |
| content  | TEXT     | Содержимое статьи (для checktype=2)                    |
| datetime | DATETIME | Дата публикации статьи (из RSS)                        |
| income   | DATETIME | Дата получения/отправки статьи транспортом             |

### Таблица `schema_version`

```sql
CREATE TABLE schema_version (version INT NOT NULL);
```

Хранит текущую версию схемы. Текущая версия: **2**.

### Миграции

`DB.ensure_schema()` при подключении:
1. Создаёт отсутствующие таблицы (CREATE IF NOT EXISTS)
2. Сравнивает `schema_version` с `SCHEMA_VERSION` (константа)
3. Применяет миграции из словаря `MIGRATIONS` последовательно

Миграция v1→v2: добавление PK, уникальных ключей, индексов, удаление дубликатов, расширение TEXT-полей.

### Класс `DB`

```python
class DB:
    conn = None
    cursor = None

    def connect(self)           # PyMySQL connect, utf8mb4, autocommit=False
    def ensure_schema(self)     # CREATE TABLE + миграции (вызывается в connect)
    def ensure_connected(self)  # Lazy-connect если нет cursor
    def execute(self, sql, param=None)  # Execute + авто-реконнект при обрыве
    def commit(self)            # Commit + авто-реконнект при InterfaceError
    def close(self)             # Закрытие соединения

    def dbfeeds(self) -> list   # SELECT все ленты (10 полей)
    def dbnews(self) -> list    # Агрегация количества новостей (hour, day)
    def dbtimes(self) -> list   # Timestamps новостей за 24ч (UNIX)

    def fetchone(self)          # Proxy cursor.fetchone()
    def fetchall(self) -> list  # Proxy cursor.fetchall()
```

### Строковые représentation OrderedDict для DB.describe()

```python
{
    "feeds":    " feeds with timeout 0",
    "subscribers": " subscribers",
    "sent":     " items in the archive"
}
```

## 6. Архитектура модулей

### `jrdrss.py` — Транспорт

```python
class Transport(ComponentXMPP, FeedMixin, MessageMixin, ServiceMixin, AdHocMixin):
    # Class-level attributes
    start_time = int(time.time())
    last_upd = {}            # {feedname: timestamp} последнего обновления
    name = NAME
    updating = 0
    idleflag = 0
    times = {}               # {feedname: [timestamps]}
    new = {}                 # {feedname: count} за день
    lasthournew = {}         # {feedname: count} за час
    adaptive = int(ADAPTIVE)
    regallow = int(REGALLOW)
    iconlogo = int(ICONLOGO)
    sentsize = int(SENTSIZE) # clamp [3, 365]
    adaptime = {}            # {feedname: seconds}
    admins = admins
    rsslogo = rsslogo
```

#### Жизненный цикл

```python
def __init__(self)
    # ComponentXMPP.__init__(NAME, PASSWORD, HOST, PORT, plugin_whitelist=['xep_0030', 'xep_0050'])
    # 5 DB-инстансов: dbCurST, dbCurUT, dbCurRT, dbCurPT, dbCurTT
    # Загрузка feeds из БД в self.dbfeeds
    # Регистрация event handlers
    # Регистрация 10 IQ handlers

def started(self, event)
    # Сброс состояния, загрузка feeds, загрузка счётчиков новостей
    # Инициализация disco + adhoc
    # Запуск update_loop как asyncio task

def on_disconnected(self, event)
    # Авто-реконнект через 60 секунд (если не завершение работы)
```

#### Presence

```python
def presence(self, stanza)            # Ответ на available/unavailable
def _handle_probe(self, pres)         # Override probe: статус ленты вместо roster
def get_show(self, feedname)          # XMPP show: 'chat'/'away'/'xa'/None
def get_status(self, feedname)        # Rich status: описание, счётчики, интервалы
def presence_control(self, stanza)    # subscribe/unsubscribe: UPDATE subscribers
```

#### Вспомогательные методы

```python
def _send(self, stanza)               # Thread-safe send через loop.call_soon_threadsafe
def _send_now(self, stanza)           # Прямой stanza.send()
def isFeedNameRegistered(self, fn)    # Поиск в self.dbfeeds
def isFeedUrlRegistered(self, url)    # Поиск в self.dbfeeds
def sendmsg(self, fromjid, tojid, msg)  # Отправка chat message (/rss resource)
def send_feed_presence(self, fn, tojid, ptype, show, status)
```

#### Точка входа

```python
def main():
    # --selftest    → run_selftest()
    # --dryrun [fn] → run_dryrun(fn)
    # иначе         → asyncio.run(run_transport())
```

### `jrdrss_feed.py` — Обработка лент

```python
class FeedMixin:
    def update_loop(self)             # Периодический цикл (15 сек)
    def idle(self)                    # Определение лент для проверки
    async def _run_checkrss(self, checkfeeds)  # asyncio.to_thread
    def checkrss(self, checkfeeds)    # Основной цикл обновления
    def isSent(self, feedname, checkdata, checktype) -> bool
    def botstatus(self, feedname, jid)
    def sendItem(self, feedname, item, jids)

    @staticmethod
    def strip_utf8mb4(mb4: str) -> str
```

#### Свободные функции

```python
def clean_summary(summary) -> str
    # HTML → plain text: <br>\n, <blockquote> → > «...», strip tags, entities

def format_news_item(item, summary, jids) -> list[tuple[str, str]]
    # Возвращает [(bare_jid, text), ...] для каждого подписчика
    # Учитывает posfilter, negfilter, short, mute
```

#### Константа `SAMPLE_FEED`

Минимальный RSS 2.0 XML с 2 тестовыми статьями для selftest.

### `jrdrss_dialog.py` — Текстовые команды

```python
class MessageMixin:
    def message(self, msg)            # Главный роутер команд
    def printsearch(self, data, tojid, fromjid, inall, feedname)
```

### `jrdrss_service.py` — IQ-обработчики

#### Стanzа-классы (8 штук, зарегистрированы как plugins на `Iq`):

| Класс           | XML-элемент  | Namespace                                | plugin_attrib |
|-----------------|--------------|------------------------------------------|---------------|
| Version         | `<query>`    | `jabber:iq:version`                      | version       |
| LastQuery       | `<query>`    | `jabber:iq:last`                         | last          |
| Ping            | `<ping>`     | `urn:xmpp:ping`                          | ping          |
| TimeStanza      | `<time>`     | `urn:xmpp:time`                          | time          |
| StatsQuery      | `<query>`    | `http://jabber.org/protocol/stats`       | stats         |
| RegisterQuery   | `<query>`    | `jabber:iq:register`                     | register      |
| SearchQuery     | `<query>`    | `jabber:iq:search`                       | search        |
| VCardStanza     | `<vCard>`    | `vcard-temp`                             | vcard         |

```python
class ServiceMixin:
    def get_version(self, iq)
    def get_last(self, iq)
    def pingpong(self, iq)
    def get_time(self, iq)
    def get_stats(self, iq)
    def get_register(self, iq)        # Форма регистрации (транспорт + per-feed)
    def set_register(self, iq)        # Обработка формы → regThread()
    def regThread(self, iqres, iqerr, fname, furl, fdesc, fsubs, ftime, fpriv, ftags, ctype)
    def get_search(self, iq)
    def set_search(self, iq)
    def getlogo(self, url)            # favicon.ico → base64 PNG
    def get_vCard(self, iq)           # Transport vCard или per-feed vCard
    def mknode(self, disco_items, name, desc)
    def browseitems(self, iq, node)   # Категории: feeds, owner, private, tags, tag:NAME
    def disco_get_items(self, jid, node, ifrom, data)
    def disco_get_info(self, jid, node, ifrom, data)
```

### `jrdrss_adhoc.py` — Ad-Hoc Commands

```python
COMMANDS_NS = 'http://jabber.org/protocol/commands'

ADHOC_COMMANDS = [           # Per-feed (отправляются на feedname@transport)
    ('view-info',     'Feed info',        handler)
    ('view-sub',      'My subscription',  handler)
    ('edit-info',     'Edit feed info',   handler)
    ('edit-sub',      'Edit subscription', handler)
    ('edit-privacy',  'Feed privacy',     handler)
]

ADHOC_ROOT_COMMANDS = [     # Transport-level (отправляются на transport JID)
    ('register',   'Register new feed',    handler)
    ('my-feeds',   'Show my feeds',        handler)
    ('my-private', 'Show my private feeds', handler)
    ('feeds',      'Show all feeds',       handler)
    ('tags',       'Show Categories',      handler)
]
```

```python
class _AdHocCommands(dict):
    # Динамический lookup: (jid, node) → (name, handler)
    # Избегает регистрации индивидуальных handlers на каждый feed

class AdHocMixin:
    def init_adhoc(self)                # Привязка dynamic lookup к XEP-0050

    # Helpers
    def _find_feed_record(self, name)
    def _new_form(self, ftype, title, instructions)
    def _form_type_field(self, form)
    def _field_value(self, form, var)

    # Per-feed view
    async def adhoc_view_info(self, iq, session)
    async def adhoc_view_sub(self, iq, session)

    # Per-feed edit
    async def adhoc_edit_info(self, iq, session)
    async def adhoc_edit_info_apply(self, form, session)
    async def adhoc_edit_sub(self, iq, session)
    async def adhoc_edit_sub_apply(self, form, session)
    async def adhoc_edit_privacy(self, iq, session)
    async def adhoc_edit_privacy_apply(self, form, session)

    # Root menu
    def _visible_feed(self, feed, fromjid)
    def _add_feed_contact(self, feedname, tojid)
    def _feed_pick_form(self, feednames, title, instructions)

    async def adhoc_register(self, iq, session)
    async def adhoc_myfeeds(self, iq, session)
    async def adhoc_myprivate(self, iq, session)
    async def adhoc_feeds(self, iq, session)
    async def adhoc_tags(self, iq, session)

    def _registration_step(self, session)
    def _feed_list_step(self, session, func)
    def _category_step(self, session)

    async def adhoc_tag_apply(self, form, session)
    async def adhoc_feed_apply(self, form, session)
    async def adhoc_register_apply(self, form, session)
```

## 7. XMPP-протокол

### Компонент

JRSS подключается к XMPP-серверу как **компонент** (`jabber:component:accept`):

```python
ComponentXMPP(NAME, PASSWORD, HOST, PORT, plugin_whitelist=['xep_0030', 'xep_0050'])
```

### Service Discovery (XEP-0030)

#### Корневой JID (transport domain)

**Identity**: `automation/automation` — «Jabber RSS Transport»

**Features** (12):
- `http://jabber.org/protocol/disco#info`
- `http://jabber.org/protocol/disco#items`
- `http://jabber.org/protocol/stats`
- `http://jabber.org/protocol/commands`
- `jabber:iq:version`
- `jabber:iq:search`
- `jabber:iq:register`
- `jabber:iq:last`
- `urn:xmpp:ping`
- `urn:xmpp:time`
- `vcard-temp`
- `jabber:iq:register`

**Items** (NODES_NS): `feeds`, `owner`, `private`, `tags` — корневые категории

#### Per-feed JID (`feedname@transport`)

**Identity**: ` automat/ txt` — «feedname (description)»

**Features**: `jabber:iq:register`, `http://jabber.org/protocol/commands`

#### Категории (disco#itemsbrowse)

| Название | Описание                                |
|----------|-----------------------------------------|
| `feeds`  | Все публичные ленты (private=false)     |
| `owner`  | Ленты, зарегистрированные текущим user  |
| `private`| Приватные ленты текущего user           |
| `tags`   | Все уникальные теги                     |
| `tag:X`  | Ленты с тегом X                         |

### IQ-обработчики

#### `jabber:iq:version`

```xml
<iq type="result">
  <query xmlns="jabber:iq:version">
    <name>Jabber RSS Transport</name>
    <version>2.1.0</version>
    <os>Linux</os>
  </query>
</iq>
```

#### `jabber:iq:last`

Возвращает секунды с момента последней активности (старт транспорта или последнее обновление ленты).

#### `urn:xmpp:ping`

Pong без тела.

#### `urn:xmpp:time`

Возвращает UTC-время (TZO захардкожен `+02:00`).

#### `http://jabber.org/protocol/stats`

Uptime, количество новостей за час/день, количество активных/общих лент.

#### `jabber:iq:register`

**Transport-level** (на корневой JID):
- `get`: XEP-0004 data form для регистрации новой ленты (поля: feedname, url, description, timeout, private, tags, checktype)
- `set`: Валидация URL через feedparser, INSERT INTO feeds, INSERT INTO subscribers

**Per-feed** (на feedname@transport):
- `get`: Форма подписки (инструкции + кнопка subscribe)
- `set`: INSERT INTO subscribers, отправка subscribe-presence

#### `jabber:iq:search`

- `get`: XEP-0004 data form с полем поиска
- `set`: SELECT из `sent` по title/author/content/feedname, возврат результатов

### Presence

#### Подписка (subscribe/subscribed/unsubscribe/unsubscribed)

```python
def presence_control(self, stanza):
    # subscribe:
    #   1. INSERT INTO subscribers (feedname, jid) ON DUPLICATE KEY UPDATE
    #   2. UPDATE feeds SET subscribers = subscribers + 1
    #   3. Отправить subscribed-presence обратно
    #   4. Отправить available-presence от feedname
    #
    # unsubscribe:
    #   1. DELETE FROM subscribers WHERE feedname=X AND jid=Y
    #   2. UPDATE feeds SET subscribers = subscribers - 1
    #   3. Отправить unsubscribed-presence
```

#### Probe (respond)

```python
def _handle_probe(self, pres):
    # Вместо стандартного ответа — статус ленты:
    # show: 'chat' (статьи за час > 0), 'away' (статьи за день > 0), 'xa' (есть за 24ч), None
    # status: описание, количество новостей за час/день, время обновления, следующее обновление, количество подписчиков
```

### Формат сообщения

```
*Title*
Link: <url> (by <author>)

<body>

```

Где `<body>` — `clean_summary(summary)`, обрезанный по `short`-режиму подписчика.

## 8. Обработка лент

### update_loop

```python
async def update_loop(self):
    while not self.shutting_down:
        await asyncio.sleep(15)
        self.idle()
```

### idle

Вычисляет список лент для проверки:
- Если `adaptive=0`: проверять ленту если `now - last_upd[feedname] >= timeout`
- Если `adaptive=1`: проверять ленту если `now - last_upd[feedname] >= adaptime[feedname]`
- Сразу после старта (`idleflag=0`): проверять все ленты

### checkrss (основной цикл)

```python
def checkrss(self, checkfeeds):
    for feedname, feedurl, ... in checkfeeds:
        # 1. Загрузить подписчиков из БД
        subscribers = self.dbCurUT.fetchall()

        # 2. Парсинг ленты
        feed = feedparser.parse(feedurl)

        # 3. Обработка bozo (некорректный XML)
        if feed.bozo and not isinstance(feed.bozo_exception, NonXMLContentType):
            continue

        # 4. Обработка статей (reverse = oldest first)
        for item in reversed(feed.entries):
            # 4a. Проверка дедупликации
            if self.isSent(feedname, item, checktype):
                continue

            # 4b. Форматирование (фильтры, short-режим)
            messages = format_news_item(item, clean_summary(item.summary), subscribers)

            # 4c. Отправка
            for jid, text in messages:
                self.sendmsg(feedname + '@' + self.name, jid, text)

            # 4d. Запись в архив
            self.dbCurUT.execute(
                "INSERT INTO sent (feedname, title, author, link, content, datetime) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (feedname, item.title, item.author, item.link, item.summary, datetime)
            )

        # 5. Обновление last_upd и счётчиков
        self.last_upd[feedname] = time.time()

        # 6. Расчёт адаптивного интервала
        if self.adaptive:
            self.adaptime[feedname] = max(60, min(3600 / max(1, hourly_count), timeout))

        # 7. Очистка архива
        self.dbCurUT.execute(
            "DELETE FROM sent WHERE feedname = %s AND income < NOW() - INTERVAL %s DAY",
            (feedname, self.sentsize)
        )
```

### isSent (дедупликация)

```python
def isSent(self, feedname, item, checktype):
    # checktype=0: WHERE link = item.link
    # checktype=1: WHERE CONCAT(link, title) = CONCAT(item.link, item.title)
    # checktype=2: WHERE CONCAT(link, title, IFNULL(content,'')) = CONCAT(item.link, item.title, IFNULL(item.summary,''))
```

### clean_summary

1. `<br>` → перенос строки
2. `<blockquote>` → `> «...»` (стиль цитаты)
3. Удаление всех HTML-тегов
4. Замена ~20 HTML-сущностей на Unicode (`&hellip;`→`…`, `&laquo;`→`«`, `&raquo;`→`»`, `&ndash;`→`–`, `&mdash;`→`—` и т.д.)

### format_news_item

Для каждого подписчика:
1. Если `posfilter`: regex-матч по `item.title`. Если нет совпадения — пропустить.
2. Если `negfilter`: regex-матч по `item.title`. Если есть совпадение — пропустить.
3. Если `mute=True`: пропустить полностью.
4. Обрезка по `short`:
   - `0`: полный текст
   - `1`: только заголовок
   - `2`: первое предложение (разбиение по `.!?`)
   - `3`: первый абзац (разбиение по `\n`)
   - `>3`: первые N символов + `...`
5. Формат: `*Title*\nLink: <url> (by <author>)\n\n<body>\n\n`

### strip_utf8mb4

Заменяет символы ≥ 4 UTF-8 байт (эмодзи и прочее) на `*` перед записью в БД.

## 9. Текстовые команды

Команды отправляются сообщениями на JID ленты (`feedname@transport`) или транспорта (`transport`).

Все команды доступны в两种形式: полное название + короткий алиас.

### Символ `:`

Вместо имени ленты можно использовать `:` — означает текущую ленту (JID, на который отправлено сообщение).

### Административные команды

| Команда | Синтаксис | Описание |
|---------|-----------|----------|
| `+` | `+ NAME URL INTERVAL DESC [SETTAGS: TAGS]` | Зарегистрировать новую ленту |
| `update` | `update [NAME]` | Принудительное обновление ленты |
| `updateall` | `updateall` | Принудительное обновление всех лент |
| `showall` | `showall` | Вывести все зарегистрированные ленты |
| `purgelast` | `purgelast [NAME]` | Удалить последнюю запись из архива |
| `purgeall` | `purgeall [NAME]` | Удалить все записи из архива ленты |

### Команды для всех пользователей

#### Справка

| Команда | Алиас | Синтаксис | Описание |
|---------|-------|-----------|----------|
| `help` | `?` | `help` | Показать список команд |

#### Управление лентами (owner + admin)

| Команда | Алиас | Синтаксис | Описание |
|---------|-------|-----------|----------|
| `settags` | `=#` | `settags NAME TAGS` | Установить теги |
| `setupd` | `=@` | `setupd NAME SECS` | Установить интервал обновления |
| `setdesc` | `=:` | `setdesc NAME TEXT` | Установить описание |
| `setuniq` | `=()` | `setuniq NAME (link\|title\|content)` | Установить тип дедупликации |
| `hide` | `***` | `hide [NAME]` | Сделать ленту приватной |
| `unhide` | `+++` | `unhide [NAME]` | Сделать ленту публичной |

#### Подписка (любой пользователь)

| Команда | Алиас | Синтаксис | Описание |
|---------|-------|-----------|----------|
| `setshort` | `=...` | `setshort SYMBOLS` | Режим обрезки (0-3) |
| `setposfilter` | `=+` | `setposfilter [EXP]` | Позитивный regex-фильтр |
| `setnegfilter` | `=-` | `setnegfilter [EXP]` | Негативный regex-фильтр |
| `mute` | `~~~` | `mute [NAME]` | Заглушить ленту |
| `unmute` | `@@@` | `unmute [NAME]` | Снять заглушку |

#### Просмотр (любой пользователь)

| Команда | Алиас | Синтаксис | Описание |
|---------|-------|-----------|----------|
| `showtags` | `?#` | `showtags [NAME]` | Показать теги |
| `showupd` | `?@` | `showupd [NAME]` | Показать интервал обновления |
| `showdesc` | `?:` | `showdesc [NAME]` | Показать описание |
| `showuniq` | `?()` | `showuniq [NAME]` | Показать тип дедупликации |
| `showadap` | `?%` | `showadap [NAME]` | Показать текущий адаптивный интервал |
| `showshort` | `?...` | `showshort [NAME]` | Показать режим обрезки |
| `showfilter` | `?+-` | `showfilter [NAME]` | Показать фильтры |
| `showmyprivate` | `?***` | `showmyprivate` | Мои приватные ленты |
| `showmyfeeds` | `?~` | `showmyfeeds` | Мои зарегистрированные ленты |

#### Поиск

| Команда | Алиас | Синтаксис | Описание |
|---------|-------|-----------|----------|
| `search` | `?` | `search STRING` | Поиск в текущей ленте |
| `searchall` | `?!` | `searchall STRING` | Поиск по всем лентам |
| `searchintag` | `?!#` | `searchintag TAG STRING` | Поиск по тегу |
| `searchtitle` | `?!*` | `searchtitle STRING` | Поиск только по заголовкам |

#### Прочее

| Команда | Синтаксис | Описание |
|---------|-----------|----------|
| `1..20` | `N` | Загрузить последние N статей |
| `top` | `top [today\|day\|week\|month]` | Топ-10 лент по количеству новостей за период (d/w/m — короткие формы) |

## 10. Ad-Hoc Commands (XEP-0050)

### Корневые команды (отправляются на transport JID)

| Название      | Описание                  | Шаги                                          |
|---------------|---------------------------|------------------------------------------------|
| `register`    | Регистрация новой ленты   | Форма → `_registration_step` → apply           |
| `my-feeds`    | Мои ленты                 | `_feed_list_step(owner)` → optional add contact |
| `my-private`  | Мои приватные ленты       | `_feed_list_step(private)` → optional add contact |
| `feeds`       | Все публичные ленты       | `_feed_list_step(feeds)` → optional add contact |
| `tags`        | Категории                 | `_category_step` → tag apply → feed list → add contact |

### Per-feed команды (отправляются на feedname@transport)

| Название      | Описание                  | Шаги                                          |
|---------------|---------------------------|------------------------------------------------|
| `view-info`   | Информация о ленте       | Просмотр всех параметров                      |
| `view-sub`    | Моя подписка              | Просмотр настроек подписки                    |
| `edit-info`   | Редактирование ленты      | Форма → `adhoc_edit_info_apply`               |
| `edit-sub`    | Редактирование подписки   | Форма → `adhoc_edit_sub_apply`                |
| `edit-privacy`| Приватность ленты         | Форма → `adhoc_edit_privacy_apply`            |

### Формы XEP-0004

Все формы содержат скрытое поле `FORM_TYPE` с namespace `COMMANDS_NS`.

Пример формы регистрации:
```
Title: Register new feed
Instructions: Enter feed details
Fields:
  - text-single: feedname (required)
  - text-single: url (required)
  - text-single: description
  - text-single: timeout (default: 3600)
  - boolean: private (default: false)
  - text-single: tags
  - list-single: checktype (link/title/content)
```

### `_AdHocCommands`

Динамический `dict`, который при обращении по ключу `(jid, node)` определяет:
- Если `node` пустой или `COMMANDS_NS`: вернуть список всех команд для этого JID
- Если `node` — имя команды: вернуть `(name, handler)`
- Если `node` не найден: вернуть `None`

Избегает регистрации индивидуальных handlers на каждый feed JID.

## 11. Адаптивные интервалы

При `adaptive=1`:

```
real_interval = 3600 / hourly_count
real_interval = max(60, min(real_interval, configured_timeout))
```

- `hourly_count` — количество новых статей за последний час
- Минимум: 60 секунд
- Максимум: настроенный `timeout` ленты
- Хранится в `self.adaptime[feedname]`
- Просматривается командой `showadap` / `?%`

При `adaptive=0` используется фиксированный `timeout`.

## 12. vCard и иконки

### Транспорт vCard

```xml
<vCard xmlns="vcard-temp">
  <FN>Jabber RSS Transport</FN>
  <NICKNAME>JRSS</NICKNAME>
  <DESC>...</DESC>
  <BDAY>2007-10-11</BDAY>
  <PHOTO><BINVAL>base64...</BINVAL><TYPE>image/png</TYPE></PHOTO>
</vCard>
```

### Per-feed vCard

```xml
<vCard xmlns="vcard-temp">
  <NICKNAME>feedname</NICKNAME>
  <DESC>description (tags: ..., interval: ..., subscribers: ...)</DESC>
  <URL>http://feed.url</URL>
  <BDAY>regdate</BDAY>
  <PHOTO><BINVAL>base64...</BINVAL><TYPE>image/png</TYPE></PHOTO>
</vCard>
```

### Логика загрузки favicon (`getlogo`)

1. Запрос `GET /favicon.ico` по URL ленты
2. Если 404: парсинг HTML-страницы, поиск `<link rel="icon" href="...">`
3. Конвертация в PNG через `Pillow.Image.open().save()`
4. Base64-кодирование
5. При ошибке: используется `rsslogo` (дефолтная RSS-иконка)

## 13. systemd

```ini
[Unit]
Description=RSS jabber transport
After=network.target remote-fs.target nss-lookup.target

[Service]
User=jrdrss
Group=jrdrss
Type=simple
ExecStart=/usr/bin/python3 -u jrdrss.py
WorkingDirectory=/home/jrdrss/jrdrss
Restart=always
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

## 14. Журнал изменений (кратко)

| Версия | Основные изменения |
|--------|--------------------|
| 2.1.0  | XEP-0050 Ad-Hoc Commands (per-feed + root), XEP-0077 register to feeds, disco fixes |
| 2.0.0  | Полный порт на Python 3 + slixmpp, asyncio, авто-миграция схемы |
| 1.15.2 | mute-режим, checktype (link/title/content) |
| 1.15   | Добавлен checktype |
| 1.14   | Очистка архива по sentsize |
| 1.12   | Удалён md5, добавлен income timestamp |
| 1.9    | Добавлены title, author, link, content в sent |
| 1.7    | short-режим (обрезка сообщений) |
| 1.6    | posfilter / negfilter (regex-фильтры) |
| 1.4    | tags (категории лент) |
| 1.3    | registrar (владелец ленты) |
| 1.2    | private (приватность лент) |
| 1.0    | Базовая функциональность |
