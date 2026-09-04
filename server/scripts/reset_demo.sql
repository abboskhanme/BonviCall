-- Operational data only. Never touches app_settings (the migration seeds it and
-- nothing re-seeds it) and never TRUNCATE ... CASCADE, which walks the FK graph
-- through users into app_settings and silently empties the settings table.
UPDATE users SET agent_id = NULL WHERE agent_id IS NOT NULL;
DELETE FROM users WHERE role <> 'admin';
DELETE FROM call_audio;      DELETE FROM audio_upload_sessions;
DELETE FROM calls;           DELETE FROM call_log_deltas;
DELETE FROM commands;        DELETE FROM alerts;
DELETE FROM capability_transitions; DELETE FROM capability_states;
DELETE FROM device_health;
DELETE FROM number_verifications;   DELETE FROM callback_events;
DELETE FROM enrolment_attempts;     DELETE FROM enrolment_codes;
DELETE FROM installations;   DELETE FROM devices;
DELETE FROM number_assignments;     DELETE FROM registered_numbers;
DELETE FROM line_directory_entries; DELETE FROM model_capture_stats;
DELETE FROM data_usage_daily;       DELETE FROM storage_usage_daily;
DELETE FROM agents;          DELETE FROM audit_log;
SELECT 'agents' t, count(*) FROM agents UNION ALL SELECT 'users', count(*) FROM users
  UNION ALL SELECT 'app_settings', count(*) FROM app_settings;
