#!/usr/bin/env python3
"""
Slack Archiver - Fetches messages from #general and stores locally.

Usage:
    export SLACK_TOKEN="xoxp-your-user-token"
    python archive.py
"""

import os
import sqlite3
import json
import urllib.request
import urllib.error
from pathlib import Path
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# Load environment variables from .env file
load_dotenv()

# Configuration
DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "slack.db"
AVATARS_DIR = DATA_DIR / "avatars"
FILES_DIR = DATA_DIR / "files"
EMOJIS_DIR = DATA_DIR / "emojis"
CHANNEL_NAME = "general"


def init_db(conn: sqlite3.Connection) -> None:
    """Initialize database schema."""
    conn.executescript("""
        -- Users table
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT,
            display_name TEXT,
            avatar_url TEXT,
            avatar_local TEXT
        );

        -- Messages table
        CREATE TABLE IF NOT EXISTS messages (
            ts TEXT PRIMARY KEY,
            channel TEXT,
            user_id TEXT,
            text TEXT,
            thread_ts TEXT,
            reply_count INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- Reactions table
        CREATE TABLE IF NOT EXISTS reactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_ts TEXT,
            emoji_name TEXT,
            user_ids TEXT,
            FOREIGN KEY (message_ts) REFERENCES messages(ts)
        );

        -- Files/attachments table
        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY,
            message_ts TEXT,
            name TEXT,
            mimetype TEXT,
            url TEXT,
            local_path TEXT,
            FOREIGN KEY (message_ts) REFERENCES messages(ts)
        );

        -- Sync state for incremental updates
        CREATE TABLE IF NOT EXISTS sync_state (
            channel TEXT PRIMARY KEY,
            oldest_ts TEXT,
            newest_ts TEXT,
            channel_id TEXT
        );

        -- App config (workspace URL, etc.)
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        -- Custom emoji table
        CREATE TABLE IF NOT EXISTS emojis (
            name TEXT PRIMARY KEY,
            url TEXT,
            local_path TEXT
        );

        -- Indexes for performance
        CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel);
        CREATE INDEX IF NOT EXISTS idx_messages_thread_ts ON messages(thread_ts);
        CREATE INDEX IF NOT EXISTS idx_reactions_message_ts ON reactions(message_ts);
        CREATE INDEX IF NOT EXISTS idx_files_message_ts ON files(message_ts);
    """)
    conn.commit()

    # Migrate existing sync_state table if needed
    try:
        conn.execute("ALTER TABLE sync_state ADD COLUMN channel_id TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists


def download_file(url: str, local_path: Path, headers: dict = None) -> bool:
    """Download a file from URL to local path."""
    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url)
        if headers:
            for key, value in headers.items():
                req.add_header(key, value)
        with urllib.request.urlopen(req, timeout=30) as response:
            with open(local_path, 'wb') as f:
                f.write(response.read())
        return True
    except (urllib.error.URLError, OSError) as e:
        print(f"  Failed to download {url}: {e}")
        return False


def get_channel_id(client: WebClient, channel_name: str) -> str | None:
    """Find channel ID by name."""
    try:
        cursor = None
        while True:
            response = client.conversations_list(
                types="public_channel,private_channel",
                cursor=cursor,
                limit=200
            )
            for channel in response["channels"]:
                if channel["name"] == channel_name:
                    return channel["id"]
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
    except SlackApiError as e:
        print(f"Error fetching channels: {e}")
    return None


def sync_emojis(client: WebClient, conn: sqlite3.Connection) -> dict:
    """Fetch all custom emojis from the workspace."""
    print("Syncing custom emojis...")
    emojis = {}
    try:
        response = client.emoji_list()
        emoji_list = response.get("emoji", {})

        for name, url in emoji_list.items():
            # Skip alias emojis (they start with "alias:")
            if url.startswith("alias:"):
                # Store the alias reference
                alias_target = url[6:]  # Remove "alias:" prefix
                conn.execute("""
                    INSERT OR REPLACE INTO emojis (name, url, local_path)
                    VALUES (?, ?, ?)
                """, (name, url, None))
                emojis[name] = {"url": url, "local_path": None, "alias": alias_target}
                continue

            # Download the emoji image
            local_path = None
            ext = Path(url.split("?")[0]).suffix or ".png"
            emoji_filename = f"{name}{ext}"
            emoji_path = EMOJIS_DIR / emoji_filename

            if not emoji_path.exists():
                if download_file(url, emoji_path):
                    local_path = f"emojis/{emoji_filename}"
            else:
                local_path = f"emojis/{emoji_filename}"

            conn.execute("""
                INSERT OR REPLACE INTO emojis (name, url, local_path)
                VALUES (?, ?, ?)
            """, (name, url, local_path))

            emojis[name] = {"url": url, "local_path": local_path}

        conn.commit()
        print(f"  Synced {len(emojis)} custom emojis")
    except SlackApiError as e:
        print(f"Error fetching emojis: {e}")

    return emojis


