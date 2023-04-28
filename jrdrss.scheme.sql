CREATE TABLE IF NOT EXISTS feeds (
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 DEFAULT COLLATE utf8mb4_unicode_ci;

# https://stackoverflow.com/questions/6800866/how-to-store-urls-in-mysql
# url may be varchar(765)?
# same for feedname and description

CREATE TABLE IF NOT EXISTS subscribers (
jid varchar(128),
feedname varchar(255),
posfilter varchar(255) DEFAULT NULL,
negfilter varchar(255) DEFAULT NULL,
short INT DEFAULT 0,
mute BOOLEAN DEFAULT false
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 DEFAULT COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sent (
feedname varchar(255),
title VARCHAR(255) DEFAULT NULL,
author VARCHAR(127) DEFAULT NULL,
link VARCHAR(255) DEFAULT NULL,
content VARCHAR(8191) DEFAULT NULL,
datetime TIMESTAMP(1) NOT NULL DEFAULT NOW() ON UPDATE NOW(),
income TIMESTAMP(1) NOT NULL DEFAULT NOW()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 DEFAULT COLLATE utf8mb4_unicode_ci;
