#!/usr/bin/python -u
# -*- coding: UTF8 -*-
#
# JRSS          Python based Jabber RSS transport.
# Copyright:    2007 Dobrov Sergery aka Binary from JRuDevels. JID: Binary@JRuDevels.org
#               2022 rain from JabberWorld. JID: rain@jabberworld.info
# Licence:      GPL v3
# Requirements:
#               python-pyxmpp - https://github.com/Jajcus/pyxmpp
#               python-feedparser - https://github.com/kurtmckee/feedparser
#               python-mysqldb - https://pypi.python.org/pypi/mysqlclient
#               python-pil and python-lxml (optional) - https://pypi.org/project/Pillow/ and https://lxml.de - if you want to use favicon.ico from site in vCard

import os
import sys
import time
import xml.dom.minidom
import thread
import feedparser
import re
import urlparse
import socket
import MySQLdb

from pyxmpp.jid import JID
from pyxmpp.presence import Presence
from pyxmpp.message import Message

from pyxmpp.jabber.disco import DiscoItem
from pyxmpp.jabber.disco import DiscoItems

import pyxmpp.jabberd.all

programmVersion="1.14.3"

config=os.path.abspath(os.path.dirname(sys.argv[0]))+'/config.xml'

# https://stackoverflow.com/questions/9772691/feedparser-with-timeout
# can't (?) use requests on my system, but with sockets all ok too
socket.setdefaulttimeout(10) # timeout for fetching feeds

dom = xml.dom.minidom.parse(config)

DB_HOST = dom.getElementsByTagName("dbhost")[0].childNodes[0].data
DB_USER = dom.getElementsByTagName("dbuser")[0].childNodes[0].data
DB_NAME = dom.getElementsByTagName("dbname")[0].childNodes[0].data
DB_PASS = dom.getElementsByTagName("dbpass")[0].childNodes[0].data

NAME =  dom.getElementsByTagName("name")[0].childNodes[0].data
HOST =  dom.getElementsByTagName("host")[0].childNodes[0].data
PORT =  dom.getElementsByTagName("port")[0].childNodes[0].data
PASSWORD = dom.getElementsByTagName("password")[0].childNodes[0].data

ADAPTIVE = dom.getElementsByTagName("adaptive")[0].childNodes[0].data
REGALLOW = dom.getElementsByTagName("regallow")[0].childNodes[0].data
ICONLOGO = dom.getElementsByTagName("iconlogo")[0].childNodes[0].data
SENTSIZE = dom.getElementsByTagName("sentsize")[0].childNodes[0].data

if int(ICONLOGO):
    import urllib2
    from PIL import Image
    import io
    import base64
    import lxml.html as lh

admins = []
for a in dom.getElementsByTagName("admin"):
    admins.append(a.childNodes[0].data)

# Based on https://stackoverflow.com/questions/207981/how-to-enable-mysql-client-auto-re-connect-with-mysqldb/982873#982873
# and https://github.com/shinbyh/python-mysqldb-reconnect/blob/master/mysqldb.py
class DB:

    conn = None
    cursor = None

    def connect(self):
        self.conn = MySQLdb.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, database=DB_NAME, autocommit=False, use_unicode=True, charset="utf8mb4")
        self.cursor = self.conn.cursor()

    def execute(self, sql, param=None):
        try:
            if not self.cursor:
                self.connect()
            self.cursor.execute(sql, param)
        except (AttributeError, MySQLdb.OperationalError) as msg:
            print("No connection to database:"),
            print(msg)
            print("DB call from"),
            print(sys._getframe(1).f_code.co_name)
            self.connect()
            self.cursor.execute(sql, param)
        return self.cursor

#    def close(self):
#        if self.cursor:
#            self.cursor.close()
#            self.cursor = None
#            #self.conn.close()

    def dbfeeds(self):
        self.execute("SELECT feedname, url, timeout, regdate, description, subscribers, private, registrar, tags, checktype FROM feeds")
        return self.cursor.fetchall()

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

class Component(pyxmpp.jabberd.Component):
    start_time = int(time.time())
    last_upd = {} # array of last update feeds time
    name = NAME
    updating = 0 # flag to block parallel updates
    idleflag = 0
    times = {} # array of timestamps of new messages
    new = {} # new daily messages counter
    lasthournew = {} # new hourly messages counter
    adaptive = int(ADAPTIVE) # adaptive option: on/off
    regallow = int(REGALLOW) # allowing registrations for non-admins: on/off
    iconlogo = int(ICONLOGO) # use favicon.ico as vcard photo: on/off
    sentsize = int(SENTSIZE) # maximum age for records in news archive
    adaptime = {} # array of feed update time in adaptive mode
    admins = admins
    rsslogo='iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAMAAABEpIrGAAACH1BMVEX3hCL3gyH3hCH2gyH2gh/2gR72gh72gyD4oVf6wpP6vIj5snX4pF33lUL2iSz6u4f+/v7+/Pr+9/L97eD82r36vov4n1P6u4b+/v3////+/f3+8+r817j5rWz2jDD++PT82rz4pmD2hib2giD5snf97d798uj+/Pv+9Oz6xZj3kDj2ii73lD/3mkn5tn37z6j96Nf++vb+/fv827/4nE32hCL2hiX3kjz5r3H82bv+///95tT4o1r2iCv3jDL2iSv2hCP5rGv84cn96tr5tHj84837yqH5s3f3mUn2hyj3kTr6xpr+9/H4m036wY////797+T70a34pV/2hyn5tXv+8un82776wI///v7+9e37zaX3l0X5sHH6xJb6wZD85tL5tXz4qGT70q/83sX97+P6x5v+/fz82Lr2iy/3iy73mUf84Mj++/j97+L3kTv84cr++PP4rGr3jzb98uf85M/3lkL5rW381rX4qmf97d/2hyf4nlH2hif3jjT4qmj4oln5sXP4m0z95dH83MH5sXX6voz3kz796tn84cv5snb3kDn97N73lkP70Kz97N383sT3iy/6u4X++vf5rm75uID+9/D6wI7959T3jzf4nE798un6xZf2gyL++PL70q73jTP948371bP3nE36uoT2ii37yZ785dH2iCn83MD2iS397uD5q2r5uYH2hST4pmH6uYP6uYH5q2n5sXT6uYL4nlKE35UjAAACC0lEQVR42qyRA5cjQRDHr7dqpta2bZuxbZ9t27bNz3rdebGe9p/MTONX3rM7YoyVlboHAJRkBFbMnsorKquqa2qhCMOwrr6+obGpuaW1FokVAtraO4Q6u7p7ehEKeuhIqK9/YHCI5QHDI6ONYwlofGIy10kZTE3PVM/OzS/EicWlZcohVkiWJVxdW99oFMTm1jZAtocdhVKFXFNqzZggtNtZPhjp9M0Go8mMQ2ix2uI+7MgyAUdHh7PB5fZ4Ec0+vyACk0OZQLBDKBSORIlUMUEs7h2EDGBfogv1+wdWSHVAROnypIMwOHjosKthUyBH1CtkPnqMr46foPQ0VYMnT82ePiOIsx7Cc+f54sLFjDwZEOKlysuCuHIV8doFvriuhMxWEA2pbtwUeRhuDZ1o5gv/bUzHGLpzdwoI7o2K9O4jPuDhOitTowd4OPfo8RMvqZ42cCIyiM+eizRTMYamX/ASbC8BX+n5xes3OPiWf99NDyVSRJ8w7Hj/gegjr/DTZxm/8O/X+3ICGPoW78H3H4Q/f/E+//4jDfA6zsSkBIA3/grgnxfo/+YvADIWVrEtkpaUlFgMCwnmJUvlJdOWVSszMi+XkUyTXLGSrXSVgJTENLg32Jes5lzTA0wljGvXrd+wfmMNu/amzRs2b0HkAmCOYFFmBocIKOEwAwWAACyCyHwwBpjJBKGpAgAbEWloKH7cQAAAAABJRU5ErkJggg=='

    dbCurST = DB() # search thread
    dbCurUT = DB() # update thread
    dbCurRT = DB() # register thread
    dbCurPT = DB() # presence thread
    dbCurTT = DB() # talking thread

    dbfeeds = dbCurUT.dbfeeds() # no matter which thread to use
