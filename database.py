"""Database models and operations using SQLite."""

import aiosqlite
import json
import secrets
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from enum import Enum

from config import settings


def generate_uid() -> str:
    """Generate a unique ID for streams."""
    return secrets.token_urlsafe(12)  # 16 chars, URL-safe


def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    """Hash a password with salt."""
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return hashed.hex(), salt


def verify_password(password: str, hashed: str, salt: str) -> bool:
    """Verify a password against its hash."""
    new_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(new_hash, hashed)


class StreamMode(str, Enum):
    ALWAYS_ON = "always_on"
    ON_DEMAND = "on_demand"
    SMART = "smart"


class LatencyMode(str, Enum):
    LOW = "low"        # 2-4 seconds (aggressive, may buffer)
    STABLE = "stable"  # 10-24 seconds (highly reliable, recommended)


class StreamStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"
    RECONNECTING = "reconnecting"


@dataclass
class User:
    """User model."""
    id: Optional[int] = None
    username: str = ""
    password_hash: str = ""
    password_salt: str = ""
    is_admin: bool = False
    created_at: Optional[str] = None

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "User":
        return cls(**dict(row))


@dataclass
class Session:
    """Session model."""
    id: Optional[int] = None
    user_id: int = 0
    token: str = ""
    expires_at: str = ""
    created_at: Optional[str] = None

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "Session":
        return cls(**dict(row))


@dataclass
class ApiKey:
    """API Key model."""
    id: Optional[int] = None
    name: str = ""
    key_hash: str = ""
    key_prefix: str = ""  # First 8 chars for display
    created_at: Optional[str] = None
    last_used: Optional[str] = None

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "ApiKey":
        return cls(**dict(row))


@dataclass
class Stream:
    """Stream model."""
    id: Optional[str] = None  # Changed to string UID
    name: str = ""
    rtsp_url: str = ""
    mode: str = StreamMode.ON_DEMAND.value
    status: str = StreamStatus.STOPPED.value

    # Auto-detected settings
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    resolution: Optional[str] = None
    framerate: Optional[float] = None
    bitrate: Optional[int] = None

    # User overrides (JSON string)
    ffmpeg_overrides: Optional[str] = None

    # Runtime stats
    viewer_count: int = 0
    last_viewer_time: Optional[str] = None
    last_error: Optional[str] = None
    pid: Optional[int] = None

    # Settings
    keep_alive_seconds: int = 60
    use_transcode: bool = False
    latency_mode: str = LatencyMode.STABLE.value  # stable (5-10s) or low (2-4s)

    # Timestamps
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "Stream":
        """Create from database row."""
        return cls(**dict(row))


