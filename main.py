import os
import threading

import database as db
import dashboard
import Discord_bot as discord_bot


def run_dashboard():
    port = int(os.environ.get("PORT", 5000))
    dashboard.app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    db.init_db()
    threading.Thread(target=run_dashboard, daemon=True).start()
    discord_bot.client.run(discord_bot.DISCORD_TOKEN)
