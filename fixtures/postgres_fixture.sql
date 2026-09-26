-- Fictional development data. Run only in a disposable test database using
-- a setup account. The application's connector account must have SELECT only.
-- This file is a fixture, not a product feature allowing arbitrary SQL input.
CREATE SCHEMA IF NOT EXISTS ragplayground_fixture;
CREATE TABLE IF NOT EXISTS ragplayground_fixture.support_articles (
    article_id text PRIMARY KEY,
    title text NOT NULL,
    body text NOT NULL,
    updated_at timestamptz NOT NULL
);
INSERT INTO ragplayground_fixture.support_articles
    (article_id, title, body, updated_at)
VALUES
    ('article_clock', 'Clock synchronization',
     'NEBULA-42 means the client clock differs by more than 120 seconds. Synchronize the clock and retry with a new timestamp.',
     '2026-09-03T00:00:00Z'),
    ('article_retention', 'Pro retention',
     'Pro event retention is 30 days from September 1, 2026. Starter retention is 72 hours.',
     '2026-09-01T00:00:00Z'),
    ('article_delivery', 'Duplicate events',
     'Delivery is at least once. Consumers deduplicate using event_id.',
     '2026-09-02T00:00:00Z')
ON CONFLICT (article_id) DO NOTHING;

-- Grant USAGE on this schema and SELECT on this table to an independently
-- created read-only test role. Do not embed a real role password in this file.
