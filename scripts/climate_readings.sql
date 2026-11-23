-- Hub 2 climate history for the homepage chart. New table (approved): climate_readings.
-- One row per reading (every 5 minutes by default, ~105k rows/year, a few MB).
-- Written only by the web app's Hub 2 recorder (functions/switchbot.py).
-- Run once:  psql "$DATABASE_DSN" -f scripts/climate_readings.sql
CREATE TABLE IF NOT EXISTS climate_readings (
    id           bigserial    PRIMARY KEY,
    device_id    varchar(64)  NOT NULL,                 -- SwitchBot deviceId
    device_name  varchar(255),                          -- e.g. "Hub 2 AE"
    recorded_at  timestamptz  NOT NULL DEFAULT now(),
    humidity     smallint     NOT NULL CHECK (humidity BETWEEN 0 AND 100),  -- % RH
    temperature  real,                                  -- degrees Celsius
    light_level  smallint,                              -- 1-20
    UNIQUE (device_id, recorded_at)                     -- also serves time-range queries
);

-- Rollback, if needed:
--   DROP TABLE IF EXISTS climate_readings;
