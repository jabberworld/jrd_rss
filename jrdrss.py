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

from pyxmpp.jid import JID
from pyxmpp.all import Iq
from pyxmpp.all import Presence
from pyxmpp.all import Message

from pyxmpp.jabber.disco import DiscoInfo
from pyxmpp.jabber.disco import DiscoItem
from pyxmpp.jabber.disco import DiscoItems
from pyxmpp.jabber.disco import DiscoIdentity

import pyxmpp.jabberd.all
import pyxmpp.jabber.all
import pyxmpp.all

import MySQLdb
import md5

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

programmVersion="1.0"

# Based on https://stackoverflow.com/questions/207981/how-to-enable-mysql-client-auto-re-connect-with-mysqldb/982873#982873
# and https://github.com/shinbyh/python-mysqldb-reconnect/blob/master/mysqldb.py
class DB:

    conn = None
    cursor = None

    def connect(self):
        self.conn = MySQLdb.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, database=DB_NAME, autocommit=True)
        self.cursor = self.conn.cursor()

    def execute(self, sql):
        try:
            self.cursor.execute(sql)
        except (AttributeError, MySQLdb.OperationalError):
            print "No connection to database"
            self.connect()
            self.cursor.execute(sql)
        return self.cursor

    def dbfeeds(self):
        self.execute("SELECT feedname, url, timeout, regdate, description, subscribers FROM feeds")
        return self.cursor.fetchall()

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

class Component(pyxmpp.jabberd.Component):
    start_time=int(time.time())
    last_upd={}
    name=NAME.encode("utf-8")
    updating=0
    idleflag=0
    onliners=[]
    rsslogo='iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAMAAABEpIrGAAACH1BMVEX3hCL3gyH3hCH2gyH2gh/2gR72gh72gyD4oVf6wpP6vIj5snX4pF33lUL2iSz6u4f+/v7+/Pr+9/L97eD82r36vov4n1P6u4b+/v3////+/f3+8+r817j5rWz2jDD++PT82rz4pmD2hib2giD5snf97d798uj+/Pv+9Oz6xZj3kDj2ii73lD/3mkn5tn37z6j96Nf++vb+/fv827/4nE32hCL2hiX3kjz5r3H82bv+///95tT4o1r2iCv3jDL2iSv2hCP5rGv84cn96tr5tHj84837yqH5s3f3mUn2hyj3kTr6xpr+9/H4m036wY////797+T70a34pV/2hyn5tXv+8un82776wI///v7+9e37zaX3l0X5sHH6xJb6wZD85tL5tXz4qGT70q/83sX97+P6x5v+/fz82Lr2iy/3iy73mUf84Mj++/j97+L3kTv84cr++PP4rGr3jzb98uf85M/3lkL5rW381rX4qmf97d/2hyf4nlH2hif3jjT4qmj4oln5sXP4m0z95dH83MH5sXX6voz3kz796tn84cv5snb3kDn97N73lkP70Kz97N383sT3iy/6u4X++vf5rm75uID+9/D6wI7959T3jzf4nE798un6xZf2gyL++PL70q73jTP948371bP3nE36uoT2ii37yZ785dH2iCn83MD2iS397uD5q2r5uYH2hST4pmH6uYP6uYH5q2n5sXT6uYL4nlKE35UjAAACC0lEQVR42qyRA5cjQRDHr7dqpta2bZuxbZ9t27bNz3rdebGe9p/MTONX3rM7YoyVlboHAJRkBFbMnsorKquqa2qhCMOwrr6+obGpuaW1FokVAtraO4Q6u7p7ehEKeuhIqK9/YHCI5QHDI6ONYwlofGIy10kZTE3PVM/OzS/EicWlZcohVkiWJVxdW99oFMTm1jZAtocdhVKFXFNqzZggtNtZPhjp9M0Go8mMQ2ix2uI+7MgyAUdHh7PB5fZ4Ec0+vyACk0OZQLBDKBSORIlUMUEs7h2EDGBfogv1+wdWSHVAROnypIMwOHjosKthUyBH1CtkPnqMr46foPQ0VYMnT82ePiOIsx7Cc+f54sLFjDwZEOKlysuCuHIV8doFvriuhMxWEA2pbtwUeRhuDZ1o5gv/bUzHGLpzdwoI7o2K9O4jPuDhOitTowd4OPfo8RMvqZ42cCIyiM+eizRTMYamX/ASbC8BX+n5xes3OPiWf99NDyVSRJ8w7Hj/gegjr/DTZxm/8O/X+3ICGPoW78H3H4Q/f/E+//4jDfA6zsSkBIA3/grgnxfo/+YvADIWVrEtkpaUlFgMCwnmJUvlJdOWVSszMi+XkUyTXLGSrXSVgJTENLg32Jes5lzTA0wljGvXrd+wfmMNu/amzRs2b0HkAmCOYFFmBocIKOEwAwWAACyCyHwwBpjJBKGpAgAbEWloKH7cQAAAAABJRU5ErkJggg=='

    dbCur = DB()
    dbfeeds = dbCur.dbfeeds()
