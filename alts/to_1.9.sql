ALTER TABLE sent ADD content VARCHAR(8191) DEFAULT NULL AFTER feedname;
ALTER TABLE sent ADD title VARCHAR(255) DEFAULT NULL AFTER feedname;
ALTER TABLE sent ADD link VARCHAR(255) DEFAULT NULL AFTER title;
ALTER TABLE sent ADD author VARCHAR(127) DEFAULT NULL AFTER title;