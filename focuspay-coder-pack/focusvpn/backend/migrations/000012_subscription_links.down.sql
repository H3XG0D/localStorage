DROP TABLE IF EXISTS subscription_links;

DELETE FROM devices WHERE platform = 'link';

ALTER TABLE devices DROP CONSTRAINT IF EXISTS devices_platform_check;
ALTER TABLE devices ADD CONSTRAINT devices_platform_check
    CHECK (platform IN ('android', 'ios', 'macos', 'windows', 'linux'));