#    dbfeeds = DB.dbfeeds(DB()) # this uses another connection to DB
#    print dbfeeds

    def dbQuote(self, string):
        if string is None:
            return ""
        else:
            return MySQLdb.escape_string(string)

    def isFeedNameRegistered(self, feedname):
        self.dbCur.execute("SELECT count(*) FROM feeds WHERE feedname='%s'" % self.dbQuote(feedname))
        a=self.dbCur.fetchone()
        if not a:
            return False
        elif a[0]==0:
            return False
        else:
            return True

    def isFeedUrlRegistered(self, furl):
        self.dbCur.execute("SELECT count(*) FROM feeds WHERE url='%s'" % self.dbQuote(furl))
        a=self.dbCur.fetchone()
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

    def get_last(self, iq):
        if iq.get_to().as_utf8() != self.name:
            return 0
        iq=iq.make_result_response()
        q=iq.new_query("jabber:iq:last")
        q.setProp("seconds",str(int(time.time())-self.start_time))
        self.stream.send(iq)
        return 1

    def get_register(self,iq):
        if iq.get_to().as_utf8() != self.name:
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

        checkBox=form.newChild(None,"field",None)
        checkBox.setProp("type","boolean")
        checkBox.setProp("var","tosubscribe")
        checkBox.setProp("label","Subscribe")
        value=checkBox.newTextChild(None,"value","1")

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
        if iq.get_to().as_utf8() != self.name:
            self.stream.send(iq.make_error_response("feature-not-implemented"))
            return

        fname=iq.xpath_eval("//r:field[@var='feedname']/r:value",{"r":"jabber:x:data"})
        furl=iq.xpath_eval("//r:field[@var='url']/r:value",{"r":"jabber:x:data"})
        fdesc=iq.xpath_eval("//r:field[@var='desc']/r:value",{"r":"jabber:x:data"})
        fsubs=iq.xpath_eval("//r:field[@var='tosubscribe']/r:value",{"r":"jabber:x:data"})
        ftime=iq.xpath_eval("//r:field[@var='timeout']/r:value",{"r":"jabber:x:data"})
        if fname and furl and fdesc:
            fname=fname[0].getContent().lower()
            furl=furl[0].getContent()
            fdesc=fdesc[0].getContent()
        else:
            self.stream.send(iq.make_error_response("not-acceptable"))
            return
        if fname=='' or furl=='' or fdesc=='' or fname.find("@")!=-1 or fname.find(" ")!=-1 or fname.find("'")!=-1 or fname.find("/")!=-1 or fname.find("\\")!=-1 or (furl.find("http://")!=0 and furl.find("https://")!=0):
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
            ftime=int(ftime[0].getContent())
        if self.isFeedNameRegistered(fname):
            self.stream.send(iq.make_error_response("conflict"))
            return
        if self.isFeedUrlRegistered(furl):
            self.stream.send(iq.make_error_response("conflict"))
            return
        thread.start_new_thread(self.regThread,(iq.make_result_response(),iq.make_error_response("not-acceptable"),fname,furl,fdesc,fsubs,ftime,))

    def regThread(self, iqres, iqerr, fname, furl, fdesc, fsubs, ftime):
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
        self.dbCur.execute("INSERT INTO feeds (feedname, url, description, subscribers, timeout) VALUES ('%s', '%s', '%s', %s, %s)" % (self.dbQuote(fname),self.dbQuote(furl),self.dbQuote(fdesc), vsubs, ftime))
        self.last_upd[fname] = 0
        self.dbCur.execute("SELECT feedname, url, timeout, regdate, description, subscribers FROM feeds")
        self.dbfeeds=self.dbCur.fetchall()
        if fsubs:
            self.dbCur.execute("INSERT INTO subscribers (jid,feedname) VALUES ('%s','%s')" % (self.dbQuote(iqres.get_to().bare().as_utf8()),self.dbQuote(fname)))
