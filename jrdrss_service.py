# -*- coding: utf-8 -*-
#
# JRSS  Python 3 Jabber RSS transport.
#
# Service module: IQ handlers (version/last/time/ping/stats/register/search),
# vCard, service discovery, and the small stanza classes used for routing
# incoming IQ requests.

import asyncio
import base64
import io
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import feedparser
from pymysql.err import IntegrityError as MySQLIntegrityError
import slixmpp
from slixmpp import Iq, register_stanza_plugin
from slixmpp.exceptions import XMPPError
from slixmpp.plugins.xep_0030.stanza import DiscoItems, DiscoInfo
from slixmpp.xmlstream import ElementBase

from jrdrss_adhoc import (ADHOC_COMMANDS, ADHOC_NODE_NAMES, ADHOC_NAMES,
                          ADHOC_ROOT_COMMANDS, ADHOC_ROOT_NAMES,
                          COMMANDS_NS)
from jrdrss_config import Image, lh, programmVersion


# ---------------------------------------------------------------------------
# Small stanza classes - only used for routing incoming IQ requests.
# ---------------------------------------------------------------------------

class Version(ElementBase):
    name = 'query'
    namespace = 'jabber:iq:version'
    plugin_attrib = 'version'
    interfaces = set()


class LastQuery(ElementBase):
    name = 'query'
    namespace = 'jabber:iq:last'
    plugin_attrib = 'last'
    interfaces = set()


class Ping(ElementBase):
    name = 'ping'
    namespace = 'urn:xmpp:ping'
    plugin_attrib = 'ping'
    interfaces = set()


class TimeStanza(ElementBase):
    name = 'time'
    namespace = 'urn:xmpp:time'
    plugin_attrib = 'time'
    interfaces = set()


class StatsQuery(ElementBase):
    name = 'query'
    namespace = 'http://jabber.org/protocol/stats'
    plugin_attrib = 'stats'
    interfaces = set()


class RegisterQuery(ElementBase):
    name = 'query'
    namespace = 'jabber:iq:register'
    plugin_attrib = 'register'
    interfaces = set()


class SearchQuery(ElementBase):
    name = 'query'
    namespace = 'jabber:iq:search'
    plugin_attrib = 'search'
    interfaces = set()


class VCardStanza(ElementBase):
    name = 'vCard'
    namespace = 'vcard-temp'
    plugin_attrib = 'vcard'
    interfaces = set()


for _cls in (Version, LastQuery, Ping, TimeStanza, StatsQuery,
             RegisterQuery, SearchQuery, VCardStanza):
    register_stanza_plugin(Iq, _cls)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def make_el(ns, tag, text=None, attrs=None):
    e = ET.Element('{%s}%s' % (ns, tag))
    if attrs:
        for k, v in attrs.items():
            e.set(k, v)
    if text is not None:
        e.text = text
    return e


def find_form_value(xml, var):
    """Return text of <value> for a jabber:x:data <field var=...>, or None."""
    for field in xml.iter():
        if field.tag == '{jabber:x:data}field' and field.get('var') == var:
            value = None
            for child in field:
                if child.tag == '{jabber:x:data}value':
                    value = child.text or ''
            return value
    return None