def sync_users(client: WebClient, conn: sqlite3.Connection, token: str) -> dict:
    """Fetch all users and their avatars."""
    print("Syncing users...")
    users = {}
    try:
        cursor = None
        while True:
            response = client.users_list(cursor=cursor, limit=200)
            for user in response["members"]:
                user_id = user["id"]
                profile = user.get("profile", {})
                name = user.get("name", "")
                display_name = profile.get("display_name") or profile.get("real_name") or name
                avatar_url = profile.get("image_72", "")

                # Download avatar
                avatar_local = None
                if avatar_url:
                    avatar_filename = f"{user_id}.jpg"
                    avatar_path = AVATARS_DIR / avatar_filename
                    if not avatar_path.exists():
                        if download_file(avatar_url, avatar_path):
                            avatar_local = f"avatars/{avatar_filename}"
                    else:
                        avatar_local = f"avatars/{avatar_filename}"

                conn.execute("""
                    INSERT OR REPLACE INTO users (id, name, display_name, avatar_url, avatar_local)
                    VALUES (?, ?, ?, ?, ?)
                """, (user_id, name, display_name, avatar_url, avatar_local))

                users[user_id] = {
                    "name": name,
                    "display_name": display_name,
                    "avatar_local": avatar_local
                }

            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        conn.commit()
        print(f"  Synced {len(users)} users")
    except SlackApiError as e:
        print(f"Error fetching users: {e}")

    return users


def get_sync_state(conn: sqlite3.Connection, channel: str) -> tuple[str | None, str | None]:
    """Get the oldest and newest message timestamps we have."""
    row = conn.execute(
        "SELECT oldest_ts, newest_ts FROM sync_state WHERE channel = ?",
        (channel,)
    ).fetchone()
    if row:
        return row[0], row[1]
    return None, None


def update_sync_state(conn: sqlite3.Connection, channel: str, oldest_ts: str | None, newest_ts: str | None, channel_id: str | None = None) -> None:
    """Update sync state."""
    conn.execute("""
        INSERT OR REPLACE INTO sync_state (channel, oldest_ts, newest_ts, channel_id)
        VALUES (?, ?, ?, COALESCE(?, (SELECT channel_id FROM sync_state WHERE channel = ?)))
    """, (channel, oldest_ts, newest_ts, channel_id, channel))
    conn.commit()


def save_message(conn: sqlite3.Connection, msg: dict, channel: str, token: str) -> None:
    """Save a single message with reactions and files."""
    ts = msg["ts"]
    user_id = msg.get("user", msg.get("bot_id", "unknown"))
    text = msg.get("text", "")
    thread_ts = msg.get("thread_ts") if msg.get("thread_ts") != ts else None
    reply_count = msg.get("reply_count", 0)

    conn.execute("""
        INSERT OR REPLACE INTO messages (ts, channel, user_id, text, thread_ts, reply_count)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (ts, channel, user_id, text, thread_ts, reply_count))

    # Save reactions
    if "reactions" in msg:
        # Clear existing reactions for this message
        conn.execute("DELETE FROM reactions WHERE message_ts = ?", (ts,))
        for reaction in msg["reactions"]:
            conn.execute("""
                INSERT INTO reactions (message_ts, emoji_name, user_ids)
                VALUES (?, ?, ?)
            """, (ts, reaction["name"], json.dumps(reaction["users"])))

    # Save files
    if "files" in msg:
        for file_info in msg["files"]:
            file_id = file_info.get("id", "")
            file_name = file_info.get("name", "unknown")
            mimetype = file_info.get("mimetype", "")
            url = file_info.get("url_private", file_info.get("url_private_download", ""))

            # Download file
            local_path = None
            if url:
                file_ext = Path(file_name).suffix or ""
                local_filename = f"{file_id}{file_ext}"
                file_path = FILES_DIR / local_filename
                if not file_path.exists():
                    headers = {"Authorization": f"Bearer {token}"}
                    if download_file(url, file_path, headers):
                        local_path = f"files/{local_filename}"
                else:
                    local_path = f"files/{local_filename}"

            conn.execute("""
                INSERT OR REPLACE INTO files (id, message_ts, name, mimetype, url, local_path)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (file_id, ts, file_name, mimetype, url, local_path))