#        self.db.commit()
        self.stream.send(iqres)
        if fsubs:
            pres=Presence(stanza_type="subscribe", from_jid=JID(unicode(fname+"@"+self.name, "utf-8")), to_jid=iqres.get_to().bare())
            self.stream.send(pres)

    def get_vCard(self,iq):
        description=None
        if iq.get_to().as_utf8() != self.name:
            feedvcard=1
        else:
            feedvcard=0
        iq=iq.make_result_response()
        q=iq.xmlnode.newChild(None,"vCard",None)
        q.setProp("xmlns","vcard-temp")
        if not feedvcard:
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
            nick=iq.get_from().node.encode("utf-8")
            for feedstr in self.dbfeeds:
                if feedstr[0] == nick:
                    url = feedstr[1]
                    bday = str(feedstr[3])
                    description = str(feedstr[4]+".\nFeed update interval: "+str(feedstr[2]/60)+" mins\nFeed subscribers: "+str(feedstr[5]))
# Tried to use favicon.ico from site as EXTVAL in PHOTO, but no luck - no support for EXTVAL in clients (tried Psi, Gajim, Conversations)
#                    favicon=urlparse.urlparse(url)[0]+"://"+urlparse.urlparse(url)[1]+"/favicon.ico"

                    q.newTextChild(None,"NICKNAME", nick)
                    q.newTextChild(None,"DESC", description)
                    q.newTextChild(None,"URL", url)
                    q.newTextChild(None,"BDAY", bday)
                    feedav=q.newTextChild(None,"PHOTO", None)
                    feedav.newTextChild(None, "BINVAL", self.rsslogo)
                    feedav.newTextChild(None, "TYPE", 'image/png')
        self.stream.send(iq)
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

    def set_search(self,iq):
        searchField=iq.xpath_eval("//r:field[@var='searchField']/r:value",{"r":"jabber:x:data"})
        if searchField:
            searchField='%'+searchField[0].getContent().replace("%","\\%")+'%'
        else:
            return
        if searchField=='%%' or len(searchField)<5:
            self.stream.send(iq.make_error_response("not-acceptable"))
            return
        self.dbCur.execute("SELECT feedname, description, url, subscribers, timeout FROM feeds WHERE feedname LIKE '%s'" % self.dbQuote(searchField))
        a=self.dbCur.fetchall()
        self.dbCur.execute("SELECT feedname, description, url, subscribers, timeout FROM feeds WHERE description LIKE '%s'" % self.dbQuote(searchField))
        b=self.dbCur.fetchall()
        self.dbCur.execute("SELECT feedname, description, url, subscribers, timeout FROM feeds WHERE url LIKE '%s'" % self.dbQuote(searchField))
        u=self.dbCur.fetchall()
        feednames=[]
        c=[]
        for x in a:
            feednames.append(x[0])
            c.append(x)
        for x in b:
            if not x[0] in feednames:
                feednames.append(x[0])
                c.append(x)
        for x in u:
            if not x[0] in feednames:
                feednames.append(x[0])
                c.append(x)
        print c, feednames
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

        for d in c:
            item=form.newChild(None,"item",None)
            jidField=item.newChild(None,"field",None)
            jidField.setProp("var","jid")
            jidField.newTextChild(None,"value", d[0]+"@"+self.name)

            urlField=item.newChild(None,"field",None)
            urlField.setProp("var","url")
            urlField.newTextChild(None,"value",d[2])

            descField=item.newChild(None,"field",None)
            descField.setProp("var","desc")
            descField.newTextChild(None,"value",d[1])

            sbsField=item.newChild(None,"field",None)
            sbsField.setProp("var","subscribers")
            sbsField.newTextChild(None,"value",str(d[3]))

            timeField=item.newChild(None,"field",None)
            timeField.setProp("var","timeout")
            timeField.newTextChild(None,"value",str(d[4]/60))

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
        nowTime=int(time.time())
        if not self.idleflag:
            print "idle"
            self.idleflag=1
        checkfeeds=[]
        if not self.updating:
            for feed in self.dbfeeds:
                try:
                    if (nowTime-int(self.last_upd[feed[0]])) > int(feed[2]):
                        self.last_upd[feed[0]]=nowTime
                        checkfeeds.append((feed[0], feed[1],))
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
            self.dbCur.execute("SELECT jid FROM subscribers WHERE feedname='%s'" % (self.dbQuote(feed[0])))
            jids=self.dbCur.fetchall()
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
                continue