class ServiceMixin:
    """IQ / vCard / service discovery handlers. Mixed into Transport."""

    # -- IQ handlers -------------------------------------------------------

    def get_version(self, iq):
        reply = iq.reply()
        q = make_el('jabber:iq:version', 'query')
        q.append(make_el('jabber:iq:version', 'name', 'Jabber RSS Transport'))
        q.append(make_el('jabber:iq:version', 'version', programmVersion))
        q.append(make_el('jabber:iq:version', 'os',
                         'Python ' + sys.version.split()[0] + ' + Slixmpp ' +
                         slixmpp.__version__))
        reply.set_payload(q)
        self._send(reply)
        return 1

    def get_last(self, iq):
        reply = iq.reply()
        if reply['from'].bare == self.name:
            seconds = str(int(time.time()) - self.start_time)
        else:
            if reply['from'].node in self.last_upd:
                seconds = str(int(time.time() - self.last_upd[reply['from'].node]))
            else:
                return 0
        q = make_el('jabber:iq:last', 'query', attrs={'seconds': seconds})
        reply.set_payload(q)
        self._send(reply)
        return 1

    def pingpong(self, iq):
        self._send(iq.reply())
        return 1

    def get_time(self, iq):
        reply = iq.reply()
        q = make_el('urn:xmpp:time', 'time')
        q.append(make_el('urn:xmpp:time', 'tzo', '+02:00'))
        q.append(make_el('urn:xmpp:time', 'utc',
                         time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))
        reply.set_payload(q)
        self._send(reply)
        return 1

    def get_stats(self, iq):
        reply = iq.reply()
        q = make_el('http://jabber.org/protocol/stats', 'query')

        q.append(make_el('http://jabber.org/protocol/stats', 'stat', attrs={
            'name': 'time/uptime', 'units': 'seconds',
            'value': str(int(time.time()) - self.start_time)}))

        hourly = daily = 0
        for feed in self.lasthournew:
            hourly += self.lasthournew[feed]
        for feed in self.new:
            daily += self.new[feed]

        q.append(make_el('http://jabber.org/protocol/stats', 'stat', attrs={
            'name': 'news/hourly', 'units': 'news', 'value': str(hourly)}))
        q.append(make_el('http://jabber.org/protocol/stats', 'stat', attrs={
            'name': 'news/daily', 'units': 'news', 'value': str(daily)}))

        a = sum(1 for feed in self.dbfeeds if feed[5] != 0)
        q.append(make_el('http://jabber.org/protocol/stats', 'stat', attrs={
            'name': 'feeds/active', 'units': 'feeds', 'value': str(a)}))
        q.append(make_el('http://jabber.org/protocol/stats', 'stat', attrs={
            'name': 'feeds/total', 'units': 'feeds', 'value': str(len(self.dbfeeds))}))

        reply.set_payload(q)
        self._send(reply)
        return 1

    def get_register(self, iq):
        if iq['to'].bare != self.name:
            raise XMPPError('feature-not-implemented')
        if not self.regallow and iq['from'].bare not in self.admins:
            raise XMPPError('not-acceptable')

        reply = iq.reply()
        q = make_el('jabber:iq:register', 'query')
        form = make_el('jabber:x:data', 'x', attrs={'type': 'form'})
        q.append(form)
        form.append(make_el('jabber:x:data', 'title', 'New RSS feed registration'))

        def field(var, label, ftype='text-single', required=False):
            f = make_el('jabber:x:data', 'field', attrs={
                'type': ftype, 'var': var, 'label': label})
            if required:
                f.append(make_el('jabber:x:data', 'required'))
            form.append(f)
            return f

        field('feedname', "Feed's name", required=True)
        field('url', 'URL', required=True)
        field('desc', 'Description', required=True)
        field('tags', 'Tags (comma separated)')

        checkBox = field('tosubscribe', 'Subscribe', 'boolean')
        checkBox.append(make_el('jabber:x:data', 'value', '1'))
        checkBox = field('private', 'Private', 'boolean')
        checkBox.append(make_el('jabber:x:data', 'value', '0'))

        tmup = field('timeout', 'Refresh interval, min', 'list-single')
        tmup.append(make_el('jabber:x:data', 'value', '60'))
        for t in ['1', '2', '5', '10', '15', '30', '60', '120', '240', '300',
                  '600', '900', '1440']:
            topt = make_el('jabber:x:data', 'option', attrs={'label': t})
            topt.append(make_el('jabber:x:data', 'value', t))
            tmup.append(topt)

        ctyp = field('checktype', 'News uniqueness', 'list-single')
        ctyp.append(make_el('jabber:x:data', 'value', 'By link only'))
        for t in ['By link only', 'By link + title', 'By link + title + content']:
            ctopt = make_el('jabber:x:data', 'option', attrs={'label': t})
            ctopt.append(make_el('jabber:x:data', 'value', t))
            ctyp.append(ctopt)

        reply.set_payload(q)
        self._send(reply)
        return 1

    def set_register(self, iq):
        if iq['to'].bare != self.name:
            raise XMPPError('feature-not-implemented')

        payload = iq.xml
        fname = find_form_value(payload, 'feedname')
        furl = find_form_value(payload, 'url')
        fdesc = find_form_value(payload, 'desc')
        fsubs = find_form_value(payload, 'tosubscribe')
        fpriv = find_form_value(payload, 'private')
        ftime = find_form_value(payload, 'timeout')
        ftags = find_form_value(payload, 'tags')
        ctype = find_form_value(payload, 'checktype')

        if fname is None or furl is None or fdesc is None:
            raise XMPPError('not-acceptable')

        fname = fname.lower()
        if (fname == '' or furl == '' or fdesc == '' or
                any(ch in fname for ch in ':<>&@"\\/ ') or
                (not furl.startswith('http://') and not furl.startswith('https://'))):
            raise XMPPError('not-acceptable')

        domain = urllib.parse.urlparse(furl)[1]
        furl = furl.replace('//%s/' % domain, '//%s/' % domain.lower())

        fsubs = (fsubs == "1") if fsubs else False
        if ftime:
            ftime = int(ftime)
        if fpriv:
            fpriv = int(fpriv)
        if ftags:
            ftags = re.sub(' *, *', ',', ftags.lower().strip())
            if len(ftags) > 255:
                raise XMPPError('not-acceptable')

        if self.isFeedNameRegistered(fname) or self.isFeedUrlRegistered(furl):
            raise XMPPError('conflict')

        iqres = iq.reply()
        iqerr = iq.reply()
        iqerr['type'] = 'error'
        iqerr['error']['condition'] = 'not-acceptable'
        iqerr['error']['type'] = 'cancel'
        asyncio.create_task(asyncio.to_thread(
            self.regThread, iqres, iqerr, fname, furl, fdesc,
            fsubs, ftime, fpriv, ftags, ctype))
        return 1

    def regThread(self, iqres, iqerr, fname, furl, fdesc, fsubs, ftime, fpriv,
                  ftags, ctype):
        try:
            d = feedparser.parse(furl)
            bozo = d["bozo"]
        except:
            self._send(iqerr)
            return
        if bozo == 1:
            self._send(iqerr)
            return
        if ftime:
            ftime = ftime * 60
        else:
            ftime = 60
        if ftime < 60:
            ftime = 60
        if ctype == 'By link + title':
            ctype = 1
        elif ctype == 'By link + title + content':
            ctype = 2
        else:
            ctype = 0
        registrar = iqres['to'].bare
        try:
            self.dbCurRT.execute("INSERT INTO feeds (feedname, url, description, "
                                 "timeout, private, registrar, tags, checktype) "
                                 "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                                 (fname, furl, fdesc, ftime, fpriv, registrar,
                                  ftags, ctype))
        except MySQLIntegrityError:
            self._send(iqerr)
            return
        self.last_upd[fname] = 0
        self.dbfeeds = self.dbCurRT.dbfeeds()
        self.dbCurRT.commit()
        self._send(iqres)
        if fsubs:
            self._send(self.Presence(stype="subscribe",
                                     sfrom=fname + '@' + self.name,
                                     sto=iqres['to'].bare))

    def get_search(self, iq):
        reply = iq.reply()
        q = make_el('jabber:iq:search', 'query')
        q.append(make_el('jabber:iq:search', 'instructions', 'Enter a keyword'))
        form = make_el('jabber:x:data', 'x', attrs={'type': 'form'})
        q.append(form)
        formType = make_el('jabber:x:data', 'field',
                           attrs={'type': 'hidden', 'var': 'FORM_TYPE'})
        formType.append(make_el('jabber:x:data', 'value', 'jabber:iq:search'))
        form.append(formType)
        text = make_el('jabber:x:data', 'field',
                       attrs={'type': 'text-single', 'label': 'Search',
                              'var': 'searchField'})
        form.append(text)
        reply.set_payload(q)
        self._send(reply)
        return 1

    def set_search(self, iq):
        fromjid = iq['from'].bare
        searchField = find_form_value(iq.xml, 'searchField')
        if not searchField:
            raise XMPPError('not-acceptable')
        searchField = '%' + searchField.replace('%', '\\%') + '%'
        if searchField == '%%' or len(searchField) < 5:
            raise XMPPError('not-acceptable')
        self.dbCurST.commit()
        self.dbCurST.execute("SELECT feedname, description, url, subscribers, "
                             "timeout FROM feeds WHERE (feedname LIKE %s OR "
                             "description LIKE %s OR url LIKE %s OR tags LIKE %s) "
                             "AND (private = '0' OR (private = '1' AND registrar = %s))",
                             (searchField, searchField, searchField, searchField, fromjid))
        a = self.dbCurST.fetchall()
        print(a)

        reply = iq.reply()
        q = make_el('jabber:iq:search', 'query')
        form = make_el('jabber:x:data', 'x', attrs={'type': 'result'})
        q.append(form)

        formType = make_el('jabber:x:data', 'field',
                           attrs={'type': 'hidden', 'var': 'FORM_TYPE'})
        formType.append(make_el('jabber:x:data', 'value', 'jabber:iq:search'))
        form.append(formType)

        def report_field(var, label, ftype):
            f = make_el('jabber:x:data', 'field',
                        attrs={'var': var, 'label': label, 'type': ftype})
            reported.append(f)

        reported = make_el('jabber:x:data', 'reported')
        form.append(reported)
        report_field('jid', 'JID', 'jid-single')
        report_field('url', 'URL', 'text-single')
        report_field('desc', 'Description', 'text-single')
        report_field('subscribers', 'Users', 'text-single')
        report_field('timeout', 'Update interval', 'text-single')

        for d in a:
            item = make_el('jabber:x:data', 'item')
            form.append(item)

            jidField = make_el('jabber:x:data', 'field', attrs={'var': 'jid'})
            jidField.append(make_el('jabber:x:data', 'value',
                                    d[0] + '@' + self.name))
            item.append(jidField)

            urlField = make_el('jabber:x:data', 'field', attrs={'var': 'url'})
            urlField.append(make_el('jabber:x:data', 'value', d[2]))
            item.append(urlField)

            descField = make_el('jabber:x:data', 'field', attrs={'var': 'desc'})
            descField.append(make_el('jabber:x:data', 'value', d[1]))
            item.append(descField)

            sbsField = make_el('jabber:x:data', 'field', attrs={'var': 'subscribers'})
            sbsField.append(make_el('jabber:x:data', 'value', str(d[3])))
            item.append(sbsField)

            timeField = make_el('jabber:x:data', 'field', attrs={'var': 'timeout'})
            timeField.append(make_el('jabber:x:data', 'value', str(d[4] // 60)))
            item.append(timeField)

        reply.set_payload(q)
        self._send(reply)
        return 1

    # -- vCard -------------------------------------------------------------

    def getlogo(self, url):
        if self.iconlogo:
            base = urllib.parse.urlparse(url)[0] + '://' + \
                   urllib.parse.urlparse(url)[1]

            def makerq(url):
                rq = urllib.request.Request(
                    url, headers={'User-agent': 'Mozilla/5.0 (X11; Linux '
                                  'x86_64; rv:52.0) Gecko/20100101 '
                                  'Firefox/52.0'})
                try:
                    return urllib.request.urlopen(rq, timeout=5)
                except Exception as msg:
                    raise Exception(msg)

            ico = ''
            try:
                ico = makerq(base + '/favicon.ico')
            except Exception:
                try:
                    doc = lh.parse(makerq(base))
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
                    if ico.find("http") != 0:
                        if ico.startswith('//'):
                            ico = urllib.parse.urlparse(url)[0] + ':' + ico
                        elif ico.startswith('/'):
                            ico = base + ico
                        else:
                            ico = base + '/' + ico
                    try:
                        ico = makerq(ico)
                    except Exception:
                        ico = None

            if ico not in ('', None):
                try:
                    png = Image.open(ico)
                    imgtmp = io.BytesIO()
                    png.save(imgtmp, format="PNG")
                    return base64.b64encode(imgtmp.getvalue()).decode('ascii')
                except Exception:
                    return self.rsslogo
            else:
                return self.rsslogo
        return self.rsslogo

    def get_vCard(self, iq):
        reply = iq.reply()
        q = make_el('vcard-temp', 'vCard')

        if iq['to'].bare == self.name:
            q.append(make_el('vcard-temp', 'FN', 'JRD RSS Transport'))
            q.append(make_el('vcard-temp', 'NICKNAME', 'RSS'))
            q.append(make_el('vcard-temp', 'DESC', 'RSS transport component'))
            q.append(make_el('vcard-temp', 'BDAY', '2008-03-19'))
            q.append(make_el('vcard-temp', 'ROLE',
                             'Создаю ботов для получения новостей через RSS'))
            q.append(make_el('vcard-temp', 'URL',
                             'https://github.com/jabberworld/jrd_rss'))
            transav = make_el('vcard-temp', 'PHOTO')
            transav.append(make_el('vcard-temp', 'BINVAL', self.rsslogo))
            transav.append(make_el('vcard-temp', 'TYPE', 'image/png'))
            q.append(transav)
        else:
            nick = iq['to'].node
            for feedstr in self.dbfeeds:
                if feedstr[0] == nick:
                    url = feedstr[1]
                    bday = feedstr[3]
                    if self.adaptive and nick in self.adaptime and \
                            self.adaptime[nick] != feedstr[2]:
                        real = '(adaptive: ' + str(int(self.adaptime[nick] / 60)) + \
                               'mins)'
                    else:
                        real = ''
                    tags = ''
                    if feedstr[8]:
                        for tag in feedstr[8].replace(',', ', ').split():
                            tags += tag.capitalize().replace(',', ', ')
                    description = (feedstr[4] + '\nTags: ' + tags +
                                   '\nFeed update interval: ' + str(feedstr[2] // 60) +
                                   ' mins ' + real +
                                   '\nFeed subscribers: ' + str(feedstr[5]))
                    q.append(make_el('vcard-temp', 'NICKNAME', nick))
                    q.append(make_el('vcard-temp', 'DESC', description))
                    q.append(make_el('vcard-temp', 'URL', url))
                    q.append(make_el('vcard-temp', 'BDAY', str(bday)))
                    feedav = make_el('vcard-temp', 'PHOTO')
                    feedav.append(make_el('vcard-temp', 'BINVAL', self.getlogo(url)))
                    feedav.append(make_el('vcard-temp', 'TYPE', 'image/png'))
                    q.append(feedav)

        reply.set_payload(q)
        self._send(reply)
        return 1

    # -- service discovery -------------------------------------------------

    def mknode(self, disco_items, name, desc):
        newjid = name + '@' + self.name
        disco_items.add_item(newjid, name=name + ' (' + desc + ')')

    def browseitems(self, iq, node):
        disco_items = DiscoItems()
        fromjid = iq['from'].bare
        feedtags = {}
        for i in self.dbfeeds:
            if i[8]:
                tags = i[8].split(',')
                for tag in tags:
                    tag = tag.lower()
                    if tag not in feedtags:
                        feedtags[tag] = list()
                    feedtags[tag].append((i[0], i[4], i[6], i[7]))
        if (node is None or node == '') and not iq['to'].node:
            disco_items.add_item(self.name, node="feeds", name="Registered Feeds")
            disco_items.add_item(self.name, node="owner", name="I am registrar")
            disco_items.add_item(self.name, node="private", name="My private feeds")
            disco_items.add_item(self.name, node="tags", name="Categories")
        if node == "feeds":
            for i in self.dbfeeds:
                if not i[6] or (i[6] == 1 and fromjid == i[7]):
                    self.mknode(disco_items, i[0], i[4])
        elif node == "owner":
            for i in self.dbfeeds:
                if fromjid == i[7]:
                    self.mknode(disco_items, i[0], i[4])
        elif node == "private":
            for i in self.dbfeeds:
                if i[6] == 1 and fromjid == i[7]:
                    self.mknode(disco_items, i[0], i[4])
        elif node == "tags":
            for tag in sorted(feedtags):
                name = tag.replace(' ', '')
                desc = tag.capitalize()
                disco_items.add_item(self.name, node="tag:" + name, name=desc)
        else:
            for tag in feedtags:
                if node == 'tag:' + tag.replace(' ', ''):
                    for feed in feedtags[tag]:
                        if not feed[2] or (feed[2] == 1 and fromjid == feed[3]):
                            self.mknode(disco_items, feed[0], feed[1])
        return disco_items

    def disco_get_items(self, jid, node, ifrom, data):
        try:
            feedname = data['to'].node
        except Exception:
            feedname = None
        if node == COMMANDS_NS and feedname and \
                self.isFeedNameRegistered(feedname):
            disco_items = DiscoItems()
            for cnode, cname, _ in ADHOC_COMMANDS:
                disco_items.add_item(feedname + '@' + self.name, node=cnode,
                                     name=cname)
            return disco_items
        if node == COMMANDS_NS and not feedname:
            disco_items = DiscoItems()
            for cnode, cname, _ in ADHOC_ROOT_COMMANDS:
                disco_items.add_item(jid, node=cnode, name=cname)
            return disco_items
        if node in (None, '') and feedname and \
                self.isFeedNameRegistered(feedname):
            disco_items = DiscoItems()
            disco_items.add_item(feedname + '@' + self.name,
                                 node=COMMANDS_NS, name='Commands')
            return disco_items
        return self.browseitems(data, node)

    def disco_get_info(self, jid, node, ifrom, data):
        info = DiscoInfo()
        name = 'Jabber RSS Transport'
        feedname = jid.node
        if node == COMMANDS_NS and feedname and \
                self.isFeedNameRegistered(feedname):
            info.add_identity('automation', 'command-list', 'Ad-Hoc commands')
            info.add_feature(COMMANDS_NS)
            return info
        if node == COMMANDS_NS and not feedname:
            info.add_identity('automation', 'command-list', 'Ad-Hoc commands')
            info.add_feature(COMMANDS_NS)
            return info
        if node in ADHOC_ROOT_NAMES:
            info.add_identity('automation', 'command-node',
                              ADHOC_ROOT_NAMES.get(node, node))
            info.add_feature(COMMANDS_NS)
            return info
        if node in ADHOC_NODE_NAMES and feedname and \
                self.isFeedNameRegistered(feedname):
            info.add_identity('automation', 'command-node',
                              ADHOC_NAMES.get(node, node))
            info.add_feature(COMMANDS_NS)
            return info
        if feedname and self.isFeedNameRegistered(feedname):
            for f in self.dbfeeds:
                if f[0] == feedname:
                    name = '%s (%s)' % (f[0], f[4])
                    break
        elif node == 'feeds':
            name = 'Registered Feeds'
        elif node == 'owner':
            name = 'I am registrar'
        elif node == 'private':
            name = 'My private feeds'
        elif node == 'tags':
            name = 'Categories'
        elif node and node.startswith('tag:'):
            name = node[len('tag:'):].capitalize()
        info.add_identity('headline', 'rss', name)
        for feature in ('http://jabber.org/protocol/disco#info',
                        'http://jabber.org/protocol/disco#items',
                        'http://jabber.org/protocol/stats',
                        COMMANDS_NS,
                        'jabber:iq:version',
                        'jabber:iq:search',
                        'jabber:iq:register',
                        'jabber:iq:last',
                        'urn:xmpp:ping',
                        'urn:xmpp:time',
                        'vcard-temp'):
            info.add_feature(feature)
        return info