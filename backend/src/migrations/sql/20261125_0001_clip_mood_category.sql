ALTER TABLE generated_clips
    ADD COLUMN IF NOT EXISTS mood_category VARCHAR(32);