#            self.dbCur.execute("UPDATE sent SET received=FALSE WHERE feedname='%s'" % self.dbQuote(feed[0]))
#            self.db.commit()
            for i in d["items"]:
                md5sum=md5.md5(i["link"].encode("utf-8")+i["title"].encode("utf-8")).hexdigest()
                feedname=feed[0]
                if not self.isSent(feedname, md5sum):
                    self.makeSent(feedname, md5sum)
                    self.sendItem(feedname, i, jids)
                    time.sleep(0.2)
                else:
                    pass
                self.dbCur.execute("UPDATE sent SET received = TRUE, datetime = NOW() WHERE feedname='%s' AND md5='%s'" % (self.dbQuote(feed[0]), md5sum))
#                self.db.commit()
            print "End of update"
# purging old records
        self.dbCur.execute("DELETE FROM sent WHERE received = '1' AND datetime < NOW() - INTERVAL 3 DAY")
#        self.db.commit()
        print "End of checkrss"
        self.updating=0

    def makeSent(self, feedname, md5sum):
        self.dbCur.execute("INSERT INTO sent (feedname, md5) VALUES ('%s','%s')" % (self.dbQuote(feedname), md5sum))
#        self.db.commit()

    def isSent(self, feedname, md5sum):
        self.dbCur.execute("SELECT IFNULL(received, count(*)) FROM sent WHERE feedname='%s' AND md5='%s'" % (self.dbQuote(feedname), md5sum))
        a=self.dbCur.fetchone()
        if a[0]>0:
            return True
        return False

    def sendItem(self, feedname, i, jids):
        for ii in jids:
            if not i.has_key("summary"):
                summary="No description"
            else:
                summary=i["summary"].encode("utf-8")
                summary=re.sub('<br ??/??>','\n',summary)
                summary=re.sub('<[^>]*>','',summary)
                summary=re.sub('\n\n','\n',summary)
                summary=summary.replace("&nbsp;"," ")
                summary=summary.replace("&ndash;","–")
                summary=summary.replace("&mdash;","—")
                summary=summary.replace("&laquo;","«")
                summary=summary.replace("&raquo;","»")
                summary=summary.replace("&ldquo;","“")
                summary=summary.replace("&rdquo;","”")
                summary=summary.replace("&bdquo;","„")
                summary=summary.replace("&rsquo;","’")
                summary=summary.replace("&lsquo;","‘")
                summary=summary.replace("&amp;","&")
                summary=summary.replace("&lt;","<")
                summary=summary.replace("&gt;",">")
