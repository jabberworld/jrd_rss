#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# JRSS  Python 3 Jabber RSS transport.
#
# Core module: component class wiring, connection lifecycle, presence
# handling and the entry point. Functionality is split across modules:
#
#   jrdrss_config.py   - configuration handling and constants
#   jrdrss_db.py       - database access (auto-creates the schema)
#   jrdrss_feed.py     - feed content processing and the update mixin
#   jrdrss_dialog.py   - message command handling
#   jrdrss_service.py  - IQ handlers (version/vCard/register/search/disco)
#
# Run from this directory (py3/) to avoid the Python 2 vendored libraries
# (feedparser.py, pyxmpp/, MySQLdb/, PIL/, lxml/) shadowing the real modules.

import asyncio
import sys
import time

import feedparser
from pymysql.err import IntegrityError as MySQLIntegrityError
from slixmpp import JID
from slixmpp.componentxmpp import ComponentXMPP
from slixmpp.xmlstream.handler import Callback
from slixmpp import StanzaPath

from jrdrss_config import (NAME, PASSWORD, HOST, PORT,
                           ADAPTIVE, REGALLOW, ICONLOGO, SENTSIZE,
                           admins, rsslogo)
from jrdrss_db import DB
from jrdrss_feed import FeedMixin, clean_summary, format_news_item, SAMPLE_FEED
from jrdrss_dialog import MessageMixin
from jrdrss_service import ServiceMixin
from jrdrss_adhoc import AdHocMixin


