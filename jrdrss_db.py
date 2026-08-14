# -*- coding: utf-8 -*-
#
# JRSS  Python 3 Jabber RSS transport.
#
# Database access (PyMySQL). On connect the required tables are checked
# and created automatically if missing, so a separate .sql schema file
# is not needed anymore.

import sys

import pymysql
from pymysql.err import MySQLError as MySQLNativeError
from pymysql.err import OperationalError as MySQLOperationalError

from jrdrss_config import DB_HOST, DB_USER, DB_NAME, DB_PASS

# Current schema version. Version 1 is the base layout taken from the
# original jrdrss.scheme.sql. Later versions are applied on top of it by
# ALTER-style migrations, so connecting to an already existing ("old")
# database upgrades it in place without data loss.
SCHEMA_VERSION = 2

# Base DDL (schema version 1). Statements are idempotent.
SCHEMA = [
    """CREATE TABLE IF NOT EXISTS feeds (
feedname varchar(255) NOT NULL,
url varchar(255) NOT NULL,
description varchar(255) NOT NULL,
tags varchar(255) DEFAULT NULL,
subscribers INT NOT NULL DEFAULT 0,
timeout INT NOT NULL DEFAULT 3600,
private boolean DEFAULT false,
checktype INT DEFAULT 0,
registrar varchar(128) DEFAULT NULL,
regdate TIMESTAMP NOT NULL DEFAULT NOW()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 DEFAULT COLLATE utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS subscribers (
jid varchar(128),
feedname varchar(255),
posfilter varchar(255) DEFAULT NULL,
negfilter varchar(255) DEFAULT NULL,
short INT DEFAULT 0,
mute BOOLEAN DEFAULT false
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 DEFAULT COLLATE utf8mb4_unicode_ci""",
    """CREATE TABLE IF NOT EXISTS sent (
feedname varchar(255),
title VARCHAR(255) DEFAULT NULL,
author VARCHAR(127) DEFAULT NULL,
link VARCHAR(255) DEFAULT NULL,
content VARCHAR(8191) DEFAULT NULL,
datetime TIMESTAMP(1) NOT NULL DEFAULT NOW() ON UPDATE NOW(),
income TIMESTAMP(1) NOT NULL DEFAULT NOW()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 DEFAULT COLLATE utf8mb4_unicode_ci""",
]

# MySQL/MariaDB error codes that only mean "this already exists" and are
# safely ignored while replaying a partially applied migration.
IGNORED_ERRS = {1050, 1060, 1061, 1068, 1091}

# Version -> ordered list of ALTER statements upgrading the schema from the
# previous version. Duplicate rows are removed first (oldest entry wins, i.e.
# the one with the lowest internal row id), then the constraints/indexes are
# added and column types are modernised (TEXT, DATETIME) to avoid value
# truncation and the year-2038 problem.
MIGRATIONS = {
    2: [
        "ALTER TABLE feeds ADD COLUMN id INT UNSIGNED NOT NULL "
        "AUTO_INCREMENT, ADD KEY feeds_idk (id)",
        "DELETE f2 FROM feeds f2 JOIN feeds f1 ON "
        "f1.feedname = f2.feedname AND f1.id < f2.id",
        "DELETE f2 FROM feeds f2 JOIN feeds f1 ON "
        "f1.url = f2.url AND f1.id < f2.id",
        "ALTER TABLE feeds ADD PRIMARY KEY (feedname)",
        "ALTER TABLE feeds ADD UNIQUE KEY feeds_url (url)",
        "ALTER TABLE feeds ADD KEY feeds_registrar (registrar)",
        "ALTER TABLE feeds DROP KEY feeds_idk, DROP COLUMN id",
        "ALTER TABLE feeds MODIFY description TEXT NOT NULL",
        "ALTER TABLE feeds MODIFY regdate DATETIME NOT NULL "
        "DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE subscribers ADD COLUMN id INT UNSIGNED NOT NULL "
        "AUTO_INCREMENT, ADD PRIMARY KEY (id)",
        "DELETE s2 FROM subscribers s2 JOIN subscribers s1 ON "
        "s1.jid = s2.jid AND s1.feedname = s2.feedname AND s1.id < s2.id",
        "ALTER TABLE subscribers ADD UNIQUE KEY subs_uniq (jid, feedname)",
        "ALTER TABLE subscribers ADD KEY subs_feed (feedname)",
        "ALTER TABLE sent ADD COLUMN id BIGINT UNSIGNED NOT NULL "
        "AUTO_INCREMENT, ADD PRIMARY KEY (id)",
        "ALTER TABLE sent ADD KEY sent_feed_income (feedname, income)",
        "ALTER TABLE sent ADD KEY sent_income (income)",
        "ALTER TABLE sent ADD KEY sent_link (link)",
        "ALTER TABLE sent ADD KEY sent_datetime (datetime)",
        "ALTER TABLE sent MODIFY content TEXT DEFAULT NULL",
        "ALTER TABLE sent MODIFY datetime DATETIME NOT NULL DEFAULT "
        "CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
        "ALTER TABLE sent MODIFY income DATETIME NOT NULL DEFAULT "
        "CURRENT_TIMESTAMP",
    ],
}


