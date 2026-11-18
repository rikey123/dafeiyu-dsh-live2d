from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dafeiyu_paths import data_dir

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = data_dir(ROOT)
DEFAULTS = {
    "llm_base_url": os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
    "llm_model": os.environ.get("LLM_MODEL", "deepseek-chat"),
    "llm_api_key": "" if os.environ.get("DAFEIYU_HARNESS") == "dsh" else os.environ.get("LLM_API_KEY", ""),
    "system_prompt": "你的角色名是 DeepSeek-chan，昵称大肥鱼。你是亲切、自然的中文 AI 伙伴，以真实的 AI 身份与用户交流，不冒充官方员工。像朋友聊天，通常用一到三个简短口语句子回应，先回应对方感受，再按需提一个问题。不要使用 Markdown、列表或思考过程，不要虚构你能看到用户或操作电脑。",
    "speech_base_url": os.environ.get("SPEECH_BASE_URL", "http://127.0.0.1:8766"),
    "voice": "default",
    "owner_voice_only": False,
    "streaming_asr_preview": False,
    "systemone_enabled": False,
    "systemone_provider": "ark",
    "systemone_ark_model": "doubao-seed-2-1-lite-260915",
    "systemone_ark_api_key": os.environ.get("ARK_API_KEY", ""),
    "systemone_api_key": os.environ.get("TOKENTOSEA_API_KEY", ""),
    "systemone_audio_enabled": True,
    "systemone_timeout_ms": 1200,
    "systemone_interrupt_threshold": 0.75,
    "systemone_confidence": 0.6,
    "screen_companion_mode": "systemone",
    "companion_interests": "",
    "idle_companion_enabled": False,
    "idle_companion_after_s": 120,
    "idle_companion_cooldown_s": 180,
    "idle_companion_max_per_hour": 6,
    "idle_companion_include_screen": True,
    "idle_companion_max_reply_chars": 64,
    "screen_companion_enabled": False,
    "screen_companion_style": "balanced",
    "screen_companion_interval_ms": 2500,
    "screen_companion_change_threshold": 0.06,
    "screen_companion_cooldown_s": 30,
    "screen_companion_max_judgments_per_hour": 60,
    "screen_companion_max_replies_per_hour": 12,
    "screen_companion_speak_threshold": 0.9,
    "screen_companion_wait_threshold": 0.2,
    "screen_companion_max_reply_chars": 64,
    "screen_companion_timeout_ms": 3000,
    "screen_companion_refresh_ms": 15000,
    "screen_request_enabled": True,
    "screen_request_threshold": 0.75,
    "screen_request_timeout_ms": 2000,
    "systemone_initiative_enabled": False,
    "systemone_initiative_threshold": 0.9,
    "systemone_initiative_min_speech_ms": 3000,
    "systemone_initiative_cooldown_s": 20,
    "systemone_initiative_wait_threshold": 0.2,
    "systemone_initiative_max_reply_chars": 48,
    "systemone_initiative_probe_interval_ms": 3000,
    "systemone_initiative_max_probes": 3,
    "tts_engine": "local",  # Legacy clients; explicit tts_mode takes precedence.
    "tts_mode": "legacy",
    "gpu_tts_model": "index_tts",
    "conversation_mode": "duplex",
    "moss_live_api_key": os.environ.get("MOSS_API_KEY", ""),
    "moss_live_voice": "",
    "moss_live_model": "moss-live-1.0",
    "index_tts_url": "http://127.0.0.1:8770",
    "moss_tts_url": "http://127.0.0.1:8772",
    "tts_api_provider": "deepseek",
    "tts_api_base_url": "https://api.deepseek.com/v1",
    "tts_api_model": "tts-1",
    "tts_api_voice": "stella",
    "tts_api_filter_markdown": True,
    "tts_api_key": "",
    "tts_api_speed": 1.0,
    "tts_api_timeout": 60.0,
    "cosyvoice_url": "http://127.0.0.1:8770",
    "temperature": 0.7,
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, directory: Path = DATA_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "companion.sqlite3"
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA foreign_keys = ON;
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL, content TEXT NOT NULL, interrupted INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id, created_at);
            CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, content TEXT NOT NULL, created_at TEXT NOT NULL);
        """)
        # Retire the blocking offline alignment option, including databases
        # which still selected it. Never touch TTS/LLM credentials or history.
        self.db.execute("DELETE FROM settings WHERE key IN (?, ?)", ("tts_alignment", "mfa_url"))
        self._migrate_tts_provider()
        self.db.commit()

    def _migrate_tts_provider(self):
        """Only untouched, keyless legacy templates switch to DeepSeek.

        Never send an existing provider's secret or conversation to a new host.
        Persist the choice once; clearing a key later must not switch providers.
        """
        rows = self.db.execute("SELECT key, value FROM settings WHERE key LIKE 'tts_api_%'").fetchall()
        saved = {row["key"]: json.loads(row["value"]) for row in rows}
        if "tts_api_provider" in saved:
            return
        legacy = (bool(saved.get("tts_api_key"))
                  or saved.get("tts_api_base_url", "https://api.openai.com/v1").rstrip("/") != "https://api.openai.com/v1"
                  or saved.get("tts_api_model", "tts-1") != "tts-1"
                  or saved.get("tts_api_voice", "alloy") != "alloy"
                  or saved.get("tts_api_speed", 1) != 1)
        values = {"tts_api_provider": "openai_compatible" if legacy else "deepseek",
                  "tts_api_base_url": saved.get("tts_api_base_url", "https://api.openai.com/v1") if legacy else DEFAULTS["tts_api_base_url"],
                  "tts_api_voice": saved.get("tts_api_voice", "alloy") if legacy else DEFAULTS["tts_api_voice"]}
        for key, value in values.items():
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, json.dumps(value)))

    def settings(self, *, private: bool = False) -> dict:
        with self.lock:
            from .dsh import enabled
            # The plugin never reads the standalone model credential from SQLite.
            sql = "SELECT key, value FROM settings WHERE key != 'llm_api_key'" if enabled() else "SELECT key, value FROM settings"
            rows = self.db.execute(sql).fetchall()
        settings = DEFAULTS.copy()
        from .dsh import enabled
        if enabled():
            settings["llm_api_key"] = ""
        saved = {row["key"]: json.loads(row["value"]) for row in rows if row["key"] in DEFAULTS}
        settings.update(saved)
        if settings['screen_companion_mode'] not in ('systemone', 'direct'):
            settings['screen_companion_mode'] = 'systemone'
        # Old installations must not silently send their conversation to a new
        # provider. Fresh configurations default to Ark; legacy ones stay Clef.
        if "systemone_provider" not in saved and settings["systemone_api_key"]:
            settings["systemone_provider"] = "tokentosea"
        if not private:
            settings["api_key_set"] = bool(settings.pop("llm_api_key"))
            settings["tts_api_key_set"] = bool(settings.pop("tts_api_key"))
            settings["moss_live_api_key_set"] = bool(settings.pop("moss_live_api_key"))
            settings["systemone_api_key_set"] = bool(settings.pop("systemone_api_key"))
            settings["systemone_ark_api_key_set"] = bool(settings.pop("systemone_ark_api_key"))
        return settings

    def update_settings(self, values: dict) -> dict:
        with self.lock, self.db:
            if values.get("clear_tts_api_key"):
                self.db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", ("tts_api_key", json.dumps("")))
            if values.get("clear_moss_live_api_key"):
                self.db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", ("moss_live_api_key", json.dumps("")))
            if values.get("clear_systemone_api_key"):
                self.db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", ("systemone_api_key", json.dumps("")))
            if values.get("clear_systemone_ark_api_key"):
                self.db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", ("systemone_ark_api_key", json.dumps("")))
            for key, value in values.items():
                if key not in DEFAULTS or value is None or (key in {"llm_api_key", "tts_api_key", "moss_live_api_key", "systemone_api_key", "systemone_ark_api_key"} and value == ""):
                    continue
                self.db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, json.dumps(value, ensure_ascii=False)))
        return self.settings()

    def session(self, session_id: str | None = None) -> str:
        with self.lock, self.db:
            if session_id and self.db.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone():
                return session_id
            session_id = uuid.uuid4().hex
            self.db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (session_id, "新对话", now()))
            return session_id

    def sessions(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM sessions ORDER BY created_at DESC LIMIT 200")]

    def has_session(self, session_id: str) -> bool:
        with self.lock:
            return self.db.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone() is not None

    def delete_session(self, session_id: str) -> bool:
        with self.lock, self.db:
            return self.db.execute("DELETE FROM sessions WHERE id=?", (session_id,)).rowcount > 0

    def add_message(self, session_id: str, role: str, content: str, interrupted: bool = False) -> str:
        message_id = uuid.uuid4().hex
        with self.lock, self.db:
            self.db.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)",
                            (message_id, session_id, role, content, int(interrupted), now()))
            if role == "user":
                self.db.execute("UPDATE sessions SET title=? WHERE id=? AND title=?", (content[:40], session_id, "新对话"))
        return message_id

    def update_message(self, message_id: str, session_id: str, content: str) -> bool:
        with self.lock, self.db:
            return self.db.execute("UPDATE messages SET content=? WHERE id=? AND session_id=? AND role='assistant'", (content, message_id, session_id)).rowcount == 1

    def revise_user_message(self, message_id: str, session_id: str, content: str) -> bool:
        with self.lock, self.db:
            return self.db.execute("UPDATE messages SET content=? WHERE id=? AND session_id=? AND role='user'", (content, message_id, session_id)).rowcount == 1

    def delete_empty_assistant(self, message_id: str, session_id: str) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM messages WHERE id=? AND session_id=? AND role='assistant' AND content=''", (message_id, session_id))

    def messages(self, session_id: str) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT id,role,content,interrupted,created_at FROM messages WHERE session_id=? AND NOT (role='assistant' AND content='') ORDER BY rowid", (session_id,))
            return [{**dict(row), "interrupted": bool(row["interrupted"])} for row in rows]

    def memories(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM memories ORDER BY created_at DESC LIMIT 200")]

    def add_memory(self, content: str) -> dict:
        entry = {"id": uuid.uuid4().hex, "content": content, "created_at": now()}
        with self.lock, self.db:
            self.db.execute("INSERT INTO memories VALUES (:id, :content, :created_at)", entry)
        return entry

    def delete_memory(self, memory_id: str) -> bool:
        with self.lock, self.db:
            return self.db.execute("DELETE FROM memories WHERE id=?", (memory_id,)).rowcount > 0
