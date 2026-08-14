# -*- coding: utf-8 -*-
#
# JRSS  Python 3 Jabber RSS transport.
#
# Feed content processing: HTML summary cleaning, per-subscriber message
# formatting, and the feed updating mixin (checkrss / sendItem / isSent).

import asyncio
import re
import time

import feedparser


def clean_summary(summary):
    """Convert HTML summary into readable plain text (same chain as original)."""
    summary = re.sub('<br ?/?>', '\n', summary)
    summary = re.sub('<blockquote[^>]*>\n?', '> «', summary)
    summary = re.sub('\n +\n', '\n', summary)
    summary = re.sub('\n\n+', '\n', summary)
    summary = re.sub('\n?</blockquote>', '»\n', summary)
    summary = re.sub('<[^>]*>', '', summary)
    summary = re.sub('\n»', '»', summary)
    summary = re.sub('(?<!^)(?<!\n\n)>', '\n\n>', summary)
    summary = re.sub('»\n(?!\n)', '»\n\n', summary)
    summary = re.sub('^\n+', '', summary)
    summary = summary.replace("&#8203;", '')
    summary = summary.replace("&hellip;", "…")
    summary = summary.replace("&#8230;", "…")
    summary = summary.replace("&quot;", '"')
    summary = summary.replace("&nbsp;", " ")
    summary = summary.replace("&#160;", " ")
    summary = summary.replace("&ndash;", "–")
    summary = summary.replace("&mdash;", "—")
    summary = summary.replace("&#8211;", "–")
    summary = summary.replace("&#8594;", "→")
    summary = summary.replace("&laquo;", "«")
    summary = summary.replace("&raquo;", "»")
    summary = summary.replace("&#171;", "«")
    summary = summary.replace("&#187;", "»")
    summary = summary.replace("&ldquo;", "“")
    summary = summary.replace("&rdquo;", "”")
    summary = summary.replace("&bdquo;", "„")
    summary = summary.replace("&rsquo;", "’")
    summary = summary.replace("&lsquo;", "‘")
    summary = summary.replace("&#8217;", "'")
    summary = summary.replace("&#039;", "'")
    summary = summary.replace("&#8222;", "„")
    summary = summary.replace("&#8220;", "“")
    summary = summary.replace("&amp;", "&")
    summary = summary.replace("&lt;", "<")
    summary = summary.replace("&gt;", ">")
    return summary


def format_news_item(i, summary, jids):
    """Build message text for each subscriber row.

    jids rows: (jid, posfilter, negfilter, short[, mute]) - the 5-field form
    is only used when called from the regular update cycle.
    Returns a list of (bare_jid, text) tuples.
    """
    out = []
    title = i.get('title') or ''
    for ii in jids:
        if len(ii) >= 5:
            if ii[1] and not re.search(ii[1], title):
                print("Not matched positive")
                continue
            if ii[2] and re.search(ii[2], title):
                print("Matched negative")
                continue
            if ii[4]:
                print("Feed muted")
                continue

        if ii[3] == 1 or summary == '':
            body = ''
        elif ii[3] == 2:
            body = '\n\n' + re.split(r'\.|!|\?', summary)[0] + '\n\n'
        elif ii[3] == 3:
            body = '\n\n' + re.split(r'\n', summary)[0] + '\n\n'
        elif ii[3] != 0 and len(summary) > ii[3]:
            body = '\n\n' + summary[:ii[3]] + '...\n\n'
        else:
            body = '\n\n' + summary + '\n\n'

        author = ''
        if i.get('author') is not None:
            author = ' (by ' + str(i['author']) + ')'
        ttl = ''
        if i.get('title') is not None:
            ttl = '*' + i['title'] + '*'
        text = ttl + '\nLink: ' + str(i.get('link')) + author + body
        out.append((ii[0], text))
    return out


