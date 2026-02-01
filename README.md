# Slack Archiver

A Python CLI tool that archives Slack messages from #general and serves them via a local web interface that mimics Slack's appearance.

## Features

- Archives messages, threads, reactions, and file attachments
- Incremental sync (only fetches new messages on subsequent runs)
- Slack-like web interface with search functionality
- Downloads and serves user avatars and file attachments locally

## Prerequisites

- Python 3.11+
- A Slack Bot Token with appropriate scopes

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Create a Slack App and get a Bot Token

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **Create New App** → **From scratch**
3. Name your app and select your workspace
4. Go to **OAuth & Permissions**
5. Under **Bot Token Scopes**, add:
   - `channels:history` - View messages in public channels
   - `channels:read` - View basic channel info
   - `users:read` - View users and their profiles
   - `files:read` - View files shared in channels
6. Click **Install to Workspace** and authorize
7. Copy the **Bot User OAuth Token** (starts with `xoxb-`)

### 3. Configure the token

Create a `.env` file in the project root:

```
SLACK_TOKEN=xoxb-your-bot-token-here
```

### 4. Invite the bot to #general

In Slack, go to #general and type:
```
/invite @YourBotName
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
