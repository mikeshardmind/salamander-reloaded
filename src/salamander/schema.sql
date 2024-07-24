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

CREATE TABLE IF NOT EXISTS discord_users (
    user_id INTEGER PRIMARY KEY NOT NULL,
    is_blocked INTEGER DEFAULT FALSE,
    last_interaction TEXT DEFAULT CURRENT_TIMESTAMP
) STRICT, WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS user_tags (
	user_id INTEGER NOT NULL REFERENCES discord_users (user_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	kb_article_name TEXT NOT NULL,
	content TEXT NOT NULL,
	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY (user_id, kb_article_name)
) STRICT, WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS user_notes (
	author_id INTEGER NOT NULL REFERENCES discord_users (user_id)
		ON UPDATE CASCADE ON DELETE CASCADE,
	target_id INTEGER NOT NULL,
	content TEXT NOT NULL,
	created_at TEXT DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY (author_id, target_id, created_at)
) STRICT, WITHOUT ROWID;