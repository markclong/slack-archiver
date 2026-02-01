#!/usr/bin/env python3
"""
Slack Archiver - Web server to view archived messages.

Usage:
    python serve.py
    # Opens at http://localhost:5000
"""

import sqlite3
import json
import re
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, redirect, url_for, jsonify, send_from_directory, request

# Configuration
DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "slack.db"
MESSAGES_PER_PAGE = 50

app = Flask(__name__)


def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def format_timestamp(ts: str) -> str:
    """Convert Slack timestamp to readable format."""
    try:
        unix_ts = float(ts.split(".")[0])
        dt = datetime.fromtimestamp(unix_ts)
        return dt.strftime("%b %d, %Y %I:%M %p")
    except (ValueError, IndexError):
        return ts


def format_date_divider(ts: str) -> str:
    """Format date for day divider."""
    try:
        unix_ts = float(ts.split(".")[0])
        dt = datetime.fromtimestamp(unix_ts)
        today = datetime.now().date()
        msg_date = dt.date()

        if msg_date == today:
            return "Today"
        elif (today - msg_date).days == 1:
            return "Yesterday"
        else:
            return dt.strftime("%A, %B %d, %Y")
    except (ValueError, IndexError):
        return ""


def format_time(ts: str) -> str:
    """Format just the time portion."""
    try:
        unix_ts = float(ts.split(".")[0])
        dt = datetime.fromtimestamp(unix_ts)
        return dt.strftime("%I:%M %p").lstrip("0")
    except (ValueError, IndexError):
        return ts


def get_date_key(ts: str) -> str:
    """Get date key for grouping."""
    try:
        unix_ts = float(ts.split(".")[0])
        dt = datetime.fromtimestamp(unix_ts)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, IndexError):
        return ""


def format_message_text(text: str, users: dict) -> str:
    """Format message text with user mentions, links, and basic formatting."""
    if not text:
        return ""

    # Escape HTML first
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Restore Slack-encoded entities
    text = text.replace("&amp;lt;", "&lt;").replace("&amp;gt;", "&gt;").replace("&amp;amp;", "&amp;")

    # Handle Slack links: <URL|text> or <URL>
    def replace_link(match):
        content = match.group(1)
        if "|" in content:
            url, label = content.split("|", 1)
        else:
            url = label = content
        return f'<a href="{url}" target="_blank" rel="noopener">{label}</a>'

    text = re.sub(r"&lt;(https?://[^&]+)&gt;", replace_link, text)

    # Handle user mentions: <@U123ABC>
    def replace_mention(match):
        user_id = match.group(1)
        user = users.get(user_id, {})
        name = user.get("display_name", user_id)
        return f'<span class="mention">@{name}</span>'

    text = re.sub(r"&lt;@([A-Z0-9]+)&gt;", replace_mention, text)

    # Handle channel mentions: <#C123ABC|channel-name>
    def replace_channel(match):
        channel_name = match.group(2) if match.group(2) else match.group(1)
        return f'<span class="mention">#{channel_name}</span>'

    text = re.sub(r"&lt;#([A-Z0-9]+)\|?([^&]*)&gt;", replace_channel, text)

    # Basic formatting
    # Bold: *text*
    text = re.sub(r"\*([^*]+)\*", r"<strong>\1</strong>", text)
    # Italic: _text_
    text = re.sub(r"_([^_]+)_", r"<em>\1</em>", text)
    # Strikethrough: ~text~
    text = re.sub(r"~([^~]+)~", r"<del>\1</del>", text)
    # Code: `text`
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # Code blocks: ```text```
    text = re.sub(r"```([^`]+)```", r"<pre><code>\1</code></pre>", text, flags=re.DOTALL)

    # Convert newlines to <br>
    text = text.replace("\n", "<br>")

    return text


def get_users(conn) -> dict:
    """Load all users into a dict."""
    rows = conn.execute("SELECT id, name, display_name, avatar_local FROM users").fetchall()
    return {row["id"]: dict(row) for row in rows}


def get_messages(conn, channel: str, before_ts: str = None, after_ts: str = None, limit: int = MESSAGES_PER_PAGE) -> list:
    """Get messages for a channel with pagination."""
    query = """
        SELECT m.*, u.name as user_name, u.display_name, u.avatar_local
        FROM messages m
        LEFT JOIN users u ON m.user_id = u.id
        WHERE m.channel = ? AND m.thread_ts IS NULL
    """
    params = [channel]

    if before_ts:
        query += " AND m.ts < ?"
        params.append(before_ts)
    elif after_ts:
        query += " AND m.ts > ?"
        params.append(after_ts)

    query += " ORDER BY m.ts DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in reversed(rows)]  # Reverse to show oldest first