SAMPLE_FEED = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
<title>Test channel</title><link>http://example.com/</link>
<description>Demo</description>
<item><title>First &amp; Second</title><link>http://example.com/1</link>
<description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&amp;nbsp;!&lt;/p&gt;</description></item>
<item><title>Astral test 🙃</title><link>http://example.com/2</link>
<description>Plain summary</description></item>
</channel></rss>"""


class FeedMixin:
    """Feed update logic. Mixed into Transport, uses self.* helpers."""

    @staticmethod
    def strip_utf8mb4(mb4):
        return ''.join([c if len(c.encode('utf-8')) < 4 else '*' for c in mb4])

    async def update_loop(self):
        while True:
            if self._shutdown or not getattr(self, 'sessionstarted', False):
                await asyncio.sleep(15)
                continue
            try:
                self.idle()
            except Exception as e:
                print("Update loop error:", e)
            await asyncio.sleep(15)

    def idle(self):
        nowTime = int(time.time())
        if not self.idleflag:
            print("idle")
            self.idleflag = 1
        checkfeeds = []
        if not self.updating:
            for feed in self.dbfeeds:
                if feed[0] not in self.adaptime:
                    checkfeeds.append((feed[0], feed[1], feed[2], feed[9],))
                    self.adaptime[feed[0]] = feed[2]
                try:
                    if (nowTime - int(self.last_upd[feed[0]])) > self.adaptime[feed[0]]:
                        self.last_upd[feed[0]] = nowTime
                        checkfeeds.append((feed[0], feed[1], feed[2], feed[9],))
                except:
                    self.last_upd[feed[0]] = nowTime
            if checkfeeds:
                self.idleflag = 0
                print("UPDATE:"),
                print(checkfeeds)
                self.updating = 1
                asyncio.create_task(self._run_checkrss(checkfeeds))
        else:
            print("Update in progress")

    async def _run_checkrss(self, checkfeeds):
        try:
            await asyncio.to_thread(self.checkrss, checkfeeds)
        except Exception as e:
            print("checkrss error:", e)
        finally:
            self.updating = 0

    def checkrss(self, checkfeeds):
        for feed in checkfeeds:
            feedname = feed[0]
            if feedname not in self.times:
                self.times[feedname] = list()
            self.new[feedname] = 0
            self.lasthournew[feedname] = 0

            self.dbCurUT.execute("SELECT jid, posfilter, negfilter, short, mute "
                                 "FROM subscribers WHERE feedname = %s", (feedname,))
            jids = self.dbCurUT.fetchall()
            if len(jids) == 0:
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
                    self.botstatus(feedname, jids[0])
                    continue
                else:
                    print('Bozo flag: NonXMLContentType in ' + feedname)

            for i in reversed(d["items"]):
                flink = ftitle = fauthor = fsum = None
                if 'link' in i:
                    flink = i["link"][:254]
                if 'title' in i:
                    ftitle = self.strip_utf8mb4(i["title"][:254])
                if 'author' in i:
                    fauthor = self.strip_utf8mb4(i["author"][:126])
                if 'summary' in i:
                    fsum = self.strip_utf8mb4(i["summary"][:8190])
                if 'yandex_full-text' in i and fsum == '':
                    fsum = self.strip_utf8mb4(i["yandex_full-text"][:8190])

                if feed[3] == 1:
                    checkdata = (flink or '') + (ftitle or '')
                elif feed[3] == 2:
                    checkdata = (flink or '') + (ftitle or '') + (fsum or '')
                else:
                    checkdata = flink

                if not self.isSent(feedname, checkdata, feed[3]):
                    self.sendItem(feedname, i, jids)
                    self.times[feedname].append(time.time())
                    self.dbCurUT.execute("INSERT INTO sent (feedname, title, "
                                         "author, link, content) VALUES "
                                         "(%s, %s, %s, %s, %s)",
                                         (feedname, ftitle, fauthor, flink, fsum))
                    time.sleep(0.2)
                else:
                    self.dbCurUT.execute("UPDATE sent SET datetime = NOW() "
                                         "WHERE feedname = %s AND link = %s AND "
                                         "title = %s AND datetime < NOW() - "
                                         "INTERVAL %s DAY",
                                         (feedname, flink, ftitle, self.sentsize - 1))

            for ft in list(self.times[feedname]):
                if ft > time.time() - 86400:
                    self.new[feedname] += 1
                    if ft > time.time() - 3600:
                        self.lasthournew[feedname] += 1
                else:
                    self.times[feedname].remove(ft)

            if self.adaptive and self.lasthournew[feedname] > 0:
                self.adaptime[feedname] = int(3600 / self.lasthournew[feedname])
                if self.adaptime[feedname] < 60:
                    self.adaptime[feedname] = 60
                elif self.adaptime[feedname] > feed[2]:
                    self.adaptime[feedname] = int(feed[2])
            else:
                self.adaptime[feedname] = int(feed[2])

            print("End of update")
            self.botstatus(feedname, jids[0])

        # purging old records
        self.dbCurUT.execute("DELETE FROM sent WHERE datetime < NOW() - "
                             "INTERVAL %s DAY", (self.sentsize,))
        self.dbCurUT.commit()
        print("End of checkrss")

    def isSent(self, feedname, checkdata, checktype):
        if checktype == 1:
            self.dbCurUT.execute("SELECT count(feedname) FROM sent WHERE "
                                 "feedname = %s AND CONCAT(link, title) = %s",
                                 (feedname, checkdata))
        elif checktype == 2:
            self.dbCurUT.execute("SELECT count(feedname) FROM sent WHERE "
                                 "feedname = %s AND CONCAT(link, title, "
                                 "IFNULL(content, '')) = %s",
                                 (feedname, checkdata))
        else:
            self.dbCurUT.execute("SELECT count(feedname) FROM sent WHERE "
                                 "feedname = %s AND link = %s",
                                 (feedname, checkdata))
        a = self.dbCurUT.fetchone()
        return a[0] > 0

    def botstatus(self, feedname, jid):
        self.send_feed_presence(feedname, jid[0],
                                show=self.get_show(feedname),
                                status=self.get_status(feedname))

    def sendItem(self, feedname, i, jids):
        if (('summary' not in i or i['summary'] is None) and
                ('yandex_full-text' not in i or i['yandex_full-text'] is None)):
            summary = "No description"
        else:
            summary = i.get('summary')
            if 'yandex_full-text' in i and summary == '':
                summary = i.get('yandex_full-text')
            summary = clean_summary(summary)
        for bare_jid, text in format_news_item(i, summary, jids):
            self.sendmsg(feedname + '@' + self.name, bare_jid, text)