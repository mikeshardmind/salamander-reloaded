--   Copyright 2020-present Michael Hall
--
--   Licensed under the Apache License, Version 2.0 (the "License");
--   you may not use this file except in compliance with the License.
--   You may obtain a copy of the License at
--
--       http://www.apache.org/licenses/LICENSE-2.0
--
--   Unless required by applicable law or agreed to in writing, software
--   distributed under the License is distributed on an "AS IS" BASIS,
--   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
--   See the License for the specific language governing permissions and
--   limitations under the License.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = 'wal';
PRAGMA synchronous = 'NORMAL';

CREATE TABLE IF NOT EXISTS discord_users (
    user_id INTEGER PRIMARY KEY NOT NULL,
    is_blocked INTEGER DEFAULT FALSE,
    last_interaction TEXT DEFAULT CURRENT_TIMESTAMP,
    user_tz TEXT NOT NULL DEFAULT 'America/New York'
) STRICT, WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS user_tags (
    user_id INTEGER NOT NULL REFERENCES discord_users (user_id) ON UPDATE CASCADE ON DELETE CASCADE,
    tag_name TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, tag_name)
) STRICT, WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS user_notes (
    author_id INTEGER NOT NULL REFERENCES discord_users (user_id) ON UPDATE CASCADE ON DELETE CASCADE,
    target_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (author_id, target_id, created_at)
) STRICT, WITHOUT ROWID;

CREATE TRIGGER IF NOT EXISTS note_caps BEFORE INSERT ON user_notes BEGIN
SELECT
    CASE WHEN (
        SELECT
            COUNT(1) >= 25
        FROM
            user_notes
        WHERE
            author_id = new.author_id AND target_id = new.target_id
    ) THEN RAISE(ABORT, 'too many notes') END;
END;
