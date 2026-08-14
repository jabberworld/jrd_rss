# -*- coding: utf-8 -*-
#
# JRSS  Python 3 Jabber RSS transport.
#
# Ad-Hoc commands (XEP-0050) menu exposed on every feed JID. The commands
# reuse the same functions for viewing and changing feed parameters that
# are available as message commands in the help. The feed is known from
# the JID the command was sent to, so there is no feed selection step.
#
# Instead of registering one handler per feed (which would break when feeds
# are added or removed at runtime), the XEP-0050 API lookup is overridden
# dynamically: any JID under our domain with a known command node resolves
# to the corresponding handler.

import asyncio
import re

import feedparser

from slixmpp import JID

COMMANDS_NS = 'http://jabber.org/protocol/commands'

# (node, human name, method name on Transport)
ADHOC_COMMANDS = [
    ('view-info', 'Feed info', 'adhoc_view_info'),
    ('view-sub', 'My subscription', 'adhoc_view_sub'),
    ('edit-info', 'Edit feed info', 'adhoc_edit_info'),
    ('edit-sub', 'Edit subscription', 'adhoc_edit_sub'),
    ('edit-privacy', 'Feed privacy', 'adhoc_edit_privacy'),
]

ADHOC_NODE_NAMES = {item[0] for item in ADHOC_COMMANDS}
ADHOC_NAMES = {item[0]: item[1] for item in ADHOC_COMMANDS}

# Commands exposed only on the transport's own JID (root), not per feed.
# (node, human name, method name on Transport)
ADHOC_ROOT_COMMANDS = [
    ('register', 'Register new feed', 'adhoc_register'),
    ('my-feeds', 'Show my feeds', 'adhoc_myfeeds'),
    ('my-private', 'Show my private feeds', 'adhoc_myprivate'),
    ('feeds', 'Show all feeds', 'adhoc_feeds'),
    ('tags', 'Show Categories', 'adhoc_tags'),
]

ADHOC_ROOT_NAMES = {item[0]: item[1] for item in ADHOC_ROOT_COMMANDS}
ALL_ADHOC = ADHOC_COMMANDS + ADHOC_ROOT_COMMANDS


def short_label(value):
    return {0: 'Unlimited', 1: 'Title only', 2: '1st sentence',
            3: '1st paragraph'}.get(value, str(value))


class _AdHocCommands(dict):
    """Version-independent command registry for the XEP-0050 plugin.

    Slixmpp up to 1.10 looks commands up directly in the plugin's
    ``commands`` dictionary by ``(jid.full, node)`` and expects a 2-tuple
    ``(name, handler)``, while newer versions do the lookup through the
    API registry. This storage resolves any JID under the transport
    domain dynamically, so feeds added or removed at runtime need no
    re-registration.
    """

    def __init__(self, transport):
        self._transport = transport

    def _resolve(self, key):
        try:
            jid, node = key
            domain = JID(jid).domain
        except Exception:
            return None
        if domain != self._transport.name:
            return None
        for cnode, cname, meth in ALL_ADHOC:
            if node == cnode:
                return (cname, getattr(self._transport, meth))
        return None

    def get(self, key, default=None):
        return self._resolve(key) or default

    def __getitem__(self, key):
        res = self._resolve(key)
        if res is None:
            raise KeyError(key)
        return res

    def __contains__(self, key):
        return self._resolve(key) is not None


