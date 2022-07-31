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
from hashlib import md5

from pyxmpp.jid import JID
from pyxmpp.presence import Presence
from pyxmpp.message import Message

from pyxmpp.jabber.disco import DiscoItem
from pyxmpp.jabber.disco import DiscoItems

import pyxmpp.jabberd.all

config=os.path.abspath(os.path.dirname(sys.argv[0]))+'/config.xml'

# https://stackoverflow.com/questions/9772691/feedparser-with-timeout
# can't use requests on my system, but with sockets all ok too
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

programmVersion="1.4.5"

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
            self.cursor.execute(sql, param)
        except (AttributeError, MySQLdb.OperationalError):
            print "No connection to database"
            self.connect()
            self.cursor.execute(sql, param)
        return self.cursor

    def dbfeeds(self):
        self.execute("SELECT feedname, url, timeout, regdate, description, subscribers, private, registrar, tags FROM feeds")
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
    adaptive = ADAPTIVE
    adaptime = {}
    rsslogo='iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAMAAABEpIrGAAACH1BMVEX3hCL3gyH3hCH2gyH2gh/2gR72gh72gyD4oVf6wpP6vIj5snX4pF33lUL2iSz6u4f+/v7+/Pr+9/L97eD82r36vov4n1P6u4b+/v3////+/f3+8+r817j5rWz2jDD++PT82rz4pmD2hib2giD5snf97d798uj+/Pv+9Oz6xZj3kDj2ii73lD/3mkn5tn37z6j96Nf++vb+/fv827/4nE32hCL2hiX3kjz5r3H82bv+///95tT4o1r2iCv3jDL2iSv2hCP5rGv84cn96tr5tHj84837yqH5s3f3mUn2hyj3kTr6xpr+9/H4m036wY////797+T70a34pV/2hyn5tXv+8un82776wI///v7+9e37zaX3l0X5sHH6xJb6wZD85tL5tXz4qGT70q/83sX97+P6x5v+/fz82Lr2iy/3iy73mUf84Mj++/j97+L3kTv84cr++PP4rGr3jzb98uf85M/3lkL5rW381rX4qmf97d/2hyf4nlH2hif3jjT4qmj4oln5sXP4m0z95dH83MH5sXX6voz3kz796tn84cv5snb3kDn97N73lkP70Kz97N383sT3iy/6u4X++vf5rm75uID+9/D6wI7959T3jzf4nE798un6xZf2gyL++PL70q73jTP948371bP3nE36uoT2ii37yZ785dH2iCn83MD2iS397uD5q2r5uYH2hST4pmH6uYP6uYH5q2n5sXT6uYL4nlKE35UjAAACC0lEQVR42qyRA5cjQRDHr7dqpta2bZuxbZ9t27bNz3rdebGe9p/MTONX3rM7YoyVlboHAJRkBFbMnsorKquqa2qhCMOwrr6+obGpuaW1FokVAtraO4Q6u7p7ehEKeuhIqK9/YHCI5QHDI6ONYwlofGIy10kZTE3PVM/OzS/EicWlZcohVkiWJVxdW99oFMTm1jZAtocdhVKFXFNqzZggtNtZPhjp9M0Go8mMQ2ix2uI+7MgyAUdHh7PB5fZ4Ec0+vyACk0OZQLBDKBSORIlUMUEs7h2EDGBfogv1+wdWSHVAROnypIMwOHjosKthUyBH1CtkPnqMr46foPQ0VYMnT82ePiOIsx7Cc+f54sLFjDwZEOKlysuCuHIV8doFvriuhMxWEA2pbtwUeRhuDZ1o5gv/bUzHGLpzdwoI7o2K9O4jPuDhOitTowd4OPfo8RMvqZ42cCIyiM+eizRTMYamX/ASbC8BX+n5xes3OPiWf99NDyVSRJ8w7Hj/gegjr/DTZxm/8O/X+3ICGPoW78H3H4Q/f/E+//4jDfA6zsSkBIA3/grgnxfo/+YvADIWVrEtkpaUlFgMCwnmJUvlJdOWVSszMi+XkUyTXLGSrXSVgJTENLg32Jes5lzTA0wljGvXrd+wfmMNu/amzRs2b0HkAmCOYFFmBocIKOEwAwWAACyCyHwwBpjJBKGpAgAbEWloKH7cQAAAAABJRU5ErkJggg=='

    dbCurST = DB() # search thread
    dbCurUT = DB() # update thread
    dbCurRT = DB() # register thread
    dbCurPT = DB() # presence thread

    dbfeeds = dbCurUT.dbfeeds() # no matter which thread to use