class Transport(ComponentXMPP, FeedMixin, MessageMixin, ServiceMixin,
                AdHocMixin):

    start_time = int(time.time())
    last_upd = {}          # array of last update feeds time
    name = NAME
    updating = 0           # flag to block parallel updates
    idleflag = 0
    times = {}             # array of timestamps of new messages
    new = {}               # new daily messages counter
    lasthournew = {}       # new hourly messages counter
    adaptive = int(ADAPTIVE)
    regallow = int(REGALLOW)
    iconlogo = int(ICONLOGO)
    sentsize = int(SENTSIZE)
    adaptime = {}
    admins = admins
    rsslogo = rsslogo

    def __init__(self, *args, **kwargs):
        super().__init__(NAME, PASSWORD, HOST, int(PORT),
                         plugin_whitelist=['xep_0030', 'xep_0050'])
        self.register_plugins()

        self._shutdown = False
        self._updtask = None
        self.dbCurST = DB()   # search thread
        self.dbCurUT = DB()   # update thread
        self.dbCurRT = DB()   # register thread
        self.dbCurPT = DB()   # presence thread
        self.dbCurTT = DB()   # talking thread

        try:
            self.dbfeeds = self.dbCurUT.dbfeeds()
        except Exception as msg:
            print("Failed to load feeds from DB:", msg)
            self.dbfeeds = []

        if self.sentsize < 3:
            self.sentsize = 3
        elif self.sentsize > 365:
            self.sentsize = 365

        # -- event handlers ------------------------------------------------
        self.add_event_handler('session_start', self.started)
        self.add_event_handler('disconnected', self.on_disconnected)
        self.add_event_handler('message', self.message)
        for ev in ('presence_available', 'presence_unavailable'):
            self.add_event_handler(ev, self.presence)
        for ev in ('presence_subscribe', 'presence_subscribed',
                   'presence_unsubscribe', 'presence_unsubscribed'):
            self.add_event_handler(ev, self.presence_control)

        # -- IQ handlers ----------------------------------------------------
        self.register_handler(Callback('Version get',
                                       StanzaPath('iq@type=get/version'),
                                       self.get_version))
        self.register_handler(Callback('Last get',
                                       StanzaPath('iq@type=get/last'),
                                       self.get_last))
        self.register_handler(Callback('Ping get',
                                       StanzaPath('iq@type=get/ping'),
                                       self.pingpong))
        self.register_handler(Callback('Time get',
                                       StanzaPath('iq@type=get/time'),
                                       self.get_time))
        self.register_handler(Callback('Stats get',
                                       StanzaPath('iq@type=get/stats'),
                                       self.get_stats))
        self.register_handler(Callback('vCard get',
                                       StanzaPath('iq@type=get/vcard'),
                                       self.get_vCard))
        self.register_handler(Callback('Register get',
                                       StanzaPath('iq@type=get/register'),
                                       self.get_register))
        self.register_handler(Callback('Register set',
                                       StanzaPath('iq@type=set/register'),
                                       self.set_register))
        self.register_handler(Callback('Search get',
                                       StanzaPath('iq@type=get/search'),
                                       self.get_search))
        self.register_handler(Callback('Search set',
                                       StanzaPath('iq@type=set/search'),
                                       self.set_search))

    # -- helpers -----------------------------------------------------------

    def _send(self, stanza):
        """Send a stanza from any thread."""
        loop = self.loop
        if loop.is_running():
            loop.call_soon_threadsafe(self._send_now, stanza)
        else:
            self._send_now(stanza)

    def _send_now(self, stanza):
        try:
            stanza.send()
        except Exception as msg:
            print("Send error:", msg)

    def isFeedNameRegistered(self, feedname):
        return any(f[0] == feedname for f in self.dbfeeds)

    def isFeedUrlRegistered(self, furl):
        return any(f[1] == furl for f in self.dbfeeds)

    def sendmsg(self, fromjid, tojid, msg):
        fromjid = str(fromjid) + '/rss'
        self._send(self.make_message(mto=tojid, mbody=msg,
                                     mfrom=JID(fromjid), mtype='chat'))

    def send_feed_presence(self, feedname, tojid, ptype='available',
                           show=None, status=None):
        p = self.Presence(stype=ptype,
                          sfrom=feedname + '@' + self.name + '/rss',
                          sto=tojid)
        if show is not None:
            p['show'] = show
        if status is not None:
            p['status'] = status
        self._send(p)

    # -- lifecycle ---------------------------------------------------------

    def started(self, event):
        print("Session started")
        self.idleflag = 0
        self.updating = 0
        self.last_upd = {}
        self.adaptime = {}
        self.times = {}
        self.new = {}
        self.lasthournew = {}
        try:
            self.dbfeeds = self.dbCurUT.dbfeeds()
        except Exception as msg:
            print("Failed to load feeds from DB:", msg)

        try:
            now = time.time()
            for feedname, ts in self.dbCurUT.dbtimes():
                if ts > now - 86400:
                    self.new[feedname] = self.new.get(feedname, 0) + 1
                    if ts > now - 3600:
                        self.lasthournew[feedname] = self.lasthournew.get(feedname, 0) + 1
                    self.times.setdefault(feedname, []).append(ts)
        except Exception as msg:
            print("Failed to load news counters from DB:", msg)

        disco = self.plugin.get('xep_0030', None)
        if disco:
            disco.set_node_handler('get_items', None, None, self.disco_get_items)
            disco.set_node_handler('get_info', None, None, self.disco_get_info)
        self.init_adhoc()

        if self._updtask is None or self._updtask.done():
            self._updtask = asyncio.create_task(self.update_loop())

    def on_disconnected(self, event):
        if not self._shutdown:
            print("Connection lost, reconnecting in 60 seconds")
            self.reconnect(wait=60, reason='Connection lost')

    def _handle_probe(self, pres):
        # Override the default roster-based probe handling which would send
        # 'unsubscribed' for unknown local subscriptions.
        feedname = pres['to'].node
        if feedname and self.isFeedNameRegistered(feedname):
            self.send_feed_presence(feedname, pres['from'],
                                    show=self.get_show(feedname),
                                    status=self.get_status(feedname))

    # -- presence ----------------------------------------------------------

    def presence(self, stanza):
        feedname = stanza['to'].node
        if feedname is None:
            return
        if stanza['type'] == 'unavailable' and self.isFeedNameRegistered(feedname):
            self._send(self.Presence(stype='unavailable',
                                     sfrom=stanza['to'],
                                     sto=stanza['from']))
        elif stanza['type'] == 'available':
            if self.isFeedNameRegistered(feedname):
                self.send_feed_presence(feedname, stanza['from'],
                                        show=self.get_show(feedname),
                                        status=self.get_status(feedname))

    def get_show(self, feedname):
        if feedname not in self.new:
            self.new[feedname] = 0
        if feedname not in self.lasthournew:
            self.lasthournew[feedname] = 0
        if self.new[feedname] == 0:
            st = 'away'
        elif self.new[feedname] < 0:
            st = 'xa'
        elif self.new[feedname] > 0:
            if self.lasthournew[feedname] > 0:
                st = 'chat'
            else:
                st = None
        return st

    def get_status(self, feedname):
        desc = ''
        users = 0
        for feedstr in self.dbfeeds:
            if feedstr[0] == feedname:
                desc = feedstr[4]
                users = feedstr[5]
                if feedname not in self.adaptime:
                    nextin = feedstr[2] + self.last_upd.get(feedname, 0)
                else:
                    nextin = self.adaptime[feedname] + self.last_upd.get(feedname, 0)
        if feedname not in self.new:
            self.new[feedname] = 0
        if feedname not in self.lasthournew:
            self.lasthournew[feedname] = 0
        if feedname not in self.last_upd:
            self.last_upd[feedname] = 0
        tst = self.last_upd[feedname]
        status = (desc + '\nNew messages in last 1h: ' +
                  str(self.lasthournew[feedname]) + ' / 24h: ' +
                  str(self.new[feedname]))
        status += '\nLast updated: ' + time.strftime("%d %b %Y %H:%M:%S",
                                                     time.gmtime(tst)) + ' UTC'
        status += '\nNext in: ' + time.strftime("%d %b %Y %H:%M:%S",
                                                time.gmtime(nextin)) + ' UTC'
        status += '\nUsers: ' + str(users)
        return status

    def presence_control(self, stanza):
        feedname = stanza['to'].node
        fromjid = stanza['from'].bare
        self.dbCurPT.execute("SELECT count(feedname) FROM subscribers "
                             "WHERE jid = %s AND feedname = %s", (fromjid, feedname))
        a = self.dbCurPT.fetchone()
        print("Got " + str(stanza['type']) + " request from " + str(fromjid) +
              " to " + str(feedname) + " with a:" + str(a))
        if stanza['type'] == "subscribe":
            if self.isFeedNameRegistered(feedname) and a[0] == 0:
                try:
                    self.dbCurPT.execute("INSERT INTO subscribers (jid, "
                                         "feedname) VALUES (%s, %s)",
                                         (fromjid, feedname))
                except MySQLIntegrityError:
                    pass
                else:
                    self.dbCurPT.execute("UPDATE feeds SET subscribers = (SELECT "
                                         "count(jid) FROM subscribers WHERE "
                                         "feedname = %s) WHERE feedname = %s",
                                         (feedname, feedname,))
                    self.dbCurPT.commit()
                    self.dbfeeds = self.dbCurPT.dbfeeds()
                self._send(self.Presence(stype="subscribe",
                                         sfrom=stanza['to'],
                                         sto=stanza['from']))
                self._send(self.Presence(stype="subscribed",
                                         sfrom=stanza['to'],
                                         sto=stanza['from']))
                return 1
            elif a[0] == 0:
                self._send(self.Presence(stype="unsubscribed",
                                         sfrom=stanza['to'],
                                         sto=stanza['from']))
                return 1

        if stanza['type'] == "unsubscribe" or stanza['type'] == "unsubscribed":
            if self.isFeedNameRegistered(feedname) and a[0] > 0:
                self.dbCurPT.execute("DELETE FROM subscribers WHERE jid = %s "
                                     "AND feedname = %s", (fromjid, feedname))
                self.dbCurPT.execute("UPDATE feeds SET subscribers = (SELECT "
                                     "count(jid) FROM subscribers WHERE "
                                     "feedname = %s) WHERE feedname = %s",
                                     (feedname, feedname,))
                self.dbCurPT.commit()
                self.dbfeeds = self.dbCurPT.dbfeeds()
                self._send(self.Presence(stype="unsubscribe",
                                         sfrom=stanza['to'],
                                         sto=stanza['from']))
                self._send(self.Presence(stype="unsubscribed",
                                         sfrom=stanza['to'],
                                         sto=stanza['from']))