def sync_messages(client: WebClient, conn: sqlite3.Connection, channel_id: str, channel_name: str, token: str) -> None:
    """Fetch messages from channel with incremental sync."""
    print(f"Syncing messages from #{channel_name}...")

    oldest_ts, newest_ts = get_sync_state(conn, channel_name)

    if newest_ts:
        # Incremental sync - fetch newer messages
        print(f"  Fetching messages newer than {newest_ts}")
        fetch_messages(client, conn, channel_id, channel_name, token, oldest=newest_ts)
    else:
        # Initial sync - fetch all messages
        print("  Performing initial sync...")
        fetch_messages(client, conn, channel_id, channel_name, token)


def fetch_messages(client: WebClient, conn: sqlite3.Connection, channel_id: str,
                   channel_name: str, token: str, oldest: str = None) -> None:
    """Fetch messages with pagination."""
    message_count = 0
    thread_count = 0
    first_ts = None
    last_ts = None

    try:
        cursor = None
        while True:
            kwargs = {
                "channel": channel_id,
                "limit": 200,
            }
            if cursor:
                kwargs["cursor"] = cursor
            if oldest:
                kwargs["oldest"] = oldest

            response = client.conversations_history(**kwargs)
            messages = response.get("messages", [])

            for msg in messages:
                # Skip subtypes we don't want (channel_join, etc)
                if msg.get("subtype") in ["channel_join", "channel_leave"]:
                    continue

                save_message(conn, msg, channel_name, token)
                message_count += 1

                ts = msg["ts"]
                if first_ts is None or ts < first_ts:
                    first_ts = ts
                if last_ts is None or ts > last_ts:
                    last_ts = ts

                # Fetch thread replies if this message has replies
                if msg.get("reply_count", 0) > 0:
                    thread_replies = fetch_thread(client, conn, channel_id, channel_name, msg["ts"], token)
                    thread_count += thread_replies

            conn.commit()

            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

            print(f"  Fetched {message_count} messages so far...")

        # Update sync state
        if first_ts and last_ts:
            old_oldest, old_newest = get_sync_state(conn, channel_name)
            new_oldest = min(first_ts, old_oldest) if old_oldest else first_ts
            new_newest = max(last_ts, old_newest) if old_newest else last_ts
            update_sync_state(conn, channel_name, new_oldest, new_newest, channel_id)

        print(f"  Synced {message_count} messages, {thread_count} thread replies")

    except SlackApiError as e:
        print(f"Error fetching messages: {e}")


def fetch_thread(client: WebClient, conn: sqlite3.Connection, channel_id: str,
                 channel_name: str, thread_ts: str, token: str) -> int:
    """Fetch all replies in a thread."""
    reply_count = 0
    try:
        cursor = None
        while True:
            kwargs = {
                "channel": channel_id,
                "ts": thread_ts,
                "limit": 200,
            }
            if cursor:
                kwargs["cursor"] = cursor

            response = client.conversations_replies(**kwargs)
            messages = response.get("messages", [])

            for msg in messages:
                # Skip the parent message (it's already saved)
                if msg["ts"] == thread_ts:
                    continue

                save_message(conn, msg, channel_name, token)
                reply_count += 1

            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

    except SlackApiError as e:
        print(f"Error fetching thread {thread_ts}: {e}")

    return reply_count


def main():
    # Get token
    token = os.environ.get("SLACK_TOKEN")
    if not token:
        print("Error: SLACK_TOKEN environment variable not set")
        print("Usage: export SLACK_TOKEN='xoxp-your-user-token' && python archive.py")
        return 1

    # Create directories
    DATA_DIR.mkdir(exist_ok=True)
    AVATARS_DIR.mkdir(exist_ok=True)
    FILES_DIR.mkdir(exist_ok=True)
    EMOJIS_DIR.mkdir(exist_ok=True)

    # Initialize database
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    # Initialize Slack client
    client = WebClient(token=token)

    # Store workspace URL for building permalinks later
    try:
        auth_info = client.auth_test()
        workspace_url = auth_info.get("url", "")
        if workspace_url:
            conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", ("workspace_url", workspace_url))
            conn.commit()
    except SlackApiError as e:
        print(f"Warning: Could not fetch workspace info: {e}")

    # Find channel ID
    print(f"Looking for #{CHANNEL_NAME} channel...")
    channel_id = get_channel_id(client, CHANNEL_NAME)
    if not channel_id:
        print(f"Error: Could not find #{CHANNEL_NAME} channel")
        return 1
    print(f"  Found channel: {channel_id}")

    # Sync custom emojis
    sync_emojis(client, conn)

    # Sync users
    sync_users(client, conn, token)

    # Sync messages
    sync_messages(client, conn, channel_id, CHANNEL_NAME, token)

    conn.close()
    print("Archive complete!")
    return 0


if __name__ == "__main__":
    exit(main())