#    dbfeeds = DB.dbfeeds(DB()) # this uses another connection to DB
#    print dbfeeds

    def isFeedNameRegistered(self, feedname):
        self.dbCurRT.execute("SELECT count(feedname) FROM feeds WHERE feedname = %s", (feedname,))
        a=self.dbCurRT.fetchone()
        if not a:
            return False
        elif a[0]==0:
            return False
        else:
            return True

    def isFeedUrlRegistered(self, furl):
        self.dbCurRT.execute("SELECT count(feedname) FROM feeds WHERE url = %s", (furl,))
        a=self.dbCurRT.fetchone()
        if not a:
            return False
        elif a[0]==0:
            return False
        else:
            return True

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
        self.disco_info.add_feature("vcard-temp")
        self.stream.set_iq_get_handler("vCard","vcard-temp",self.get_vCard)
        self.stream.set_iq_get_handler("query","jabber:iq:version",self.get_version)
        self.stream.set_iq_get_handler("query","jabber:iq:register",self.get_register)
        self.stream.set_iq_set_handler("query","jabber:iq:register",self.set_register)
        self.stream.set_iq_get_handler("query","jabber:iq:search",self.get_search)
        self.stream.set_iq_set_handler("query","jabber:iq:search",self.set_search)
        self.stream.set_iq_get_handler("query","jabber:iq:last",self.get_last)
        self.stream.set_presence_handler("available",self.presence)
        self.stream.set_presence_handler("unavailable",self.presence)
        self.stream.set_presence_handler("subscribe",self.presence_control)
        self.stream.set_presence_handler("subscribed",self.presence_control)
        self.stream.set_presence_handler("unsubscribe",self.presence_control)
        self.stream.set_presence_handler("unsubscribed",self.presence_control)

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
                    if not feedtags.has_key(tag):
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

    def get_last(self, iq):
        if iq.get_to() != self.name:
            return 0
        iq=iq.make_result_response()
        q=iq.new_query("jabber:iq:last")
        q.setProp("seconds",str(int(time.time())-self.start_time))
        self.stream.send(iq)
        return 1

    def get_register(self,iq):
        if iq.get_to() != self.name:
            self.stream.send(iq.make_error_response("feature-not-implemented"))
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

        self.stream.send(iq)

    def set_register(self,iq):
        if iq.get_to() != self.name:
            self.stream.send(iq.make_error_response("feature-not-implemented"))
            return

        fname=iq.xpath_eval("//r:field[@var='feedname']/r:value",{"r":"jabber:x:data"})
        furl=iq.xpath_eval("//r:field[@var='url']/r:value",{"r":"jabber:x:data"})
        fdesc=iq.xpath_eval("//r:field[@var='desc']/r:value",{"r":"jabber:x:data"})
        fsubs=iq.xpath_eval("//r:field[@var='tosubscribe']/r:value",{"r":"jabber:x:data"})
        fpriv=iq.xpath_eval("//r:field[@var='private']/r:value",{"r":"jabber:x:data"})
        ftime=iq.xpath_eval("//r:field[@var='timeout']/r:value",{"r":"jabber:x:data"})
        ftags=iq.xpath_eval("//r:field[@var='tags']/r:value",{"r":"jabber:x:data"})
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
        if fpriv:
            fpriv = int(fpriv[0].getContent())
        if ftags:
            ftags = ftags[0].getContent().lower()
            ftags = re.sub('^ *', '', ftags)
            ftags = re.sub(' *$', '', ftags)
            ftags = re.sub(' *, *', ',', ftags)
            if len(ftags) > 255:
                self.stream.send(iq.make_error_response("not-acceptable"))
                return
        if self.isFeedNameRegistered(fname) or self.isFeedUrlRegistered(furl):
            self.stream.send(iq.make_error_response("conflict"))
            return
        thread.start_new_thread(self.regThread,(iq.make_result_response(),iq.make_error_response("not-acceptable"),fname,furl,fdesc,fsubs,ftime,fpriv,ftags,))

    def regThread(self, iqres, iqerr, fname, furl, fdesc, fsubs, ftime, fpriv, ftags):
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
        registrar = iqres.get_to().bare()
        self.dbCurRT.execute("INSERT INTO feeds (feedname, url, description, subscribers, timeout, private, registrar, tags) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", (fname, furl, fdesc, vsubs, ftime, fpriv, registrar, ftags))
        self.last_upd[fname] = 0
        self.dbfeeds = self.dbCurRT.dbfeeds()