def get_reactions(conn, message_ts: str) -> list:
    """Get reactions for a message."""
    rows = conn.execute(
        "SELECT emoji_name, user_ids FROM reactions WHERE message_ts = ?",
        (message_ts,)
    ).fetchall()
    reactions = []
    for row in rows:
        user_ids = json.loads(row["user_ids"])
        reactions.append({
            "name": row["emoji_name"],
            "count": len(user_ids)
        })
    return reactions


def get_files(conn, message_ts: str) -> list:
    """Get files for a message."""
    rows = conn.execute(
        "SELECT * FROM files WHERE message_ts = ?",
        (message_ts,)
    ).fetchall()
    return [dict(row) for row in rows]


def get_thread_replies(conn, thread_ts: str, users: dict) -> list:
    """Get all replies in a thread."""
    rows = conn.execute("""
        SELECT m.*, u.name as user_name, u.display_name, u.avatar_local
        FROM messages m
        LEFT JOIN users u ON m.user_id = u.id
        WHERE m.thread_ts = ?
        ORDER BY m.ts ASC
    """, (thread_ts,)).fetchall()

    replies = []
    for row in rows:
        reply = dict(row)
        reply["reactions"] = get_reactions(conn, reply["ts"])
        reply["files"] = get_files(conn, reply["ts"])
        reply["formatted_text"] = format_message_text(reply["text"], users)
        reply["formatted_time"] = format_time(reply["ts"])
        replies.append(reply)

    return replies


def enrich_messages(conn, messages: list, users: dict) -> list:
    """Add reactions, files, and formatting to messages."""
    for msg in messages:
        msg["reactions"] = get_reactions(conn, msg["ts"])
        msg["files"] = get_files(conn, msg["ts"])
        msg["formatted_text"] = format_message_text(msg["text"], users)
        msg["formatted_time"] = format_time(msg["ts"])
        msg["formatted_timestamp"] = format_timestamp(msg["ts"])
        msg["date_key"] = get_date_key(msg["ts"])
        msg["date_divider"] = format_date_divider(msg["ts"])
    return messages


@app.route("/")
def index():
    """Redirect to #general."""
    return redirect(url_for("channel", name="general"))


@app.route("/channel/<name>")
def channel(name: str):
    """Display channel messages."""
    conn = get_db()
    users = get_users(conn)

    before_ts = request.args.get("before")
    messages = get_messages(conn, name, before_ts=before_ts)
    messages = enrich_messages(conn, messages, users)

    # Check if there are more messages
    has_more = False
    if messages:
        older = conn.execute(
            "SELECT 1 FROM messages WHERE channel = ? AND thread_ts IS NULL AND ts < ? LIMIT 1",
            (name, messages[0]["ts"])
        ).fetchone()
        has_more = older is not None

    conn.close()

    return render_template(
        "channel.html",
        channel_name=name,
        messages=messages,
        has_more=has_more,
        oldest_ts=messages[0]["ts"] if messages else None
    )


@app.route("/channel/<name>/load-more")
def load_more(name: str):
    """Load more messages (AJAX endpoint)."""
    before_ts = request.args.get("before")
    if not before_ts:
        return jsonify({"error": "before parameter required"}), 400

    conn = get_db()
    users = get_users(conn)

    messages = get_messages(conn, name, before_ts=before_ts)
    messages = enrich_messages(conn, messages, users)

    # Check if there are more messages
    has_more = False
    if messages:
        older = conn.execute(
            "SELECT 1 FROM messages WHERE channel = ? AND thread_ts IS NULL AND ts < ? LIMIT 1",
            (name, messages[0]["ts"])
        ).fetchone()
        has_more = older is not None

    conn.close()

    # Render message HTML
    from flask import render_template_string
    html = render_template(
        "components/messages_list.html",
        messages=messages,
        channel_name=name
    )

    return jsonify({
        "html": html,
        "has_more": has_more,
        "oldest_ts": messages[0]["ts"] if messages else None
    })


@app.route("/api/thread/<ts>")
def api_thread(ts: str):
    """Get thread replies as JSON."""
    conn = get_db()
    users = get_users(conn)
    replies = get_thread_replies(conn, ts, users)
    conn.close()

    # Render HTML for replies
    html = render_template("components/thread.html", replies=replies)

    return jsonify({
        "html": html,
        "count": len(replies)
    })


@app.route("/media/<path:filepath>")
def media(filepath: str):
    """Serve downloaded media files."""
    return send_from_directory(DATA_DIR, filepath)


# Template helpers
@app.context_processor
def utility_processor():
    return {
        "format_time": format_time,
        "format_timestamp": format_timestamp,
    }


if __name__ == "__main__":
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}")
        print("Run 'python archive.py' first to fetch messages.")
        exit(1)

    print("Starting Slack Archive Viewer...")
    print("Open http://localhost:5000 in your browser")
    app.run(debug=True, port=5000)
