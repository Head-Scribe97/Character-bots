import os

from flask import Flask, render_template, request, redirect, url_for, session

import database as db

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-me-in-production")
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "changeme")

db.init_db()

SETTINGS_KEYS = ["characters_channel_id", "welcome_channel_id", "announcements_channel_id"]


@app.before_request
def require_login():
    if request.endpoint in ("login", "static"):
        return
    if not session.get("authed"):
        return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == DASHBOARD_PASSWORD:
            session["authed"] = True
            return redirect(url_for("index"))
        error = "Wrong password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    return render_template("characters.html", characters=db.list_characters())


@app.route("/characters/new", methods=["GET", "POST"])
def new_character():
    if request.method == "POST":
        db.create_character(_form_to_data(request.form))
        return redirect(url_for("index"))
    return render_template("character_form.html", character=None)


@app.route("/characters/<int:character_id>/edit", methods=["GET", "POST"])
def edit_character(character_id):
    character = db.get_character(character_id)
    if request.method == "POST":
        db.update_character(character_id, _form_to_data(request.form))
        return redirect(url_for("index"))
    return render_template("character_form.html", character=character)


@app.route("/characters/<int:character_id>/delete", methods=["POST"])
def delete_character(character_id):
    db.delete_character(character_id)
    return redirect(url_for("index"))


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        for key in SETTINGS_KEYS:
            db.set_setting(key, request.form.get(key, "").strip())
        return redirect(url_for("settings"))
    values = {key: db.get_setting(key, "") or "" for key in SETTINGS_KEYS}
    return render_template("settings.html", values=values)


def _form_to_data(form):
    return {
        "name": form.get("name", "").strip(),
        "avatar_url": form.get("avatar_url", "").strip(),
        "personality": form.get("personality", "").strip(),
        "backstory": form.get("backstory", "").strip(),
        "speech_style": form.get("speech_style", "").strip(),
        "boundaries": form.get("boundaries", "").strip(),
        "active": 1 if form.get("active") == "on" else 0,
        "welcome_enabled": 1 if form.get("welcome_enabled") == "on" else 0,
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