#        if fsubs:
#            self.dbCurRT.execute("INSERT INTO subscribers (jid, feedname) VALUES (%s, %s)", (iqres.get_to().bare(), fname))
        self.dbCurRT.execute("COMMIT")
        self.stream.send(iqres)
        if fsubs:
            pres=Presence(stanza_type="subscribe", from_jid=JID(unicode(fname, 'utf-8')+u"@"+self.name), to_jid=iqres.get_to().bare())
            self.stream.send(pres)

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
                    if self.adaptive and self.adaptime.has_key(nick) and self.adaptime[nick] != feedstr[2]:
                        real = u"(adaptive: "+str(int(self.adaptime[nick]/60))+u"mins)"
                    else:
                        real = u""
                    description = feedstr[4]+u'.\nFeed update interval: '+str(feedstr[2]/60)+u' mins '+real+u'\nFeed subscribers: '+str(feedstr[5])
# Tried to use favicon.ico from site as EXTVAL in PHOTO, but no luck - no support for EXTVAL in clients (tried Psi, Gajim, Conversations)
#                    favicon=urlparse.urlparse(url)[0]+"://"+urlparse.urlparse(url)[1]+"/favicon.ico"

                    q.newTextChild(None,"NICKNAME", nick.encode('utf-8'))
                    q.newTextChild(None,"DESC", description.encode('utf-8'))
                    q.newTextChild(None,"URL", url.encode('utf-8'))
                    q.newTextChild(None,"BDAY", str(bday))
                    feedav=q.newTextChild(None,"PHOTO", None)
                    feedav.newTextChild(None, "BINVAL", self.rsslogo)
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
        self.dbCurST.execute("SELECT feedname, description, url, subscribers, timeout FROM feeds WHERE (feedname LIKE %s OR description LIKE %s OR url LIKE %s OR tags LIKE %s) AND (private = '0' OR (private = '1' AND registrar = %s))", (searchField, searchField, searchField, searchField, fromjid))
        a=self.dbCurST.fetchall()

        print a

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
        q.newTextChild(q.ns(), "name", "Jabber RSS Transport (https://github.com/jabberworld/jrd_rss)")
        q.newTextChild(q.ns(), "version", programmVersion)
        self.stream.send(iq)
        return 1

    def disco_get_info(self,node,iq):
        return self.disco_info

    def idle(self):
        nowTime = int(time.time())
        if not self.idleflag:
            print "idle"
            self.idleflag=1
        checkfeeds=[]
        if not self.updating:
            for feed in self.dbfeeds:
                if not self.adaptime.has_key(feed[0]):
                    checkfeeds.append((feed[0], feed[1], feed[2],)) # update all feeds at startup time
                    self.adaptime[feed[0]] = feed[2] # set update times to its defined values. This will be redefined after checkrss() (or not)
                try:
                    if (nowTime-int(self.last_upd[feed[0]])) > self.adaptime[feed[0]]:
                        self.last_upd[feed[0]] = nowTime
                        checkfeeds.append((feed[0], feed[1], feed[2],))
                except:
                    self.last_upd[feed[0]]=nowTime
            if checkfeeds:
                self.idleflag=0
                print "UPDATE:",
                print checkfeeds
                thread.start_new_thread(self.checkrss,(checkfeeds,))
                self.updating=1
        else:
            print "Update in progress"

    def checkrss(self, checkfeeds):
        for feed in checkfeeds:
            feedname = feed[0]

            if not self.times.has_key(feedname):
                self.times[feedname] = list()

            self.new[feedname] = 0
            self.lasthournew[feedname] = 0

            self.dbCurUT.execute("SELECT jid FROM subscribers WHERE feedname = %s", (feedname,))
            jids=self.dbCurUT.fetchall()
            if len(jids)==0:
                continue
            try:
                print "FETCHING",
                print feed[1]
                d=feedparser.parse(feed[1])
                bozo=d["bozo"]
            except:
                continue
            if bozo==1:
                print "Some problems with feed"
                self.new[feedname] = -1
                self.botstatus(feedname, jids) # Send XA status if problems with feed
                continue
            for i in d["items"]:
                md5sum = md5(i["link"].encode("utf-8")+i["title"].encode("utf-8")).hexdigest()
                if not self.isSent(feedname, md5sum):
                    self.sendItem(feedname, i, jids)
                    self.times[feedname].append(time.time())
                    self.dbCurUT.execute("INSERT INTO sent (received, feedname, md5) VALUES (TRUE, %s, %s)", (feedname, md5sum))
                    time.sleep(0.2)
                else:
                    self.dbCurUT.execute("UPDATE sent SET received = TRUE, datetime = NOW() WHERE feedname = %s AND md5 = %s AND datetime < NOW() - INTERVAL 1 DAY", (feed[0], md5sum))

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

            print "End of update"
            self.botstatus(feedname, jids)
