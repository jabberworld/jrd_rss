ALTER TABLE sent ADD income TIMESTAMP(1) NOT NULL DEFAULT NOW() AFTER datetime ;
ALTER TABLE sent DROP COLUMN received;