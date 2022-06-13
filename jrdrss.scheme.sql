CREATE TABLE IF NOT EXISTS feeds (
feedname varchar(255) NOT NULL,
url varchar(255) NOT NULL,
description varchar(255) NOT NULL,
subscribers integer NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8 DEFAULT COLLATE utf8_unicode_ci;

# https://stackoverflow.com/questions/6800866/how-to-store-urls-in-mysql
# url may be varchar(765)?
# same for feedname and description

CREATE TABLE IF NOT EXISTS subscribers (
jid varchar(128),
feedname varchar(255)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 DEFAULT COLLATE utf8_unicode_ci;

CREATE TABLE IF NOT EXISTS sent (
received boolean DEFAULT true,
md5 varchar(32),
feedname varchar(255),
datetime TIMESTAMP NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8 DEFAULT COLLATE utf8_unicode_ci;