class AdHocMixin:

    def init_adhoc(self):
        """Wire the dynamic command lookup into the XEP-0050 plugin.

        Two mechanisms are installed so that both old and new slixmpp
        versions resolve our handlers: slixmpp <= 1.10 reads the plugin's
        ``commands`` dict directly, slixmpp >= 1.11 goes through the API.
        """
        adhoc = self.plugin.get('xep_0050', None)
        if adhoc is None:
            return
        adhoc.commands = _AdHocCommands(self)
        try:
            adhoc.api.register(self._adhoc_get_command, 'get_command',
                               default=True)
        except Exception:
            import traceback
            traceback.print_exc()

    async def _adhoc_get_command(self, jid=None, node=None, ifrom=None,
                                 args=None):
        try:
            domain = JID(jid).domain
        except Exception:
            return None
        if domain != self.name:
            return None
        for node_, name, meth in ALL_ADHOC:
            if node == node_:
                return (name, getattr(self, meth), None, 0)
        return None

    # -- helpers -----------------------------------------------------------

    def _find_feed_record(self, name):
        for f in self.dbfeeds:
            if f[0] == name:
                return f
        return None

    def _new_form(self, ftype, title='', instructions=''):
        return self.plugin['xep_0004'].make_form(ftype=ftype, title=title,
                                                 instructions=instructions)

    def _form_type_field(self, form):
        form.add_field('FORM_TYPE', 'hidden', value=COMMANDS_NS)

    def _field_value(self, form, var):
        value = form.get_values().get(var)
        if isinstance(value, list):
            return value[0] if value else ''
        return '' if value is None else value

    # -- view commands -----------------------------------------------------

    async def adhoc_view_info(self, iq, session):
        feed = self._find_feed_record(iq['to'].node)
        session['next'] = None
        if not feed:
            session['notes'] = [('error', 'Feed not found')]
            session['payload'] = None
            return session
        uniq = {0: 'By link only', 1: 'By link + title',
                2: 'By link + title + content'}.get(feed[9], str(feed[9]))
        form = self._new_form('result', 'Feed info',
                              'Parameters of the feed ' + feed[0])
        self._form_type_field(form)
        form.add_field('desc', label='Description', value=feed[4])
        form.add_field('tags', label='Tags', value=feed[8] or '')
        form.add_field('timeout', label='Update interval',
                       value='%s seconds (%s min)' % (feed[2], feed[2] // 60))
        form.add_field('checktype', label='Uniqueness check', value=uniq)
        form.add_field('adaptive', label='Real (adaptive) interval',
                       value=str(self.adaptime.get(feed[0], 'disabled')))
        form.add_field('subscribers', label='Subscribers',
                       value=str(feed[5]))
        session['payload'] = form
        return session

    async def adhoc_view_sub(self, iq, session):
        feedname = iq['to'].node
        fromjid = iq['from'].bare
        session['next'] = None
        if not self._find_feed_record(feedname):
            session['notes'] = [('error', 'Feed not found')]
            session['payload'] = None
            return session
        try:
            self.dbCurTT.execute(
                "SELECT posfilter, negfilter, short, mute FROM subscribers "
                "WHERE feedname = %s AND jid = %s", (feedname, fromjid))
            row = self.dbCurTT.fetchone()
        except Exception:
            row = None
        if not row:
            session['notes'] = [('info', 'You are not subscribed to this feed')]
            session['payload'] = None
            return session
        form = self._new_form('result', 'My subscription',
                              'Settings for ' + feedname)
        self._form_type_field(form)
        form.add_field('posfilter', label='Positive filter', value=row[0] or '')
        form.add_field('negfilter', label='Negative filter', value=row[1] or '')
        form.add_field('short', label='Message size', value=short_label(row[2]))
        form.add_field('mute', label='Muted', value=bool(row[3]))
        session['payload'] = form
        return session

    # -- edit commands -----------------------------------------------------

    async def adhoc_edit_info(self, iq, session):
        feedname = iq['to'].node
        feed = self._find_feed_record(feedname)
        fromjid = iq['from'].bare
        session['next'] = None
        if not feed:
            session['notes'] = [('error', 'Feed not found')]
            return session
        if not (feed[7] == fromjid or fromjid in self.admins):
            session['notes'] = [('error', 'You are not the registrar of '
                                         'this feed')]
            return session
        form = self._new_form('form', 'Edit feed info',
                              'Edit parameters of ' + feedname)
        self._form_type_field(form)
        form.add_field('tags', 'text-single', label='Tags', value=feed[8] or '')
        timeout = form.add_field('timeout', 'list-single',
                                 label='Update interval (seconds)',
                                 value=str(feed[2]))
        timeout_choices = [300, 600, 900, 1800, 3600, 7200, 14400,
                           21600, 43200, 86400]
        if feed[2] not in timeout_choices:
            timeout_choices.append(feed[2])
        for t in timeout_choices:
            timeout.add_option(label=str(t), value=str(t))
        check = form.add_field('checktype', 'list-single',
                               label='Uniqueness check', value=str(feed[9]))
        for v, l in [(0, 'By link only'), (1, 'By link + title'),
                     (2, 'By link + title + content')]:
            check.add_option(label=l, value=str(v))
        form.add_field('desc', 'text-multi', label='Description', value=feed[4])
        session['payload'] = form
        session['next'] = self.adhoc_edit_info_apply
        session['allow_complete'] = True
        return session

    async def adhoc_edit_info_apply(self, form, session):
        feedname = session['to'].node
        fromjid = session['from'].bare
        feed = self._find_feed_record(feedname)
        session['next'] = None
        if not feed:
            session['notes'] = [('error', 'Feed not found')]
            return session
        if not (feed[7] == fromjid or fromjid in self.admins):
            session['notes'] = [('error', 'You are not the registrar of '
                                         'this feed')]
            return session
        tags = self._field_value(form, 'tags')
        try:
            timeout = int(self._field_value(form, 'timeout'))
        except (TypeError, ValueError):
            session['notes'] = [('error', 'Invalid update interval')]
            return session
        try:
            ctype = int(self._field_value(form, 'checktype'))
        except (TypeError, ValueError):
            ctype = 0
        desc = self._field_value(form, 'desc')
        if timeout < 60:
            timeout = 60
        if ctype not in (0, 1, 2):
            ctype = 0
        tags = re.sub(' *, *', ',', tags.lower().strip())[:255]
        try:
            self.dbCurTT.execute(
                "UPDATE feeds SET tags = %s, timeout = %s, checktype = %s, "
                "description = %s WHERE feedname = %s",
                (tags, timeout, ctype, desc, feedname))
            self.dbCurTT.commit()
        except Exception as msg:
            session['notes'] = [('error', 'Failed to save: %s' % msg)]
            return session
        self.dbfeeds = self.dbCurTT.dbfeeds()
        session['notes'] = [('info', 'Feed parameters saved')]
        session['payload'] = None
        return session

    async def adhoc_edit_sub(self, iq, session):
        feedname = iq['to'].node
        fromjid = iq['from'].bare
        session['next'] = None
        if not self._find_feed_record(feedname):
            session['notes'] = [('error', 'Feed not found')]
            return session
        try:
            self.dbCurTT.execute(
                "SELECT posfilter, negfilter, short, mute FROM subscribers "
                "WHERE feedname = %s AND jid = %s", (feedname, fromjid))
            row = self.dbCurTT.fetchone()
        except Exception:
            row = None
        if not row:
            session['notes'] = [('error', 'You are not subscribed to this '
                                         'feed')]
            return session
        form = self._new_form('form', 'Edit subscription',
                              'Edit settings for ' + feedname)
        self._form_type_field(form)
        form.add_field('posfilter', 'text-single', label='Positive filter',
                       value=row[0] or '')
        form.add_field('negfilter', 'text-single', label='Negative filter',
                       value=row[1] or '')
        short = form.add_field('short', 'list-single', label='Message size',
                               value=str(row[2]))
        for v, l in [(0, 'Unlimited (0)'), (1, 'Title only (1)'),
                     (2, '1st sentence (2)'), (3, '1st paragraph (3)')]:
            short.add_option(label=l, value=str(v))
        form.add_field('mute', 'boolean',
                       label='Muted (do not receive news)', value=bool(row[3]))
        session['payload'] = form
        session['next'] = self.adhoc_edit_sub_apply
        session['allow_complete'] = True
        return session

    async def adhoc_edit_sub_apply(self, form, session):
        feedname = session['to'].node
        fromjid = session['from'].bare
        session['next'] = None
        posfilter = self._field_value(form, 'posfilter')
        negfilter = self._field_value(form, 'negfilter')
        mute = form.get_values().get('mute')
        if isinstance(mute, list):
            mute = mute and mute[0]
        try:
            short = int(self._field_value(form, 'short'))
        except (TypeError, ValueError):
            short = 0
        if short not in (0, 1, 2, 3):
            short = 0
        try:
            self.dbCurTT.execute(
                "UPDATE subscribers SET posfilter = %s, negfilter = %s, "
                "short = %s, mute = %s WHERE feedname = %s AND jid = %s",
                (posfilter or None, negfilter or None, short,
                 int(bool(mute)), feedname, fromjid))
            self.dbCurTT.commit()
        except Exception as msg:
            session['notes'] = [('error', 'Failed to save: %s' % msg)]
            return session
        session['notes'] = [('info', 'Subscription settings saved')]
        session['payload'] = None
        return session

    async def adhoc_edit_privacy(self, iq, session):
        feedname = iq['to'].node
        feed = self._find_feed_record(feedname)
        fromjid = iq['from'].bare
        session['next'] = None
        if not feed:
            session['notes'] = [('error', 'Feed not found')]
            return session
        if not (feed[7] == fromjid or fromjid in self.admins):
            session['notes'] = [('error', 'You are not the registrar of '
                                         'this feed')]
            return session
        form = self._new_form('form', 'Feed privacy',
                              'Visibility of ' + feedname)
        self._form_type_field(form)
        form.add_field('private', 'boolean',
                       label='Private (hidden from search)',
                       value=bool(feed[6]))
        session['payload'] = form
        session['next'] = self.adhoc_edit_privacy_apply
        session['allow_complete'] = True
        return session

    async def adhoc_edit_privacy_apply(self, form, session):
        feedname = session['to'].node
        fromjid = session['from'].bare
        feed = self._find_feed_record(feedname)
        session['next'] = None
        if not feed:
            session['notes'] = [('error', 'Feed not found')]
            return session
        if not (feed[7] == fromjid or fromjid in self.admins):
            session['notes'] = [('error', 'You are not the registrar of '
                                         'this feed')]
            return session
        private = form.get_values().get('private')
        if isinstance(private, list):
            private = private and private[0]
        try:
            self.dbCurTT.execute("UPDATE feeds SET private = %s "
                                 "WHERE feedname = %s",
                                 (int(bool(private)), feedname))
            self.dbCurTT.commit()
        except Exception as msg:
            session['notes'] = [('error', 'Failed to save: %s' % msg)]
            return session
        self.dbfeeds = self.dbCurTT.dbfeeds()
        label = 'hidden from search' if private else 'visible in search'
        session['notes'] = [('info', 'Feed is now %s' % label)]
        session['payload'] = None
        return session

    # -- root menu (commands on the transport's own JID) -------------------

    def _visible_feed(self, feed, fromjid):
        """Mirror browseitems visibility: hide private feeds of others."""
        return not feed[6] or (feed[6] == 1 and fromjid == feed[7])

    def _add_feed_contact(self, feedname, tojid):
        """Send a presence subscription request from a feed JID to a user."""
        self._send(self.Presence(stype="subscribe",
                                 sfrom=feedname + '@' + self.name,
                                 sto=tojid))

    def _feed_pick_form(self, feednames, title, instructions):
        form = self._new_form('form', title, instructions)
        self._form_type_field(form)
        f = form.add_field('feed', 'list-single', label='Feed')
        for name, desc in feednames:
            f.add_option(label='%s (%s)' % (name, desc), value=name)
        form.add_field('addcontact', 'boolean', label='Add to contacts',
                       value=True)
        return form

    async def adhoc_register(self, iq, session):
        return self._registration_step(session)

    async def adhoc_myfeeds(self, iq, session):
        return self._feed_list_step(session, 'myfeeds')

    async def adhoc_myprivate(self, iq, session):
        return self._feed_list_step(session, 'myprivate')

    async def adhoc_feeds(self, iq, session):
        return self._feed_list_step(session, 'feeds')

    async def adhoc_tags(self, iq, session):
        return self._category_step(session)

    def _registration_step(self, session):
        if not self.regallow and session['from'].bare not in self.admins:
            session['notes'] = [('error', 'Registration is disabled')]
            session['payload'] = None
            return session
        form = self._new_form('form', 'Register new feed',
                              'Fill in the feed details')
        self._form_type_field(form)
        form.add_field('feedname', 'text-single', label="Feed's name",
                       required=True)
        form.add_field('url', 'text-single', label='URL', required=True)
        form.add_field('desc', 'text-single', label='Description',
                       required=True)
        form.add_field('tags', 'text-single',
                       label='Tags (comma separated)')
        form.add_field('tosubscribe', 'boolean', label='Subscribe',
                       value=True)
        form.add_field('private', 'boolean', label='Private', value=False)
        tmup = form.add_field('timeout', 'list-single',
                              label='Refresh interval, min', value='60')
        for t in ['1', '2', '5', '10', '15', '30', '60', '120', '240',
                  '300', '600', '900', '1440']:
            tmup.add_option(label=t, value=t)
        ctyp = form.add_field('checktype', 'list-single',
                              label='News uniqueness', value='By link only')
        for t in ['By link only', 'By link + title',
                  'By link + title + content']:
            ctyp.add_option(label=t, value=t)
        session['payload'] = form
        session['next'] = self.adhoc_register_apply
        session['has_next'] = False
        session['allow_complete'] = True
        return session

    def _feed_list_step(self, session, func):
        fromjid = session['from'].bare
        if func == 'myfeeds':
            feednames = [(f[0], f[4]) for f in self.dbfeeds
                         if fromjid == f[7]]
            title = 'Show my feeds'
        elif func == 'myprivate':
            feednames = [(f[0], f[4]) for f in self.dbfeeds
                         if f[6] == 1 and fromjid == f[7]]
            title = 'Show my private feeds'
        else:
            feednames = [(f[0], f[4]) for f in self.dbfeeds
                         if self._visible_feed(f, fromjid)]
            title = 'Show all feeds'
        if not feednames:
            session['notes'] = [('info', 'No feeds found')]
            session['payload'] = None
            return session
        session['payload'] = self._feed_pick_form(feednames, title,
                                                  'Select a feed')
        session['next'] = self.adhoc_feed_apply
        session['has_next'] = False
        session['allow_complete'] = True
        return session

    def _category_step(self, session):
        tags = set()
        for f in self.dbfeeds:
            if f[8]:
                for tag in f[8].split(','):
                    tag = tag.lower().strip()
                    if tag:
                        tags.add(tag)
        if not tags:
            session['notes'] = [('info', 'No categories found')]
            session['payload'] = None
            return session
        form = self._new_form('form', 'Categories', 'Choose a category')
        self._form_type_field(form)
        f = form.add_field('tag', 'list-single', label='Category')
        for tag in sorted(tags):
            f.add_option(label=tag, value=tag)
        session['payload'] = form
        session['next'] = self.adhoc_tag_apply
        session['has_next'] = True
        session['allow_complete'] = False
        return session

    async def adhoc_tag_apply(self, form, session):
        tag = self._field_value(form, 'tag').lower()
        fromjid = session['from'].bare
        session['next'] = None
        session['has_next'] = False
        session['allow_complete'] = True
        feednames = []
        for f in self.dbfeeds:
            if f[8] and tag in [t.lower().strip() for t in f[8].split(',')] \
                    and self._visible_feed(f, fromjid):
                feednames.append((f[0], f[4]))
        if not feednames:
            session['notes'] = [('info', 'No feeds in this category')]
            session['payload'] = None
            return session
        session['payload'] = self._feed_pick_form(
            feednames, 'Category: ' + tag, 'Select a feed')
        session['next'] = self.adhoc_feed_apply
        return session

    async def adhoc_feed_apply(self, form, session):
        feedname = self._field_value(form, 'feed')
        addcontact = form.get_values().get('addcontact')
        if isinstance(addcontact, list):
            addcontact = addcontact and addcontact[0]
        session['next'] = None
        if not self._find_feed_record(feedname):
            session['notes'] = [('error', 'Feed not found')]
            session['payload'] = None
            return session
        if addcontact:
            self._add_feed_contact(feedname, session['from'].bare)
            session['notes'] = [('info', 'Feed "%s" added to your contacts '
                                         '(subscription request sent)'
                                 % feedname)]
        else:
            session['notes'] = [('info', 'Selected feed: %s' % feedname)]
        session['payload'] = None
        return session

    async def adhoc_register_apply(self, form, session):
        fromjid = session['from'].bare
        session['next'] = None
        if not self.regallow and fromjid not in self.admins:
            session['notes'] = [('error', 'Registration is disabled')]
            session['payload'] = None
            return session
        fname = (self._field_value(form, 'feedname') or '').lower()
        furl = self._field_value(form, 'url')
        fdesc = self._field_value(form, 'desc')
        ftags = self._field_value(form, 'tags')
        tosub = form.get_values().get('tosubscribe')
        if isinstance(tosub, list):
            tosub = tosub and tosub[0]
        fpriv = form.get_values().get('private')
        if isinstance(fpriv, list):
            fpriv = fpriv and fpriv[0]
        ftime = self._field_value(form, 'timeout')
        ctype = self._field_value(form, 'checktype')
        if not (fname and furl and fdesc):
            session['notes'] = [('error', 'Name, URL and description are '
                                          'required')]
            session['payload'] = None
            return session
        if any(ch in fname for ch in ':<>&@"\\/ ') or \
                (not furl.startswith('http://') and
                 not furl.startswith('https://')):
            session['notes'] = [('error', 'Invalid feed name or URL')]
            session['payload'] = None
            return session
        if self.isFeedNameRegistered(fname) or self.isFeedUrlRegistered(furl):
            session['notes'] = [('error', 'This feed is already registered')]
            session['payload'] = None
            return session
        try:
            ftime = int(ftime or 60) * 60
        except (TypeError, ValueError):
            ftime = 3600
        if ftime < 60:
            ftime = 60
        ctype = 1 if ctype == 'By link + title' else (
            2 if ctype == 'By link + title + content' else 0)
        ftags = re.sub(' *, *', ',', ftags.lower().strip()) if ftags else ''
        if len(ftags) > 255:
            session['notes'] = [('error', 'Tags are too long')]
            session['payload'] = None
            return session
        try:
            d = await asyncio.to_thread(feedparser.parse, furl)
            bozo = d.get('bozo')
        except Exception:
            bozo = 1
        if bozo:
            session['notes'] = [('error', 'Cannot parse feed at this URL')]
            session['payload'] = None
            return session
        try:
            self.dbCurTT.execute(
                "INSERT INTO feeds (feedname, url, description, timeout, "
                "private, registrar, tags, checktype) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (fname, furl, fdesc, ftime, int(bool(fpriv)), fromjid,
                 ftags, ctype))
            self.dbCurTT.commit()
        except Exception as msg:
            session['notes'] = [('error', 'Failed to register: %s' % msg)]
            session['payload'] = None
            return session
        self.last_upd[fname] = 0
        self.dbfeeds = self.dbCurTT.dbfeeds()
        if tosub:
            self._add_feed_contact(fname, fromjid)
        session['notes'] = [('info', 'Feed "%s" registered' % fname)]
        session['payload'] = None
        return session