CREATE TABLE activity_log (
    id SERIAL PRIMARY KEY,
    action VARCHAR(255) NOT NULL,
    entity_type VARCHAR(255) NOT NULL,
    entity_id VARCHAR(255) NOT NULL,
    platform VARCHAR(255),
    details JSONB,
    user_id INTEGER,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_activity_log_entity ON activity_log(entity_type, entity_id);
CREATE INDEX idx_activity_log_platform ON activity_log(platform);
CREATE INDEX idx_activity_log_created_at ON activity_log(created_at);