#    dbfeeds = DB.dbfeeds(DB()) # this uses another connection to DB
#    print dbfeeds

    if sentsize < 3:
        sentsize = 3
    elif sentsize > 365:
        sentsize = 365

    def isFeedNameRegistered(self, feedname):
        if any(f[0] == feedname for f in self.dbfeeds):
            return True
        else:
            return False

    def isFeedUrlRegistered(self, furl):
        if any(f[1] == furl for f in self.dbfeeds):
            return True
        else:
            return False

    def connected(self):
        self.orig_stream_idle=self.stream._idle
        self.stream._idle=self.idle

    def authenticated(self):
        pyxmpp.jabberd.Component.authenticated(self)
        self.disco_info.add_feature("http://jabber.org/protocol/disco#info")
        self.disco_info.add_feature("http://jabber.org/protocol/disco#items")
        self.disco_info.add_feature("jabber:iq:version")
        self.disco_info.add_feature("jabber:iq:search")
        self.disco_info.add_feature("jabber:iq:register")
        self.disco_info.add_feature("jabber:iq:last")
        self.disco_info.add_feature("urn:xmpp:ping")
        self.disco_info.add_feature("urn:xmpp:time")
        self.disco_info.add_feature("vcard-temp")
        self.stream.set_iq_get_handler("vCard","vcard-temp",self.get_vCard)
        self.stream.set_iq_get_handler("query","jabber:iq:version",self.get_version)
        self.stream.set_iq_get_handler("query","jabber:iq:search",self.get_search)
        self.stream.set_iq_set_handler("query","jabber:iq:search",self.set_search)
        self.stream.set_iq_get_handler("query","jabber:iq:last",self.get_last)
        self.stream.set_iq_get_handler("ping","urn:xmpp:ping",self.pingpong)
        self.stream.set_iq_get_handler("time","urn:xmpp:time",self.get_time)
        self.stream.set_iq_get_handler("query","jabber:iq:register",self.get_register)
        self.stream.set_iq_set_handler("query","jabber:iq:register",self.set_register)
        self.stream.set_presence_handler("available",self.presence)
        self.stream.set_presence_handler("unavailable",self.presence)
        self.stream.set_presence_handler("subscribe",self.presence_control)
        self.stream.set_presence_handler("subscribed",self.presence_control)
        self.stream.set_presence_handler("unsubscribe",self.presence_control)
        self.stream.set_presence_handler("unsubscribed",self.presence_control)
        self.stream.set_message_handler("normal", self.message)

    def message(self, iq):
        body = iq.get_body()
        if body == None or body == '':
            print("Got no msg")
            return False
        body = body.strip()
        bodyp = body.split()
        fromjid = iq.get_from().bare()
        tojid = iq.get_to().bare()
        feedname = iq.get_to().node
        if not feedname and len(bodyp) > 1 and bodyp[1] == ':':
            print("You should specify correct feed name")
            self.sendmsg(tojid, fromjid, "You should specify correct feed name")
            return False
        if fromjid in self.admins:
            if bodyp[0] == '+' and len(bodyp) > 4 and bodyp[3].isdigit(): # + feedname url interval description [tags]
                fd = feedparser.parse(bodyp[2])
                if bool(urlparse.urlparse(bodyp[2]).netloc) and not any(bodyp[2] in url for url in self.dbfeeds) and not any(bodyp[1] in feed for feed in self.dbfeeds) and (fd["bozo"] == 0 or (fd["bozo"] == 1 and type(fd.bozo_exception).__name__ == 'NonXMLContentType')):
                    fint = bodyp[3]
                    if fint < 60:
                        fint = 60
                    tagmark = body.rfind("SETTAGS:")
                    if tagmark < 0:
                        tagmark = None
                        ftags = ''
                    else:
                        ftags = body[tagmark+8:]
                        ftags = re.sub(' *, *', ',', ftags.strip())
                    fdesc = body[body.rfind(bodyp[4], 0, tagmark):tagmark].strip()
                    self.dbCurTT.execute("INSERT INTO feeds (feedname, url, description, subscribers, timeout, private, registrar, tags) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", (bodyp[1], bodyp[2], fdesc, 0, fint, 0, fromjid, ftags))
                    self.dbCurTT.execute("COMMIT")
                    self.dbfeeds = self.dbCurTT.dbfeeds()
                    self.sendmsg(tojid, fromjid, "Added new feed: "+bodyp[1]+" ("+fdesc+")")
                else:
                    self.sendmsg(tojid, fromjid, "Something wrong with this feed")

            elif bodyp[0] == 'update' and len(bodyp) < 3:
                if len(bodyp) == 2:
                    feedname = bodyp[1]
                if feedname in self.last_upd and feedname != None:
                    print("Forced update for "+feedname)
                    self.last_upd[feedname] = 0 # forced updates allowed only for admins, so 0 is ok
                    self.sendmsg(tojid, fromjid, "Forced update for: "+feedname)
                else:
                    self.sendmsg(tojid, fromjid, "Can't find this feed")
            elif bodyp[0] == 'updateall':
                for a in self.last_upd:
                    print("Forced update for all feeds")
                    self.last_upd[a] = 0
                    self.sendmsg(tojid, fromjid, "Forced update for all feeds")

            elif bodyp[0] == 'showall':
                allfeeds = ''
                for f in self.dbfeeds:
                    if f[8]:
                        tags = " SETTAGS: "+f[8]
                    else:
                        tags = ''
                    allfeeds += "\n+ "+f[0]+" "+f[1]+" "+str(f[2])+" "+f[4]+tags
                self.sendmsg(tojid, fromjid, allfeeds)

            elif bodyp[0] == 'purgelast' and len(bodyp) < 3:
                if len(bodyp) == 2:
                    feedname = bodyp[1]
                if any(feedname in fn for fn in self.dbfeeds) and feedname != None:
                    print("purgelast for "+feedname)
                    self.dbCurTT.execute("DELETE FROM sent WHERE feedname = %s ORDER BY income DESC LIMIT 1", (feedname,))
                    self.dbCurTT.execute("COMMIT")
                    self.sendmsg(tojid, fromjid, "Purged last record for "+feedname)
                else:
                    self.sendmsg(tojid, fromjid, "Can't find this feed")
            elif bodyp[0] == 'purgeall' and len(bodyp) < 3:
                if len(bodyp) == 2:
                    feedname = bodyp[1]
                if any(feedname in fn for fn in self.dbfeeds) and feedname != None:
                    print("purgeall for "+feedname)
                    self.dbCurTT.execute("DELETE FROM sent WHERE feedname = %s", (feedname,))
                    self.dbCurTT.execute("COMMIT")
                    self.sendmsg(tojid, fromjid, "Purged all records for "+feedname)
                else:
                    self.sendmsg(tojid, fromjid, "Can't find this feed")

