# JRSS — Архитектура проекта

## Обзор

**JRSS** — XMPP-компонент (транспорт), доставляющий RSS-ленты пользователям Jabber в виде отдельных ботов. Каждая лента становится JID в ростере (`feedname@transport.domain`), а новые статьи приходят как сообщения в чат.

- **Версия**: 2.1.0
- **Python**: 3.9+ (требуется `asyncio.to_thread`)
- **XMPP-библиотека**: slixmpp 1.10+
- **БД**: MySQL / MariaDB через PyMySQL
- **Лицензия**: GPL v3

Два поколения проекта:
- **Legacy** (корень репозитория): Python 2 + pyxmpp, версия 1.15.2 — **не используется**
- **Современное** (`py3/`): Python 3 + slixmpp, версия 2.1.0 — **активная версия**

## Структура файлов

```
py3/
├── jrdrss.py            Транспорт: жизненный цикл, presence, entry point, selftest
├── jrdrss_config.py     Конфигурация: загрузка XML, глобальные настройки
├── jrdrss_db.py         БД: класс DB, авто-миграция схемы, реконнект
├── jrdrss_feed.py       Ленты: загрузка, очистка HTML, форматирование, цикл обновления
├── jrdrss_dialog.py     Текстовые команды (диалог с ботом через сообщения)
├── jrdrss_service.py    IQ-обработчики: version, vCard, register, search, disco
├── jrdrss_adhoc.py      XEP-0050 Ad-Hoc Commands (корневые + per-feed)
├── jrdrss.service       systemd unit для Python 3
├── config.xml           Конфигурация (production)
├── config.xml.example   Пример конфигурации
├── CHANGELOG.md         Полный журнал изменений
├── README.md            Документация (англ.)
└── README.ru.md         Документация (рус.)
```

## Архитектура классов

```
Transport (slixmpp.ComponentXMPP)
  ├── FeedMixin         загрузка/обновление лент, форматирование, дедупликация
  ├── MessageMixin      обработка текстовых команд (диалог через сообщения)
  ├── ServiceMixin      IQ-обработчики, vCard, service discovery (XEP-0030)
  └── AdHocMixin        XEP-0050 Ad-Hoc Commands (корневые + per-feed)
```

Transport наследует `ComponentXMPP` и все 4 миксина через множественное наследование. Каждый миксин отвечает за свою область XMPP-протокола. Все атрибуты состояния хранятся на Transport и доступны миксинам через `self`.

## Пять потоков БД

Каждый миксин использует отдельное соединение с БД (атрибуты класса Transport), чтобы избежать блокировок при параллельной работе:

| Атрибут       | Миксин / модуль   | Назначение                         |
|---------------|-------------------|------------------------------------|
| `dbCurST`     | FeedMixin         | Поиск, SELECT-запросы (read-only)  |
| `dbCurUT`     | FeedMixin         | Обновление лент (INSERT/UPDATE)    |
| `dbCurRT`     | ServiceMixin      | Регистрация лент (INSERT)          |
| `dbCurPT`     | Transport         | Presence-обработка (UPDATE)        |
| `dbCurTT`     | MessageMixin      | Текстовые команды (все операции)   |

Все соединения **ленивые** (`conn=None`, `cursor=None`). При обрыве соединения автоматический реконнект через `DB.execute()` или `DB.commit()`.

## In-memory кэш лент

`self.dbfeeds` — список кортежей, загружаемый из БД при старте и обновляемый после каждого изменения в таблице `feeds`:

```
(0 feedname, 1 url, 2 timeout, 3 regdate, 4 description,
 5 subscribers, 6 private, 7 registrar, 8 tags, 9 checktype)
```

После INSERT/UPDATE в таблицу `feeds` вызывается `self.dbfeeds = dbCurXX.dbfeeds()` для перезагрузки кэша.

## Конфигурация

Файл `config.xml` загружается при импорте `jrdrss_config.py`. Порядок поиска: `$JRSS_CONFIG` → `py3/config.xml` → `../config.xml`.