class Database:
    """Async SQLite database handler."""

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or settings.database_path
        self._connection: Optional[aiosqlite.Connection] = None

    async def connect(self):
        """Connect to database."""
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._create_tables()

    async def close(self):
        """Close database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None

    async def _create_tables(self):
        """Create database tables if they don't exist."""
        # Users table
        await self._connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                created_at TEXT
            )
        """)

        # Sessions table
        await self._connection.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                created_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # API Keys table
        await self._connection.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                key_hash TEXT NOT NULL,
                key_prefix TEXT NOT NULL,
                created_at TEXT,
                last_used TEXT
            )
        """)

        # Streams table - with string ID
        await self._connection.execute("""
            CREATE TABLE IF NOT EXISTS streams (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                rtsp_url TEXT NOT NULL UNIQUE,
                mode TEXT DEFAULT 'on_demand',
                status TEXT DEFAULT 'stopped',
                video_codec TEXT,
                audio_codec TEXT,
                resolution TEXT,
                framerate REAL,
                bitrate INTEGER,
                ffmpeg_overrides TEXT,
                viewer_count INTEGER DEFAULT 0,
                last_viewer_time TEXT,
                last_error TEXT,
                pid INTEGER,
                keep_alive_seconds INTEGER DEFAULT 60,
                use_transcode INTEGER DEFAULT 0,
                latency_mode TEXT DEFAULT 'stable',
                created_at TEXT,
                updated_at TEXT
            )
        """)
        # Migration: add latency_mode column if it doesn't exist
        try:
            await self._connection.execute(
                "ALTER TABLE streams ADD COLUMN latency_mode TEXT DEFAULT 'stable'"
            )
        except Exception:
            pass  # Column already exists

        # Create indexes for better performance with 300+ cameras
        await self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_streams_status ON streams(status)"
        )
        await self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_streams_mode ON streams(mode)"
        )
        await self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_streams_name ON streams(name)"
        )

        # Settings table for app configuration (API keys, etc.)
        await self._connection.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT
            )
        """)

        await self._connection.commit()

    # ==================== User Management ====================

    async def is_setup_complete(self) -> bool:
        """Check if initial setup is complete (admin user exists)."""
        cursor = await self._connection.execute(
            "SELECT COUNT(*) FROM users WHERE is_admin = 1"
        )
        row = await cursor.fetchone()
        return row[0] > 0

    async def create_user(self, username: str, password: str, is_admin: bool = False) -> User:
        """Create a new user."""
        password_hash, password_salt = hash_password(password)
        now = datetime.utcnow().isoformat()
        cursor = await self._connection.execute(
            """
            INSERT INTO users (username, password_hash, password_salt, is_admin, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (username, password_hash, password_salt, int(is_admin), now)
        )
        await self._connection.commit()
        return User(
            id=cursor.lastrowid,
            username=username,
            password_hash=password_hash,
            password_salt=password_salt,
            is_admin=is_admin,
            created_at=now
        )

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        cursor = await self._connection.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        )
        row = await cursor.fetchone()
        return User.from_row(row) if row else None

    async def verify_user(self, username: str, password: str) -> Optional[User]:
        """Verify user credentials."""
        user = await self.get_user_by_username(username)
        if user and verify_password(password, user.password_hash, user.password_salt):
            return user
        return None

    async def update_user_password(self, user_id: int, new_password: str):
        """Update user password."""
        password_hash, password_salt = hash_password(new_password)
        await self._connection.execute(
            """
            UPDATE users SET password_hash = ?, password_salt = ?
            WHERE id = ?
            """,
            (password_hash, password_salt, user_id)
        )
        await self._connection.commit()

    # ==================== Session Management ====================

    async def create_session(self, user_id: int, expires_hours: int = 24) -> Session:
        """Create a new session."""
        token = secrets.token_urlsafe(32)
        now = datetime.utcnow()
        expires_at = (now + timedelta(hours=expires_hours)).isoformat()
        cursor = await self._connection.execute(
            """
            INSERT INTO sessions (user_id, token, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, token, expires_at, now.isoformat())
        )
        await self._connection.commit()
        return Session(
            id=cursor.lastrowid,
            user_id=user_id,
            token=token,
            expires_at=expires_at,
            created_at=now.isoformat()
        )

    async def get_session(self, token: str) -> Optional[Session]:
        """Get session by token."""
        cursor = await self._connection.execute(
            "SELECT * FROM sessions WHERE token = ?", (token,)
        )
        row = await cursor.fetchone()
        if row:
            session = Session.from_row(row)
            # Check if expired
            if datetime.fromisoformat(session.expires_at) < datetime.utcnow():
                await self.delete_session(token)
                return None
            return session
        return None

    async def delete_session(self, token: str):
        """Delete a session."""
        await self._connection.execute("DELETE FROM sessions WHERE token = ?", (token,))
        await self._connection.commit()

    async def get_user_by_session(self, token: str) -> Optional[User]:
        """Get user by session token."""
        session = await self.get_session(token)
        if not session:
            return None
        cursor = await self._connection.execute(
            "SELECT * FROM users WHERE id = ?", (session.user_id,)
        )
        row = await cursor.fetchone()
        return User.from_row(row) if row else None

    async def cleanup_expired_sessions(self):
        """Remove expired sessions."""
        now = datetime.utcnow().isoformat()
        await self._connection.execute(
            "DELETE FROM sessions WHERE expires_at < ?", (now,)
        )
        await self._connection.commit()

    # ==================== API Key Management ====================

    async def create_api_key(self, name: str) -> tuple[ApiKey, str]:
        """Create a new API key. Returns (ApiKey, raw_key)."""
        raw_key = secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:8]
        now = datetime.utcnow().isoformat()
        cursor = await self._connection.execute(
            """
            INSERT INTO api_keys (name, key_hash, key_prefix, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (name, key_hash, key_prefix, now)
        )
        await self._connection.commit()
        api_key = ApiKey(
            id=cursor.lastrowid,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            created_at=now
        )
        return api_key, raw_key

    async def verify_api_key(self, raw_key: str) -> Optional[ApiKey]:
        """Verify an API key and return the ApiKey if valid."""
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        cursor = await self._connection.execute(
            "SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)
        )
        row = await cursor.fetchone()
        if row:
            api_key = ApiKey.from_row(row)
            # Update last_used
            await self._connection.execute(
                "UPDATE api_keys SET last_used = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), api_key.id)
            )
            await self._connection.commit()
            return api_key
        return None

    async def get_all_api_keys(self) -> List[ApiKey]:
        """Get all API keys (without the actual key)."""
        cursor = await self._connection.execute(
            "SELECT * FROM api_keys ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        return [ApiKey.from_row(row) for row in rows]

    async def delete_api_key(self, key_id: int):
        """Delete an API key."""
        await self._connection.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        await self._connection.commit()

    # ==================== Stream Management ====================

    async def add_stream(self, stream: Stream) -> Stream:
        """Add a new stream."""
        now = datetime.utcnow().isoformat()
        stream_id = stream.id or generate_uid()
        await self._connection.execute(
            """
            INSERT INTO streams (
                id, name, rtsp_url, mode, status, video_codec, audio_codec,
                resolution, framerate, bitrate, ffmpeg_overrides,
                keep_alive_seconds, use_transcode, latency_mode,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stream_id, stream.name, stream.rtsp_url, stream.mode, stream.status,
                stream.video_codec, stream.audio_codec, stream.resolution,
                stream.framerate, stream.bitrate, stream.ffmpeg_overrides,
                stream.keep_alive_seconds, int(stream.use_transcode),
                stream.latency_mode, now, now
            )
        )
        await self._connection.commit()
        stream.id = stream_id
        stream.created_at = now
        stream.updated_at = now
        return stream

    async def get_stream(self, stream_id: str) -> Optional[Stream]:
        """Get stream by ID."""
        cursor = await self._connection.execute(
            "SELECT * FROM streams WHERE id = ?", (stream_id,)
        )
        row = await cursor.fetchone()
        if row:
            return Stream.from_row(row)
        return None

    async def get_stream_by_url(self, rtsp_url: str) -> Optional[Stream]:
        """Get stream by RTSP URL."""
        cursor = await self._connection.execute(
            "SELECT * FROM streams WHERE rtsp_url = ?", (rtsp_url,)
        )
        row = await cursor.fetchone()
        if row:
            return Stream.from_row(row)
        return None

    async def get_all_streams(self) -> List[Stream]:
        """Get all streams."""
        cursor = await self._connection.execute("SELECT * FROM streams ORDER BY id")
        rows = await cursor.fetchall()
        return [Stream.from_row(row) for row in rows]

    async def get_streams_paginated(
        self,
        page: int = 1,
        per_page: int = 20,
        search: str = None,
        status: str = None,
        mode: str = None,
        sort_by: str = "id",
        sort_order: str = "asc"
    ) -> tuple[List[Stream], int]:
        """Get streams with pagination, search, and filters."""
        # Build WHERE clause
        conditions = []
        params = []

        if search:
            conditions.append("(name LIKE ? OR rtsp_url LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])

        if status:
            conditions.append("status = ?")
            params.append(status)

        if mode:
            conditions.append("mode = ?")
            params.append(mode)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Validate sort column to prevent SQL injection
        valid_sort_cols = ["id", "name", "status", "mode", "created_at", "updated_at", "viewer_count"]
        if sort_by not in valid_sort_cols:
            sort_by = "id"
        sort_order = "DESC" if sort_order.lower() == "desc" else "ASC"

        # Get total count
        count_cursor = await self._connection.execute(
            f"SELECT COUNT(*) FROM streams WHERE {where_clause}", params
        )
        total = (await count_cursor.fetchone())[0]

        # Get paginated results
        offset = (page - 1) * per_page
        query = f"""
            SELECT * FROM streams
            WHERE {where_clause}
            ORDER BY {sort_by} {sort_order}
            LIMIT ? OFFSET ?
        """
        cursor = await self._connection.execute(query, params + [per_page, offset])
        rows = await cursor.fetchall()

        return [Stream.from_row(row) for row in rows], total

    async def get_stream_counts(self) -> dict:
        """Get counts by status and mode for quick stats."""
        cursor = await self._connection.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) as running,
                SUM(CASE WHEN status = 'stopped' THEN 1 ELSE 0 END) as stopped,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error,
                SUM(CASE WHEN mode = 'always_on' THEN 1 ELSE 0 END) as always_on,
                SUM(CASE WHEN mode = 'on_demand' THEN 1 ELSE 0 END) as on_demand
            FROM streams
        """)
        row = await cursor.fetchone()
        return dict(row) if row else {}

    async def batch_update_status(self, stream_ids: List[int], status: str):
        """Update status for multiple streams at once."""
        if not stream_ids:
            return
        placeholders = ",".join("?" * len(stream_ids))
        now = datetime.utcnow().isoformat()
        await self._connection.execute(
            f"UPDATE streams SET status = ?, updated_at = ? WHERE id IN ({placeholders})",
            [status, now] + stream_ids
        )
        await self._connection.commit()

    async def update_stream(self, stream: Stream) -> Stream:
        """Update stream."""
        stream.updated_at = datetime.utcnow().isoformat()
        await self._connection.execute(
            """
            UPDATE streams SET
                name = ?, rtsp_url = ?, mode = ?, status = ?,
                video_codec = ?, audio_codec = ?, resolution = ?,
                framerate = ?, bitrate = ?, ffmpeg_overrides = ?,
                viewer_count = ?, last_viewer_time = ?, last_error = ?,
                pid = ?, keep_alive_seconds = ?, use_transcode = ?,
                latency_mode = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                stream.name, stream.rtsp_url, stream.mode, stream.status,
                stream.video_codec, stream.audio_codec, stream.resolution,
                stream.framerate, stream.bitrate, stream.ffmpeg_overrides,
                stream.viewer_count, stream.last_viewer_time, stream.last_error,
                stream.pid, stream.keep_alive_seconds, int(stream.use_transcode),
                stream.latency_mode, stream.updated_at, stream.id
            )
        )
        await self._connection.commit()
        return stream

    async def delete_stream(self, stream_id: str) -> bool:
        """Delete stream."""
        cursor = await self._connection.execute(
            "DELETE FROM streams WHERE id = ?", (stream_id,)
        )
        await self._connection.commit()
        return cursor.rowcount > 0

    async def update_stream_status(
        self, stream_id: str, status: StreamStatus,
        error: str = None, pid: int = None
    ):
        """Update stream status quickly."""
        now = datetime.utcnow().isoformat()
        await self._connection.execute(
            """
            UPDATE streams SET status = ?, last_error = ?, pid = ?, updated_at = ?
            WHERE id = ?
            """,
            (status.value, error, pid, now, stream_id)
        )
        await self._connection.commit()

    async def update_viewer_count(self, stream_id: str, count: int):
        """Update viewer count."""
        now = datetime.utcnow().isoformat()
        await self._connection.execute(
            """
            UPDATE streams SET viewer_count = ?, last_viewer_time = ?, updated_at = ?
            WHERE id = ?
            """,
            (count, now, now, stream_id)
        )
        await self._connection.commit()

    async def get_always_on_streams(self) -> List[Stream]:
        """Get all always-on streams."""
        cursor = await self._connection.execute(
            "SELECT * FROM streams WHERE mode = ?", (StreamMode.ALWAYS_ON.value,)
        )
        rows = await cursor.fetchall()
        return [Stream.from_row(row) for row in rows]

    # ==================== Settings Management ====================

    async def get_setting(self, key: str) -> Optional[str]:
        """Get a setting value by key."""
        cursor = await self._connection.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def set_setting(self, key: str, value: str):
        """Set a setting value."""
        now = datetime.utcnow().isoformat()
        await self._connection.execute(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?
            """,
            (key, value, now, value, now)
        )
        await self._connection.commit()

    async def delete_setting(self, key: str):
        """Delete a setting."""
        await self._connection.execute("DELETE FROM settings WHERE key = ?", (key,))
        await self._connection.commit()

    async def get_all_settings(self) -> Dict[str, str]:
        """Get all settings."""
        cursor = await self._connection.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}


# Global database instance
db = Database()
