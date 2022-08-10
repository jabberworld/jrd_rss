ALTER TABLE subscribers ADD posfilter varchar(255) DEFAULT NULL AFTER feedname;
ALTER TABLE subscribers ADD negfilter varchar(255) DEFAULT NULL AFTER posfilter;
