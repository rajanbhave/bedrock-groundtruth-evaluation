-- Simplified Aurora PostgreSQL Schema for Human Evaluation Storage
-- Matches the simplified evaluation template (1 rating + 1 feedback field)

-- Drop existing functions first
DROP FUNCTION IF EXISTS get_evaluation_stats(TIMESTAMP WITH TIME ZONE, TIMESTAMP WITH TIME ZONE);
DROP FUNCTION IF EXISTS get_worker_stats(VARCHAR);

-- Drop existing views
DROP VIEW IF EXISTS evaluation_summary CASCADE;
DROP VIEW IF EXISTS low_rated_responses CASCADE;
DROP VIEW IF EXISTS high_rated_responses CASCADE;
DROP VIEW IF EXISTS problematic_responses CASCADE;
DROP VIEW IF EXISTS high_quality_responses CASCADE;

-- Drop existing tables
DROP TABLE IF EXISTS evaluations CASCADE;
DROP TABLE IF EXISTS human_evaluations CASCADE;
DROP TABLE IF EXISTS worker_feedback CASCADE;

-- Main evaluation results table
CREATE TABLE evaluations (
    id SERIAL PRIMARY KEY,
    prompt_id VARCHAR(255) UNIQUE NOT NULL,
    question TEXT NOT NULL,
    response TEXT NOT NULL,
    category VARCHAR(100),

    -- Rating (1-5 scale)
    overall_rating INTEGER CHECK (overall_rating BETWEEN 1 AND 5),

    -- Text feedback
    feedback TEXT,

    -- Worker metadata
    worker_id VARCHAR(255),
    time_spent_seconds NUMERIC(10, 3),

    -- Timestamps
    acceptance_time TIMESTAMP WITH TIME ZONE,
    submission_time TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- Job metadata
    labeling_job_arn TEXT,
    metadata JSONB
);

-- Indexes for performance
DROP INDEX IF EXISTS idx_evaluations_prompt_id;
DROP INDEX IF EXISTS idx_evaluations_category;
DROP INDEX IF EXISTS idx_evaluations_rating;
DROP INDEX IF EXISTS idx_evaluations_created_at;
DROP INDEX IF EXISTS idx_evaluations_worker;
DROP INDEX IF EXISTS idx_evaluations_metadata_gin;
DROP INDEX IF EXISTS idx_evaluations_quality;
DROP INDEX IF EXISTS idx_evaluations_timestamp;
DROP INDEX IF EXISTS idx_evaluations_violations;
DROP INDEX IF EXISTS idx_evaluations_compliance_gin;
DROP INDEX IF EXISTS idx_feedback_prompt;
DROP INDEX IF EXISTS idx_feedback_worker;
DROP INDEX IF EXISTS idx_feedback_timestamp;

CREATE INDEX idx_evaluations_prompt_id ON evaluations(prompt_id);
CREATE INDEX idx_evaluations_category ON evaluations(category);
CREATE INDEX idx_evaluations_rating ON evaluations(overall_rating DESC);
CREATE INDEX idx_evaluations_created_at ON evaluations(created_at DESC);
CREATE INDEX idx_evaluations_worker ON evaluations(worker_id);

-- GIN index for JSONB metadata
CREATE INDEX idx_evaluations_metadata_gin ON evaluations USING GIN (metadata);

-- View for summary statistics by category
CREATE OR REPLACE VIEW evaluation_summary AS
SELECT
    category,
    COUNT(*) as total_evaluations,
    ROUND(AVG(overall_rating), 2) as avg_rating,
    COUNT(CASE WHEN overall_rating >= 4 THEN 1 END) as good_count,
    COUNT(CASE WHEN overall_rating <= 2 THEN 1 END) as poor_count,
    COUNT(CASE WHEN feedback IS NOT NULL AND LENGTH(feedback) > 0 THEN 1 END) as with_feedback_count
FROM evaluations
GROUP BY category
ORDER BY total_evaluations DESC;

-- View for low-rated responses
CREATE OR REPLACE VIEW low_rated_responses AS
SELECT
    prompt_id,
    question,
    response,
    category,
    overall_rating,
    feedback,
    worker_id,
    submission_time
FROM evaluations
WHERE overall_rating <= 2
ORDER BY overall_rating ASC, submission_time DESC;

-- View for high-rated responses
CREATE OR REPLACE VIEW high_rated_responses AS
SELECT
    prompt_id,
    question,
    response,
    category,
    overall_rating,
    feedback,
    worker_id,
    submission_time
FROM evaluations
WHERE overall_rating >= 4
ORDER BY overall_rating DESC, submission_time DESC;

COMMENT ON TABLE evaluations IS 'Human evaluation results from Ground Truth labeling jobs';
COMMENT ON VIEW evaluation_summary IS 'Summary statistics of evaluations grouped by category';
COMMENT ON VIEW low_rated_responses IS 'Responses with poor ratings (1-2)';
COMMENT ON VIEW high_rated_responses IS 'High-quality responses (4-5)';
