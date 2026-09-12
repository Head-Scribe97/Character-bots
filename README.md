# Discord Character Bots — Dashboard + Bot

A single Discord bot process that plays multiple fictional characters,
managed through a small password-protected web dashboard instead of editing
code. Each character is stored in a database and posted to Discord via a
**webhook**, so each one shows up with its own name and avatar without
needing a separate bot application per character.

## How it works

- `dashboard.py` — the web app where you add/edit characters and set your
  channel IDs.
- `discord_bot.py` — the bot that reads characters from the database,
  decides who should respond, calls Claude, and posts as that character.
- `database.py` — SQLite storage shared by both.
- `main.py` — runs the dashboard and the bot together in one process.

**Important limitation:** webhook "characters" aren't real Discord user
accounts, so people can't @mention them with Discord's real mention feature.
A character responds when someone types their name in a message (e.g. "hey
Ridoc, ...") or replies to that character's last message.

## 1. Create the Discord bot

1. Go to https://discord.com/developers/applications → **New Application**.
   One application/token covers *all* your characters — you don't need a
   new one per character.
2. Go to the **Bot** tab → **Reset Token** → copy the token. Keep it secret.
3. Still on the **Bot** tab, enable **Message Content Intent** and
   **Server Members Intent** (the second lets it detect new members for
   welcome greetings).
4. Go to **OAuth2 → URL Generator**. Check `bot` scope, then under Bot
   Permissions check: `Read Messages/View Channels`, `Send Messages`,
   `Read Message History`, `Manage Webhooks`. Copy the generated URL, open
   it, and invite the bot to your server.

## 2. Set environment variables

You'll need to set these wherever you run it (locally or on your host):

- `DISCORD_TOKEN` — from step 1.
- `ANTHROPIC_API_KEY` — from https://console.anthropic.com/ → API Keys.
- `DASHBOARD_PASSWORD` — the password you'll use to log into the dashboard.
  Pick something real; don't leave the default.
- `FLASK_SECRET_KEY` — any random string (used to sign login sessions).

## 3. Run it locally first

```bash
pip install -r requirements.txt
export DISCORD_TOKEN="..."
export ANTHROPIC_API_KEY="..."
export DASHBOARD_PASSWORD="pick-something"
export FLASK_SECRET_KEY="pick-something-random"
python main.py
```

The dashboard will be at http://localhost:5000 — log in, add your first
character (Ridoc), and set your channel IDs under **Settings** (Developer
Mode on in Discord → right-click a channel → Copy Channel ID).

## 4. Deploy to Railway (so it stays online without your computer)

1. Push this folder to a new GitHub repo.
2. Go to https://railway.app → **New Project** → **Deploy from GitHub repo**.
3. In the project's **Variables** tab, add the four environment variables
   from step 2.
4. Railway auto-detects the `Procfile` and runs `python main.py`. It also
   gives the service a public URL — that's your dashboard link.
5. **Add a persistent volume** in Railway's service settings and mount it
   at the app's working directory (or wherever `characters.db` lives).
   Without this, your characters get wiped on every redeploy since
   Railway's default filesystem is not persistent between deploys.

## Adding more characters

Just use the dashboard — no code changes needed. Add a character, set
"Active" so it can respond in #characters, and optionally "Greets new
members" so it also posts in #welcome when someone joins.