# i["title"] and i["link"] - unicode obj
# Conversations doesnt support subject for messages, so all data moved to body:
            m=Message(to_jid=JID(unicode(ii[0], "utf-8")),
                from_jid=unicode(feedname+"@"+self.name, "utf-8"),
                stanza_type="chat", # was headline # can be "normal","chat","headline","error","groupchat"
                body="*"+i["title"].encode("utf-8")+"*\nLink: "+i["link"].encode("utf-8")+"\n\n"+summary+"\n")
# You can use separate subject for normal clients and for headline type of messages
#            m=Message(to_jid=JID(unicode(ii[0], "utf-8")),
#                from_jid=unicode(feedname+"@"+self.name, "utf-8"),
#                stanza_type="chat", # was headline # can be "normal","chat","headline","error","groupchat"
#                subject=i["title"]+"\n  URL: "+i["link"],
#                body=summary)

# uncomment this if you want use "headline" message type and remove "+"\n  URL: "+i["link"]" from subject above
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
            feedname=feedname.encode("utf-8")
        if stanza.get_type()=="unavailable" and self.isFeedNameRegistered(feedname):
            if not fr in self.onliners:
                return None
            del self.onliners[self.onliners.index(fr)]
            p=Presence(from_jid=stanza.get_to(),to_jid=stanza.get_from(),stanza_type="unavailable")
            self.stream.send(p)
        if stanza.get_type()=="available" or stanza.get_type()==None:
            if self.isFeedNameRegistered(feedname):
                p=Presence(from_jid=stanza.get_to(),to_jid=stanza.get_from())
                self.stream.send(p)

    def presence_control(self, stanza):
        feedname=stanza.get_to().node
        feedname=feedname.encode("utf-8")
        self.dbCur.execute("SELECT count(*) FROM subscribers WHERE jid='%s' AND feedname='%s'" % (self.dbQuote(stanza.get_from().bare().as_utf8()),self.dbQuote(feedname)))
        a=self.dbCur.fetchone()
        if stanza.get_type()=="subscribe":
            if self.isFeedNameRegistered(feedname) and a[0]==0:
                self.dbCur.execute("SELECT count(*) FROM subscribers WHERE jid='%s' AND feedname='%s'" % (self.dbQuote(stanza.get_from().bare().as_utf8()),self.dbQuote(feedname)))
                if self.dbCur.fetchone()[0]==0:
                    self.dbCur.execute("INSERT INTO subscribers (jid,feedname) VALUES ('%s','%s')" % (self.dbQuote(stanza.get_from().bare().as_utf8()),self.dbQuote(feedname)))
                    self.dbCur.execute("UPDATE feeds SET subscribers=subscribers+1 WHERE feedname='%s'" % self.dbQuote(feedname))
#                    self.db.commit()
                    self.dbCur.execute("SELECT feedname, url, timeout, regdate, description, subscribers FROM feeds")
                    self.dbfeeds=self.dbCur.fetchall()
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
                self.dbCur.execute("DELETE FROM subscribers WHERE jid='%s' AND feedname='%s'" % (self.dbQuote(stanza.get_from().bare().as_utf8()),self.dbQuote(feedname)))
                self.dbCur.execute("UPDATE feeds SET subscribers=subscribers-1 WHERE feedname='%s'" % self.dbQuote(feedname))
                self.dbCur.execute("SELECT feedname, url, timeout, regdate, description, subscribers FROM feeds")
                self.dbfeeds=self.dbCur.fetchall()
                p=Presence(stanza_type="unsubscribe",
                    to_jid=stanza.get_from().bare(),
                    from_jid=stanza.get_to())
                self.stream.send(p)
                p=Presence(stanza_type="unsubscribed",
                    to_jid=stanza.get_from().bare(),
                    from_jid=stanza.get_to())
                self.stream.send(p)
#                self.db.commit()

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