# available to all users
        if bodyp[0] == 'help' or (bodyp[0] == '?' and len(bodyp) == 1):
            msg =  "List of commands:\n"
            msg += "* help or ? - show available commands\n\n"
            msg += "* settags or =# (NAME or ':') TAG1,TAG2,TAG3... - set new tags for feed NAME (or : for this feed)\n"
            msg += "* setupd or =@ (NAME or ':') SECS - set new update interval for feed NAME (or : for this feed) in SECS\n"
            msg += "* setuniq or =() (NAME or ':') (link | title | content) - set news uniqueness check type for feed NAME (or : for this feed)\n"
            msg += "* setdesc or =: (NAME or ':') New feed description - set new feed description for feed NAME (or : for this feed)\n\n"
            msg += "* showtags or ?# [NAME] - show tags for feed NAME (or this feed)\n"
            msg += "* showupd or ?@ [NAME] - show update interval for feed NAME (or this feed)\n"
            msg += "* showdesc or ?: [NAME] - show description for feed NAME (or this feed)\n"
            msg += "* showuniq or ?() [NAME] - show news uniqueness check type for feed NAME (or this feed)\n"
            msg += "* showadap or ?% [NAME] - show real update time for feed NAME (or this feed)\n"
            msg += "* showmyprivate or ?*** - show my private feeds\n"
            msg += "* showmyfeeds or ?~ - show all feeds where i am registrar\n\n"
            msg += "* setposfilter or =+ (NAME or ':') [EXP] - deliver news for feed NAME (or : for this feed) only with subject matched expression EXP\n"
            msg += "* setnegfilter or =- (NAME or ':') [EXP] - block news for feed NAME (or : for this feed) with subject matched expression EXP\n"
            msg += "* showfilter or ?+- [NAME] - show filters for feed NAME (or this feed)\n\n"
            msg += "* setshort or =... (NAME or ':') [SYMBOLS] - limit maximum message size in feed NAME (or : for this feed).\n"
            msg += "  * Use setshort NAME 1 for 'Title only' mode.\n  * Use setshort NAME 2 for '1st sentence mode'.\n  * Use setshort NAME 3 for '1st paragraph' mode.\n"
            msg += "* showshort or ?... [NAME] - show maximum message size for feed NAME (or this feed)\n\n"
            msg += "* hide or *** [NAME] - make feed NAME (or this feed) private\n"
            msg += "* unhide or +++ [NAME] - make feed NAME (or this feed) public\n\n"
            msg += "* search or ? SOME STRING - search by title, author or content in this feed\n"
            msg += "* searchintag or ?!# TAG SOME STRING - search by title, author or content in TAG\n"
            msg += "* searchtitle or ?!* SOME STRING - search by title in all feeds\n"
            msg += "* searchall or ?! SOME STRING - search by title, author or content in all feeds\n\n"
            msg += "* 1..9 - fetch last N news for this feed\n\n"
            if fromjid in self.admins:
                msg += "* updateall - update all feeds\n"
                msg += "* update [NAME] - update feed NAME (or this feed)\n\n"
                msg += "* purgelast [NAME] - forget about last sent item for feed NAME (or this feed)\n"
                msg += "* purgeall [NAME] - forget about all sent items for feed NAME (or this feed)\n\n"
                msg += "* showall - dump all registered feeds\n\n"
                msg += "* + NAME URL INTERVAL DESCRIPTION [SETTAGS: TAG1,TAG2,TAG3] - add new feed to database"
            self.sendmsg(tojid, fromjid, msg)
        elif (bodyp[0] == 'showmyprivate' or bodyp[0] == '?***'):
            myprivate = ''
            for f in self.dbfeeds:
                if f[7] == fromjid and f[6] == 1:
                    if f[8]:
                        tags = " SETTAGS: "+f[8]
                    else:
                        tags = ''
                    myprivate += '\n+ '+f[0]+' '+f[1]+' '+str(f[2])+' '+f[4]+tags
            self.sendmsg(tojid, fromjid, myprivate)
        elif (bodyp[0] == 'showmyfeeds' or bodyp[0] == '?~'):
            myfeeds = ''
            for f in self.dbfeeds:
                if f[7] == fromjid:
                    if f[8]:
                        tags = " SETTAGS: "+f[8]
                    else:
                        tags = ''
                    myfeeds += '\n+ '+f[0]+' '+f[1]+' '+str(f[2])+' '+f[4]+tags
            self.sendmsg(tojid, fromjid, myfeeds)

        elif (bodyp[0] == 'settags' or bodyp[0] == '=#') and len(bodyp) > 2 and (any(fromjid == f[7] for f in self.dbfeeds) or fromjid in self.admins):
            if bodyp[1] != ':':
                feedname = bodyp[1]
            if any(f[0] == feedname for f in self.dbfeeds):
                newtags = body[body.rfind(bodyp[2]):]
                newtags = re.sub(' *, *', ',', newtags.strip().lower())
                self.dbCurTT.execute("UPDATE feeds SET tags = %s WHERE feedname = %s", (newtags, feedname,))
                self.dbCurTT.execute("COMMIT")
                self.dbfeeds = self.dbCurTT.dbfeeds()
                self.sendmsg(tojid, fromjid, "New tags for "+feedname+": "+newtags)
            else:
                self.sendmsg(tojid, fromjid, "Can't find this feed")
        elif (bodyp[0] == 'setupd' or bodyp[0] == '=@') and len(bodyp) == 3 and (any(fromjid == f[7] for f in self.dbfeeds) or fromjid in self.admins) and bodyp[2].isdigit():
            newupd = int(bodyp[2])
            if newupd < 60:
                newupd = 60
            if bodyp[1] != ':':
                feedname = bodyp[1]
            if any(f[0] == feedname for f in self.dbfeeds):
                self.dbCurTT.execute("UPDATE feeds SET timeout = %s WHERE feedname = %s", (newupd, feedname,))
                self.dbCurTT.execute("COMMIT")
                self.dbfeeds = self.dbCurTT.dbfeeds()
                self.sendmsg(tojid, fromjid, "New update interval for "+feedname+": "+str(newupd)+' seconds')
            else:
                self.sendmsg(tojid, fromjid, "Can't find this feed")
        elif (bodyp[0] == 'setdesc' or bodyp[0] == '=:') and len(bodyp) > 2 and (any(fromjid == f[7] for f in self.dbfeeds) or fromjid in self.admins):
            if bodyp[1] != ':':
                feedname = bodyp[1]
            if any(f[0] == feedname for f in self.dbfeeds):
                newdesc = body[body.rfind(bodyp[2]):].strip()
                self.dbCurTT.execute("UPDATE feeds SET description = %s WHERE feedname = %s", (newdesc, feedname,))
                self.dbCurTT.execute("COMMIT")
                self.dbfeeds = self.dbCurTT.dbfeeds()
                self.sendmsg(tojid, fromjid, "New description for "+feedname+": "+newdesc)
            else:
                self.sendmsg(tojid, fromjid, "Can't find this feed")
        elif (bodyp[0] == 'setuniq' or bodyp[0] == '=()') and len(bodyp) == 3 and (any(fromjid == f[7] for f in self.dbfeeds) or fromjid in self.admins):
            newuniq = str(bodyp[2])
            if newuniq == 'title':
                newuniq = 1
            elif newuniq == 'content':
                newuniq = 2
            else:
                newuniq = 0
            if bodyp[1] != ':':
                feedname = bodyp[1]
            if any(f[0] == feedname for f in self.dbfeeds):
                self.dbCurTT.execute("UPDATE feeds SET checktype = %s WHERE feedname = %s", (newuniq, feedname,))
                self.dbCurTT.execute("COMMIT")
                self.dbfeeds = self.dbCurTT.dbfeeds()
                self.sendmsg(tojid, fromjid, "New news uniqueness check type for "+feedname+": "+bodyp[2])
            else:
                self.sendmsg(tojid, fromjid, "Can't find this feed")

        elif (bodyp[0] == 'showtags' or bodyp[0] == '?#'):
            if len(bodyp) > 1:
                feedname = bodyp[1]
            for i in (f[8] for f in self.dbfeeds if f[0] == feedname):
                self.sendmsg(tojid, fromjid, i)
        elif (bodyp[0] == 'showupd' or bodyp[0] == '?@'):
            if len(bodyp) > 1:
                feedname = bodyp[1]
            for i in (f[2] for f in self.dbfeeds if f[0] == feedname):
                self.sendmsg(tojid, fromjid, 'Feed update interval: '+str(i)+' seconds')
        elif (bodyp[0] == 'showdesc' or bodyp[0] == '?:'):
            if len(bodyp) > 1:
                feedname = bodyp[1]
            for i in (f[4] for f in self.dbfeeds if f[0] == feedname):
                self.sendmsg(tojid, fromjid, i)
        elif (bodyp[0] == 'showadap' or bodyp[0] == '?%'):
            if len(bodyp) > 1:
                feedname = bodyp[1]
            if feedname in self.adaptime:
                self.sendmsg(tojid, fromjid, 'Feed real update interval: '+str(self.adaptime[feedname])+' seconds')
        elif (bodyp[0] == 'showuniq' or bodyp[0] == '?()'):
            if len(bodyp) > 1:
                feedname = bodyp[1]
            for i in (f[9] for f in self.dbfeeds if f[0] == feedname):
                if i == 1:
                    myuniq = 'title'
                elif i == 2:
                    myuniq = 'content'
                else:
                    myuniq = 'link'
                self.sendmsg(tojid, fromjid, 'News uniqueness check type: '+myuniq)

        elif (bodyp[0] == 'setposfilter' or bodyp[0] == 'setnegfilter' or bodyp[0] == '=+' or bodyp[0] == '=-') and len(bodyp) > 1:
            if bodyp[1] != ':':
                feedname = bodyp[1]
            if len(bodyp) > 2:
                myfilter = body[body.rfind(bodyp[2]):].strip()
                if len(myfilter) < 255:
                    print("New filter: "+myfilter)
                    if (bodyp[0] == 'setposfilter' or bodyp[0] == '=+'):
                        self.dbCurTT.execute("UPDATE subscribers SET posfilter = %s WHERE feedname = %s AND jid = %s", (myfilter, feedname, fromjid,))
                        self.sendmsg(tojid, fromjid, "New positive filter for "+feedname+": "+myfilter)
                    else:
                        self.dbCurTT.execute("UPDATE subscribers SET negfilter = %s WHERE feedname = %s AND jid = %s", (myfilter, feedname, fromjid,))
                        self.sendmsg(tojid, fromjid, "New negative filter for "+feedname+": "+myfilter)
                else:
                    print("Filter too long")
                    self.sendmsg(tojid, fromjid, "Filter too long")
            else:
                print("No filter")
                if (bodyp[0] == 'setposfilter' or bodyp[0] == '=+'):
                    self.dbCurTT.execute("UPDATE subscribers SET posfilter = NULL WHERE feedname = %s AND jid = %s", (feedname, fromjid,))
                    self.sendmsg(tojid, fromjid, "Positive filter for "+feedname+" cleared")
                else:
                    self.dbCurTT.execute("UPDATE subscribers SET negfilter = NULL WHERE feedname = %s AND jid = %s", (feedname, fromjid,))
                    self.sendmsg(tojid, fromjid, "Negative filter for "+feedname+" cleared")
            self.dbCurTT.execute("COMMIT")
        elif (bodyp[0] == 'showfilter' or bodyp[0] == '?+-') and len(bodyp) < 3:
            if len(bodyp) == 2:
                feedname = bodyp[1]
            self.dbCurTT.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            self.dbCurTT.execute("SELECT posfilter, negfilter FROM subscribers WHERE feedname = %s AND jid = %s", (feedname, fromjid,))
            myfilter = self.dbCurTT.fetchone()
            if myfilter[0]:
                posfilter = myfilter[0]
            else:
                posfilter = ''
            if myfilter[1]:
                negfilter = myfilter[1]
            else:
                negfilter = ''
            self.sendmsg(tojid, fromjid, "Filters for "+feedname+":\nPositive (include): "+posfilter+"\nNegative (exclude): "+negfilter)

        elif (bodyp[0] == 'setshort' or bodyp[0] == '=...') and len(bodyp) > 1:
            if bodyp[1] != ':':
                feedname = bodyp[1]
            if len(bodyp) == 3 and bodyp[2].isdigit():
                self.dbCurTT.execute("UPDATE subscribers SET short = %s WHERE feedname = %s AND jid = %s", (bodyp[2], feedname, fromjid,))
                msg = str(bodyp[2])
                if msg == '0':
                    msg = 'unlimited'
                elif msg == '1':
                    msg = 'title only'
                elif msg == '2':
                    msg = '1st sentence'
                elif msg == '3':
                    msg = '1st paragraph'
                self.sendmsg(tojid, fromjid, "Maximum size for "+feedname+" set to "+msg)
            elif len(bodyp) == 2:
                self.dbCurTT.execute("UPDATE subscribers SET short = 0 WHERE feedname = %s AND jid = %s", (feedname, fromjid,))
                self.sendmsg(tojid, fromjid, "Maximum size for "+feedname+" set to unlimited")
            self.dbCurTT.execute("COMMIT")
        elif (bodyp[0] == 'showshort' or bodyp[0] == '?...'):
            if len(bodyp) > 1:
                feedname = bodyp[1]
            self.dbCurTT.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            self.dbCurTT.execute("SELECT short FROM subscribers WHERE feedname = %s AND jid = %s", (feedname, fromjid,))
            myshort = self.dbCurTT.fetchone()
            if myshort:
                msg = str(myshort[0])
                if msg == '0':
                    msg = 'Unlimited'
                elif msg == '1':
                    msg = 'Title only'
                elif msg == '2':
                    msg = 'Only 1st sentence'
                elif msg == '3':
                    msg = 'Only 1st paragraph'
                self.sendmsg(tojid, fromjid, msg)

        elif (bodyp[0] == 'hide' or bodyp[0] == '***') and len(bodyp) < 3:
            if len(bodyp) == 2:
                feedname = bodyp[1]
            if any((fromjid == f[7] or fromjid in self.admins) and f[0] == feedname for f in self.dbfeeds) and feedname != None:
                self.dbCurTT.execute("UPDATE feeds SET private = 1 WHERE feedname = %s AND registrar = %s", (feedname, fromjid,))
                self.dbCurTT.execute("COMMIT")
                self.dbfeeds = self.dbCurTT.dbfeeds()
                self.sendmsg(tojid, fromjid, "Feed "+feedname+" is now hidden from search")
            else:
                self.sendmsg(tojid, fromjid, "Can't find this feed or you are not owner")
        elif (bodyp[0] == 'unhide' or bodyp[0] == '+++') and len(bodyp) < 3:
            if len(bodyp) == 2:
                feedname = bodyp[1]
            if any((fromjid == f[7] or fromjid in self.admins) and f[0] == feedname for f in self.dbfeeds) and feedname != None:
                self.dbCurTT.execute("UPDATE feeds SET private = 0 WHERE feedname = %s AND registrar = %s", (feedname, fromjid,))
                self.dbCurTT.execute("COMMIT")
                self.dbfeeds = self.dbCurTT.dbfeeds()
                self.sendmsg(tojid, fromjid, "Feed "+feedname+" is now visible in search")
            else:
                self.sendmsg(tojid, fromjid, "Can't find this feed or you are not owner")

        elif len(bodyp) == 1 and feedname != None and bodyp[0].isdigit() and 21 > int(bodyp[0]) > 0:
            self.dbCurTT.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            self.dbCurTT.execute("SELECT title, author, link, content FROM sent WHERE feedname = %s AND link IS NOT NULL GROUP BY link ORDER BY income DESC LIMIT %s", (feedname, int(bodyp[0])))
            news = self.dbCurTT.fetchall()
            self.dbCurTT.execute("SELECT jid, posfilter, negfilter, short FROM subscribers WHERE feedname = %s AND jid = %s", (feedname, fromjid))
            jids = self.dbCurTT.fetchall()
            for msg in reversed(news):
                self.sendItem(feedname, {'title': msg[0], 'author': msg[1], 'link': msg[2], 'summary': msg[3]}, jids)

        elif (bodyp[0] == 'search' or bodyp[0] == '?') and len(bodyp) > 1 and feedname != None:
            searchstr = '%'+body[len(bodyp[0])+1:]+'%'
            self.dbCurTT.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            self.dbCurTT.execute("SELECT title, author, link, DATE_FORMAT(income, '%%Y-%%m-%%d %%H:%%i') FROM sent WHERE feedname = %s AND (author LIKE %s OR title LIKE %s OR content LIKE %s) AND link IS NOT NULL ORDER BY income ASC LIMIT 10", (feedname, searchstr, searchstr, searchstr))
            self.printsearch(self.dbCurTT.fetchall(), tojid, fromjid, None, feedname)
        elif (bodyp[0] == 'searchall' or bodyp[0] == '?!') and len(bodyp) > 1:
            searchstr = '%'+body[len(bodyp[0])+1:]+'%'
            self.dbCurTT.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            self.dbCurTT.execute("SELECT title, author, link, DATE_FORMAT(income, '%%Y-%%m-%%d %%H:%%i'), feedname FROM sent WHERE (author LIKE %s OR title LIKE %s OR content LIKE %s) AND link IS NOT NULL ORDER BY income ASC LIMIT 10", (searchstr, searchstr, searchstr))
            self.printsearch(self.dbCurTT.fetchall(), tojid, fromjid, True, None)
        elif (bodyp[0] == 'searchintag' or bodyp[0] == '?!#') and len(bodyp) > 2:
            searchstr = '%'+body[body.rfind(bodyp[2]):]+'%'
            searchtag = '%'+bodyp[1]+'%'
            self.dbCurTT.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            self.dbCurTT.execute("SELECT title, author, link, DATE_FORMAT(income, '%%Y-%%m-%%d %%H:%%i'), sent.feedname FROM sent INNER JOIN feeds ON sent.feedname = feeds.feedname WHERE (author LIKE %s OR title LIKE %s OR content LIKE %s) AND link IS NOT NULL AND feeds.tags LIKE %s GROUP BY link ORDER BY income ASC LIMIT 10", (searchstr, searchstr, searchstr, searchtag))
            self.printsearch(self.dbCurTT.fetchall(), tojid, fromjid, True, None)
        elif (bodyp[0] == 'searchtitle' or bodyp[0] == '?!*') and len(bodyp) > 1:
            searchstr = '%'+body[len(bodyp[0])+1:]+'%'
            self.dbCurTT.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            self.dbCurTT.execute("SELECT title, author, link, DATE_FORMAT(income, '%%Y-%%m-%%d %%H:%%i'), feedname FROM sent WHERE title LIKE %s AND link IS NOT NULL ORDER BY income ASC LIMIT 10", (searchstr, ))
            self.printsearch(self.dbCurTT.fetchall(), tojid, fromjid, True, None)

    def printsearch(self, data, tojid, fromjid, inall = None, feedname = None):
        if len(data) > 0:
            msg = 'Found '
            msg += str(len(data))+' results'
            if not inall:
                msg += ' in '+feedname
            msg += ':\n'
            for article in data:
                if article[0] != None:
                    msg += article[0]
                else:
                    msg += 'No title'
                if article[1] != None:
                    msg += ' (by '+article[1]+')'
                msg += ' @ '+str(article[3])
                if inall:
                    msg += ' in '+article[4]
                msg += ': '+article[2]+'\n\n'
            self.sendmsg(tojid, fromjid, msg)
        else:
            self.sendmsg(tojid, fromjid, 'Nothing found')

    def sendmsg(self, fromjid, tojid, msg):
        m = Message(to_jid = tojid, from_jid = fromjid, stanza_type='chat', body = msg)
        self.stream.send(m)

    def mknode(self, disco_items, name, desc):
        desc = name+" ("+desc+")"
        newjid = JID(name, self.name)
        item = DiscoItem(disco_items, newjid, name=desc, node=None)

    def browseitems(self, iq=None, node=None):
        disco_items=DiscoItems()
        fromjid = iq.get_from().bare()
        feedtags = {}
        for i in self.dbfeeds:
            if i[8]:
                tags = i[8].split(',')
                for tag in tags:
                    tag = tag.lower()
                    if tag not in feedtags:
                        feedtags[tag] = list()
                    feedtags[tag].append((i[0], i[4], i[6], i[7]))
        if node == None and iq.get_to().node == None:
            newjid = JID(domain=self.name)
            item = DiscoItem(disco_items, newjid, name="Registered Feeds",  node="feeds")
            item = DiscoItem(disco_items, newjid, name="I am registrar",    node="owner")
            item = DiscoItem(disco_items, newjid, name="My private feeds",  node="private")
            item = DiscoItem(disco_items, newjid, name="Categories",        node="tags")
        if node=="feeds":
            for i in self.dbfeeds:
                if not i[6] or (i[6] == 1 and fromjid == i[7]):
                    self.mknode(disco_items, i[0], i[4])
        elif node=="owner":
            for i in self.dbfeeds:
                if fromjid == i[7]:
                    self.mknode(disco_items, i[0], i[4])
        elif node=="private":
            for i in self.dbfeeds:
                if i[6] == 1 and fromjid == i[7]:
                    self.mknode(disco_items, i[0], i[4])
        elif node=="tags":
            for tag in sorted(feedtags):
                name = tag.replace(' ','')
                desc = tag.capitalize()
                newjid = JID(domain=self.name)
                item = DiscoItem(disco_items, newjid, name=desc, node="tag:"+name)
        else:
            for tag in feedtags:
                if node == 'tag:'+tag.replace(' ',''):
                    for feed in feedtags[tag]:
                        if not feed[2] or (feed[2] == 1 and fromjid == feed[3]):
                            self.mknode(disco_items, feed[0], feed[1])
        return disco_items

    def disco_get_items(self, node, iq):
        return self.browseitems(iq, node)

    def pingpong(self, iq):
        iq = iq.make_result_response()
        self.stream.send(iq)
        return 1

    def get_time(self, iq):
        iq = iq.make_result_response()
        q = iq.xmlnode.newChild(None, "time", None)
        q.setProp("xmlns", "urn:xmpp:time")
 #       q = iq.new_query("urn:xmpp:time")
        q.newTextChild(q.ns(), "tzo", "+02:00")
        q.newTextChild(q.ns(), "utc", time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        self.stream.send(iq)
        return 1

    def get_last(self, iq):
        iq = iq.make_result_response()
        q = iq.new_query("jabber:iq:last")
        if iq.get_from() == self.name:
            q.setProp("seconds", str(int(time.time()) - self.start_time))
        else:
            if iq.get_from().node in self.last_upd:
                q.setProp("seconds", str(int(time.time() - self.last_upd[iq.get_from().node])))
            else:
                return 0
        self.stream.send(iq)
        return 1

    def get_register(self,iq):
        if iq.get_to() != self.name:
            self.stream.send(iq.make_error_response("feature-not-implemented"))
            return
        if not self.regallow and iq.get_from().bare() not in self.admins:
            self.stream.send(iq.make_error_response("not-acceptable"))
            return
        iq=iq.make_result_response()
        q=iq.new_query("jabber:iq:register")
        form=q.newChild(None,"x",None)
        form.setProp("xmlns","jabber:x:data")
        form.setProp("type","form")
        form.newTextChild(None,"title","New RSS feed registration")

        fname=form.newChild(None,"field",None)
        fname.setProp("type","text-single")
        fname.setProp("var","feedname")
        fname.setProp("label","Feed's name")
        fname.newChild(None,"required",None)

        url=form.newChild(None,"field",None)
        url.setProp("type","text-single")
        url.setProp("var","url")
        url.setProp("label","URL")
        url.newChild(None,"required",None)

        desc=form.newChild(None,"field",None)
        desc.setProp("type","text-single")
        desc.setProp("var","desc")
        desc.setProp("label","Description")
        desc.newChild(None,"required",None)

        tags=form.newChild(None,"field",None)
        tags.setProp("type","text-single")
        tags.setProp("var","tags")
        tags.setProp("label","Tags (comma separated)")

        checkBox=form.newChild(None,"field",None)
        checkBox.setProp("type","boolean")
        checkBox.setProp("var","tosubscribe")
        checkBox.setProp("label","Subscribe")
        value=checkBox.newTextChild(None,"value","1")

        checkBox=form.newChild(None,"field",None)
        checkBox.setProp("type","boolean")
        checkBox.setProp("var","private")
        checkBox.setProp("label","Private")
        value=checkBox.newTextChild(None,"value","0")

# https://xmpp.org/extensions/xep-0004.html
        tmup=form.newChild(None, "field", None)
        tmup.setProp("type", "list-single")
        tmup.setProp("var", "timeout")
        tmup.setProp("label", "Refresh interval, min")
        tmup.newChild(None, "value", "60")
        for t in ['1', '2', '5', '10', '15', '30', '60', '120', '240', '300', '600', '900', '1440']:
            topt=tmup.newChild(None, "option", None)
            topt.setProp("label", t)
            topt.newChild(None, "value", t)

        ctyp = form.newChild(None, "field", None)
        ctyp.setProp("type", "list-single")
        ctyp.setProp("var", "checktype")
        ctyp.setProp("label", "News uniqueness")
        ctyp.newChild(None, "value", "By link only")
        for t in ['By link only', 'By link + title', 'By link + title + content']:
            ctopt = ctyp.newChild(None, "option", None)
            ctopt.setProp("label", t)
            ctopt.newChild(None, "value", t)

        self.stream.send(iq)

    def set_register(self,iq):
        if iq.get_to() != self.name:
            self.stream.send(iq.make_error_response("feature-not-implemented"))
            return

        fname = iq.xpath_eval("//r:field[@var='feedname']/r:value",{"r":"jabber:x:data"})
        furl = iq.xpath_eval("//r:field[@var='url']/r:value",{"r":"jabber:x:data"})
        fdesc = iq.xpath_eval("//r:field[@var='desc']/r:value",{"r":"jabber:x:data"})
        fsubs = iq.xpath_eval("//r:field[@var='tosubscribe']/r:value",{"r":"jabber:x:data"})
        fpriv = iq.xpath_eval("//r:field[@var='private']/r:value",{"r":"jabber:x:data"})
        ftime = iq.xpath_eval("//r:field[@var='timeout']/r:value",{"r":"jabber:x:data"})
        ftags = iq.xpath_eval("//r:field[@var='tags']/r:value",{"r":"jabber:x:data"})
        ctype = iq.xpath_eval("//r:field[@var='checktype']/r:value",{"r":"jabber:x:data"})
        if fname and furl and fdesc:
            fname=fname[0].getContent().lower()
            furl=furl[0].getContent()
            fdesc=fdesc[0].getContent()
        else:
            self.stream.send(iq.make_error_response("not-acceptable"))
            return
        if fname=='' or furl=='' or fdesc=='' or fname.find(':')!=-1 or fname.find('&')!=-1 or fname.find('>')!=-1 or fname.find('<')!=-1 or fname.find("@")!=-1 or fname.find(" ")!=-1 or fname.find("'")!=-1 or fname.find("/")!=-1 or fname.find('"')!=-1 or fname.find("\\")!=-1 or (furl.find("http://")!=0 and furl.find("https://")!=0):
            self.stream.send(iq.make_error_response("not-acceptable"))
            return
        domain=urlparse.urlparse(furl)[1]
        furl=furl.replace("//%s/" % domain,"//%s/" % domain.lower())
        if fsubs:
            fsubs=fsubs[0].getContent()
            if fsubs=="1":
                fsubs=True
            else:
                fsubs=False
        else:
            fsubs=False
        if ftime:
            ftime = int(ftime[0].getContent())
        if ctype:
            ctype = str(ctype[0].getContent())
        if fpriv:
            fpriv = int(fpriv[0].getContent())
        if ftags:
            ftags = ftags[0].getContent().lower()
            ftags = re.sub(' *, *', ',', ftags.strip())
            if len(ftags) > 255:
                self.stream.send(iq.make_error_response("not-acceptable"))
                return
        if self.isFeedNameRegistered(fname) or self.isFeedUrlRegistered(furl):
            self.stream.send(iq.make_error_response("conflict"))
            return
        thread.start_new_thread(self.regThread,(iq.make_result_response(),iq.make_error_response("not-acceptable"),fname,furl,fdesc,fsubs,ftime,fpriv,ftags,ctype,))

    def regThread(self, iqres, iqerr, fname, furl, fdesc, fsubs, ftime, fpriv, ftags, ctype):
        try:
            d=feedparser.parse(furl)
            bozo=d["bozo"]
        except:
            self.stream.send(iqerr)
            return
        if bozo==1:
            self.stream.send(iqerr)
            return
        vsubs=0
        if fsubs:
            vsubs=1
        ftime=ftime*60
        if ftime<60:
            ftime=60
        if ctype == 'By link + title':
            ctype = 1
        elif ctype == 'By link + title + content':
            ctype = 2
        else:
            ctype = 0
        registrar = iqres.get_to().bare()
        self.dbCurRT.execute("INSERT INTO feeds (feedname, url, description, subscribers, timeout, private, registrar, tags, checktype) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", (fname, furl, fdesc, vsubs, ftime, fpriv, registrar, ftags, ctype))
        self.last_upd[fname] = 0
        self.dbfeeds = self.dbCurRT.dbfeeds()
        self.dbCurRT.execute("COMMIT")
        self.stream.send(iqres)
        if fsubs:
            pres = Presence(stanza_type="subscribe", from_jid=JID(unicode(fname, 'utf-8') + '@' + self.name), to_jid=iqres.get_to().bare())
            self.stream.send(pres)

    def getlogo(self, url):
        if self.iconlogo:
            url = urlparse.urlparse(url)[0]+"://"+urlparse.urlparse(url)[1]

            def makerq(url):
                rq = urllib2.Request(url, headers={'User-agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:52.0) Gecko/20100101 Firefox/52.0'})
                try:
                    return urllib2.urlopen(rq, timeout=5)
                except Exception as msg:
                    raise Exception(msg)

            try:
                ico = makerq(url+'/favicon.ico')
            except:
                try:
                    doc = lh.parse(makerq(url))
                    data = doc.xpath('//link[contains(@rel, "icon")]/@href')
                    if len(data):
                        ico = data[0]
                    else:
                        ico = ''
                except Exception as msg:
                    print("Can't find ico: "),
                    print(msg)
                    ico = ''

                if ico != '':
                    if ico.find("http")!=0:
                        if ico.startswith('//'):
                            ico = urlparse.urlparse(url)[0]+':'+ico
                        elif ico.startswith('/'):
                            ico = url+ico
                        else:
                            ico = url+'/'+ico

                    ico = makerq(ico) # may be in some cases i should use try/except here
            if ico != '':
                try:
                    png = Image.open(ico)
                    imgtmp = io.BytesIO()
                    png.save(imgtmp, format="PNG")
                    return base64.b64encode(imgtmp.getvalue())
                except:
                    return self.rsslogo
            else:
                return self.rsslogo

    def get_vCard(self,iq):

        iqmr=iq.make_result_response()
        q=iqmr.xmlnode.newChild(None,"vCard",None)
        q.setProp("xmlns","vcard-temp")

        if iq.get_to() == self.name:
            q.newTextChild(None,"FN","JRD RSS Transport")
            q.newTextChild(None,"NICKNAME","RSS")
            q.newTextChild(None,"DESC","RSS transport component")
            q.newTextChild(None,"BDAY","2008-03-19")
            q.newTextChild(None,"ROLE","Создаю ботов для получения новостей через RSS")
            q.newTextChild(None,"URL","https://github.com/jabberworld/jrd_rss")
            transav=q.newTextChild(None,"PHOTO", None)
            transav.newTextChild(None, "BINVAL", self.rsslogo)
            transav.newTextChild(None, "TYPE", 'image/png')
        else:
            nick = iqmr.get_from().node
            for feedstr in self.dbfeeds:
                if feedstr[0] == nick:
                    url = feedstr[1]
                    bday = feedstr[3]
                    if self.adaptive and nick in self.adaptime and self.adaptime[nick] != feedstr[2]:
                        real = "(adaptive: " + str(int(self.adaptime[nick]/60)) + "mins)"
                    else:
                        real = ''
                    tags = ''
                    if feedstr[8]:
                        for tag in feedstr[8].replace(',', ', ').split():
                            tags += tag.capitalize().replace(',', ', ')
                    description = feedstr[4] + '\nTags: ' + tags + '\nFeed update interval: '+str(feedstr[2]/60) + ' mins ' + real + '\nFeed subscribers: '+str(feedstr[5])
# Tried to use favicon.ico from site as EXTVAL in PHOTO, but no luck - no support for EXTVAL in clients (tried Psi, Gajim, Conversations)
#                    favicon=urlparse.urlparse(url)[0]+"://"+urlparse.urlparse(url)[1]+"/favicon.ico"

                    q.newTextChild(None,"NICKNAME", nick.encode('utf-8'))
                    q.newTextChild(None,"DESC", description.encode('utf-8'))
                    q.newTextChild(None,"URL", url.encode('utf-8'))
                    q.newTextChild(None,"BDAY", str(bday))
                    feedav=q.newTextChild(None,"PHOTO", None)
                    feedav.newTextChild(None, "BINVAL", self.getlogo(url))
                    feedav.newTextChild(None, "TYPE", 'image/png')
        self.stream.send(iqmr)
        return 1

    def get_search(self,iq):
        iq=iq.make_result_response()
        q=iq.xmlnode.newChild(None,"query",None)
        q.setProp("xmlns","jabber:iq:search")
        q.newTextChild(None,"instructions","Enter a keyword")
        form=q.newChild(None,"x",None)
        form.setProp("xmlns","jabber:x:data")
        form.setProp("type","form")
        formType=form.newChild(None,"field",None)
        formType.setProp("type","hidden")
        formType.setProp("var","FORM_TYPE")
        formType.newTextChild(None,"value","jabber:iq:search")
        text=form.newChild(None,"field",None)
        text.setProp("type","text-single")
        text.setProp("label","Search")
        text.setProp("var","searchField")
        self.stream.send(iq)
        return 1

    def set_search(self, iq):
        fromjid = iq.get_from().bare()
        searchField=iq.xpath_eval("//r:field[@var='searchField']/r:value",{"r":"jabber:x:data"})
        if searchField:
            searchField='%'+searchField[0].getContent().replace("%","\\%")+'%'
        else:
            return
        if searchField=='%%' or len(searchField)<5:
            self.stream.send(iq.make_error_response("not-acceptable"))
            return
        self.dbCurST.execute("COMMIT")
        self.dbCurST.execute("SELECT feedname, description, url, subscribers, timeout FROM feeds WHERE (feedname LIKE %s OR description LIKE %s OR url LIKE %s OR tags LIKE %s) AND (private = '0' OR (private = '1' AND registrar = %s))", (searchField, searchField, searchField, searchField, fromjid))
        a=self.dbCurST.fetchall()

        print (a)

        iq=iq.make_result_response()
        q=iq.new_query("jabber:iq:search")

        form=q.newChild(None,"x",None)
        form.setProp("xmlns","jabber:x:data")
        form.setProp("type","result")

        formType=form.newChild(None,"field",None)
        formType.setProp("type","hidden")
        formType.setProp("var","FORM_TYPE")
        formType.newTextChild(None,"value","jabber:iq:search")

        reported=form.newChild(None,"reported",None)
        reportedJid=reported.newChild(None,"field",None)
        reportedJid.setProp("var","jid")
        reportedJid.setProp("label","JID")
        reportedJid.setProp("type","jid-single")

        reportedUrl=reported.newChild(None,"field",None)
        reportedUrl.setProp("var","url")
        reportedUrl.setProp("label","URL")
        reportedUrl.setProp("type","text-single")

        reportedDesc=reported.newChild(None,"field",None)
        reportedDesc.setProp("var","desc")
        reportedDesc.setProp("label","Description")
        reportedDesc.setProp("type","text-single")

        reportedSubs=reported.newChild(None,"field",None)
        reportedSubs.setProp("var","subscribers")
        reportedSubs.setProp("type","text-single")
        reportedSubs.setProp("label","Users")

        reportedTime=reported.newChild(None,"field",None)
        reportedTime.setProp("var","timeout")
        reportedTime.setProp("type","text-single")
        reportedTime.setProp("label","Update interval")

        for d in a:
            item=form.newChild(None, "item", None)
            jidField=item.newChild(None, "field", None)
            jidField.setProp("var", "jid")
            jiddata = d[0]+"@"+self.name
            jidField.newTextChild(None, "value", jiddata.encode('utf-8'))

            urlField=item.newChild(None, "field", None)
            urlField.setProp("var", "url")
            urlField.newTextChild(None, "value", d[2].encode('utf-8'))

            descField=item.newChild(None, "field", None)
            descField.setProp("var", "desc")
            descField.newTextChild(None, "value", d[1].encode('utf-8'))

            sbsField=item.newChild(None, "field", None)
            sbsField.setProp("var", "subscribers")
            sbsField.newTextChild(None, "value", unicode(str(d[3]), 'utf-8'))

            timeField=item.newChild(None, "field", None)
            timeField.setProp("var", "timeout")
            timeField.newTextChild(None, "value", unicode(str(d[4]/60), 'utf-8'))

        self.stream.send(iq)
        return 1

    def get_version(self,iq):
        global programmVersion
        iq=iq.make_result_response()
        q=iq.new_query("jabber:iq:version")
        q.newTextChild(q.ns(), "name", "Jabber RSS Transport")
        q.newTextChild(q.ns(), "version", programmVersion)
        q.newTextChild(q.ns(), "os", "Python "+sys.version.split()[0]+" + PyXMPP")
        self.stream.send(iq)
        return 1

    def disco_get_info(self,node,iq):
        return self.disco_info

    def idle(self):
        nowTime = int(time.time())
        if not self.idleflag:
            print("idle")
            self.idleflag=1
        checkfeeds=[]
        if not self.updating:
            for feed in self.dbfeeds:
                if feed[0] not in self.adaptime:
                    checkfeeds.append((feed[0], feed[1], feed[2], feed[9],)) # update all feeds at startup time
                    self.adaptime[feed[0]] = feed[2] # set update times to its defined values. This will be redefined after checkrss() (or not)
                try:
                    if (nowTime-int(self.last_upd[feed[0]])) > self.adaptime[feed[0]]:
                        self.last_upd[feed[0]] = nowTime
                        checkfeeds.append((feed[0], feed[1], feed[2], feed[9],))
                except:
                    self.last_upd[feed[0]]=nowTime
            if checkfeeds:
                self.idleflag=0
                print("UPDATE:"),
                print(checkfeeds)
                thread.start_new_thread(self.checkrss,(checkfeeds,))
                self.updating=1
        else:
            print("Update in progress")

    def strip_utf8mb4(self, mb4):
        return ''.join([c if len(c.encode('utf-8')) < 4 else '*' for c in mb4])

    def checkrss(self, checkfeeds):
        for feed in checkfeeds:
            feedname = feed[0]

            if feedname not in self.times:
                self.times[feedname] = list()

            self.new[feedname] = 0
            self.lasthournew[feedname] = 0

            self.dbCurUT.execute("COMMIT")
            self.dbCurUT.execute("SELECT jid, posfilter, negfilter, short FROM subscribers WHERE feedname = %s", (feedname,))
            jids=self.dbCurUT.fetchall()

            if len(jids)==0:
                continue
            try:
                print("FETCHING"),
                print(feed[1])
                d = feedparser.parse(feed[1])
                bozo = d["bozo"]
            except:
                continue
            if bozo == 1:
                if type(d.bozo_exception).__name__ != 'NonXMLContentType':
                    print("Some problems with feed")
                    self.new[feedname] = -1
                    self.botstatus(feedname, jids[0]) # Send XA status if problems with feed
                    continue
                else:
                    print('Bozo flag: NonXMLContentType in '+feedname)
            for i in reversed(d["items"]):
                flink = ftitle = fauthor = fsum = None
                if 'link' in i:
                    flink = i["link"][:254]
                if 'title' in i:
                    ftitle = self.strip_utf8mb4(i["title"][:254]) # removing utf8mb4 for python-mysqldb
                if 'author' in i:
                    fauthor = self.strip_utf8mb4(i["author"][:126])
                if 'summary' in i:
                    fsum = self.strip_utf8mb4(i["summary"][:8190])

                if feed[3] == 1:
                    checkdata = flink+ftitle
                elif feed[3] == 2:
                    checkdata = flink+ftitle+fsum
                else:
                    checkdata = flink
                if not self.isSent(feedname, checkdata, feed[3]):
                    self.sendItem(feedname, i, jids)
                    self.times[feedname].append(time.time())
                    self.dbCurUT.execute("INSERT INTO sent (feedname, title, author, link, content) VALUES (%s, %s, %s, %s, %s)", (feedname, ftitle, fauthor, flink, fsum))
                    time.sleep(0.2)
                else:
                    self.dbCurUT.execute("UPDATE sent SET datetime = NOW() WHERE feedname = %s AND link = %s AND title = %s AND datetime < NOW() - INTERVAL %s DAY", (feedname, flink, ftitle, self.sentsize-1))

            for ft in self.times[feedname]:
                if ft > time.time() - 86400:
                    self.new[feedname] += 1
                    if ft > time.time() - 3600:
                        self.lasthournew[feedname] += 1
                else:
                    self.times[feedname].remove(ft)

            if self.adaptive and self.lasthournew[feedname] > 0:
                self.adaptime[feedname] = int(3600/self.lasthournew[feedname])
                if self.adaptime[feedname] < 60:
                    self.adaptime[feedname] = 60
                elif self.adaptime[feedname] > feed[2]:
                    self.adaptime[feedname] = int(feed[2])
            else:
                self.adaptime[feedname] = int(feed[2])

            print("End of update")
            self.botstatus(feedname, jids[0])
# purging old records
        self.dbCurUT.execute("DELETE FROM sent WHERE datetime < NOW() - INTERVAL %s DAY", (self.sentsize,))
        self.dbCurUT.execute("COMMIT")
        print("End of checkrss")
        self.updating = 0

    def isSent(self, feedname, checkdata, checktype):
        if checktype == 1:
            self.dbCurUT.execute("SELECT count(feedname) FROM sent WHERE feedname = %s AND CONCAT(link, title) = %s", (feedname, checkdata))
        elif checktype == 2:
            self.dbCurUT.execute("SELECT count(feedname) FROM sent WHERE feedname = %s AND CONCAT(link, title, content) = %s", (feedname, checkdata))
        else:
            self.dbCurUT.execute("SELECT count(feedname) FROM sent WHERE feedname = %s AND link = %s", (feedname, checkdata))
        a = self.dbCurUT.fetchone()
        if a[0]>0:
            return True
        return False

    def botstatus(self, feedname, jid):
        p=Presence(from_jid=feedname + '@' + self.name + "/rss",
            to_jid=JID(jid[0]),
            show = self.get_show(feedname),
            status = self.get_status(feedname))
        self.stream.send(p)

    def sendItem(self, feedname, i, jids):
        if 'summary' not in i or i['summary'] == None:
            summary = "\n\nNo description"
        else:
            summary = i["summary"].encode('utf-8')
            summary = re.sub('<br ??/??>','\n',summary)
            summary = re.sub('<blockquote[^>]*>\n?', '> «', summary)
            summary = re.sub('\n +\n', '\n', summary)
            summary = re.sub('\n\n+','\n',summary)
            summary = re.sub('\n?</blockquote>', '»\n', summary)
            summary = re.sub('<[^>]*>','',summary)
            summary = re.sub('\n»', '»', summary)
            summary = re.sub('(?<!^)(?<!\n\n)>', '\n\n>', summary)
            summary = re.sub('»\n(?!\n)', '»\n\n', summary)
            summary = re.sub('^\n+', '', summary)
            summary = summary.replace("&hellip;","…")
            summary = summary.replace('&quot;','"')
            summary = summary.replace("&nbsp;"," ")
            summary = summary.replace("&#160;"," ")
            summary = summary.replace("&ndash;","–")
            summary = summary.replace("&mdash;","—")
            summary = summary.replace("&laquo;","«")
            summary = summary.replace("&raquo;","»")
            summary = summary.replace("&#171;", "«")
            summary = summary.replace("&#187;", "»")
            summary = summary.replace("&ldquo;","“")
            summary = summary.replace("&rdquo;","”")
            summary = summary.replace("&bdquo;","„")
            summary = summary.replace("&rsquo;","’")
            summary = summary.replace("&lsquo;","‘")
            summary = summary.replace("&#8222;","„")
            summary = summary.replace("&#8220;","“")
            summary = summary.replace("&amp;","&")
            summary = summary.replace("&lt;","<")
            summary = summary.replace("&gt;",">")
            summary = unicode(summary, 'utf-8')

        for ii in jids:
            if ii[1]:
                if not re.search(ii[1], i['title']):
                    print("Not matched positive")
                    continue
            if ii[2]:
                if re.search(ii[2], i['title']):
                    print("Matched negative")
                    continue

            if ii[3] == 1:
                body = ''
            elif ii[3] == 2:
                body = '\n\n' + re.split(r'\.|!|\?', summary)[0] + '\n\n'
            elif ii[3] == 3:
                body = '\n\n' + re.split(r'\n', summary)[0] + '\n\n'
            elif ii[3] != 0 and len(summary) > ii[3]:
                body = '\n\n' + summary[:ii[3]] + '...\n\n'
            else:
                body = '\n\n' + summary + '\n\n'

            author = title = ''
            if 'author' in i and i['author'] != None:
                author = ' (by '+i["author"] + ')'
            if 'title' in i and i['title'] != None:
                title = '*' + i['title'] + '*'
# Conversations doesnt support subject for messages, so all data moved to body:
            self.sendmsg(feedname + '@' + self.name, JID(ii[0]), title + '\nLink: ' + i["link"] + author + body)

#            m=Message(to_jid=JID(ii[0]),
#                from_jid=feedname+u"@"+self.name,
#                stanza_type='chat', # was headline # can be "normal","chat","headline","error","groupchat"
#                body=u'*'+i["title"]+u'*\nLink: '+i["link"]+author+u'\n\n'+summary+u'\n\n')

# You can use separate subject for normal clients and for headline type of messages
#            m=Message(to_jid=JID(ii[0]),
#                from_jid=feedname+"@"+self.name,
#                stanza_type="chat", # was headline # can be "normal","chat","headline","error","groupchat"
#                subject=i["title"]+"\n Link: "+i["link"],
#                body=summary)

# uncomment this if you want to use "headline" message type and remove "+"\n  Link: "+i["link"]" from subject above
#            oob=m.add_new_content("jabber:x:oob","x")
#            desc=oob.newTextChild(oob.ns(), "desc", i["title"].encode("utf-8")) # use this to add url description with headline type of message
#            url=oob.newTextChild(oob.ns(), "url", i["link"].encode("utf-8"))

#            self.stream.send(m)

    def presence(self, stanza):
        fr=stanza.get_from().as_unicode()
        feedname=stanza.get_to().node
        if feedname==None:
            return None
        else:
            feedname=feedname
        if stanza.get_type()=="unavailable" and self.isFeedNameRegistered(feedname):
            p=Presence(from_jid=stanza.get_to(),to_jid=stanza.get_from(),stanza_type="unavailable")
            self.stream.send(p)
        if stanza.get_type()=="available" or stanza.get_type()==None:
            if self.isFeedNameRegistered(feedname):
                p=Presence(from_jid=JID(stanza.get_to().as_unicode()+'/rss'),
                            to_jid=stanza.get_from(),
                            show=self.get_show(feedname),
                            status=self.get_status(feedname))
                self.stream.send(p)

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
        for feedstr in self.dbfeeds:
            if feedstr[0] == feedname:
                desc = feedstr[4]
                users = feedstr[5]
                if feedname not in self.adaptime:
                    nextin = feedstr[2] + self.last_upd[feedname]
                else:
                    nextin = self.adaptime[feedname] + self.last_upd[feedname]
        if feedname not in self.new:
            self.new[feedname] = 0
        if feedname not in self.lasthournew:
            self.lasthournew[feedname] = 0
        if feedname not in self.last_upd:
            self.last_upd[feedname] = 0
        if self.updating:
            tst = None
        else:
            tst = self.last_upd[feedname]
        status = desc + '\nNew messages in last 1h: ' + unicode(str(self.lasthournew[feedname]), 'utf-8') + ' / 24h: ' + unicode(str(self.new[feedname]), 'utf-8')
        status += '\nLast updated: ' + unicode(time.strftime("%d %b %Y %H:%M:%S", time.localtime(tst)), 'utf-8')
        status += '\nNext in: ' + unicode(time.strftime("%d %b %Y %H:%M:%S", time.localtime(nextin)), 'utf-8')
        status += '\nUsers: ' + unicode(str(users), 'utf-8')
        return status

    def presence_control(self, stanza):
        feedname = stanza.get_to().node
        fromjid = stanza.get_from().bare()
        self.dbCurPT.execute("COMMIT")
        self.dbCurPT.execute("SELECT count(feedname) FROM subscribers WHERE jid = %s AND feedname = %s", (fromjid, feedname))
        a=self.dbCurPT.fetchone()
        print("Got "+str(stanza.get_type())+" request from "+str(fromjid)+" to"),
        print(feedname),
        print("with a:"),
        print(a)
        if stanza.get_type()=="subscribe":
            if self.isFeedNameRegistered(feedname) and a[0]==0:
                self.dbCurPT.execute("INSERT INTO subscribers (jid, feedname) VALUES (%s, %s)", (fromjid, feedname))
                self.dbCurPT.execute("UPDATE feeds SET subscribers=subscribers+1 WHERE feedname = %s", (feedname,))
                self.dbCurPT.execute("COMMIT")
                self.dbfeeds = self.dbCurPT.dbfeeds()
                p=Presence(stanza_type="subscribe",
                    to_jid=fromjid,
                    from_jid=stanza.get_to())
                self.stream.send(p)
                p=Presence(stanza_type="subscribed",
                    to_jid=fromjid,
                    from_jid=stanza.get_to())
                self.stream.send(p)
                return 1
            elif a[0]==0:
                p=Presence(stanza_type="unsubscribed",
                    to_jid=fromjid,
                    from_jid=stanza.get_to())
                self.stream.send(p)
                return 1

        if stanza.get_type()=="unsubscribe" or stanza.get_type()=="unsubscribed":
            if self.isFeedNameRegistered(feedname) and a[0]>0:
                self.dbCurPT.execute("DELETE FROM subscribers WHERE jid = %s AND feedname = %s", (fromjid, feedname))
                self.dbCurPT.execute("UPDATE feeds SET subscribers=subscribers-1 WHERE feedname = %s", (feedname,))
                self.dbCurPT.execute("COMMIT")
                self.dbfeeds = self.dbCurPT.dbfeeds()
                p=Presence(stanza_type="unsubscribe",
                    to_jid=fromjid,
                    from_jid=stanza.get_to())
                self.stream.send(p)
                p=Presence(stanza_type="unsubscribed",
                    to_jid=fromjid,
                    from_jid=stanza.get_to())
                self.stream.send(p)

while True:
    try:
        print("Connecting to server")
# https://xmpp.org/registrar/disco-categories.html
        c=Component(JID(NAME), PASSWORD, HOST, int(PORT), disco_category='headline', disco_type="rss", disco_name="Jabber RSS Transport")
        c.connect()
        c.loop(1)
        time.sleep(1) # to prevent fast reconnects in case of auth problems
    except KeyboardInterrupt:
        print("Keyboard interrupt, shutting down")
        c.disconnect()
        sys.exit()
    except Exception as ae:
        print(ae)
        print("Lost connection to server, reconnect in 60 seconds")
        time.sleep(60)
        pass
