# -*- coding: utf-8 -*-
#
# JRSS  Python 3 Jabber RSS transport.
#
# Dialogue (message command) handling. Mixed into Transport.

import re
import urllib.parse

import feedparser
from pymysql.err import IntegrityError as MySQLIntegrityError


class MessageMixin:

    def message(self, msg):
        if msg['type'] in ('error', 'groupchat', 'headline'):
            return
        body = msg.get('body')
        if body is None or body == '':
            print("Got no msg")
            return
        body = body.strip()
        bodyp = body.split()
        if not bodyp:
            return
        fromjid = msg['from'].bare
        tojid = msg['to'].bare
        feedname = msg['to'].node
        if not feedname and len(bodyp) > 1 and bodyp[1] == ':':
            print("You should specify correct feed name")
            self.sendmsg(tojid, fromjid, "You should specify correct feed name")
            return

        if fromjid in self.admins:
            if bodyp[0] == '+' and len(bodyp) > 4 and bodyp[3].isdigit():
                fd = feedparser.parse(bodyp[2])
                if (bool(urllib.parse.urlparse(bodyp[2]).netloc) and
                        not any(bodyp[2] in url for url in self.dbfeeds) and
                        not any(bodyp[1] in feed for feed in self.dbfeeds) and
                        (fd["bozo"] == 0 or
                         (fd["bozo"] == 1 and
                          type(fd.bozo_exception).__name__ == 'NonXMLContentType'))):
                    fint = int(bodyp[3])
                    if fint < 60:
                        fint = 60
                    tagmark = body.rfind("SETTAGS:")
                    if tagmark < 0:
                        tagmark = None
                        ftags = ''
                    else:
                        ftags = body[tagmark + 8:]
                        ftags = re.sub(' *, *', ',', ftags.strip())
                    fdesc = body[body.rfind(bodyp[4], 0, tagmark):tagmark].strip()
                    try:
                        self.dbCurTT.execute("INSERT INTO feeds (feedname, url, "
                                             "description, timeout, private, "
                                             "registrar, tags) VALUES (%s, %s, %s, "
                                             "%s, %s, %s, %s)",
                                             (bodyp[1], bodyp[2], fdesc, fint, 0,
                                              fromjid, ftags))
                    except MySQLIntegrityError:
                        self.sendmsg(tojid, fromjid,
                                     "This feed already registered")
                        return
                    self.dbCurTT.commit()
                    self.dbfeeds = self.dbCurTT.dbfeeds()
                    self.sendmsg(tojid, fromjid,
                                 "Added new feed: " + bodyp[1] + " (" + fdesc + ")")
                else:
                    self.sendmsg(tojid, fromjid, "Something wrong with this feed")

            elif bodyp[0] == 'update' and len(bodyp) < 3:
                if len(bodyp) == 2:
                    feedname = bodyp[1]
                if feedname in self.last_upd and feedname is not None:
                    print("Forced update for " + feedname)
                    self.last_upd[feedname] = 0
                    self.sendmsg(tojid, fromjid, "Forced update for: " + feedname)
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
                        tags = " SETTAGS: " + f[8]
                    else:
                        tags = ''
                    allfeeds += "\n+ " + f[0] + " " + f[1] + " " + str(f[2]) + \
                                " " + f[4] + tags
                self.sendmsg(tojid, fromjid, allfeeds)

            elif bodyp[0] == 'purgelast' and len(bodyp) < 3:
                if len(bodyp) == 2:
                    feedname = bodyp[1]
                if any(feedname in fn for fn in self.dbfeeds) and feedname is not None:
                    print("purgelast for " + feedname)
                    self.dbCurTT.execute("DELETE FROM sent WHERE feedname = %s "
                                         "ORDER BY income DESC LIMIT 1", (feedname,))
                    self.dbCurTT.commit()
                    self.sendmsg(tojid, fromjid, "Purged last record for " + feedname)
                else:
                    self.sendmsg(tojid, fromjid, "Can't find this feed")
            elif bodyp[0] == 'purgeall' and len(bodyp) < 3:
                if len(bodyp) == 2:
                    feedname = bodyp[1]
                if any(feedname in fn for fn in self.dbfeeds) and feedname is not None:
                    print("purgeall for " + feedname)
                    self.dbCurTT.execute("DELETE FROM sent WHERE feedname = %s",
                                         (feedname,))
                    self.dbCurTT.commit()
                    self.sendmsg(tojid, fromjid, "Purged all records for " + feedname)
                else:
                    self.sendmsg(tojid, fromjid, "Can't find this feed")

        # available to all users
        if bodyp[0] == 'help' or (bodyp[0] == '?' and len(bodyp) == 1):
            msgstr = "List of commands:\n"
            msgstr += "* help or ? - show available commands\n\n"
            msgstr += "* settags or =# (NAME or ':') TAG1,TAG2,TAG3... - set new tags for feed NAME (or : for this feed)\n"
            msgstr += "* setupd or =@ (NAME or ':') SECS - set new update interval for feed NAME (or : for this feed) in SECS\n"
            msgstr += "* setuniq or =() (NAME or ':') (link | title | content) - set news uniqueness check type for feed NAME (or : for this feed)\n"
            msgstr += "* setdesc or =: (NAME or ':') New feed description - set new feed description for feed NAME (or : for this feed)\n\n"

            msgstr += "* showtags or ?# [NAME] - show tags for feed NAME (or this feed)\n"
            msgstr += "* showupd or ?@ [NAME] - show update interval for feed NAME (or this feed)\n"
            msgstr += "* showdesc or ?: [NAME] - show description for feed NAME (or this feed)\n"
            msgstr += "* showuniq or ?() [NAME] - show news uniqueness check type for feed NAME (or this feed)\n"
            msgstr += "* showadap or ?% [NAME] - show real update time for feed NAME (or this feed)\n"

            msgstr += "* showmyprivate or ?*** - show my private feeds\n"
            msgstr += "* showmyfeeds or ?~ - show all feeds where i am registrar\n\n"

            msgstr += "* setposfilter or =+ [EXP] - deliver news for feed only with subject matched expression EXP\n"
            msgstr += "* setnegfilter or =- [EXP] - block news for feed with subject matched expression EXP\n"
            msgstr += "* showfilter or ?+- [NAME] - show filters for feed NAME (or this feed)\n\n"

            msgstr += "* setshort or =... SYMBOLS - limit maximum message size in feed body.\n"
            msgstr += "  * Use setshort 1 for 'Title only' mode.\n  * Use setshort 2 for '1st sentence mode'.\n  * Use setshort 3 for '1st paragraph' mode.\n"
            msgstr += "* showshort or ?... [NAME] - show maximum message size for feed NAME (or this feed)\n\n"

            msgstr += "* hide or *** [NAME] - make feed NAME (or this feed) private\n"
            msgstr += "* unhide or +++ [NAME] - make feed NAME (or this feed) public\n\n"

            msgstr += "* mute or ~~~ [NAME] - do not receive news from feed NAME (or this feed)\n"
            msgstr += "* unmute or @@@ [NAME] - cancel mute command for feed NAME (or this feed)\n\n"

            msgstr += "* search or ? SOME STRING - search by title, author or content in this feed\n"
            msgstr += "* searchintag or ?!# TAG SOME STRING - search by title, author or content in TAG\n"
            msgstr += "* searchtitle or ?!* SOME STRING - search by title in all feeds\n"
            msgstr += "* searchall or ?! SOME STRING - search by title, author or content in all feeds\n\n"

            msgstr += "* 1..20 - fetch last N news for this feed\n\n"
            msgstr += "* top [today | day | week | month] - show statistics for period - default for this day. You can use shorts d, w, m for periods\n\n"
            if fromjid in self.admins:
                msgstr += "* updateall - update all feeds\n"
                msgstr += "* update [NAME] - update feed NAME (or this feed)\n\n"
                msgstr += "* purgelast [NAME] - forget about last sent item for feed NAME (or this feed)\n"
                msgstr += "* purgeall [NAME] - forget about all sent items for feed NAME (or this feed)\n\n"
                msgstr += "* showall - dump all registered feeds\n\n"
                msgstr += "* + NAME URL INTERVAL DESCRIPTION [SETTAGS: TAG1,TAG2,TAG3] - add new feed to database"
            self.sendmsg(tojid, fromjid, msgstr)

        elif bodyp[0] == 'showmyprivate' or bodyp[0] == '?***':
            myprivate = ''
            for f in self.dbfeeds:
                if f[7] == fromjid and f[6] == 1:
                    if f[8]:
                        tags = " SETTAGS: " + f[8]
                    else:
                        tags = ''
                    myprivate += '\n+ ' + f[0] + ' ' + f[1] + ' ' + str(f[2]) + \
                                 ' ' + f[4] + tags
            self.sendmsg(tojid, fromjid, myprivate)
        elif bodyp[0] == 'showmyfeeds' or bodyp[0] == '?~':
            myfeeds = ''
            for f in self.dbfeeds:
                if f[7] == fromjid:
                    if f[8]:
                        tags = " SETTAGS: " + f[8]
                    else:
                        tags = ''
                    myfeeds += '\n+ ' + f[0] + ' ' + f[1] + ' ' + str(f[2]) + \
                               ' ' + f[4] + tags
            self.sendmsg(tojid, fromjid, myfeeds)

        elif (bodyp[0] == 'settags' or bodyp[0] == '=#') and len(bodyp) > 2 and \
                (any(fromjid == f[7] for f in self.dbfeeds) or fromjid in self.admins):
            if bodyp[1] != ':':
                feedname = bodyp[1]
            if any(f[0] == feedname for f in self.dbfeeds):
                newtags = body[body.rfind(bodyp[2]):]
                newtags = re.sub(' *, *', ',', newtags.strip().lower())
                self.dbCurTT.execute("UPDATE feeds SET tags = %s WHERE feedname = %s",
                                     (newtags, feedname,))
                self.dbCurTT.commit()
                self.dbfeeds = self.dbCurTT.dbfeeds()
                self.sendmsg(tojid, fromjid,
                             "New tags for " + feedname + ": " + newtags)
            else:
                self.sendmsg(tojid, fromjid, "Can't find this feed")
        elif (bodyp[0] == 'setupd' or bodyp[0] == '=@') and len(bodyp) == 3 and \
                (any(fromjid == f[7] for f in self.dbfeeds) or fromjid in self.admins) and \
                bodyp[2].isdigit():
            newupd = int(bodyp[2])
            if newupd < 60:
                newupd = 60
            if bodyp[1] != ':':
                feedname = bodyp[1]
            if any(f[0] == feedname for f in self.dbfeeds):
                self.dbCurTT.execute("UPDATE feeds SET timeout = %s WHERE feedname = %s",
                                     (newupd, feedname,))
                self.dbCurTT.commit()
                self.dbfeeds = self.dbCurTT.dbfeeds()
                self.sendmsg(tojid, fromjid, "New update interval for " + feedname +
                             ": " + str(newupd) + ' seconds')
            else:
                self.sendmsg(tojid, fromjid, "Can't find this feed")
        elif (bodyp[0] == 'setdesc' or bodyp[0] == '=:') and len(bodyp) > 2 and \
                (any(fromjid == f[7] for f in self.dbfeeds) or fromjid in self.admins):
            if bodyp[1] != ':':
                feedname = bodyp[1]
            if any(f[0] == feedname for f in self.dbfeeds):
                newdesc = body[body.rfind(bodyp[2]):].strip()
                self.dbCurTT.execute("UPDATE feeds SET description = %s WHERE feedname = %s",
                                     (newdesc, feedname,))
                self.dbCurTT.commit()
                self.dbfeeds = self.dbCurTT.dbfeeds()
                self.sendmsg(tojid, fromjid,
                             "New description for " + feedname + ": " + newdesc)
            else:
                self.sendmsg(tojid, fromjid, "Can't find this feed")
        elif (bodyp[0] == 'setuniq' or bodyp[0] == '=()') and len(bodyp) == 3 and \
                (any(fromjid == f[7] for f in self.dbfeeds) or fromjid in self.admins):
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
                self.dbCurTT.execute("UPDATE feeds SET checktype = %s WHERE feedname = %s",
                                     (newuniq, feedname,))
                self.dbCurTT.commit()
                self.dbfeeds = self.dbCurTT.dbfeeds()
                self.sendmsg(tojid, fromjid, "New news uniqueness check type for " +
                             feedname + ": " + bodyp[2])
            else:
                self.sendmsg(tojid, fromjid, "Can't find this feed")

        elif bodyp[0] == 'showtags' or bodyp[0] == '?#':
            if len(bodyp) > 1:
                feedname = bodyp[1]
            for i in (f[8] for f in self.dbfeeds if f[0] == feedname):
                self.sendmsg(tojid, fromjid, i)
        elif bodyp[0] == 'showupd' or bodyp[0] == '?@':
            if len(bodyp) > 1:
                feedname = bodyp[1]
            for i in (f[2] for f in self.dbfeeds if f[0] == feedname):
                self.sendmsg(tojid, fromjid,
                             'Feed update interval: ' + str(i) + ' seconds')
        elif bodyp[0] == 'showdesc' or bodyp[0] == '?:':
            if len(bodyp) > 1:
                feedname = bodyp[1]
            for i in (f[4] for f in self.dbfeeds if f[0] == feedname):
                self.sendmsg(tojid, fromjid, i)
        elif bodyp[0] == 'showadap' or bodyp[0] == '?%':
            if len(bodyp) > 1:
                feedname = bodyp[1]
            if feedname in self.adaptime:
                self.sendmsg(tojid, fromjid, 'Feed real update interval: ' +
                             str(self.adaptime[feedname]) + ' seconds')
        elif bodyp[0] == 'showuniq' or bodyp[0] == '?()':
            if len(bodyp) > 1:
                feedname = bodyp[1]
            for i in (f[9] for f in self.dbfeeds if f[0] == feedname):
                if i == 1:
                    myuniq = 'title'
                elif i == 2:
                    myuniq = 'content'
                else:
                    myuniq = 'link'
                self.sendmsg(tojid, fromjid,
                             'News uniqueness check type: ' + myuniq)

        elif (bodyp[0] in ('setposfilter', 'setnegfilter', '=+', '=-')):
            if len(bodyp) > 1:
                myfilter = body[body.rfind(bodyp[1]):].strip()
                if len(myfilter) < 255:
                    print("New filter: " + myfilter)
                    if bodyp[0] in ('setposfilter', '=+'):
                        self.dbCurTT.execute("UPDATE subscribers SET posfilter = %s "
                                             "WHERE feedname = %s AND jid = %s",
                                             (myfilter, feedname, fromjid,))
                        self.sendmsg(tojid, fromjid, "New positive filter for " +
                                     feedname + ": " + myfilter)
                    else:
                        self.dbCurTT.execute("UPDATE subscribers SET negfilter = %s "
                                             "WHERE feedname = %s AND jid = %s",
                                             (myfilter, feedname, fromjid,))
                        self.sendmsg(tojid, fromjid, "New negative filter for " +
                                     feedname + ": " + myfilter)
                else:
                    print("Filter too long")
                    self.sendmsg(tojid, fromjid, "Filter too long")
            else:
                print("No filter")
                if bodyp[0] in ('setposfilter', '=+'):
                    self.dbCurTT.execute("UPDATE subscribers SET posfilter = NULL "
                                         "WHERE feedname = %s AND jid = %s",
                                         (feedname, fromjid,))
                    self.sendmsg(tojid, fromjid, "Positive filter for " + feedname +
                                 " cleared")
                else:
                    self.dbCurTT.execute("UPDATE subscribers SET negfilter = NULL "
                                         "WHERE feedname = %s AND jid = %s",
                                         (feedname, fromjid,))
                    self.sendmsg(tojid, fromjid, "Negative filter for " + feedname +
                                 " cleared")
            self.dbCurTT.commit()
        elif (bodyp[0] == 'showfilter' or bodyp[0] == '?+-') and len(bodyp) < 3:
            if len(bodyp) == 2:
                feedname = bodyp[1]
            self.dbCurTT.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            self.dbCurTT.execute("SELECT posfilter, negfilter FROM subscribers "
                                 "WHERE feedname = %s AND jid = %s",
                                 (feedname, fromjid,))
            myfilter = self.dbCurTT.fetchone()
            if myfilter[0]:
                posfilter = myfilter[0]
            else:
                posfilter = ''
            if myfilter[1]:
                negfilter = myfilter[1]
            else:
                negfilter = ''
            self.sendmsg(tojid, fromjid, "Filters for " + feedname +
                         ":\nPositive (include): " + posfilter +
                         "\nNegative (exclude): " + negfilter)

        elif (bodyp[0] == 'setshort' or bodyp[0] == '=...') and len(bodyp) == 2 and \
                bodyp[1].isdigit():
            self.dbCurTT.execute("UPDATE subscribers SET short = %s WHERE feedname = %s "
                                 "AND jid = %s", (bodyp[1], feedname, fromjid,))
            self.dbCurTT.commit()
            msg = str(bodyp[1])
            if msg == '0':
                msg = 'unlimited'
            elif msg == '1':
                msg = 'title only'
            elif msg == '2':
                msg = '1st sentence'
            elif msg == '3':
                msg = '1st paragraph'
            self.sendmsg(tojid, fromjid,
                         "Maximum size for " + feedname + " is set to " + msg)
        elif bodyp[0] == 'showshort' or bodyp[0] == '?...':
            if len(bodyp) > 1:
                feedname = bodyp[1]
            self.dbCurTT.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            self.dbCurTT.execute("SELECT short FROM subscribers WHERE feedname = %s "
                                 "AND jid = %s", (feedname, fromjid,))
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
            if any((fromjid == f[7] or fromjid in self.admins) and f[0] == feedname
                   for f in self.dbfeeds) and feedname is not None:
                self.dbCurTT.execute("UPDATE feeds SET private = 1 WHERE feedname = %s "
                                     "AND registrar = %s", (feedname, fromjid,))
                self.dbCurTT.commit()
                self.dbfeeds = self.dbCurTT.dbfeeds()
                self.sendmsg(tojid, fromjid,
                             "Feed " + feedname + " is now hidden from search")
            else:
                self.sendmsg(tojid, fromjid,
                             "Can't find this feed or you are not owner")
        elif (bodyp[0] == 'unhide' or bodyp[0] == '+++') and len(bodyp) < 3:
            if len(bodyp) == 2:
                feedname = bodyp[1]
            if any((fromjid == f[7] or fromjid in self.admins) and f[0] == feedname
                   for f in self.dbfeeds) and feedname is not None:
                self.dbCurTT.execute("UPDATE feeds SET private = 0 WHERE feedname = %s "
                                     "AND registrar = %s", (feedname, fromjid,))
                self.dbCurTT.commit()
                self.dbfeeds = self.dbCurTT.dbfeeds()
                self.sendmsg(tojid, fromjid,
                             "Feed " + feedname + " is now visible in search")
            else:
                self.sendmsg(tojid, fromjid,
                             "Can't find this feed or you are not owner")

        elif (bodyp[0] == 'mute' or bodyp[0] == '~~~') and len(bodyp) < 3:
            if len(bodyp) == 2:
                feedname = bodyp[1]
            self.dbCurTT.execute("UPDATE subscribers SET mute = TRUE WHERE feedname = %s "
                                 "AND jid = %s", (feedname, fromjid,))
            self.sendmsg(tojid, fromjid, "Feed " + feedname + " muted")
            self.dbCurTT.commit()
        elif (bodyp[0] == 'unmute' or bodyp[0] == '@@@') and len(bodyp) < 3:
            if len(bodyp) == 2:
                feedname = bodyp[1]
            self.dbCurTT.execute("UPDATE subscribers SET mute = FALSE WHERE feedname = %s "
                                 "AND jid = %s", (feedname, fromjid,))
            self.sendmsg(tojid, fromjid, "Feed " + feedname + " unmuted")
            self.dbCurTT.commit()

        elif len(bodyp) == 1 and feedname is not None and bodyp[0].isdigit() and \
                21 > int(bodyp[0]) > 0:
            self.dbCurTT.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            self.dbCurTT.execute("SELECT title, author, link, content FROM sent "
                                 "WHERE feedname = %s AND link IS NOT NULL GROUP BY "
                                 "link ORDER BY income DESC LIMIT %s",
                                 (feedname, int(bodyp[0])))
            news = self.dbCurTT.fetchall()
            self.dbCurTT.execute("SELECT jid, posfilter, negfilter, short FROM "
                                 "subscribers WHERE feedname = %s AND jid = %s",
                                 (feedname, fromjid))
            jids = self.dbCurTT.fetchall()
            for msgrow in reversed(news):
                self.sendItem(feedname, {'title': msgrow[0], 'author': msgrow[1],
                                         'link': msgrow[2], 'summary': msgrow[3]},
                              jids)

        elif (bodyp[0] == 'search' or bodyp[0] == '?') and len(bodyp) > 1 and \
                feedname is not None:
            searchstr = '%' + body[len(bodyp[0]) + 1:] + '%'
            self.dbCurTT.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            self.dbCurTT.execute("SELECT title, author, link, DATE_FORMAT(income, "
                                 "'%%Y-%%m-%%d %%H:%%i') FROM sent WHERE feedname = "
                                 "%s AND (author LIKE %s OR title LIKE %s OR content "
                                 "LIKE %s) AND link IS NOT NULL ORDER BY income ASC "
                                 "LIMIT 10", (feedname, searchstr, searchstr, searchstr))
            self.printsearch(self.dbCurTT.fetchall(), tojid, fromjid, None, feedname)
        elif (bodyp[0] == 'searchall' or bodyp[0] == '?!') and len(bodyp) > 1:
            searchstr = '%' + body[len(bodyp[0]) + 1:] + '%'
            self.dbCurTT.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            self.dbCurTT.execute("SELECT title, author, link, DATE_FORMAT(income, "
                                 "'%%Y-%%m-%%d %%H:%%i'), feedname FROM sent WHERE "
                                 "(author LIKE %s OR title LIKE %s OR content LIKE %s) "
                                 "AND link IS NOT NULL ORDER BY income ASC LIMIT 10",
                                 (searchstr, searchstr, searchstr))
            self.printsearch(self.dbCurTT.fetchall(), tojid, fromjid, True, None)
        elif (bodyp[0] == 'searchintag' or bodyp[0] == '?!#') and len(bodyp) > 2:
            searchstr = '%' + body[body.rfind(bodyp[2]):] + '%'
            searchtag = '%' + bodyp[1] + '%'
            self.dbCurTT.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            self.dbCurTT.execute("SELECT title, author, link, DATE_FORMAT(income, "
                                 "'%%Y-%%m-%%d %%H:%%i'), sent.feedname FROM sent "
                                 "INNER JOIN feeds ON sent.feedname = feeds.feedname "
                                 "WHERE (author LIKE %s OR title LIKE %s OR content "
                                 "LIKE %s) AND link IS NOT NULL AND feeds.tags LIKE "
                                 "%s GROUP BY link ORDER BY income ASC LIMIT 10",
                                 (searchstr, searchstr, searchstr, searchtag))
            self.printsearch(self.dbCurTT.fetchall(), tojid, fromjid, True, None)
        elif (bodyp[0] == 'searchtitle' or bodyp[0] == '?!*') and len(bodyp) > 1:
            searchstr = '%' + body[len(bodyp[0]) + 1:] + '%'
            self.dbCurTT.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            self.dbCurTT.execute("SELECT title, author, link, DATE_FORMAT(income, "
                                 "'%%Y-%%m-%%d %%H:%%i'), feedname FROM sent WHERE "
                                 "title LIKE %s AND link IS NOT NULL ORDER BY income "
                                 "ASC LIMIT 10", (searchstr, ))
            self.printsearch(self.dbCurTT.fetchall(), tojid, fromjid, True, None)

        elif bodyp[0] == 'top':
            self.dbCurTT.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            if len(bodyp) == 1 or bodyp[1] == 'today':
                self.dbCurTT.execute("SELECT feedname, count(feedname) FROM sent WHERE "
                                     "income >= CURDATE() GROUP BY feedname ORDER BY "
                                     "count(feedname) DESC LIMIT 10")
            elif bodyp[1] == 'day' or bodyp[1] == 'd':
                self.dbCurTT.execute("SELECT feedname, count(feedname) FROM sent WHERE "
                                     "income >= NOW() - INTERVAL 1 DAY GROUP BY "
                                     "feedname ORDER BY count(feedname) DESC LIMIT 10")
            elif bodyp[1] == 'week' or bodyp[1] == 'w':
                self.dbCurTT.execute("SELECT feedname, count(feedname) FROM sent WHERE "
                                     "income >= NOW() - INTERVAL 1 WEEK GROUP BY "
                                     "feedname ORDER BY count(feedname) DESC LIMIT 10")
            elif bodyp[1] == 'month' or bodyp[1] == 'm':
                self.dbCurTT.execute("SELECT feedname, count(feedname) FROM sent WHERE "
                                     "income >= NOW() - INTERVAL 1 MONTH GROUP BY "
                                     "feedname ORDER BY count(feedname) DESC LIMIT 10")
            else:
                self.sendmsg(tojid, fromjid, "Incorrect period!")
                return
            msg = ''
            for val in self.dbCurTT.fetchall():
                msg += str("%04d" % (val[1],)) + ' | ' + val[0] + '@' + self.name + '\n'
            if msg:
                self.sendmsg(tojid, fromjid, "Top 10 feeds:\nNews | Feedname\n" + msg)

    def printsearch(self, data, tojid, fromjid, inall=None, feedname=None):
        if len(data) > 0:
            msg = 'Found '
            msg += str(len(data)) + ' results'
            if not inall:
                msg += ' in ' + feedname
            msg += ':\n'
            for article in data:
                if article[0] is not None:
                    msg += article[0]
                else:
                    msg += 'No title'
                if article[1] is not None:
                    msg += ' (by ' + article[1] + ')'
                msg += ' @ ' + str(article[3])
                if inall:
                    msg += ' in ' + article[4]
                msg += ': ' + article[2] + '\n\n'
            self.sendmsg(tojid, fromjid, msg)
        else:
            self.sendmsg(tojid, fromjid, 'Nothing found')