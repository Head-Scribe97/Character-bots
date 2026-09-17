import os
import asyncio
import random
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
REACTION_CHANCE = 0.12
REACTION_EMOJIS = ["😂", "👀", "🔥", "😳", "💀", "🐉", "⚔️", "❤️", "😬"]
SPONTANEOUS_CHANCE = 0.06
SPONTANEOUS_COOLDOWN = 90  # seconds between unprompted chime-ins, per channel
 
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
 
# channel_id -> unix timestamp of the last unprompted chime-in
_last_spontaneous = {}
 
 
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
 
 
def _call_gemini(system_prompt: str, contents: list, max_tokens: int, retries: int = 3) -> str:
    last_error = None
    for attempt in range(retries):
        try:
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
        except Exception as e:
            last_error = e
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                print(f"[DEBUG] Gemini overloaded (attempt {attempt + 1}/{retries}), retrying...")
                time.sleep(2 * (attempt + 1))
                continue
            raise
    raise last_error
 
 
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
 
    # Occasionally react to a human message with an emoji, independent of
    # whether a character actually replies. (Reactions always show as
    # coming from the bot's real account, since webhook "characters" can't
    # react themselves — same limitation as the typing indicator.)
    if content and random.random() < REACTION_CHANCE:
        try:
            await message.add_reaction(random.choice(REACTION_EMOJIS))
        except Exception as e:
            print(f"[DEBUG] Couldn't add reaction: {e}")
 
    characters = db.list_characters(active_only=True)
    print(f"[DEBUG] Active characters: {[c['name'] for c in characters]}")
    character = find_mentioned_character(content, characters)
 
    if character is None and message.reference and message.reference.resolved:
        resolved = message.reference.resolved
        if getattr(resolved, "webhook_id", None):
            character = db.get_character_by_name(resolved.author.name)
 
    if character is None:
        # No name mentioned and not a direct reply — check whether this
        # channel has an active, still-open conversation with a character.
        convo = active_conversations.get(message.channel.id)
        if convo and time.time() - convo["last_active"] <= ACTIVE_CONVO_TIMEOUT:
            character = db.get_character(convo["character_id"])
            if character:
                print(f"[DEBUG] Continuing active conversation with {character['name']}.")
 
    if character is None and characters:
        # Nobody was addressed directly — small random chance one of the
        # active characters chimes in unprompted, as long as it hasn't
        # happened too recently in this channel.
        last_spontaneous = _last_spontaneous.get(message.channel.id, 0)
        if (
            content
            and time.time() - last_spontaneous > SPONTANEOUS_COOLDOWN
            and random.random() < SPONTANEOUS_CHANCE
        ):
            character = random.choice(characters)
            _last_spontaneous[message.channel.id] = time.time()
            print(f"[DEBUG] Spontaneous chime-in from {character['name']}.")
 
    if character is None:
        print("[DEBUG] No character matched this message — ignoring.")
        return
 
    print(f"[DEBUG] Matched character: {character['name']} — generating reply.")
 
    async with message.channel.typing():
        try:
            reply = await generate_reply(character, message.channel.id)
        except Exception as e:
            print(f"Error generating reply: {e}")
            webhook = await get_webhook(message.channel)
            await webhook.send(
                content="(signal's spotty — give me a sec and try that again)",
                username=character["name"],
                avatar_url=character["avatar_url"] or None,
            )
            return
 
        # Natural-feeling pause before sending — longer replies take a
        # little longer to "type."
        if reply:
            delay = min(0.4 + len(reply) * 0.02, 4.0)
            await asyncio.sleep(delay)
 
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
        active_conversations[message.channel.id] = {
            "character_id": character["id"],
            "user_id": message.author.id,
            "last_active": time.time(),
        }
 
 
async def post_announcement(character_id: int, topic: str) -> str:
    """Called from the dashboard to have a character post directly to the
    announcements channel, with no chat message needed to trigger it."""
    character = db.get_character(character_id)
    if not character:
        raise ValueError("Character not found.")
 
    channel_id = db.get_setting("announcements_channel_id")
    if not channel_id:
        raise ValueError("No announcements channel set in Settings.")
 
    channel = client.get_channel(int(channel_id))
    if channel is None:
        raise ValueError("Couldn't find that channel — check the bot has access to it.")
 
    prompt_contents = [
        {
            "role": "user",
            "parts": [
                {
                    "text": (
                        "Write a short in-character announcement post for "
                        f"the server about: {topic}"
                    )
                }
            ],
        }
    ]
    text = await asyncio.to_thread(
        _call_gemini, build_system_prompt(character), prompt_contents, 800
    )
    text = strip_name_prefix(text, character["name"])
 
    webhook = await get_webhook(channel)
    await webhook.send(
        content=text,
        username=character["name"],
        avatar_url=character["avatar_url"] or None,
    )
    history[channel.id].append(
        {"role": "model", "parts": [{"text": f"{character['name']}: {text}"}]}
    )
    return text
 
