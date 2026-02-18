# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Slack Archiver is a Python CLI tool that archives Slack messages from #general and serves them via a local Flask web interface. It allows users to browse and search archived messages with a Slack-like interface.

### Key Features
- Fetches messages, threads, reactions, and file attachments from Slack
- Incremental sync (only fetches new messages on subsequent runs)
- Slack-like web UI with search functionality
- Downloads and serves user avatars and file attachments locally
- Handles custom Slack emojis (including aliases) and emoji conversion

## Architecture

The application is split into two main components:

### 1. **archive.py** - CLI message fetcher
Fetches data from Slack API and stores it in SQLite database with local file downloads.

**Key flow:**
- Initializes SQLite database with schema for users, messages, reactions, files, emojis
- Syncs custom emojis, users (with avatars), and messages with incremental state tracking
- Downloads all attachments and avatars to `data/` directory
- Thread replies are fetched separately when parent message has `reply_count > 0`

**Key functions:**
- `sync_emojis()` - Handles custom emojis and alias resolution
- `sync_users()` - Fetches users and downloads avatars with Bearer token auth
- `sync_messages()` / `fetch_messages()` - Paginated message fetching with incremental sync via `sync_state` table
- `fetch_thread()` - Fetches thread replies for messages with responses
- `download_file()` - Generic file downloader with timeout and authorization headers

### 2. **serve.py** - Flask web server
Renders archived messages using Jinja2 templates and serves as a local web interface.

**Key routes:**
- `/` - Redirects to #general
- `/channel/<name>` - Main channel view with pagination (`before_ts` parameter)
- `/channel/<name>/around/<ts>` - Load messages centered around a specific timestamp (used for search context)
- `/channel/<name>/load-more` - AJAX endpoint for infinite scroll
- `/search` - Full-text search across all messages
- `/api/thread/<ts>` - JSON endpoint returning thread replies as HTML
- `/media/<path>` - Serves downloaded avatars, files, and emojis from `data/` directory

**Message enrichment pipeline:**
- `enrich_messages()` loads reactions, files, formatting, and timestamps
- `format_message_text()` converts Slack formatting to HTML (handles mentions, links, bold/italic/code, emoji)
- `convert_emoji()` converts emoji shortcodes to unicode or custom emoji paths

## Database Schema

SQLite database at `data/slack.db` with the following tables:

- **users** - User profiles with avatar paths
- **messages** - Messages with `thread_ts` NULL for parent messages, set for replies
- **reactions** - Emoji reactions with user list as JSON
- **files** - File attachments and images
- **emojis** - Custom workspace emojis with alias resolution
- **sync_state** - Tracks oldest/newest message timestamps for incremental sync

## Common Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables (requires actual Slack token)
export SLACK_TOKEN="xoxb-your-token"
# Or create .env file with: SLACK_TOKEN=xoxb-your-token

# Fetch/sync messages from Slack
python archive.py

# Run local web server (requires data/slack.db to exist)
python serve.py
# Opens at http://localhost:5000
```

## Key Dependencies

- **slack-sdk** - Slack API client
- **Flask** - Web framework
- **python-dotenv** - Load environment variables from .env
- **emoji** - Convert emoji shortcodes to unicode

## Template Structure

Templates are in `templates/` directory using Jinja2:

- **base.html** - Base layout with header/sidebar
- **channel.html** - Main message view with infinite scroll
- **search.html** - Search results page with context link to `/channel/<name>/around/<ts>`
- **components/message.html** - Individual message rendering (avatars, reactions, files, formatted text)
- **components/messages_list.html** - List of messages (used in AJAX load-more)
- **components/thread.html** - Thread reply rendering (used in `/api/thread` endpoint)

## Important Implementation Details

### Message Pagination
- Uses `before_ts` parameter (not page numbers) for pagination via timestamp ordering
- `MESSAGES_PER_PAGE = 50` controls batch size
- Load-more is AJAX-based for infinite scroll experience

### Slack API Details
- Thread parents have `reply_count > 0`; replies have `thread_ts` set
- Emoji names use underscores in Slack (e.g., `custom_emoji`) but emoji library uses hyphens
- Files require Bearer token authorization header for downloads
- User mentions are `<@USER_ID>`, channel mentions are `<#CHANNEL_ID|name>`

### Incremental Sync
- `sync_state` table tracks oldest/newest message timestamps per channel
- Subsequent `archive.py` runs fetch messages newer than `newest_ts`
- Handles both initial and incremental syncs in `sync_messages()`

### Emoji Conversion
- Custom emoji URLs starting with "alias:" are resolved to target emoji
- Standard emoji use `emoji` library with fallback to underscore-to-hyphen conversion
- Returns different types: "custom" (local file), "unicode" (converted), or "text" (shortcode if not found)

## Git Workflow

Recent commits show feature additions (search, setup docs) and maintenance. The `/init` command helped establish this CLAUDE.md documentation.
