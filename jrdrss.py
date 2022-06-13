#!/usr/bin/python -u
# -*- coding: UTF8 -*-
#
# JSMS          Python based Jabber weather transport.
# Copyright:    2007 Dobrov Sergery aka Binary from JRuDevels JID: Binary@JRuDevels.org
# Licence:      GPL v3
# Requirements:
#               pyxmpp - http://jabberstudio.org/projects/pyxmpp/project/view.php

import os
import sys
import time
import xml.dom.minidom
import urllib
import urllib2
import time
import thread
import feedparser
import re
import urlparse

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

NAME="rss.linuxoid.in"
PORT="5555"
HOST="192.168.220.250"
#NAME="weather.jrudevels.org"
#PORT="8880"
#HOST="127.0.0.1"
PASSWORD="superpassword"

DB_HOST="192.168.220.252"
DB_USER="dbuser"
DB_PASS="superpassword"
DB_NAME="jrdrss"

programmVersion="0.1.1"

class Component(pyxmpp.jabberd.Component):
    start_time=int(time.time())
    last_upd=0
    name=NAME
    onliners=[]
    db=MySQLdb.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, database=DB_NAME)
    dbCur=db.cursor()

    def dbQuote(self, string):
	if string is None:
		return ""
	else:
		return MySQLdb.escape_string(string)