# ---------------------------------------------------------------------------
# selftest / dryrun / main
# ---------------------------------------------------------------------------


def run_selftest():
    print("== self-test ==")
    loaded = feedparser.parse(SAMPLE_FEED)
    assert loaded['bozo'] == 0, "sample feed should parse cleanly"
    items = loaded['items']
    assert len(items) == 2

    summary = clean_summary(items[0]['summary'])
    assert 'Hello world !' in summary, summary
    assert '<' not in summary and '>' not in summary, summary

    text = format_news_item(items[0], summary,
                            [('user@example.org', None, None, 0, False)])
    assert text[0][1].startswith('*First & Second*'), text

    filtered = format_news_item(items[0], summary,
                                [('user@example.org', 'Nomatch', None, 0, False)])
    assert filtered == [], "positive filter should reject"

    neg = format_news_item(items[0], summary,
                           [('user@example.org', None, 'Second', 0, False)])
    assert neg == [], "negative filter should reject"

    muted = format_news_item(items[0], summary,
                             [('user@example.org', None, None, 0, True)])
    assert muted == [], "muted subscription should not receive news"

    short = format_news_item(items[0], summary,
                             [('user@example.org', None, None, 10, False)])
    assert '...' in short[0][1], short

    assert Transport.strip_utf8mb4('a\U0001f643b') == 'a*b'
    print("OK")


def run_dryrun(feedname=None):
    print("== dry run ==")
    try:
        db = DB()
        feeds = db.dbfeeds()
    except Exception as e:
        print("DB error:", e)
        return
    print("feeds in DB:", len(feeds))
    for f in feeds:
        if feedname is None or f[0] == feedname:
            print("--", f[0], f[1], "timeout:", f[2], "checktype:", f[9])
            try:
                d = feedparser.parse(f[1])
                print("   parsed items:", len(d.get('items', [])))
                print("   bozo:", d['bozo'])
            except Exception as e:
                print("   fetch error:", e)
    db.close()


async def run_transport():
    c = Transport()
    try:
        c.connect()
    except Exception as e:
        print("connect failed:", e)
        return
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("Shutting down")
    finally:
        c._shutdown = True
        if c._updtask:
            c._updtask.cancel()
        try:
            c.disconnect()
        except Exception:
            pass


def main():
    args = sys.argv[1:]
    if '--selftest' in args:
        run_selftest()
        return 0
    if '--dryrun' in args:
        name = None
        try:
            name = args[args.index('--dryrun') + 1]
        except IndexError:
            pass
        run_dryrun(name)
        return 0
    asyncio.run(run_transport())
    return 0


if __name__ == '__main__':
    sys.exit(main())