```xml
<config>
    <dbhost>127.0.0.1</dbhost>       <!-- Хост MySQL -->
    <dbuser>root</dbuser>             <!-- Пользователь MySQL -->
    <dbpass>password</dbpass>         <!-- Пароль MySQL -->
    <dbname>jrdrss</dbname>           <!-- Имя базы данных -->
    <name>rss.example.com</name>      <!-- XMPP-домен компонента -->
    <host>127.0.0.1</host>            <!-- XMPP-сервер (jabberd2/ejabberd) -->
    <port>5555</port>                 <!-- Порт XMPP-сервера -->
    <password>component_pass</password>
    <adaptive>1</adaptive>            <!-- Адаптивные интервалы: 0=выкл, 1=вкл -->
    <regallow>1</regallow>            <!-- Публичная регистрация лент: 0=выкл, 1=вкл -->
    <iconlogo>1</iconlogo>            <!-- favicon.ico → vCard фото: 0=выкл, 1=вкл -->
    <sentsize>3</sentsize>            <!-- Хранение архива в днях (3-365) -->
    <admin>admin@example.com</admin>  <!-- JID администратора (можно несколько) -->
</config>
```

## База данных

### Таблицы

| Таблица        | PK       | Назначение                                    |
|----------------|----------|-----------------------------------------------|
| `feeds`        | feedname | Зарегистрированные RSS-ленты                  |
| `subscribers`  | id       | Подписки пользователей на ленты               |
| `sent`         | id       | Архив отправленных статей (для дедупликации)  |
| `schema_version`| version | Текущая версия схемы (2)                     |

### Авто-миграция

`DB.ensure_schema()` вызывается при каждом подключении. Создаёт отсутствующие таблицы и применяет ALTER-запросы при изменении версии схемы. Внешний SQL-файл не требуется.

## Поток данных: RSS → XMPP

```
update_loop() [каждые 15 сек]
  → idle() [вычисляет какие ленты пора проверять]
    → _run_checkrss(checkfeeds) [asyncio.to_thread — не блокирует event loop]
      → checkrss(checkfeeds):
          1. SELECT subscribers WHERE feedname = X
          2. feedparser.parse(url)
          3. Для каждой статьи (reverse = oldest first):
              a. isSent() — проверка дедупликации
              b. format_news_item() — фильтры, short-режим, формат
              c. sendmsg() → XMPP chat message подписчику
              d. INSERT INTO sent (дедупликация)
          4. Расчёт адаптивного интервала: 3600 / hourly_count
          5. Очистка архива старше sentsize дней
```

## Тестирование

```bash
# Self-test: проверка clean_summary, format_news_item, strip_utf8mb4
cd py3 && python3 jrdrss.py --selftest

# Dry-run: загрузка и парсинг всех лент без отправки сообщений
cd py3 && python3 jrdrss.py --dryrun

# Запуск транспорта
cd py3 && python3 -u jrdrss.py
```

## Типичные ошибки

1. **feedparser-конфликт** — при запуске из корня проекта Python подхватывает `feedparser.py` (Python 2). Всегда запускать из `py3/`.

2. **InterfaceError(0, '')** — PyMySQL при обрыве TCP-соединения. Обрабатывается в `DB.commit()` и `DB.execute()` с авто-реконнектом.

3. **utf8mb4** — эмодзи и символы ≥ 4 байт заменяются на `*` перед записью в БД через `strip_utf8mb4()`.

4. **Bozo feeds** — некорректный XML. feedparser парсит что может; `NonXMLContentType` — допустимое исключение.

5. **asyncio.to_thread** — требует Python 3.9+. CPU-bound операции (парсинг лент) выполняются в отдельном потоке.

6. **Привилегии команд** — команды `+`, `update`, `updateall`, `showall`, `purgelast`, `purgeall` доступны только администраторам (список `admins` в конфиге).

7. **Символ `:`** в текстовых командах заменяет имя текущей ленты (ленты, в которую отправлена команда).

8. **Минимальный интервал** — 60 секунд. Значение < 60 автоматически заменяется на 60.
