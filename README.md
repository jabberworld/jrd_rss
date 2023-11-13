# Jabber RSS Transport

This is a transport (service) for Jabber (XMPP), which allows to receive content of RSS feeds in any Jabber client. Based on code of transport used on rss.jrudevels.org (http://wiki.jrudevels.org/Rss.jrudevels.org - author - Binary).

## Requirements

* python2.7
* python-pyxmpp
* python-feedparser
* python-mysqldb

Optionally you can install following dependencies for support favicon.ico of feed's site as a photo in vCard:

* python-pil
* python-lxml

Was tested on Debian 12 with installed dependencies from Debian 10 (pyxmpp 1.1.2-1, feedparser 5.2.1-1 и mysqldb 1.3.10-2). If you can't install it from repository - you can download and place it manually in transport directory. Technically, all you need in your system is a Python2 - because of developing of transport's main dependency - pyxmpp - is stopped and it's only for python2.

## Installation

* Put files of transport in any directory.
* Create user and database in MySQL or MariaDB (checked on MariaDB 10.11.4)
* Import scheme from jrdrss.scheme.sql
* Add a service definition in your jabber server config.

As an example for ejabberd:

Old format:
```
     {5555, ejabberd_service, [
                              {ip, {127.0.0.1}},
                              {access, all},
                              {shaper_rule, fast},
                              {host, "rss.domain.com", [{password, "superpassword"}]}
                              ]},
```
New format:
```
    -
      port: 5555
      ip: "127.0.0.1"
      module: ejabberd_service
      access: all
      hosts:
       "rss.domain.com":
         password: "superpassword"
      shaper_rule: fast
```

Or for Prosody:
```
component_ports = 5555
Component "rss.domain.com"
        component_secret = 'superpassword'
```

* Write into config file config.xml all required credentials: to DB (host, user, password and database name) and to Jabber server (transport name, IP, port, password).
* Run somehow jrdrss.py - preferably from dedicated user. For example, you can use GNU screen or included jrdrss.service - put it into /etc/systemd/system, and in jrdrss.service write required home directory (with a path to service's files), username and group, then run:
```
    # systemctl enable jrdrss.service
    # systemctl start  jrdrss.service
```

## Usage

Open "Service discovery", then find your transport. You can search for feeds using transport's context menu to find something interesting from already registered feeds, or you can look at list of feeds directly, or register new one. In last case you should specify feed name (short, without spaces), URL of RSS feed, some description - and select update interval (1 hour by default, but for active feeds you can set it up to 1 minute); also you can add some tags. After all into your contact list will be added a bot named "feed_name@rss.domain.com" - you should authorize it and it will deliver news after some time. To unsubscribe - just remove this bot.

You can send commands to feeds; for full list of available commands send "help" to feed.

https://jabberworld.info/Jabber_RSS_Transport - more details and with pictures.

----

JabberWorld, https://jabberworld.info
