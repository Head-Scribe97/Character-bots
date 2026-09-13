import os
import asyncio
from collections import defaultdict, deque

import discord
from google import genai
from google.genai import types

import database as db

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
MODEL = "gemini-3.8-flash"
HISTORY_LENGTH = 30
WEBHOOK_NAME = "Character Bots"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # required to detect new members joining

client = discord.Client(intents=intents)
genai_client = genai.Client(api_key=GEMINI_API_KEY)

# channel_id -> deque of {"role": "user"|"model", "parts": [text]}
history = defaultdict(lambda: deque(maxlen=HISTORY_LENGTH))
_webhook_cache = {}


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
    lowered = content.lower()
    for character in characters:
        if character["name"].lower() in lowered:
            return character
    return None


def _call_gemini(system_prompt: str, contents: list, max_tokens: int) -> str:
    response = genai_client.models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens,
        ),
    )
    return response.text or ""


async def generate_reply(character: dict, channel_id: int) -> str:
    contents = list(history[channel_id])
    return await asyncio.to_thread(
        _call_gemini, build_system_prompt(character), contents, 400
    )


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
        prompt_contents = [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            f"A new member named {member.display_name} just "
                            "joined the Discord server. Post a short, "
                            "in-character welcome message for them."
                        )
                    }
                ],
            }
        ]
        try:
            greeting = await asyncio.to_thread(
                _call_gemini, build_system_prompt(character), prompt_contents, 200
            )
        except Exception as e:
            print(f"Error generating welcome message for {character['name']}: {e}")
            continue

        if greeting:
            await webhook.send(
                content=greeting,
                username=character["name"],
                avatar_url=character["avatar_url"] or None,
            )
            await asyncio.sleep(1.5)  # stagger multiple greetings


@client.event
async def on_message(message: discord.Message):
    print(
        f"[DEBUG] Received message in channel {message.channel.id} "
        f"from {message.author}: {message.content!r}"
    )

    if message.author == client.user:
        return

    if message.webhook_id is not None:
        # A message posted by one of our own character webhooks — record it
        # so other characters can react to it, but don't reply to ourselves.
        history[message.channel.id].append(
            {"role": "model", "parts": [{"text": f"{message.author.name}: {message.content}"}]}
        )
        return

    allowed = allowed_channel_ids()
    print(f"[DEBUG] Allowed channel IDs from settings: {allowed}")
    if message.channel.id not in allowed:
        print("[DEBUG] Channel not in allowed list — ignoring.")
        return

    content = message.content.strip()
    author_name = message.author.display_name

    if content:
        history[message.channel.id].append(
            {"role": "user", "parts": [{"text": f"{author_name}: {content}"}]}
        )

    characters = db.list_characters(active_only=True)
    print(f"[DEBUG] Active characters: {[c['name'] for c in characters]}")
    character = find_mentioned_character(content, characters)

    if character is None and message.reference and message.reference.resolved:
        resolved = message.reference.resolved
        if getattr(resolved, "webhook_id", None):
            character = db.get_character_by_name(resolved.author.name)

    if character is None:
        print("[DEBUG] No character matched this message — ignoring.")
        return

    print(f"[DEBUG] Matched character: {character['name']} — generating reply.")

    async with message.channel.typing():
        try:
            reply = await generate_reply(character, message.channel.id)
        except Exception as e:
            print(f"Error generating reply: {e}")
            return

    if reply:
        webhook = await get_webhook(message.channel)
        await webhook.send(
            content=reply,
            username=character["name"],
            avatar_url=character["avatar_url"] or None,
        )
        history[message.channel.id].append(
            {"role": "model", "parts": [{"text": f"{character['name']}: {reply}"}]}
        )