# purging old records
        self.dbCurUT.execute("DELETE FROM sent WHERE received = '1' AND datetime < NOW() - INTERVAL 3 DAY")
        self.dbCurUT.execute("COMMIT")
        print "End of checkrss"
        self.updating = 0

    def isSent(self, feedname, md5sum):
        self.dbCurUT.execute("SELECT count(received) FROM sent WHERE feedname = %s AND md5 = %s", (feedname, md5sum))
        a=self.dbCurUT.fetchone()
        if a[0]>0:
            return True
        return False

    def botstatus(self, feedname, jids):
        for jid in jids:
            p=Presence(from_jid=feedname+u"@"+self.name,
                to_jid=JID(jid[0]),
                show = self.get_show(feedname),
                status = self.get_status(feedname))
            self.stream.send(p)

    def sendItem(self, feedname, i, jids):
        for ii in jids:
            if not i.has_key("summary"):
                summary=u"No description"
            else:
                summary=i["summary"].encode('utf-8')
                summary=re.sub('<br ??/??>','\n',summary)
                summary=re.sub('<[^>]*>','',summary)
                summary=re.sub('\n\n','\n',summary)
                summary=summary.replace("&nbsp;"," ")
                summary=summary.replace("&ndash;","–")
                summary=summary.replace("&mdash;","—")
                summary=summary.replace("&laquo;","«")
                summary=summary.replace("&raquo;","»")
                summary=summary.replace("&#171;", "«")
                summary=summary.replace("&#187;", "»")
                summary=summary.replace("&ldquo;","“")
                summary=summary.replace("&rdquo;","”")
                summary=summary.replace("&bdquo;","„")
                summary=summary.replace("&rsquo;","’")
                summary=summary.replace("&lsquo;","‘")
                summary=summary.replace("&amp;","&")
                summary=summary.replace("&lt;","<")
                summary=summary.replace("&gt;",">")
                summary = unicode(summary, 'utf-8')
            if i.has_key("author"):
                author = u" (by "+i["author"]+u")"
            else:
                author = u""
# i["title"] and i["link"] - unicode obj
# Conversations doesnt support subject for messages, so all data moved to body:
            m=Message(to_jid=JID(ii[0]),
                from_jid=feedname+u"@"+self.name,
                stanza_type='chat', # was headline # can be "normal","chat","headline","error","groupchat"
                body=u'*'+i["title"]+u'*\nLink: '+i["link"]+author+u'\n\n'+summary+u'\n\n')
# You can use separate subject for normal clients and for headline type of messages
#            m=Message(to_jid=JID(unicode(ii[0], "utf-8")),
#                from_jid=unicode(feedname+"@"+self.name, "utf-8"),
#                stanza_type="chat", # was headline # can be "normal","chat","headline","error","groupchat"
#                subject=i["title"]+"\n Link: "+i["link"],
#                body=summary)

