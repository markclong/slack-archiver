# Slack Archiver

A Python CLI tool that archives Slack messages from #general and serves them via a local web interface that mimics Slack's appearance.

## Features

- Archives messages, threads, reactions, and file attachments
- Incremental sync (only fetches new messages on subsequent runs)
- Slack-like web interface with search functionality
- Downloads and serves user avatars and file attachments locally

## Prerequisites

- Python 3.11+
- A Slack User Token with appropriate scopes

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Create a Slack App and get a User Token

This uses a **user token** (`xoxp-`) so it authenticates as you — no bot user needed, and no need to invite anything to channels. You already have access to the channels you're in.

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **Create New App** → **From scratch**
3. Name your app (e.g. "Archiver") and select your workspace
4. Go to **OAuth & Permissions**
5. Under **User Token Scopes** (not Bot Token Scopes), add:
   - `channels:history` - View messages in public channels
   - `channels:read` - View basic channel info
   - `groups:history` - View messages in private channels
   - `groups:read` - View basic private channel info
   - `users:read` - View users and their profiles
   - `files:read` - View files shared in channels
6. Click **Install to Workspace** and authorize
7. Copy the **User OAuth Token** (starts with `xoxp-`)

### 3. Configure the token

Create a `.env` file in the project root:

```
SLACK_TOKEN=xoxp-your-user-token-here
```

## Usage

### Archive messages

```bash
python archive.py
```

This fetches all messages from #general and stores them locally. Run it again anytime to fetch new messages (incremental sync).

### View the archive

```bash
python serve.py
```

Open http://localhost:5000 in your browser.

### Search

Use the search box in the sidebar, or go directly to `/search?q=your+query`.

## Project Structure

```
slack-archiver/
├── archive.py          # CLI to fetch messages from Slack
├── serve.py            # Flask web server
├── requirements.txt    # Python dependencies
├── .env                # Slack token (create this)
├── templates/          # Jinja2 templates
├── static/             # CSS styles
└── data/               # Created at runtime
    ├── slack.db        # SQLite database
    ├── avatars/        # User profile photos
    └── files/          # Attachments and images
```

## Data Storage

All data is stored locally:
- **Messages, users, reactions**: SQLite database at `data/slack.db`
- **Avatars**: Downloaded to `data/avatars/`
- **File attachments**: Downloaded to `data/files/`

The `data/` directory is gitignored.
