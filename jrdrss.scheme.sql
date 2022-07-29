CREATE TABLE IF NOT EXISTS feeds (
feedname varchar(255) NOT NULL,
url varchar(255) NOT NULL,
description varchar(255) NOT NULL,
tags varchar(255) DEFAULT NULL,
subscribers INT NOT NULL DEFAULT 0,
timeout INT NOT NULL DEFAULT 3600,
private boolean DEFAULT false,
registrar varchar(128) DEFAULT NULL,
regdate TIMESTAMP NOT NULL DEFAULT NOW()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 DEFAULT COLLATE utf8mb4_unicode_ci;

# https://stackoverflow.com/questions/6800866/how-to-store-urls-in-mysql
# url may be varchar(765)?
# same for feedname and description

CREATE TABLE IF NOT EXISTS subscribers (
jid varchar(128),
feedname varchar(255)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 DEFAULT COLLATE utf8_unicode_ci;

CREATE TABLE IF NOT EXISTS sent (
received boolean DEFAULT false,
md5 varchar(32),
feedname varchar(255),
datetime TIMESTAMP NOT NULL DEFAULT NOW() ON UPDATE NOW()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 DEFAULT COLLATE utf8mb4_unicode_ci;