# uncomment this if you want to use "headline" message type and remove "+"\n  Link: "+i["link"]" from subject above
#            oob=m.add_new_content("jabber:x:oob","x")
#            desc=oob.newTextChild(oob.ns(), "desc", i["title"].encode("utf-8")) # use this to add url description with headline type of message
#            url=oob.newTextChild(oob.ns(), "url", i["link"].encode("utf-8"))
            self.stream.send(m)

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
                p=Presence(from_jid=stanza.get_to(),
                            to_jid=stanza.get_from(),
                            show=self.get_show(feedname),
                            status=self.get_status(feedname))
                self.stream.send(p)

    def get_show(self, feedname):
        if not self.new.has_key(feedname):
            self.new[feedname] = 0
        if not self.lasthournew.has_key(feedname):
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
                if not self.adaptime.has_key(feedname):
                    nextin = feedstr[2] + self.last_upd[feedname]
                else:
                    nextin = self.adaptime[feedname] + self.last_upd[feedname]
        if not self.new.has_key(feedname):
            self.new[feedname] = 0
        if not self.lasthournew.has_key(feedname):
            self.lasthournew[feedname] = 0
        if not self.last_upd.has_key(feedname):
            self.last_upd[feedname] = 0
        if self.updating:
            tst = None
        else:
            tst = self.last_upd[feedname]
        status = desc+u'\nNew messages in last 1h: '+unicode(str(self.lasthournew[feedname]), 'utf-8')+u' / 24h: '+unicode(str(self.new[feedname]), 'utf-8')+u'\nLast updated: '+unicode(time.strftime("%d %b %Y %H:%M:%S", time.localtime(tst)), 'utf-8')+u'\nNext in: '+unicode(time.strftime("%d %b %Y %H:%M:%S", time.localtime(nextin)), 'utf-8')+u'\nUsers: '+unicode(str(users), 'utf-8')
        return status

    def presence_control(self, stanza):
        feedname=stanza.get_to().node
        self.dbCurPT.execute("SELECT count(feedname) FROM subscribers WHERE jid = %s AND feedname = %s", (stanza.get_from().bare(), feedname))
        a=self.dbCurPT.fetchone()
        if stanza.get_type()=="subscribe":
            if self.isFeedNameRegistered(feedname) and a[0]==0:
                self.dbCurPT.execute("INSERT INTO subscribers (jid, feedname) VALUES (%s, %s)", (stanza.get_from().bare(), feedname))
                self.dbCurPT.execute("UPDATE feeds SET subscribers=subscribers+1 WHERE feedname = %s", (feedname,))
                self.dbCurPT.execute("COMMIT")
                self.dbfeeds = self.dbCurPT.dbfeeds()
                p=Presence(stanza_type="subscribe",
                    to_jid=stanza.get_from().bare(),
                    from_jid=stanza.get_to())
                self.stream.send(p)
                p=Presence(stanza_type="subscribed",
                    to_jid=stanza.get_from().bare(),
                    from_jid=stanza.get_to())
                self.stream.send(p)
                return 1
            elif a[0]==0:
                p=Presence(stanza_type="unsubscribed",
                    to_jid=stanza.get_from().bare(),
                    from_jid=stanza.get_to())
                self.stream.send(p)
                return 1

        if stanza.get_type()=="unsubscribe" or stanza.get_type()=="unsubscribed":
            if self.isFeedNameRegistered(feedname) and a[0]>0:
                self.dbCurPT.execute("DELETE FROM subscribers WHERE jid = %s AND feedname = %s", (stanza.get_from().bare(), feedname))
                self.dbCurPT.execute("UPDATE feeds SET subscribers=subscribers-1 WHERE feedname = %s", (feedname,))
                self.dbCurPT.execute("COMMIT")
                self.dbfeeds = self.dbCurPT.dbfeeds()
                p=Presence(stanza_type="unsubscribe",
                    to_jid=stanza.get_from().bare(),
                    from_jid=stanza.get_to())
                self.stream.send(p)
                p=Presence(stanza_type="unsubscribed",
                    to_jid=stanza.get_from().bare(),
                    from_jid=stanza.get_to())
                self.stream.send(p)

while True:
    try:
        print "Connecting to server"
# https://xmpp.org/registrar/disco-categories.html
        c=Component(JID(NAME), PASSWORD, HOST, int(PORT), disco_category='headline', disco_type="rss", disco_name="Jabber RSS Transport")
        c.connect()
        c.loop(1)
        time.sleep(1) # to prevent fast reconnects in case of auth problems
    except KeyboardInterrupt:
        print "Keyboard interrupt, shutting down"
        c.disconnect()
        sys.exit()
    except Exception as ae:
        print ae
        print "Lost connection to server, reconnect in 60 seconds"
        time.sleep(60)
        pass