class DB:

    conn = None
    cursor = None

    def connect(self):
        self.conn = pymysql.connect(host=DB_HOST, user=DB_USER,
                                    password=DB_PASS, database=DB_NAME,
                                    autocommit=False, charset="utf8mb4")
        self.cursor = self.conn.cursor()
        self.ensure_schema()

    def ensure_schema(self):
        """Create missing tables and apply pending schema migrations.

        Safe to call on every connect. If the database already holds the
        old (v1) tables, the ALTER-based migrations in MIGRATIONS upgrade
        them in place instead of recreating anything.
        """
        self.cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = DATABASE()")
        existing = {row[0] for row in self.cursor.fetchall()}
        for ddl in SCHEMA:
            name = ddl.splitlines()[0].rsplit(' ', 1)[-1]
            if name not in existing:
                self.cursor.execute(ddl)

        if 'schema_version' not in existing:
            self.cursor.execute("CREATE TABLE schema_version "
                                "(version INT NOT NULL)")
        self.cursor.execute("SELECT version FROM schema_version")
        row = self.cursor.fetchone()
        if row is None:
            self.cursor.execute("INSERT INTO schema_version (version) "
                                "VALUES (1)")
            current = 1
        else:
            current = row[0]

        for version in range(current + 1, SCHEMA_VERSION + 1):
            statements = MIGRATIONS.get(version)
            if not statements:
                continue
            print("Applying schema migration to version %d" % version)
            for statement in statements:
                try:
                    self.cursor.execute(statement)
                except MySQLNativeError as msg:
                    if msg.args and msg.args[0] in IGNORED_ERRS:
                        continue
                    raise
            self.cursor.execute("UPDATE schema_version SET version = %s",
                                (version,))
        self.conn.commit()

    def ensure_connected(self):
        if not self.cursor:
            self.connect()

    def execute(self, sql, param=None):
        try:
            self.ensure_connected()
            self.cursor.execute(sql, param)
        except (AttributeError, MySQLOperationalError) as msg:
            print("No connection to database:")
            print(msg)
            print("DB call from"),
            print(sys._getframe(1).f_code.co_name)
            self.connect()
            self.cursor.execute(sql, param)
        return self.cursor

    def commit(self):
        if self.conn:
            try:
                self.conn.commit()
            except (AttributeError, MySQLOperationalError):
                pass

    def close(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None
            self.cursor = None

    def dbfeeds(self):
        self.execute("SELECT feedname, url, timeout, regdate, description, "
                     "subscribers, private, registrar, tags, checktype FROM feeds")
        return self.cursor.fetchall()

    def dbnews(self):
        self.execute(
            "SELECT feedname, "
            "SUM(income >= NOW() - INTERVAL 3600 SECOND) AS lasthour, "
            "SUM(income >= NOW() - INTERVAL 86400 SECOND) AS lastday "
            "FROM sent GROUP BY feedname")
        return self.cursor.fetchall()

    def dbtimes(self):
        self.execute(
            "SELECT feedname, UNIX_TIMESTAMP(income) FROM sent "
            "WHERE income >= NOW() - INTERVAL 86400 SECOND")
        return self.cursor.fetchall()

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()
