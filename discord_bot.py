import os
import asyncio
import re
import time
from collections import defaultdict, deque

import discord
from google import genai
from google.genai import types

import database as db

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
MODEL = "gemini-3.5-flash"
HISTORY_LENGTH = 30
WEBHOOK_NAME = "Character Bots"
ACTIVE_CONVO_TIMEOUT = 180  # seconds a conversation stays "open" without repeating the character's name

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # required to detect new members joining

client = discord.Client(intents=intents)
genai_client = genai.Client(api_key=GEMINI_API_KEY)

# channel_id -> deque of {"role": "user"|"model", "parts": [text]}
history = defaultdict(lambda: deque(maxlen=HISTORY_LENGTH))
_webhook_cache = {}

# channel_id -> {"character_id": int, "user_id": int, "last_active": float}
active_conversations = {}


def default_boundaries() -> str:
    return (
        "Stay in character but never produce harmful, hateful, or NSFW "
        "content. Don't reproduce or closely paraphrase copyrighted "
        "book/show text or dialogue verbatim — speak in new, original "
        "lines. Keep most replies short and conversational (1-3 "
        "sentences) unless the moment calls for more. Never claim to be "
        "a real human if asked directly — everyone here knows you're an "
        "AI character bot."
    )


def build_system_prompt(character: dict) -> str:
    return f"""
You are playing a fictional character in a Discord server.

CHARACTER NAME: {character['name']}

PERSONALITY:
{character['personality']}

BACKSTORY:
{character['backstory']}

SPEECH STYLE:
{character['speech_style']}

BOUNDARIES:
{character['boundaries'] or default_boundaries()}

Reply only with what your character would say next — no stage directions,
no quotation marks around the whole reply, no name prefix.
""".strip()


async def get_webhook(channel: discord.TextChannel) -> discord.Webhook:
    if channel.id in _webhook_cache:
        return _webhook_cache[channel.id]
    webhooks = await channel.webhooks()
    webhook = discord.utils.get(webhooks, name=WEBHOOK_NAME)
    if webhook is None:
        webhook = await channel.create_webhook(name=WEBHOOK_NAME)
    _webhook_cache[channel.id] = webhook
    return webhook


def allowed_channel_ids() -> set:
    ids = set()
    for key in ("characters_channel_id", "welcome_channel_id", "announcements_channel_id"):
        value = db.get_setting(key)
        if value:
            try:
                ids.add(int(value))
            except ValueError:
                pass
    return ids


def find_mentioned_character(content: str, characters: list):
    words = set(re.findall(r"\w+", content.lower()))
    for character in characters:
        name_words = character["name"].lower().split()
        if any(name_word in words for name_word in name_words):
            return character
    return None


def _call_gemini(system_prompt: str, contents: list, max_tokens: int) -> str:
    response = genai_client.models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    if response.candidates:
        print(f"[DEBUG] Gemini finish_reason: {response.candidates[0].finish_reason}")
    return response.text or ""


def strip_name_prefix(reply: str, name: str) -> str:
    pattern = rf"^\s*{re.escape(name)}\s*:\s*"
    return re.sub(pattern, "", reply, count=1, flags=re.IGNORECASE).strip()


async def generate_reply(character: dict, channel_id: int) -> str:
    contents = list(history[channel_id])
    reply = await asyncio.to_thread(
        _call_gemini, build_system_prompt(character), contents, 2048
    )
    return strip_name_prefix(reply, character["name"])


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")


@client.event
async def on_member_join(member: discord.Member):
    welcome_channel_id = db.get_setting("welcome_channel_id")
    if not welcome_channel_id:
        return
    channel = client.get_channel(int(welcome_channel_id))
    if channel is None:
        return

    greeters = [c for c in db.list_characters(active_only=True) if c["welcome_enabled"]]
    if not greeters:
        return
    webhook = await get_webhook(channel)

    for character in greeters:
