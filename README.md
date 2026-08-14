# Jabber RSS Transport

This is a transport (service) for Jabber (XMPP), which allows to receive content of RSS feeds in any Jabber client.
Reworked with the help of AI to Python 3 + slixmpp based on the first version of the transport (for Python 2 + pyxmpp), which, in turn, was based on the code of the transport used once on rss.jrudevels.org (by Binary).

## Requirements

* Python 3.9+
* slixmpp
* feedparser
* pymysql

Optionally you can install following dependencies for support favicon.ico of feed's site as a photo in vCard:

* pillow
* lxml

Dependencies can be installed with pip:

```
pip install slixmpp feedparser pymysql pillow lxml
```

Or by installing system-wide packages:

```
apt-get install python3-slixmpp python3-feedparser python3-pymysql python3-pil python3-lxml
```

Was tested on Debian 13 with slixmpp 1.10.

## Installation

* Put files of transport in any directory (the Python 3 version lives in the py3/ subdirectory).
* Install the dependencies (see Requirements above).
* Create user and database in MySQL or MariaDB (checked on MariaDB 11.8). The scheme is created and updated in the database automatically at startup.
* Add a service definition in your jabber server config.

For ejabberd:

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
Component "rss.example.com"
        component_secret = 'superpassword'
```


* Write into config file config.xml all required credentials: to DB (host, user, password and database name) and to Jabber server (transport name, IP, port, password).
* Run somehow jrdrss.py (preferably from dedicated user) - for example, using the bundled jrdrss.service file for systemd, placing it into /etc/systemd/system, and writing the required user and group into jrdrss.service.

## Usage

Open "Service discovery", then find your transport. You can search for feeds using transport's context menu to find something interesting from already registered feeds, or you can look at list of feeds directly, or register new one. In last case you should specify feed name (short, without spaces; ideally - but not necessarily - latin), URL of RSS feed, some description - and select update interval (1 hour by default, but for active feeds you can set it up to 1 minute); also you can add some tags. After all into your contact list will be added a bot named "feed_name@rss.domain.com" - you should authorize it and it will deliver news after some time. To unsubscribe - just remove this bot.

You can send commands to feeds; for full list of available commands send "help" to feed.

The transport and each feed also expose Ad-Hoc commands (XEP-0050) in service discovery. A feed has commands for viewing and editing its parameters and subscription settings; the transport itself offers registration of a new feed, as well as viewing the existing ones.

https://jabberworld.info/Jabber_RSS_Transport - more details and with pictures.

----

JabberWorld, https://jabberworld.info