#	return string.replace("\\","\\\\").replace("'","\\'")

    def isFeedNameRegistered(self, feedname):
        self.dbCur.execute("SELECT count(*) FROM feeds WHERE feedname='%s'" % self.dbQuote(feedname).encode("utf-8"))
        a=self.dbCur.fetchone()
        if not a:
            return False
        elif a[0]==0:
            return False
        else:
            return True

    def isFeedUrlRegistered(self, furl):
        self.dbCur.execute("SELECT count(*) FROM feeds WHERE url='%s'" % self.dbQuote(furl).encode("utf-8"))
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
        if iq.get_to().as_utf8()!=self.name:
            return 0
        iq=iq.make_result_response()
        q=iq.new_query("jabber:iq:last")
        q.setProp("seconds",str(int(time.time())-self.start_time))
        self.stream.send(iq)
        return 1

    def get_register(self,iq):
        if iq.get_to().as_utf8()!=self.name:
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
        self.stream.send(iq)

    def set_register(self,iq):
        if iq.get_to().as_utf8()!=self.name:
            self.stream.send(iq.make_error_response("feature-not-implemented"))
            return

        fname=iq.xpath_eval("//r:field[@var='feedname']/r:value",{"r":"jabber:x:data"})
        furl=iq.xpath_eval("//r:field[@var='url']/r:value",{"r":"jabber:x:data"})
        fdesc=iq.xpath_eval("//r:field[@var='desc']/r:value",{"r":"jabber:x:data"})
        fsubs=iq.xpath_eval("//r:field[@var='tosubscribe']/r:value",{"r":"jabber:x:data"})
        if fname and furl and fdesc:
            fname=unicode(fname[0].getContent(),"utf-8").lower()
            furl=unicode(furl[0].getContent(),"utf-8")
            fdesc=unicode(fdesc[0].getContent(),"utf-8")
        else:
            self.stream.send(iq.make_error_response("not-acceptable"))
            return
        if fname=='' or furl=='' or fdesc=='' or fname.find("@")!=-1 or fname.find(" ")!=-1 or fname.find("'")!=-1 or fname.find("/")!=-1 or fname.find("\\")!=-1 or furl.find("http://")!=0:
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
        if self.isFeedNameRegistered(fname):
            self.stream.send(iq.make_error_response("conflict"))
            return
        if self.isFeedUrlRegistered(furl):
            self.stream.send(iq.make_error_response("conflict"))
            return
        thread.start_new_thread(self.regThread,(iq.make_result_response(),iq.make_error_response("not-acceptable"),fname,furl,fdesc,fsubs,))

    def regThread(self,iqres,iqerr,fname,furl,fdesc,fsubs):
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
        self.dbCur.execute("INSERT INTO feeds (feedname,url,description,subscribers) VALUES ('%s','%s','%s',%s)" % (self.dbQuote(fname).encode("utf-8"),self.dbQuote(furl).encode("utf-8"),self.dbQuote(fdesc).encode("utf-8"),vsubs))
        if fsubs:
            self.dbCur.execute("INSERT INTO subscribers (jid,feedname) VALUES ('%s','%s')" % (self.dbQuote(iqres.get_to().bare().as_utf8()),self.dbQuote(fname).encode("utf-8")))
        self.db.commit()
        self.stream.send(iqres)
        if fsubs:
            pres=Presence(stanza_type="subscribe", from_jid=JID(fname+"@"+self.name), to_jid=iqres.get_to().bare())
            self.stream.send(pres)

    def get_vCard(self,iq):
        description=None
        if iq.get_to().as_utf8()!=self.name:
            description=u"RSS Transport's feed. http://jrudevels.org" #TODO
        iq=iq.make_result_response()
        q=iq.xmlnode.newChild(None,"vCard",None)
        q.setProp("xmlns","vcard-temp")
        if not description:
            q.newTextChild(None,"NICKNAME","JRD RSS")
            q.newTextChild(None,"DESC","RSS transport component")
        else:
            q.newTextChild(None,"NICKNAME",iq.get_from().node.encode("utf-8"))
            q.newTextChild(None,"DESC",description.encode("utf-8"))
        q.newTextChild(None,"URL","http://JRuDevels.org")
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
            searchField='%'+searchField[0].getContent().replace("%","\\%").encode("utf-8")+'%'
        else:
            return
        if searchField=='%%' or len(searchField)<5:
            self.stream.send(iq.make_error_response("not-acceptable"))
            return
        self.dbCur.execute("SELECT feedname,description,url,subscribers from feeds WHERE feedname LIKE '%s'" % self.dbQuote(searchField))
        a=self.dbCur.fetchall()
        self.dbCur.execute("SELECT feedname,description,url,subscribers from feeds WHERE description LIKE '%s'" % self.dbQuote(searchField))
        b=self.dbCur.fetchall()
        feednames=[]
        c=[]
        for x in a:
            feednames.append(x[0])
            c.append(x)
        for x in b:
            if not x[0] in feednames:
                feednames.append(x[0])
                c.append(x)
        print c,feednames
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
        reportedSubs.setProp("type","text=single")
        reportedSubs.setProp("label","Number of subscribers")
        for d in c:
            item=form.newChild(None,"item",None)
            jidField=item.newChild(None,"field",None)
            jidField.setProp("var","jid")
            jidField.newTextChild(None,"value",d[0]+"@"+self.name)
            urlField=item.newChild(None,"field",None)
            urlField.setProp("var","url")
            urlField.newTextChild(None,"value",d[2])
            descField=item.newChild(None,"field",None)
            descField.setProp("var","desc")
            descField.newTextChild(None,"value",d[1])
            sbsField=item.newChild(None,"field",None)
            sbsField.setProp("var","subscribers")
            sbsField.newTextChild(None,"value",str(d[3]))
        self.stream.send(iq)
        return 1

    def get_version(self,iq):
        global programmVersion
        iq=iq.make_result_response()
        q=iq.new_query("jabber:iq:version")
        q.newTextChild(q.ns(),"name","Jabber RSS Transport (http://JRuDevels.org)")
        q.newTextChild(q.ns(),"version",programmVersion)
        self.stream.send(iq)
        return 1

    def disco_get_info(self,node,iq):
        return self.disco_info

    def idle(self):
        nowTime=int(time.time())
        if (nowTime-self.last_upd)>300:
            print "idle"
            self.last_upd=nowTime
            thread.start_new_thread(self.checkrss,())

    def checkrss(self):
        self.dbCur.execute("SELECT feedname,url FROM feeds")
        feeds=self.dbCur.fetchall()
        for feed in feeds:
            self.dbCur.execute("SELECT jid FROM subscribers WHERE feedname='%s'" % (self.dbQuote(feed[0])))
            jids=self.dbCur.fetchall()
            if len(jids)==0:
                continue
            try:
                print feed[1]
                d=feedparser.parse(feed[1])
                bozo=d["bozo"]
            except:
                continue
            if bozo==1:
                continue
            self.dbCur.execute("UPDATE sent SET received=FALSE WHERE feedname='%s'" % self.dbQuote(feed[0]))
            self.db.commit()
            for i in d["items"]:
                md5sum=md5.md5(unicode(i).encode("utf-8")).hexdigest()
                feedname=unicode(feed[0],"utf-8")
                if not self.isSent(feedname, md5sum):
                    self.makeSent(feedname,md5sum)
                    self.sendItem(feedname, i, jids)
                else:
                    pass
                self.dbCur.execute("UPDATE sent SET received=TRUE WHERE feedname='%s' AND md5='%s'" % (self.dbQuote(feed[0]),self.dbQuote(md5sum)))
                self.db.commit()
            self.dbCur.execute("DELETE FROM sent WHERE feedname='%s' AND received=FALSE" % self.dbQuote(feed[0]))
            self.db.commit()
        print "end idle"

    def makeSent(self,feedname,md5sum):
        self.dbCur.execute("INSERT INTO sent (feedname,md5,datetime) VALUES ('%s','%s',now())" % (self.dbQuote(feedname).encode("utf-8"),self.dbQuote(md5sum)))
        self.db.commit()

    def isSent(self,feedname,md5sum):
        self.dbCur.execute("SELECT count(*) FROM sent WHERE feedname='%s' AND md5='%s'" % (self.dbQuote(feedname).encode("utf-8"),self.dbQuote(md5sum)))
        a=self.dbCur.fetchone()
        if a[0]>0:
            return True
        return False

    def sendItem(self, feedname, i, jids):
        for ii in jids:
            if not i.has_key("summary"):
                summary="No description"
            else:
                summary=i["summary"]
                summary=re.sub('<br ??/??>','\n',summary)
                summary=re.sub('\n\n','\n',summary)
                summary=summary.replace("&nbsp;"," ")
                summary=re.sub('<[^>]*>','',summary)
            m=Message(to_jid=JID(unicode(ii[0],"utf-8")),
                from_jid=feedname+"@"+self.name,
                stanza_type="headline",
                subject=i["title"],
                body=summary)
            oob=m.add_new_content("jabber:x:oob","x")
            url=oob.newTextChild(oob.ns(),"url",i["link"])
            desc=oob.newTextChild(oob.ns(),"desc",i["title"].encode("utf-8"))
            self.stream.send(m)

    def presence(self,stanza):
        fr=stanza.get_from().as_unicode()
        feedname=stanza.get_to().node#.lower()
        if feedname==None:
            return None
        if stanza.get_type()=="unavailable" and self.isFeedNameRegistered(feedname):
            if not fr in self.onliners:
                return None
            del self.onliners[self.onliners.index(fr)]
                    #del self.weathers[weatherCode]['jids'][self.weathers[weatherCode]['jids'].index(fr)]
                    #if self.weathers[weatherCode]['jids']=='':
                        #del self.weathers[weatherCode]
            p=Presence(from_jid=stanza.get_to(),to_jid=stanza.get_from(),stanza_type="unavailable")
            self.stream.send(p)
        if stanza.get_type()=="available" or stanza.get_type()==None:
            if self.isFeedNameRegistered(feedname):
                p=Presence(from_jid=stanza.get_to(),to_jid=stanza.get_from())
                self.stream.send(p)

    def presence_control(self,stanza):
        feedname=stanza.get_to().node
        self.dbCur.execute("SELECT count(*) FROM subscribers WHERE jid='%s' AND feedname='%s'" % (self.dbQuote(stanza.get_from().bare().as_utf8()),self.dbQuote(feedname).encode("utf-8")))
        a=self.dbCur.fetchone()
        if stanza.get_type()=="subscribe":
            if self.isFeedNameRegistered(feedname) and a[0]==0:
                self.dbCur.execute("SELECT count(*) FROM subscribers WHERE jid='%s' AND feedname='%s'" % (self.dbQuote(stanza.get_from().bare().as_utf8()),self.dbQuote(feedname).encode("utf-8")))
                if self.dbCur.fetchone()[0]==0:
                    self.dbCur.execute("INSERT INTO subscribers (jid,feedname) VALUES ('%s','%s')" % (self.dbQuote(stanza.get_from().bare().as_utf8()),self.dbQuote(feedname).encode("utf-8")))
                    self.dbCur.execute("UPDATE feeds SET subscribers=subscribers+1 WHERE feedname='%s'" % self.dbQuote(feedname).encode("utf-8"))
                    self.db.commit()
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
                self.dbCur.execute("DELETE FROM subscribers WHERE jid='%s' AND feedname='%s'" % (self.dbQuote(stanza.get_from().bare().as_utf8()),self.dbQuote(feedname).encode("utf-8")))
                self.dbCur.execute("UPDATE feeds SET subscribers=subscribers-1 WHERE feedname='%s'" % self.dbQuote(feedname).encode("utf-8"))
                p=Presence(stanza_type="unsubscribe",
                    to_jid=stanza.get_from().bare(),
                    from_jid=stanza.get_to())
                self.stream.send(p)
                p=Presence(stanza_type="unsubscribed",
                    to_jid=stanza.get_from().bare(),
                    from_jid=stanza.get_to())
                self.stream.send(p)
                self.db.commit()

#try:
c=Component(JID(NAME),PASSWORD,HOST,int(PORT),disco_type="x-rss",disco_name="JRuDevels RSS Transport")
c.connect()
c.loop(1)
#except KeyboardInterrupt:
    #sys.exit()
    #c.disconnect()
#except:
    #sys.exit(1)
