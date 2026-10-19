import os
import re
import sqlite3
import logging
import discord
from discord.ext import commands
from discord.ui import View, Button, Select, Modal, TextInput

# ============================================================
# PRO ST PAID TOUR MANAGER — PRODUCTION ARCHITECTURE
# Fully Compatible with discord.py 2.x & SQLite probot.db
# Modern Esports Visual Design & Slot List Formatting
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("pro_st")

# Discord Bot Token from Environment
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Core Constants
DB_PATH = "probot.db"
PANEL_TITLE = "PRO ST Paid Tour Manager"

# Premium Esports Color Palette
COLOR_PRIMARY = discord.Colour(0x5865F2)      # Discord Royal Blurple
COLOR_GOLD = discord.Colour(0xF59E0B)         # Championship Trophy Amber
COLOR_SUCCESS = discord.Colour(0x10B981)      # Emerald Neon Green (Approved)
COLOR_DANGER = discord.Colour(0xEF4444)       # Crimson Red (Rejected / Destructive)
COLOR_INFO = discord.Colour(0x3B82F6)         # Vibrant Cobalt Blue (Panels / Info)
COLOR_DARK = discord.Colour(0x1E1F22)         # Deep Esports Charcoal

# Backward-Compatible Color Aliases (guarantees zero breakage)
RED = COLOR_DANGER
GREEN = COLOR_SUCCESS
BLUE = COLOR_INFO
GOLD = COLOR_GOLD

MOD_ROLE = "Scrime Mod"
LEGACY_MOD_ROLE = "Scrim Mod"
ADMIN_ROLE = "Admin"
REG_CHANNEL = "paid-tour-registration"
LOG_CHANNEL = "payment-logs"
SCRIM_MAPS = "Bermuda, Purgatory, Kalahari"

# Default temporary interaction expiration (seconds)
PANEL_EXPIRY_SECONDS = 60

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix=["!", "?"], intents=intents, help_command=None)
views_loaded = False


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def make_embed(title, description=None, colour=COLOR_INFO, footer_text=None, timestamp=True):
    """
    Creates a modern, high-contrast, esports-styled Discord embed.
    Consistent typography, timestamps, and branding.
    """
    embed = discord.Embed(title=title, description=description, colour=colour)
    if timestamp:
        embed.timestamp = discord.utils.utcnow()
    footer = footer_text or "PRO ST Paid Tour Manager • Safe & Automated Slot System"
    embed.set_footer(text=footer)
    return embed


async def reply_embed(target, title, description, ephemeral=False, colour=COLOR_INFO):
    embed = make_embed(title, description, colour=colour)
    if isinstance(target, discord.Interaction):
        if target.response.is_done():
            await target.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            await target.response.send_message(embed=embed, ephemeral=ephemeral)
    else:
        await target.reply(embed=embed)


def safe_text(value, fallback="N/A"):
    """
    Safely handles str, int, float, None and other types.
    Converts to string before stripping to prevent AttributeError.
    """
    if value is None:
        return fallback
    value = str(value).strip()
    return value if value else fallback


def slugify(value):
    if value is None:
        return "tour"
    value = str(value)
    value = re.sub(r"[^a-zA-Z0-9-]", "-", value.lower())
    value = re.sub(r"-+", "-", value).strip("-")
    return (value[:80] or "tour").strip("-")


def parse_maps(value):
    if value is None:
        return "Not set"
    maps = [part.strip() for part in str(value).replace("\n", ",").split(",")]
    return ", ".join(part for part in maps if part) or "Not set"


def format_tour_type(tour_type_raw):
    raw = str(tour_type_raw or "scrim").strip().lower()
    if raw in ("scrim", "scrime"):
        return "Scrime"
    if raw == "champion_rush":
        return "Champion Rush"
    if raw == "custom":
        return "Custom Tournament"
    return raw.replace("_", " ").title()


def format_tour(tour):
    tour_type = format_tour_type(tour["tour_type"])
    badge = "🔥" if "scrim" in str(tour["tour_type"] or "").lower() else ("👑" if "champion" in str(tour["tour_type"] or "").lower() else "⚙️")
    lines = [
        f"🏆 **Tournament:** `{safe_text(tour['name'])}`",
        f"🏷️ **Category:** {badge} **{tour_type}**",
        f"⚔️ **Game Mode:** `{safe_text(tour['mode'], 'Squad')}`",
        f"🗓️ **Date & Time:** `{safe_text(tour['date_time'])}`",
        f"💰 **Entry Fee:** `{safe_text(tour['fee'])}`",
        f"🎮 **Matches:** `{tour['matches'] or 3} Matches`",
        f"🗺️ **Maps:** `{safe_text(tour['maps'])}`",
    ]
    if str(tour["tour_type"] or "").lower() == "champion_rush":
        lines.append(f"🔓 **Unlock Points:** `{safe_text(tour['unlock_points'])} points`")
    lines.append(f"👥 **Total Capacity:** `{tour['total_slots']} Slots`")
    lines.append(f"🆔 **Tour Reference:** `ID #{tour['id']}`")
    return "\n".join(lines)


def is_manager(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    settings = get_settings(member.guild.id)
    if settings and settings["mod_role_id"]:
        if any(role.id == settings["mod_role_id"] for role in member.roles):
            return True
    for role in member.roles:
        if role.name.lower() in (MOD_ROLE.lower(), LEGACY_MOD_ROLE.lower(), ADMIN_ROLE.lower()):
            return True
    return False


# ============================================================
# DATABASE ENGINE (TRANSACTIONAL & STRICTLY NON-DESTRUCTIVE)
# ============================================================

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    """
    Initializes tables and runs non-destructive schema migrations.
    Never drops tables or deletes user records.
    """
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tournaments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                mode TEXT DEFAULT 'Squad',
                date_time TEXT NOT NULL,
                fee TEXT NOT NULL,
                total_slots INTEGER NOT NULL,
                guild_id INTEGER,
                role_id INTEGER,
                channel_id INTEGER,
                tour_type TEXT DEFAULT 'scrim',
                matches INTEGER DEFAULT 3,
                maps TEXT,
                unlock_points TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tournament_id INTEGER NOT NULL,
                slot_number INTEGER NOT NULL,
                status TEXT DEFAULT 'available',
                team_name TEXT,
                assigned_user_id INTEGER,
                FOREIGN KEY (tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tournament_id INTEGER NOT NULL,
                discord_user_id INTEGER NOT NULL,
                team_name TEXT NOT NULL,
                p1_ign TEXT NOT NULL,
                p2_ign TEXT,
                p3_ign TEXT,
                p4_ign TEXT,
                p1_uid TEXT,
                transaction_id TEXT,
                screenshot_url TEXT,
                status TEXT DEFAULT 'pending',
                slot_number INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                guild_id INTEGER PRIMARY KEY,
                payment_method TEXT DEFAULT 'bKash',
                payment_number TEXT,
                registration_channel_id INTEGER,
                log_channel_id INTEGER,
                mod_role_id INTEGER,
                registration_message_id INTEGER,
                panel_expiry_seconds INTEGER DEFAULT 120
            );
        """)

        def add_missing_columns(table_name, col_definitions):
            cur = conn.execute(f"PRAGMA table_info({table_name});")
            existing = {row["name"] for row in cur.fetchall()}
            for col, definition in col_definitions.items():
                if col not in existing:
                    try:
                        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {col} {definition};")
                        logger.info(f"Safe Migration: Added column '{col}' to table '{table_name}'.")
                    except sqlite3.OperationalError as e:
                        logger.warning(f"Column add note ({table_name}.{col}): {e}")

        add_missing_columns("tournaments", {
            "guild_id": "INTEGER",
            "role_id": "INTEGER",
            "channel_id": "INTEGER",
            "tour_type": "TEXT DEFAULT 'scrim'",
            "matches": "INTEGER DEFAULT 3",
            "maps": f"TEXT DEFAULT '{SCRIM_MAPS}'",
            "unlock_points": "TEXT",
            "mode": "TEXT DEFAULT 'Squad'",
        })

        add_missing_columns("slots", {
            "assigned_user_id": "INTEGER",
        })

        add_missing_columns("registrations", {
            "p1_uid": "TEXT",
            "p2_ign": "TEXT",
            "p3_ign": "TEXT",
            "p4_ign": "TEXT",
            "slot_number": "INTEGER",
        })

        add_missing_columns("settings", {
            "registration_message_id": "INTEGER",
            "mod_role_id": "INTEGER",
            "panel_expiry_seconds": "INTEGER DEFAULT 120",
        })

        # Backfill default tour_type
        conn.execute("""
            UPDATE tournaments
            SET tour_type='scrim'
            WHERE tour_type IS NULL OR tour_type='';
        """)
        # Backfill default maps
        conn.execute("""
            UPDATE tournaments
            SET maps=?
            WHERE maps IS NULL OR maps='';
        """, (SCRIM_MAPS,))


def get_tournament(tour_id):
    with db() as conn:
        return conn.execute("SELECT * FROM tournaments WHERE id=?", (tour_id,)).fetchone()


def tournament_options(guild_id):
    with db() as conn:
        return conn.execute("""
            SELECT * FROM tournaments
            WHERE guild_id=?
            ORDER BY id DESC
        """, (guild_id,)).fetchall()


def get_scrimes(guild_id):
    with db() as conn:
        return conn.execute("""
            SELECT * FROM tournaments
            WHERE guild_id=? AND LOWER(tour_type) IN ('scrim', 'scrime')
            ORDER BY id DESC
        """, (guild_id,)).fetchall()


def get_settings(guild_id):
    with db() as conn:
        row = conn.execute("SELECT * FROM settings WHERE guild_id=?", (guild_id,)).fetchone()
        if not row:
            conn.execute("INSERT OR IGNORE INTO settings (guild_id) VALUES (?)", (guild_id,))
            row = conn.execute("SELECT * FROM settings WHERE guild_id=?", (guild_id,)).fetchone()
        return row


def save_settings(guild_id, **kwargs):
    if not kwargs:
        return
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO settings (guild_id) VALUES (?)", (guild_id,))
        fields = ", ".join(f"{k}=?" for k in kwargs.keys())
        values = list(kwargs.values()) + [guild_id]
        conn.execute(f"UPDATE settings SET {fields} WHERE guild_id=?", values)


# ============================================================
# CHANNELS & ROLES ASSURANCE
# ============================================================

async def ensure_registration_channel(guild: discord.Guild):
    settings = get_settings(guild.id)
    if settings and settings["registration_channel_id"]:
        ch = guild.get_channel(settings["registration_channel_id"])
        if ch:
            return ch

    ch = discord.utils.get(guild.text_channels, name=REG_CHANNEL)
    if ch:
        save_settings(guild.id, registration_channel_id=ch.id)
        return ch

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True, send_messages=False, read_message_history=True,
            create_public_threads=False, create_private_threads=False, send_messages_in_threads=False
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, embed_links=True, attach_files=True
        )
    }
    new_ch = await guild.create_text_channel(
        REG_CHANNEL,
        overwrites=overwrites,
        reason="PRO ST automated registration channel"
    )
    save_settings(guild.id, registration_channel_id=new_ch.id)
    return new_ch


async def ensure_log_channel(guild: discord.Guild):
    settings = get_settings(guild.id)
    if settings and settings["log_channel_id"]:
        ch = guild.get_channel(settings["log_channel_id"])
        if ch:
            return ch

    ch = discord.utils.get(guild.text_channels, name=LOG_CHANNEL)
    if ch:
        save_settings(guild.id, log_channel_id=ch.id)
        return ch

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False, create_public_threads=False, create_private_threads=False,
            send_messages_in_threads=False
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, embed_links=True, attach_files=True
        )
    }
    new_ch = await guild.create_text_channel(
        LOG_CHANNEL,
        overwrites=overwrites,
        reason="PRO ST payment log verification channel"
    )
    save_settings(guild.id, log_channel_id=new_ch.id)
    return new_ch


async def ensure_mod_role(guild: discord.Guild):
    settings = get_settings(guild.id)
    if settings and settings["mod_role_id"]:
        role = guild.get_role(settings["mod_role_id"])
        if role:
            return role

    for role_name in (MOD_ROLE, LEGACY_MOD_ROLE):
        existing = discord.utils.get(guild.roles, name=role_name)
        if existing:
            save_settings(guild.id, mod_role_id=existing.id)
            return existing

    try:
        new_role = await guild.create_role(
            name=MOD_ROLE,
            colour=discord.Colour.orange(),
            reason="PRO ST tournament moderator role"
        )
        save_settings(guild.id, mod_role_id=new_role.id)
        return new_role
    except discord.Forbidden:
        return None


# ============================================================
# REGISTRATION ANNOUNCEMENT (PREMIUM ESPORTS DESIGN)
# ============================================================

def get_registration_announcement_embed():
    """
    Modern, attractive, and professional registration announcement embed.
    Clean esports visual hierarchy, clear instructions, no clutter.
    """
    desc = (
        "⚡ **Welcome to the Official PRO ST Tournament Portal!**\n\n"
        "এখানে নিয়মিত **Daily Scrime**, **Champion Rush** ও বিশেষ **Custom Tournament** আয়োজন করা হয়। "
        "নিরাপদ ও স্বয়ংক্রিয় স্লট বুকিংয়ের জন্য নিচের ধাপগুলো অনুসরণ করুন:\n\n"
        "📌 **অংশগ্রহণের নিয়মাবলী:**\n"
        "• 1️⃣ নিচের **Register Now** বাটনে ক্লিক করুন।\n"
        "• 2️⃣ অ্যাক্টিভ টুর্নামেন্ট বেছে নিয়ে দলের তথ্য ও প্লেয়ারদের IGN দিন।\n"
        "• 3️⃣ বটের DM-এ প্রেরিত নম্বরে ফি পাঠিয়ে স্ক্রিনশট সাবমিট করুন।\n"
        "• 4️⃣ Scrime Mod ভেরিফাই করার সাথে সাথে অফিশিয়াল স্লট কনফার্ম হবে।\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👉 টুর্নামেন্ট দেখতে বা অংশ নিতে নিচের বাটনে ক্লিক করুন।"
    )
    embed = make_embed(
        "🏆 PRO ST TOURNAMENT REGISTRATION DESK",
        desc,
        colour=COLOR_GOLD
    )
    embed.set_footer(text="PRO ST Esports • Safe & Automated Slot System • Real-Time Sync")
    return embed


async def post_tour_registration(guild, tour_id=None):
    """
    Ensures a single, professional Registration Announcement exists in the guild's
    registration channel. Reuses existing message to avoid duplicate spam.
    """
    channel = await ensure_registration_channel(guild)
    settings = get_settings(guild.id)
    embed = get_registration_announcement_embed()

    existing_msg = None
    if settings and settings["registration_message_id"]:
        try:
            existing_msg = await channel.fetch_message(settings["registration_message_id"])
        except (discord.NotFound, discord.HTTPException):
            existing_msg = None

    if existing_msg is not None:
        try:
            await existing_msg.edit(embed=embed, view=RegistrationView())
            return existing_msg
        except discord.HTTPException:
            pass

    # Post new announcement and record message ID
    new_msg = await channel.send(embed=embed, view=RegistrationView())
    save_settings(guild.id, registration_message_id=new_msg.id)
    return new_msg


# ============================================================
# APPROVED TEAM SLOT LIST (EXACT SPECIFICATION)
# ============================================================

async def refresh_tournament_team_list(guild: discord.Guild, tour_id: int):
    """
    Keep one roster embed in the tournament channel, displaying ONLY approved teams.
    Format exactly as required:
    Slot 01 → Team Apex Trine
               Player: PlayerOne | PlayerTwo

    Slot 02 → Team Alpha
               Player: PlayerThree | PlayerFour
    Updates existing message instead of posting duplicate messages.
    Does NOT post individual team welcome messages in the channel.
    """
    tour = get_tournament(tour_id)
    if not tour or not tour["channel_id"]:
        return
    channel = guild.get_channel(tour["channel_id"])
    if not isinstance(channel, discord.TextChannel):
        return

    with db() as conn:
        rows = conn.execute(
            "SELECT slot_number, team_name, p1_ign, p2_ign FROM registrations "
            "WHERE tournament_id=? AND LOWER(status)='approved' "
            "AND slot_number IS NOT NULL ORDER BY slot_number ASC",
            (tour_id,)
        ).fetchall()

    lines = []
    for row in rows:
        slot_number = int(row["slot_number"])
        team_name = safe_text(row["team_name"], "Unnamed Team")
        p1_ign = safe_text(row["p1_ign"], "—")
        p2_ign = safe_text(row["p2_ign"], "—")
        # Format strictly compliant with specification:
        lines.append(f"Slot {slot_number:02} → {team_name}\n           Player: {p1_ign} | {p2_ign}")

    total_slots = tour["total_slots"]
    approved_count = len(rows)

    if lines:
        roster_text = "\n\n".join(lines)
        description = (
            f"**Tournament:** `{safe_text(tour['name'])}`\n"
            f"**Mode:** `{safe_text(tour['mode'], 'Squad')}` • **Approved Slots:** `{approved_count}/{total_slots}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"```\n{roster_text}\n```"
        )
    else:
        description = (
            f"**Tournament:** `{safe_text(tour['name'])}`\n"
            f"**Mode:** `{safe_text(tour['mode'], 'Squad')}` • **Approved Slots:** `0/{total_slots}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⏳ *এখনো কোনো Approved দল নেই। স্লট বরাদ্দের অপেক্ষায় রয়েছে...*"
        )

    if len(description) > 4000:
        description = description[:3950] + "\n```\n… আরও দল রয়েছে।"

    embed = make_embed(
        f"🏆 OFFICIAL SLOT LIST — {safe_text(tour['name']).upper()}",
        description,
        colour=COLOR_GOLD
    )
    embed.set_footer(text=f"PRO ST Esports • {safe_text(tour['name'])} • Approved Teams Only")

    try:
        async for message in channel.history(limit=50):
            if message.author.id == bot.user.id and message.embeds:
                title = message.embeds[0].title or ""
                # Match current title or legacy title to edit in-place
                if "OFFICIAL SLOT LIST" in title or title == "📋 Registered Teams":
                    await message.edit(embed=embed)
                    return
        await channel.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException) as exc:
        logger.warning("Could not refresh team roster for tournament %s: %s", tour_id, exc)


# ============================================================
# CREATE TOUR FLOW (COMPLIANT WITH DISCORD MODAL RULES)
# ============================================================

class TourTypeSelect(Select):
    def __init__(self):
        super().__init__(
            placeholder="Choose tournament category to create",
            min_values=1, max_values=1,
            options=[
                discord.SelectOption(
                    label="Scrime",
                    value="scrim",
                    description="Standard 3 matches; Bermuda, Purgatory, Kalahari",
                    emoji="🔥"
                ),
                discord.SelectOption(
                    label="Champion Rush",
                    value="champion_rush",
                    description="Competitive rush; custom matches, maps & unlock points",
                    emoji="👑"
                ),
                discord.SelectOption(
                    label="Custom Tournament",
                    value="custom",
                    description="Full custom cup; Solo/Duo/Squad with custom maps",
                    emoji="⚙️"
                ),
            ]
        )

    async def callback(self, interaction: discord.Interaction):
        if not is_manager(interaction.user):
            return await reply_embed(interaction, "Permission Denied", "এই action করার permission নেই.", ephemeral=True, colour=COLOR_DANGER)
        await interaction.response.send_modal(CreateTourBaseModal(self.values[0]))


class TourTypePicker(View):
    def __init__(self):
        super().__init__(timeout=PANEL_EXPIRY_SECONDS)
        self.add_item(TourTypeSelect())


class CreateTourStep2PromptView(View):
    def __init__(self, tour_type, name, date_time, fee, total_slots):
        super().__init__(timeout=PANEL_EXPIRY_SECONDS)
        self.tour_type = tour_type
        self.name = name
        self.date_time = date_time
        self.fee = fee
        self.total_slots = total_slots

    @discord.ui.button(label="Continue to Step 2 (Settings)", style=discord.ButtonStyle.primary, emoji="➡️")
    async def continue_step2(self, interaction: discord.Interaction, button: Button):
        if not is_manager(interaction.user):
            return await reply_embed(interaction, "Permission Denied", "এই action করার permission নেই.", ephemeral=True, colour=COLOR_DANGER)
        modal = CreateTourDetailsModal(
            self.tour_type, self.name, self.date_time, self.fee, self.total_slots
        )
        await interaction.response.send_modal(modal)


class CreateTourBaseModal(Modal):
    def __init__(self, tour_type):
        self.tour_type = tour_type
        titles = {
            "scrim": "Create Scrime (Step 1/2)",
            "champion_rush": "Create Champion Rush (Step 1/2)",
            "custom": "Create Custom Tour (Step 1/2)",
        }
        super().__init__(title=titles.get(tour_type, "Create Tournament (Step 1/2)"))

        self.name_field = TextInput(label="Tournament Name", placeholder="e.g. 9:00 PM Daily Scrime", max_length=100)
        self.date_field = TextInput(label="Date & Time", placeholder="e.g. 20-10-2026, 9:00 PM", max_length=100)
        self.fee_field = TextInput(label="Entry Fee", placeholder="e.g. 50 BDT (or Free)", max_length=50)
        self.slots_field = TextInput(label="Total Slots (Number)", placeholder="12", default="12", max_length=4)

        self.add_item(self.name_field)
        self.add_item(self.date_field)
        self.add_item(self.fee_field)
        self.add_item(self.slots_field)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_manager(interaction.user):
            return await reply_embed(interaction, "Permission Denied", "এই action করার permission নেই.", ephemeral=True, colour=COLOR_DANGER)

        name = self.name_field.value.strip()
        date_time = self.date_field.value.strip()
        fee = self.fee_field.value.strip()
        slots_str = self.slots_field.value.strip()

        try:
            total_slots = int(slots_str)
            if not 1 <= total_slots <= 100:
                raise ValueError
        except ValueError:
            return await reply_embed(interaction, "Invalid Slots", "Total slots 1 থেকে 100-এর মধ্যে হতে হবে.", ephemeral=True, colour=COLOR_DANGER)

        embed = make_embed(
            "✅ Step 1 Saved!",
            f"**Tournament Name:** `{name}`\n"
            f"**Date & Time:** `{date_time}`\n"
            f"**Entry Fee:** `{fee}`\n"
            f"**Total Slots:** `{total_slots}`\n\n"
            "👉 নিচের **Continue to Step 2 (Settings)** বাটনে ক্লিক করে Mode, Matches ও Maps নির্ধারণ করুন।",
            colour=COLOR_INFO
        )
        view = CreateTourStep2PromptView(self.tour_type, name, date_time, fee, total_slots)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class CreateTourDetailsModal(Modal):
    def __init__(self, tour_type, tour_name, date_time, fee, total_slots):
        self.tour_type = tour_type
        self.tour_name = tour_name
        self.date_time = date_time
        self.fee = fee
        self.total_slots = total_slots

        titles = {
            "scrim": "Scrime Settings (Step 2/2)",
            "champion_rush": "Champion Rush Settings (Step 2/2)",
            "custom": "Custom Settings (Step 2/2)",
        }
        super().__init__(title=titles.get(tour_type, "Settings (Step 2/2)"))

        self.mode_field = TextInput(label="Mode (Solo, Duo, Squad)", default="Squad", max_length=10)
        self.matches_field = TextInput(label="Matches (Number)", default="3", max_length=3)
        self.add_item(self.mode_field)
        self.add_item(self.matches_field)

        self.maps_field = None
        self.unlock_field = None

        if tour_type == "scrim":
            self.maps_field = TextInput(label="Maps (default B/P/K)", default=SCRIM_MAPS, max_length=200)
            self.add_item(self.maps_field)
        elif tour_type == "champion_rush":
            self.unlock_field = TextInput(label="Champion Rush Unlock Points", placeholder="e.g. 50", max_length=50)
            self.add_item(self.unlock_field)
            self.maps_field = TextInput(label="Maps, comma separated", placeholder="Bermuda, Purgatory", default=SCRIM_MAPS, max_length=200)
            self.add_item(self.maps_field)
        else:
            self.maps_field = TextInput(label="Maps, comma separated", placeholder="Bermuda, Purgatory", default=SCRIM_MAPS, max_length=200)
            self.add_item(self.maps_field)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_manager(interaction.user):
            return await reply_embed(interaction, "Permission Denied", "এই action করার permission নেই.", ephemeral=True, colour=COLOR_DANGER)

        mode = self.mode_field.value.strip().title()
        if mode not in ("Solo", "Duo", "Squad"):
            return await reply_embed(interaction, "Invalid Mode", "Mode অবশ্যই Solo, Duo অথবা Squad হতে হবে.", ephemeral=True, colour=COLOR_DANGER)

        try:
            matches = int(self.matches_field.value.strip())
            if not 1 <= matches <= 30:
                raise ValueError
        except (ValueError, AttributeError):
            return await reply_embed(interaction, "Invalid Matches", "Match সংখ্যা 1 থেকে 30-এর মধ্যে হতে হবে.", ephemeral=True, colour=COLOR_DANGER)

        maps = parse_maps(self.maps_field.value if self.maps_field else SCRIM_MAPS)
        if self.tour_type == "scrim" and not maps:
            maps = SCRIM_MAPS
        unlock = self.unlock_field.value.strip() if self.unlock_field else None
        if self.tour_type == "champion_rush" and not unlock:
            return await reply_embed(interaction, "Unlock Points Required", "Champion Rush unlock point লিখতে হবে.", ephemeral=True, colour=COLOR_DANGER)

        guild = interaction.guild
        if not guild:
            return await reply_embed(interaction, "Server Required", "Server-এর মধ্যে ব্যবহার করো.", ephemeral=True, colour=COLOR_DANGER)

        await interaction.response.defer(ephemeral=True)

        role = None
        channel = None
        tour_id = None
        try:
            # 1. Create Role
            try:
                role = await guild.create_role(
                    name=f"{self.tour_name[:80]} Players",
                    reason="PRO ST tournament player role"
                )
            except discord.Forbidden:
                raise PermissionError("Bot lacks 'Manage Roles' permission or Bot role is below member roles in Server Settings.")

            # 2. Create Private Channel
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                role: discord.PermissionOverwrite(
                    view_channel=True, send_messages=False, read_message_history=True,
                    create_public_threads=False, create_private_threads=False, send_messages_in_threads=False
                ),
            }
            if guild.me:
                overwrites[guild.me] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True,
                    manage_channels=True, embed_links=True, attach_files=True,
                    create_public_threads=False, create_private_threads=False, send_messages_in_threads=False
                )
            try:
                channel = await guild.create_text_channel(
                    f"tour-{slugify(self.tour_name)}"[:100],
                    overwrites=overwrites,
                    reason="PRO ST private tournament channel"
                )
            except discord.Forbidden:
                raise PermissionError("Bot lacks 'Manage Channels' permission in this server.")

            # 3. Save to database
            with db() as conn:
                cursor = conn.execute("""
                    INSERT INTO tournaments
                    (name, mode, date_time, fee, total_slots, guild_id, role_id,
                     channel_id, tour_type, matches, maps, unlock_points)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    self.tour_name, mode, self.date_time, self.fee,
                    self.total_slots, guild.id, role.id, channel.id,
                    self.tour_type, matches, maps, unlock
                ))
                tour_id = cursor.lastrowid
                conn.executemany("""
                    INSERT INTO slots (tournament_id, slot_number, status, team_name)
                    VALUES (?, ?, 'available', NULL)
                """, [(tour_id, n) for n in range(1, self.total_slots + 1)])

            # 4. Refresh registration announcement (prevents duplicates)
            reg_channel = await ensure_registration_channel(guild)
            announcement = ""
            try:
                await post_tour_registration(guild, tour_id)
                announcement = f"**Registration Channel:** {reg_channel.mention}"
            except Exception as post_error:
                logger.error(f"Registration announcement error: {post_error}")
                announcement = "⚠️ **Note:** Tournament তৈরি হয়েছে, কিন্তু registration চ্যানেলে পোস্ট করা যায়নি।"

            # 5. Success Embed
            tour = get_tournament(tour_id)
            tour_details = format_tour(tour) if tour else f"**Name:** {self.tour_name}\n**Slots:** {self.total_slots}"

            embed = make_embed(
                "🏆 TOURNAMENT CREATED SUCCESSFULLY!",
                tour_details,
                colour=COLOR_SUCCESS
            )
            embed.add_field(name="🔒 Private Channel", value=channel.mention, inline=True)
            embed.add_field(name="🛡️ Player Role", value=role.mention, inline=True)
            if announcement:
                embed.add_field(name="📢 Announcement", value=announcement, inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)

        except PermissionError as perm_err:
            logger.error(f"Permission error: {perm_err}")
            if tour_id:
                with db() as conn:
                    conn.execute("DELETE FROM slots WHERE tournament_id=?", (tour_id,))
                    conn.execute("DELETE FROM tournaments WHERE id=?", (tour_id,))
            for resource in (channel, role):
                if resource:
                    try:
                        await resource.delete(reason="Tour creation rollback")
                    except discord.HTTPException:
                        pass
            await interaction.followup.send(
                embed=make_embed("Permission Error", str(perm_err), colour=COLOR_DANGER),
                ephemeral=True
            )
        except Exception as error:
            logger.error(f"Create tour error: {error}", exc_info=True)
            if tour_id:
                with db() as conn:
                    conn.execute("DELETE FROM slots WHERE tournament_id=?", (tour_id,))
                    conn.execute("DELETE FROM tournaments WHERE id=?", (tour_id,))
            for resource in (channel, role):
                if resource:
                    try:
                        await resource.delete(reason="Tour creation rollback")
                    except discord.HTTPException:
                        pass
            err_detail = f"{type(error).__name__}: {str(error)}"
            await interaction.followup.send(
                embed=make_embed(
                    "❌ Create Failed (Error Details)",
                    f"**টুর্নামেন্ট তৈরি করতে সমস্যা হয়েছে:**\n```{err_detail}```\n"
                    "👉 **কীভাবে ঠিক করবেন:**\n"
                    "1. আপনার সার্ভার সেটিংসে গিয়ে **Roles** অপশনে যান।\n"
                    "2. বট-এর রোলটি সাধারণ মেম্বার রোলের **উপরে টেনে তুলুন** (Role Hierarchy)।\n"
                    "3. বট রোলে **Administrator** বা 'Manage Roles' ও 'Manage Channels' পারমিশন অন আছে কি না নিশ্চিত করুন।",
                    colour=COLOR_DANGER
                ),
                ephemeral=True
            )


# ============================================================
# EDIT TOUR FLOW (MULTI-STEP SAFE)
# ============================================================

class EditTourSelect(Select):
    def __init__(self, guild_id):
        tours = tournament_options(guild_id)
        options = [
            discord.SelectOption(
                label=row["name"][:100],
                description=f"{format_tour_type(row['tour_type'])} | Mode: {row['mode'] or 'Squad'} | Fee: {row['fee']}",
                value=str(row["id"]),
                emoji="⚙️"
            )
            for row in tours[:25]
        ]
        super().__init__(placeholder="Choose tournament to edit", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if not is_manager(interaction.user):
            return await reply_embed(interaction, "Permission Denied", "এই action করার permission নেই.", ephemeral=True, colour=COLOR_DANGER)
        tour_id = int(self.values[0])
        tour = get_tournament(tour_id)
        if not tour or tour["guild_id"] != interaction.guild_id:
            return await reply_embed(interaction, "Tour Not Found", "Tour পাওয়া যায়নি.", ephemeral=True, colour=COLOR_DANGER)
        await interaction.response.send_modal(EditTourBaseModal(tour))


class EditTourPicker(View):
    def __init__(self, guild_id):
        super().__init__(timeout=PANEL_EXPIRY_SECONDS)
        tours = tournament_options(guild_id)
        if tours:
            self.add_item(EditTourSelect(guild_id))


class EditTourStep2PromptView(View):
    def __init__(self, tour_id):
        super().__init__(timeout=PANEL_EXPIRY_SECONDS)
        self.tour_id = tour_id

    @discord.ui.button(label="Continue to Step 2 (Mode, Matches, Maps)", style=discord.ButtonStyle.primary, emoji="➡️")
    async def continue_step2(self, interaction: discord.Interaction, button: Button):
        if not is_manager(interaction.user):
            return await reply_embed(interaction, "Permission Denied", "এই action করার permission নেই.", ephemeral=True, colour=COLOR_DANGER)
        tour = get_tournament(self.tour_id)
        if not tour or tour["guild_id"] != interaction.guild_id:
            return await reply_embed(interaction, "Tour Not Found", "Tour পাওয়া যায়নি.", ephemeral=True, colour=COLOR_DANGER)
        await interaction.response.send_modal(EditTourDetailsModal(tour))


class EditTourBaseModal(Modal):
    def __init__(self, tour):
        self.tour_id = tour["id"]
        super().__init__(title=f"Edit Tour: {tour['name']}"[:45])
        self.name_field = TextInput(label="Tournament Name", default=tour["name"][:100], max_length=100)
        self.date_field = TextInput(label="Date & Time", default=tour["date_time"][:100], max_length=100)
        self.fee_field = TextInput(label="Entry Fee", default=str(tour["fee"])[:50], max_length=50)
        self.slots_field = TextInput(label="Total Slots", default=str(tour["total_slots"]), max_length=4)

        self.add_item(self.name_field)
        self.add_item(self.date_field)
        self.add_item(self.fee_field)
        self.add_item(self.slots_field)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_manager(interaction.user):
            return await reply_embed(interaction, "Permission Denied", "এই action করার permission নেই.", ephemeral=True, colour=COLOR_DANGER)
        try:
            total_slots = int(self.slots_field.value.strip())
            if not 1 <= total_slots <= 100:
                raise ValueError
        except ValueError:
            return await reply_embed(interaction, "Invalid Slots", "Slots 1 থেকে 100-এর মধ্যে হতে হবে.", ephemeral=True, colour=COLOR_DANGER)

        new_name = self.name_field.value.strip()
        new_date = self.date_field.value.strip()
        new_fee = self.fee_field.value.strip()

        with db() as conn:
            conn.execute("""
                UPDATE tournaments
                SET name=?, date_time=?, fee=?, total_slots=?
                WHERE id=?
            """, (new_name, new_date, new_fee, total_slots, self.tour_id))

        tour = get_tournament(self.tour_id)
        guild = interaction.guild
        if guild and tour and tour["channel_id"]:
            ch = guild.get_channel(tour["channel_id"])
            if ch:
                try:
                    await ch.edit(name=f"tour-{slugify(new_name)}"[:100])
                except discord.HTTPException:
                    pass

        embed = make_embed(
            "✅ Step 1 Updated!",
            f"**Name:** `{new_name}`\n"
            f"**Date & Time:** `{new_date}`\n"
            f"**Fee:** `{new_fee}`\n"
            f"**Slots:** `{total_slots}`\n\n"
            "👉 নিচের **Continue to Step 2** বাটনে ক্লিক করে Mode ও Maps আপডেট করুন।",
            colour=COLOR_INFO
        )
        await interaction.response.send_message(
            embed=embed,
            view=EditTourStep2PromptView(self.tour_id),
            ephemeral=True
        )


class EditTourDetailsModal(Modal):
    def __init__(self, tour):
        self.tour_id = tour["id"]
        self.tour_type = tour["tour_type"] or "scrim"
        super().__init__(title="Edit Tour Settings (Step 2/2)")
        self.mode_field = TextInput(label="Mode (Solo, Duo, Squad)", default=str(tour["mode"] or "Squad")[:10], max_length=10)
        self.matches_field = TextInput(label="Matches (Number)", default=str(tour["matches"] or 3)[:3], max_length=3)
        self.maps_field = TextInput(label="Maps, comma separated", default=str(tour["maps"] or SCRIM_MAPS)[:200], max_length=200)

        self.unlock_field = None
        self.add_item(self.mode_field)
        self.add_item(self.matches_field)
        self.add_item(self.maps_field)
        if self.tour_type == "champion_rush":
            self.unlock_field = TextInput(label="Champion Rush Unlock Points", default=str(tour["unlock_points"] or "")[:50], max_length=50)
            self.add_item(self.unlock_field)

    async def on_submit(self, interaction: discord.Interaction):
        tour = get_tournament(self.tour_id)
        if not tour or tour["guild_id"] != interaction.guild_id:
            return await reply_embed(interaction, "Tour Not Found", "Tour পাওয়া যায়নি.", ephemeral=True, colour=COLOR_DANGER)
        mode = self.mode_field.value.strip().title()
        if mode not in ("Solo", "Duo", "Squad"):
            return await reply_embed(interaction, "Invalid Mode", "Mode অবশ্যই Solo, Duo অথবা Squad হতে হবে.", ephemeral=True, colour=COLOR_DANGER)
        try:
            matches = int(self.matches_field.value.strip())
            if not 1 <= matches <= 30:
                raise ValueError
        except ValueError:
            return await reply_embed(interaction, "Invalid Matches", "Match সংখ্যা 1 থেকে 30-এর মধ্যে হতে হবে.", ephemeral=True, colour=COLOR_DANGER)
        maps = parse_maps(self.maps_field.value)
        unlock = self.unlock_field.value.strip() if self.unlock_field else tour["unlock_points"]
        if self.tour_type == "champion_rush" and not unlock:
            return await reply_embed(interaction, "Unlock Points Required", "Champion Rush unlock point লিখতে হবে.", ephemeral=True, colour=COLOR_DANGER)

        with db() as conn:
            conn.execute("""
                UPDATE tournaments SET mode=?, matches=?, maps=?, unlock_points=?
                WHERE id=?
            """, (mode, matches, maps, unlock, self.tour_id))

        updated = get_tournament(self.tour_id)
        await reply_embed(
            interaction,
            "✅ Tournament Updated Successfully",
            format_tour(updated),
            ephemeral=True,
            colour=COLOR_SUCCESS
        )


# ============================================================
# DELETE TOUR (SAFE CLEANUP)
# ============================================================

class DeleteTourView(View):
    def __init__(self, tour_id):
        super().__init__(timeout=PANEL_EXPIRY_SECONDS)
        self.tour_id = tour_id

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=make_embed("Cancelled", "Tour delete করা হয়নি। সব ডেটা অপরিবর্তিত রয়েছে।", colour=COLOR_INFO),
            view=self
        )

    @discord.ui.button(label="Confirm Delete", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: Button):
        if not is_manager(interaction.user):
            return await reply_embed(interaction, "Permission Denied", "এই action করার permission নেই.", ephemeral=True, colour=COLOR_DANGER)
        tour = get_tournament(self.tour_id)
        if not tour or tour["guild_id"] != interaction.guild_id:
            return await reply_embed(interaction, "Tour Not Found", "Tour পাওয়া যায়নি.", ephemeral=True, colour=COLOR_DANGER)

        guild = interaction.guild
        if guild:
            if tour["channel_id"]:
                ch = guild.get_channel(tour["channel_id"])
                if ch:
                    try:
                        await ch.delete(reason="Tour deleted by manager")
                    except discord.HTTPException:
                        pass
            if tour["role_id"]:
                rl = guild.get_role(tour["role_id"])
                if rl:
                    try:
                        await rl.delete(reason="Tour deleted by manager")
                    except discord.HTTPException:
                        pass

        with db() as conn:
            conn.execute("DELETE FROM slots WHERE tournament_id=?", (self.tour_id,))
            conn.execute("DELETE FROM registrations WHERE tournament_id=?", (self.tour_id,))
            conn.execute("DELETE FROM tournaments WHERE id=?", (self.tour_id,))

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=make_embed("✅ Tournament Deleted", f"Tournament **{tour['name']}** সফলভাবে ডিলিট করা হয়েছে।", colour=COLOR_SUCCESS),
            view=self
        )


class DeleteTourSelect(Select):
    def __init__(self, guild_id):
        tours = tournament_options(guild_id)
        options = [
            discord.SelectOption(
                label=row["name"][:100],
                description=f"{format_tour_type(row['tour_type'])} | Mode: {row['mode'] or 'Squad'} | Fee: {row['fee']}",
                value=str(row["id"]),
                emoji="🗑️"
            )
            for row in tours[:25]
        ]
        super().__init__(placeholder="Choose tournament to delete", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if not is_manager(interaction.user):
            return await reply_embed(interaction, "Permission Denied", "এই action করার permission নেই.", ephemeral=True, colour=COLOR_DANGER)
        tour_id = int(self.values[0])
        tour = get_tournament(tour_id)
        if not tour or tour["guild_id"] != interaction.guild_id:
            return await reply_embed(interaction, "Tour Not Found", "Tour পাওয়া যায়নি.", ephemeral=True, colour=COLOR_DANGER)

        embed = make_embed(
            "⚠️ Confirm Tournament Deletion",
            f"আপনি কি নিশ্চিত যে নিচের টুর্নামেন্টটি মুছে ফেলতে চান?\n\n"
            f"**Tournament:** `{tour['name']}`\n"
            f"**Type:** `{format_tour_type(tour['tour_type'])}`\n"
            f"**Mode:** `{tour['mode']}`\n"
            f"**Date:** `{tour['date_time']}`\n\n"
            f"⚠️ **সতর্কতা:** এই টুর্নামেন্টের সমস্ত স্লট, প্লেয়ার রোল ও প্রাইভেট চ্যানেল স্বয়ংক্রিয়ভাবে মুছে যাবে।",
            colour=COLOR_DANGER
        )
        await interaction.response.send_message(embed=embed, view=DeleteTourView(tour_id), ephemeral=True)


class DeleteTourPicker(View):
    def __init__(self, guild_id):
        super().__init__(timeout=PANEL_EXPIRY_SECONDS)
        tours = tournament_options(guild_id)
        if tours:
            self.add_item(DeleteTourSelect(guild_id))


# ============================================================
# PAYMENT CONFIGURATION MODAL
# ============================================================

class SetPaymentModal(Modal):
    def __init__(self, current_method="bKash", current_number=""):
        super().__init__(title="Configure Payment Details")
        self.method = TextInput(label="Payment Method (bKash / Nagad / Upay)", default=current_method, max_length=20)
        self.number = TextInput(label="Payment Number (Send Money / Personal)", default=current_number, max_length=30)
        self.add_item(self.method)
        self.add_item(self.number)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_manager(interaction.user):
            return await reply_embed(interaction, "Permission Denied", "এই action করার permission নেই.", ephemeral=True, colour=COLOR_DANGER)
        method = self.method.value.strip().lower()
        if method not in ("bkash", "nagad", "upay"):
            return await reply_embed(interaction, "Invalid Method", "Method অবশ্যই bKash, Nagad অথবা Upay হতে হবে.", ephemeral=True, colour=COLOR_DANGER)
        number = self.number.value.strip()
        save_settings(interaction.guild_id, payment_method=method.title(), payment_number=number)
        embed = make_embed(
            "✅ Payment Gateway Updated",
            f"💳 **Method:** `{method.title()}`\n"
            f"📱 **Account Number:** `{number}` (Send Money / Personal)\n\n"
            "🛡️ *নতুন রেজিস্ট্রেশনের সময় ইউজাররা এই নম্বরে ফি পাঠানোর নির্দেশ পাবে।*",
            colour=COLOR_SUCCESS
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================================================
# REGISTRATION SYSTEM & PUBLIC FLOW
# ============================================================

class RegisterTourSelect(Select):
    def __init__(self, guild_id):
        tours = tournament_options(guild_id)
        options = [
            discord.SelectOption(
                label=row["name"][:100],
                description=f"{format_tour_type(row['tour_type'])} | Mode: {row['mode'] or 'Squad'} | Fee: {row['fee'] or 'Free'}",
                value=str(row["id"]),
                emoji="🎯"
            )
            for row in tours[:25]
        ]
        super().__init__(placeholder="Choose an active tournament to enter", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        tour_id = int(self.values[0])
        tour = get_tournament(tour_id)
        if not tour or tour["guild_id"] != interaction.guild_id:
            return await reply_embed(interaction, "Tour Not Found", "এই tournament আর available নেই.", ephemeral=True, colour=COLOR_DANGER)
        embed = make_embed(
            f"📋 Tournament Information — {tour['name']}",
            format_tour(tour) + "\n\n👉 অংশগ্রহণ করতে নিচের **Proceed to Registration** বাটনে ক্লিক করুন।",
            colour=COLOR_INFO
        )
        await interaction.response.send_message(
            embed=embed,
            view=RegisterThisTourView(tour_id),
            ephemeral=True
        )


class RegisterTourPicker(View):
    def __init__(self, guild_id):
        super().__init__(timeout=PANEL_EXPIRY_SECONDS)
        if tournament_options(guild_id):
            self.add_item(RegisterTourSelect(guild_id))


class RegisterThisTourView(View):
    def __init__(self, tour_id):
        super().__init__(timeout=PANEL_EXPIRY_SECONDS)
        self.tour_id = tour_id

    @discord.ui.button(label="Proceed to Registration", style=discord.ButtonStyle.success, emoji="📝")
    async def register_this(self, interaction: discord.Interaction, button: Button):
        tour = get_tournament(self.tour_id)
        if not tour or tour["guild_id"] != interaction.guild_id:
            return await reply_embed(interaction, "Tour Not Found", "এই tour আর available নেই.", ephemeral=True, colour=COLOR_DANGER)
        settings = get_settings(interaction.guild_id)
        if not settings or not settings["payment_number"] or not settings["payment_method"]:
            return await reply_embed(interaction, "Payment Not Configured", "Admin এখনো bKash/Nagad payment details set করেনি।", ephemeral=True, colour=COLOR_DANGER)

        mode = (tour["mode"] or "Squad").title()
        await interaction.response.send_modal(AdaptiveTeamInfoModal(self.tour_id, mode))


class RegistrationView(View):
    """
    Permanent, persistent public view placed on the Registration Announcement.
    Does NOT expire (timeout=None).
    """
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Register Now", style=discord.ButtonStyle.success, custom_id="pro_st_register", emoji="🎟️")
    async def register(self, interaction: discord.Interaction, button: Button):
        if not interaction.guild_id:
            return await reply_embed(interaction, "Server Required", "Server-এর registration channel থেকে ব্যবহার করুন।", ephemeral=True, colour=COLOR_DANGER)
        tours = tournament_options(interaction.guild_id)
        if not tours:
            return await reply_embed(
                interaction, "No Active Tournaments",
                "বর্তমানে কোনো tournament রেজিস্ট্রেশনের জন্য উন্মুক্ত নেই। অনুগ্রহ করে অপেক্ষা করুন।",
                ephemeral=True,
                colour=COLOR_GOLD
            )
        await interaction.response.send_message(
            embed=make_embed(
                "🎯 Select a Tournament to Register",
                "নিচের তালিকা থেকে টুর্নামেন্ট বেছে নিন। এরপর সম্পূর্ণ তথ্য দেখে **Proceed to Registration** বাটনে ক্লিক করুন:",
                colour=COLOR_INFO
            ),
            view=RegisterTourPicker(interaction.guild_id),
            ephemeral=True
        )

    @discord.ui.button(label="Tournament List", style=discord.ButtonStyle.primary, custom_id="pro_st_view_tours", emoji="📋")
    async def view_tournaments(self, interaction: discord.Interaction, button: Button):
        if not interaction.guild_id:
            return await reply_embed(interaction, "Server Required", "Server থেকে ব্যবহার করুন।", ephemeral=True, colour=COLOR_DANGER)
        tours = tournament_options(interaction.guild_id)
        if not tours:
            return await reply_embed(
                interaction, "Active Tournaments",
                "বর্তমানে কোনো tournament চলমান নেই। নতুন টুর্নামেন্ট যুক্ত হলে এখানে দেখতে পাবেন।",
                ephemeral=True,
                colour=COLOR_INFO
            )
        lines = []
        for i, t in enumerate(tours, start=1):
            badge = "🔥" if "scrim" in str(t["tour_type"] or "").lower() else ("👑" if "champion" in str(t["tour_type"] or "").lower() else "⚙️")
            lines.append(
                f"`{i:02}.` {badge} **{safe_text(t['name'])}** ({format_tour_type(t['tour_type'])})\n"
                f"     • Mode: `{safe_text(t['mode'], 'Squad')}` | 💰 Fee: `{safe_text(t['fee'], 'Free')}`\n"
                f"     • 🗓️ Time: `{safe_text(t['date_time'], 'TBA')}` | 👥 Slots: `{t['total_slots']}`"
            )
        embed = make_embed(
            "📋 Current Active Tournaments",
            "\n\n".join(lines) + "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n👉 অংশগ্রহণ করতে **Register Now** বাটনে ক্লিক করুন।",
            colour=COLOR_GOLD
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class AdaptiveTeamInfoModal(Modal):
    def __init__(self, tour_id, mode):
        self.tour_id = tour_id
        self.mode = mode
        title = f"{mode} Team Registration"
        super().__init__(title=title[:45])

        if mode == "Solo":
            self.team_field = TextInput(label="Player / Tag Name", max_length=80, placeholder="Your nickname or tag")
            self.p1_ign = TextInput(label="Player IGN", max_length=50, placeholder="In-game Name")
            self.p1_uid = TextInput(label="Player Game UID (Optional)", max_length=30, required=False, placeholder="Free Fire UID")
            self.add_item(self.team_field)
            self.add_item(self.p1_ign)
            self.add_item(self.p1_uid)
            self.p2_ign = None
            self.p3_ign = None
            self.p4_ign = None
        elif mode == "Duo":
            self.team_field = TextInput(label="Duo Team Name", max_length=80, placeholder="Team Name")
            self.p1_ign = TextInput(label="Player 1 IGN", max_length=50, placeholder="P1 In-game Name")
            self.p2_ign = TextInput(label="Player 2 IGN", max_length=50, placeholder="P2 In-game Name")
            self.p1_uid = TextInput(label="P1 UID (Optional)", max_length=30, required=False, placeholder="P1 UID")
            self.add_item(self.team_field)
            self.add_item(self.p1_ign)
            self.add_item(self.p2_ign)
            self.add_item(self.p1_uid)
            self.p3_ign = None
            self.p4_ign = None
        else:  # Squad
            self.team_field = TextInput(label="Squad Name", max_length=80, placeholder="Team Name")
            self.p1_ign = TextInput(label="Player 1 (Leader) IGN", max_length=50, placeholder="Leader IGN")
            self.p2_ign = TextInput(label="Player 2 IGN", max_length=50, placeholder="Player 2 IGN")
            self.p3_ign = TextInput(label="Player 3 IGN (Optional)", max_length=50, required=False, placeholder="Player 3 IGN")
            self.p4_ign = TextInput(label="Player 4 IGN (Optional)", max_length=50, required=False, placeholder="Player 4 IGN")
            self.add_item(self.team_field)
            self.add_item(self.p1_ign)
            self.add_item(self.p2_ign)
            self.add_item(self.p3_ign)
            self.add_item(self.p4_ign)
            self.p1_uid = None

    async def on_submit(self, interaction: discord.Interaction):
        tour = get_tournament(self.tour_id)
        if not tour or tour["guild_id"] != interaction.guild_id:
            return await reply_embed(interaction, "Tour Not Found", "Tour পাওয়া যায়নি.", ephemeral=True, colour=COLOR_DANGER)

        team_name = self.team_field.value.strip()
        p1 = self.p1_ign.value.strip()
        p2 = self.p2_ign.value.strip() if self.p2_ign else ""
        p3 = self.p3_ign.value.strip() if self.p3_ign else ""
        p4 = self.p4_ign.value.strip() if self.p4_ign else ""
        p1_uid = self.p1_uid.value.strip() if self.p1_uid else ""

        with db() as conn:
            cursor = conn.execute("""
                INSERT INTO registrations
                (tournament_id, discord_user_id, team_name, p1_ign, p2_ign, p3_ign, p4_ign, p1_uid, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """, (self.tour_id, interaction.user.id, team_name, p1, p2, p3, p4, p1_uid))
            reg_id = cursor.lastrowid

        if interaction.guild:
            await refresh_tournament_team_list(interaction.guild, self.tour_id)

        settings = get_settings(interaction.guild_id)
        embed = make_embed(
            "🧾 INVOICE & PAYMENT DIRECTIVE • PRO ST",
            f"**Tournament:** `{tour['name']}`\n"
            f"**Team / Player:** `{team_name}`\n"
            f"**Registration ID:** `#{reg_id}`\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 **Entry Fee:** `{tour['fee']}`\n"
            f"📱 **{settings['payment_method']} Number:** `{settings['payment_number']}` (Personal / Send Money)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ **কীভাবে পেমেন্ট জমা দেবেন:**\n"
            f"1️⃣ উপরোক্ত নম্বরে `{settings['payment_method']}` দিয়ে Entry Fee সেন্ড মানি করুন।\n"
            "2️⃣ সফল ট্রানজেকশনের পরিষ্কার Screenshot সরাসরি **এই বটের DM-এ ইমেজ ফাইল হিসেবে** পাঠান।\n"
            "3️⃣ Scrime Mod যাচাই করে Accept করলেই অফিশিয়াল স্লট ও চ্যানেলের এক্সেস পাবেন।",
            colour=COLOR_GOLD
        )
        try:
            await interaction.user.send(embed=embed)
            dm_notice = "📩 পেমেন্টের সম্পূর্ণ নিয়ম আপনার **Discord DM**-এ পাঠানো হয়েছে। অনুগ্রহ করে DM চেক করুন।"
        except discord.Forbidden:
            dm_notice = "⚠️ আপনার DM বন্ধ থাকায় মেসেজ পাঠানো যায়নি। অনুগ্রহ করে সার্ভার প্রাইভেসি সেটিংসে DM চালু করুন।"

        await reply_embed(
            interaction,
            "✅ Registration Initiated",
            f"আপনার দল **{team_name}**-এর প্রাথমিক রেজিস্ট্রেশন গৃহীত হয়েছে।\n\n{dm_notice}",
            ephemeral=True,
            colour=COLOR_SUCCESS
        )


# ============================================================
# SLOTS LIST & LOGS DISPLAY
# ============================================================

class ViewSlotsSelect(Select):
    def __init__(self, guild_id):
        tours = tournament_options(guild_id)
        options = [
            discord.SelectOption(
                label=row["name"][:100],
                description=f"{format_tour_type(row['tour_type'])} | Mode: {row['mode'] or 'Squad'} | Fee: {row['fee']}",
                value=str(row["id"]),
                emoji="📊"
            )
            for row in tours[:25]
        ]
        super().__init__(placeholder="Choose tournament to view slot status", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        tour_id = int(self.values[0])
        tour = get_tournament(tour_id)
        if not tour or tour["guild_id"] != interaction.guild_id:
            return await reply_embed(interaction, "Tour Not Found", "Tour পাওয়া যায়নি.", ephemeral=True, colour=COLOR_DANGER)

        with db() as conn:
            slots = conn.execute("""
                SELECT * FROM slots WHERE tournament_id=? ORDER BY slot_number ASC
            """, (tour_id,)).fetchall()

        lines = []
        booked_count = sum(1 for s in slots if s["status"] != "available")
        for s in slots:
            is_avail = s["status"] == "available"
            status_badge = "🟢 OPEN" if is_avail else "🔴 BOOKED"
            team = safe_text(s["team_name"], "Vacant Slot")
            lines.append(f"`Slot {s['slot_number']:02}`  {status_badge}  {team}")

        header = (
            f"**Tournament:** `{safe_text(tour['name'])}`\n"
            f"**Status Summary:** 🟢 `{len(slots) - booked_count} Available` • 🔴 `{booked_count} Booked` • 👥 `{len(slots)} Total`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        embed = make_embed(
            f"📊 Slot Matrix — {tour['name']}",
            header + "\n".join(lines),
            colour=COLOR_INFO
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ViewSlotsPicker(View):
    def __init__(self, guild_id):
        super().__init__(timeout=PANEL_EXPIRY_SECONDS)
        tours = tournament_options(guild_id)
        if tours:
            self.add_item(ViewSlotsSelect(guild_id))


class ViewTeamsSelect(Select):
    def __init__(self, guild_id):
        tours = tournament_options(guild_id)
        options = [
            discord.SelectOption(
                label=row["name"][:100],
                description=f"{format_tour_type(row['tour_type'])} | Mode: {row['mode'] or 'Squad'}",
                value=str(row["id"]),
                emoji="👥"
            )
            for row in tours[:25]
        ]
        super().__init__(placeholder="Choose tournament to view approved roster", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        tour_id = int(self.values[0])
        tour = get_tournament(tour_id)
        if not tour or tour["guild_id"] != interaction.guild_id:
            return await reply_embed(interaction, "Tour Not Found", "Tour পাওয়া যায়নি.", ephemeral=True, colour=COLOR_DANGER)

        with db() as conn:
            teams = conn.execute("""
                SELECT * FROM registrations
                WHERE tournament_id=? AND LOWER(status)='approved'
                ORDER BY slot_number ASC
            """, (tour_id,)).fetchall()

        if not teams:
            return await reply_embed(
                interaction,
                "No Approved Teams",
                "এই টুর্নামেন্টে এখনো কোনো অনুমোদিত টিম নেই।",
                ephemeral=True,
                colour=COLOR_GOLD
            )

        lines = []
        for row in teams:
            slot_num = int(row['slot_number'])
            team_name = safe_text(row['team_name'], 'Team')
            p1 = safe_text(row['p1_ign'], '—')
            p2 = safe_text(row['p2_ign'], '—')
            lines.append(f"Slot {slot_num:02} → {team_name}\n           Player: {p1} | {p2}")

        header = (
            f"**Tournament:** `{safe_text(tour['name'])}`\n"
            f"**Mode:** `{safe_text(tour['mode'], 'Squad')}` • **Approved Teams:** `{len(teams)}/{tour['total_slots']}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        embed = make_embed(
            f"👥 Approved Teams — {safe_text(tour['name'])}",
            header + f"```\n{chr(10).join(lines)}\n```",
            colour=COLOR_SUCCESS
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ViewTeamsPicker(View):
    def __init__(self, guild_id):
        super().__init__(timeout=PANEL_EXPIRY_SECONDS)
        tours = tournament_options(guild_id)
        if tours:
            self.add_item(ViewTeamsSelect(guild_id))


# ============================================================
# PAYMENT VERIFICATION REVIEW (APPROVE / REJECT)
# ============================================================

class ReviewModal(Modal):
    def __init__(self, reg_id, action):
        self.reg_id = reg_id
        self.action = action
        title = "Approve Registration" if action == "approve" else "Reject Registration"
        super().__init__(title=title)
        if action == "approve":
            self.slot_field = TextInput(label="Assign Slot Number (Optional)", placeholder="Leave blank for auto-assign", required=False, max_length=3)
            self.add_item(self.slot_field)
        else:
            self.reason_field = TextInput(label="Reason for Rejection", placeholder="Invalid screenshot / payment not received", max_length=150)
            self.add_item(self.reason_field)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_manager(interaction.user):
            return await reply_embed(interaction, "Permission Denied", "শুধু Scrime Mod বা Admin Accept/Reject করতে পারবে।", ephemeral=True, colour=COLOR_DANGER)

        await interaction.response.defer(ephemeral=True)
        with db() as conn:
            reg = conn.execute("SELECT * FROM registrations WHERE id=?", (self.reg_id,)).fetchone()
            if not reg or reg["status"] != "pending":
                return await reply_embed(interaction, "Not Found", "এই রেজিস্ট্রেশন ইতিমধ্যে প্রসেস করা হয়েছে।", ephemeral=True, colour=COLOR_DANGER)
            tour = conn.execute("SELECT * FROM tournaments WHERE id=?", (reg["tournament_id"],)).fetchone()

        guild = interaction.guild
        member = guild.get_member(reg["discord_user_id"]) if guild else None

        if self.action == "approve":
            assigned_slot = None
            if hasattr(self, "slot_field") and self.slot_field.value.strip():
                try:
                    custom_slot = int(self.slot_field.value.strip())
                    with db() as conn:
                        existing = conn.execute("""
                            SELECT * FROM slots WHERE tournament_id=? AND slot_number=? AND status='available'
                        """, (reg["tournament_id"], custom_slot)).fetchone()
                        if existing:
                            assigned_slot = custom_slot
                except ValueError:
                    pass

            with db() as conn:
                if not assigned_slot:
                    avail = conn.execute("""
                        SELECT slot_number FROM slots WHERE tournament_id=? AND status='available' ORDER BY slot_number ASC LIMIT 1
                    """, (reg["tournament_id"],)).fetchone()
                    if not avail:
                        return await reply_embed(interaction, "Full", "এই টুর্নামেন্টের সমস্ত স্লট পূর্ণ হয়ে গেছে!", ephemeral=True, colour=COLOR_DANGER)
                    assigned_slot = avail["slot_number"]

                conn.execute("""
                    UPDATE slots SET status='booked', team_name=?, assigned_user_id=?
                    WHERE tournament_id=? AND slot_number=?
                """, (reg["team_name"], reg["discord_user_id"], reg["tournament_id"], assigned_slot))

                conn.execute("""
                    UPDATE registrations SET status='approved', slot_number=? WHERE id=?
                """, (assigned_slot, self.reg_id))

            # Assign Player Role to member
            if guild and tour and tour["role_id"] and member:
                role = guild.get_role(tour["role_id"])
                if role:
                    try:
                        await member.add_roles(role, reason="Tournament registration approved")
                    except discord.HTTPException:
                        pass

            # Update the single existing slot list message in tournament channel
            # (Does NOT post old individual welcome messages in channel)
            if guild and tour:
                await refresh_tournament_team_list(guild, reg["tournament_id"])

            # Send clean confirmation DM to approved player
            if member:
                try:
                    await member.send(
                        embed=make_embed(
                            "🎉 REGISTRATION APPROVED • SLOT CONFIRMED",
                            f"অভিনন্দন! আপনার দলের রেজিস্ট্রেশন অনুমোদিত হয়েছে।\n\n"
                            f"🏆 **Tournament:** `{tour['name']}`\n"
                            f"👥 **Team:** `{reg['team_name']}`\n"
                            f"🎯 **Assigned Slot:** `Slot #{assigned_slot:02}`\n\n"
                            f"🛡️ আপনাকে টুর্নামেন্টের **Player Role** প্রদান করা হয়েছে এবং প্রাইভেট চ্যানেলে যুক্ত করা হয়েছে।",
                            colour=COLOR_SUCCESS
                        )
                    )
                except discord.HTTPException:
                    pass

            await reply_embed(
                interaction,
                "✅ Registration Approved",
                f"দল **{reg['team_name']}** অনুমোদিত হয়েছে এবং **Slot #{assigned_slot:02}** বরাদ্দ করা হয়েছে।\nটুর্নামেন্ট চ্যানেলের অফিশিয়াল স্লট লিস্ট আপডেট হয়েছে।",
                ephemeral=True,
                colour=COLOR_SUCCESS
            )
        else:
            reason = self.reason_field.value.strip() if hasattr(self, "reason_field") else "Payment verification failed"
            with db() as conn:
                conn.execute("UPDATE registrations SET status='rejected' WHERE id=?", (self.reg_id,))
            if member:
                try:
                    await member.send(
                        embed=make_embed(
                            "❌ REGISTRATION STATUS • REJECTED",
                            f"আপনার টুর্নামেন্ট রেজিস্ট্রেশন বাতিল করা হয়েছে।\n\n"
                            f"🏆 **Tournament:** `{tour['name'] if tour else 'N/A'}`\n"
                            f"👥 **Team:** `{reg['team_name']}`\n"
                            f"⚠️ **Reason:** `{reason}`\n\n"
                            "প্রয়োজনে অ্যাডমিন বা স্ক্রিম মডারেটরের সাথে যোগাযোগ করুন।",
                            colour=COLOR_DANGER
                        )
                    )
                except discord.HTTPException:
                    pass

            await reply_embed(
                interaction,
                "❌ Registration Rejected",
                f"দল **{reg['team_name']}**-এর আবেদন বাতিল করা হয়েছে।",
                ephemeral=True,
                colour=COLOR_DANGER
            )


class ReviewView(View):
    """Persistent per-registration review buttons with explicit custom IDs."""
    def __init__(self, reg_id):
        super().__init__(timeout=None)
        self.reg_id = int(reg_id)

        accept_button = Button(
            label="Accept & Assign Slot", style=discord.ButtonStyle.success,
            emoji="✅", custom_id=f"pro_st_review_accept:{self.reg_id}"
        )
        reject_button = Button(
            label="Reject Payment", style=discord.ButtonStyle.danger,
            emoji="❌", custom_id=f"pro_st_review_reject:{self.reg_id}"
        )
        accept_button.callback = self.accept
        reject_button.callback = self.reject
        self.add_item(accept_button)
        self.add_item(reject_button)

    async def accept(self, interaction: discord.Interaction):
        if not is_manager(interaction.user):
            return await reply_embed(interaction, "Permission Denied", "শুধু Scrime Mod বা Admin পরিচালনা করতে পারবে।", ephemeral=True, colour=COLOR_DANGER)
        await interaction.response.send_modal(ReviewModal(self.reg_id, "approve"))

    async def reject(self, interaction: discord.Interaction):
        if not is_manager(interaction.user):
            return await reply_embed(interaction, "Permission Denied", "শুধু Scrime Mod বা Admin পরিচালনা করতে পারবে।", ephemeral=True, colour=COLOR_DANGER)
        await interaction.response.send_modal(ReviewModal(self.reg_id, "reject"))


async def forward_payment_verification(guild: discord.Guild, row):
    log_ch = await ensure_log_channel(guild)
    embed = make_embed(
        f"💳 PAYMENT VERIFICATION • REG #{row['reg_id']}",
        "Scrime Mod: পেমেন্ট স্ক্রিনশট ও দলের বিবরণ যাচাই করে সিদ্ধান্ত নিন।",
        colour=COLOR_GOLD
    )
    embed.add_field(name="🏆 Tournament", value=f"`{safe_text(row['tour_name'])}`", inline=True)
    embed.add_field(name="🆔 Reg ID", value=f"`#{row['reg_id']}`", inline=True)
    embed.add_field(name="👤 Applicant", value=f"<@{row['discord_user_id']}>", inline=True)

    embed.add_field(name="👥 Team Name", value=f"**{safe_text(row['team_name'], '—')}**", inline=False)
    embed.add_field(name="🎮 Player 1 (Leader) IGN", value=f"`{safe_text(row['p1_ign'], '—')}`", inline=True)
    if row.get("p2_ign"):
        embed.add_field(name="🎮 Player 2 IGN", value=f"`{safe_text(row['p2_ign'], '—')}`", inline=True)
    if row.get("p3_ign"):
        embed.add_field(name="🎮 Player 3 IGN", value=f"`{safe_text(row['p3_ign'], '—')}`", inline=True)
    if row.get("p4_ign"):
        embed.add_field(name="🎮 Player 4 IGN", value=f"`{safe_text(row['p4_ign'], '—')}`", inline=True)

    embed.add_field(name="📊 Status", value="🟡 `Pending Moderator Action`", inline=False)

    if row.get("payment_screenshot"):
        embed.set_image(url=row["payment_screenshot"])

    settings = get_settings(guild.id)
    mod_role = guild.get_role(settings["mod_role_id"]) if settings and settings["mod_role_id"] else None
    if mod_role is None:
        mod_role = discord.utils.find(
            lambda r: r.name.lower() in (MOD_ROLE.lower(), LEGACY_MOD_ROLE.lower()),
            guild.roles,
        )
    mod_mention = f"🔔 {mod_role.mention} — New verification submission!" if mod_role else "🔔 **Scrime Mod** — New verification submission!"

    view = ReviewView(row["reg_id"])
    await log_ch.send(content=mod_mention, embed=embed, view=view, allowed_mentions=discord.AllowedMentions(roles=True))


# ============================================================
# PRO ST TOURNAMENT MANAGEMENT PANEL (ppt COMMAND)
# ============================================================

class TournamentPanel(View):
    def __init__(self, guild_id):
        super().__init__(timeout=PANEL_EXPIRY_SECONDS)
        self.guild_id = guild_id

    async def on_timeout(self):
        # After expiry period, disable every panel button and update message
        for item in self.children:
            item.disabled = True
        message = getattr(self, "message", None)
        if message is not None:
            try:
                await message.edit(view=self)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

    @discord.ui.button(label="Create Tour", style=discord.ButtonStyle.success, emoji="🏆", row=0)
    async def create_tour(self, interaction: discord.Interaction, button: Button):
        if not is_manager(interaction.user):
            return await reply_embed(interaction, "Permission Denied", "এই action করার permission নেই.", ephemeral=True, colour=COLOR_DANGER)
        await interaction.response.send_message(
            embed=make_embed("➕ Select Tournament Category", "তৈরি করার জন্য টুর্নামেন্টের ধরন বেছে নিন:", colour=COLOR_INFO),
            view=TourTypePicker(),
            ephemeral=True
        )

    @discord.ui.button(label="Edit Tour", style=discord.ButtonStyle.primary, emoji="⚙️", row=0)
    async def edit_tour(self, interaction: discord.Interaction, button: Button):
        if not is_manager(interaction.user):
            return await reply_embed(interaction, "Permission Denied", "এই action করার permission নেই.", ephemeral=True, colour=COLOR_DANGER)
        tours = tournament_options(self.guild_id)
        if not tours:
            return await reply_embed(interaction, "No Tournaments", "Edit করার মতো কোনো tournament নেই.", ephemeral=True, colour=COLOR_INFO)
        await interaction.response.send_message(
            embed=make_embed("⚙️ Select Tournament to Edit", "যে টুর্নামেন্টটি এডিট করতে চান সেটি বেছে নিন:", colour=COLOR_INFO),
            view=EditTourPicker(self.guild_id),
            ephemeral=True
        )

    @discord.ui.button(label="Delete Tour", style=discord.ButtonStyle.danger, emoji="🗑️", row=0)
    async def delete_tour(self, interaction: discord.Interaction, button: Button):
        if not is_manager(interaction.user):
            return await reply_embed(interaction, "Permission Denied", "এই action করার permission নেই.", ephemeral=True, colour=COLOR_DANGER)
        tours = tournament_options(self.guild_id)
        if not tours:
            return await reply_embed(interaction, "No Tournaments", "Delete করার মতো কোনো tournament নেই.", ephemeral=True, colour=COLOR_INFO)
        await interaction.response.send_message(
            embed=make_embed("🗑️ Select Tournament to Delete", "যে টুর্নামেন্টটি মুছে ফেলতে চান সেটি বেছে নিন:", colour=COLOR_DANGER),
            view=DeleteTourPicker(self.guild_id),
            ephemeral=True
        )

    @discord.ui.button(label="Payment Setup", style=discord.ButtonStyle.secondary, emoji="💳", row=1)
    async def set_payment(self, interaction: discord.Interaction, button: Button):
        if not is_manager(interaction.user):
            return await reply_embed(interaction, "Permission Denied", "এই action করার permission নেই.", ephemeral=True, colour=COLOR_DANGER)
        settings = get_settings(self.guild_id)
        modal = SetPaymentModal(
            current_method=settings["payment_method"] or "bKash",
            current_number=settings["payment_number"] or ""
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Slot Matrix", style=discord.ButtonStyle.secondary, emoji="📊", row=1)
    async def view_slots(self, interaction: discord.Interaction, button: Button):
        tours = tournament_options(self.guild_id)
        if not tours:
            return await reply_embed(interaction, "No Tournaments", "কোনো টুর্নামেন্ট নেই.", ephemeral=True, colour=COLOR_INFO)
        await interaction.response.send_message(
            embed=make_embed("📊 View Slot Status", "স্লট দেখার জন্য টুর্নামেন্ট বেছে নিন:", colour=COLOR_INFO),
            view=ViewSlotsPicker(self.guild_id),
            ephemeral=True
        )

    @discord.ui.button(label="Approved Roster", style=discord.ButtonStyle.secondary, emoji="👥", row=1)
    async def view_teams(self, interaction: discord.Interaction, button: Button):
        tours = tournament_options(self.guild_id)
        if not tours:
            return await reply_embed(interaction, "No Tournaments", "কোনো টুর্নামেন্ট নেই.", ephemeral=True, colour=COLOR_INFO)
        await interaction.response.send_message(
            embed=make_embed("👥 View Approved Roster", "অনুমোদিত টিম দেখার জন্য টুর্নামেন্ট বেছে নিন:", colour=COLOR_INFO),
            view=ViewTeamsPicker(self.guild_id),
            ephemeral=True
        )


# ============================================================
# COMMANDS & DISCORD LISTENERS
# ============================================================

@bot.command(name="ppt")
async def cmd_ppt(ctx):
    """
    Main Tournament Management Panel.
    Accessible to Admins and Scrime Mods.
    """
    if not ctx.guild:
        return await reply_embed(ctx, "Server Required", "এই command শুধুমাত্র Discord সার্ভারে ব্যবহারযোগ্য।", colour=COLOR_DANGER)
    if not is_manager(ctx.author):
        return await reply_embed(ctx, "Permission Denied", "এই command চালানোর permission আপনার নেই।", colour=COLOR_DANGER)

    tours = tournament_options(ctx.guild.id)
    settings = get_settings(ctx.guild.id)

    payment_info = f"`{settings['payment_method']}` ({settings['payment_number'] or 'Not Configured'})"
    desc = (
        f"**Server:** `{ctx.guild.name}`\n"
        f"**Active Tournaments:** `{len(tours)}`\n"
        f"**Payment Gateway:** {payment_info}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<a:ts_redfire:1509499121961275573> **Quick Controls:**\n"
        "•  **Create Tour:** Launch a new Scrime, Champion Rush, or Custom Tour\n"
        "•  **Edit Tour:** Modify schedule, fee, slots, or map rotation\n"
        "•  **Delete Tour:** Safe removal with channel & role rollback\n"
        "•  **Payment Setup:** Configure bKash, Nagad, or Upay credentials\n"
        "•  **Slot Matrix:** Real-time slot allocation & vacancy monitor\n"
        "•  **Approved Roster:** Formatted list of all confirmed teams\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👉 নিচের বাটনগুলো দিয়ে টুর্নামেন্ট পরিচালনা করুন:"
    )

    embed = make_embed(
        f"⚡ {PANEL_TITLE.upper()} • DASHBOARD",
        desc,
        colour=COLOR_GOLD
    )
    embed.set_footer(text=f"PRO ST Esports Suite • Session Active for {PANEL_EXPIRY_SECONDS}s")
    view = TournamentPanel(ctx.guild.id)
    view.message = await ctx.send(embed=embed, view=view)


@bot.command(name="tour_list")
async def cmd_tour_list(ctx):
    """
    Quick list of tournaments for the current server.
    """
    if not ctx.guild:
        return
    tours = tournament_options(ctx.guild.id)
    if not tours:
        return await reply_embed(ctx, "No Tournaments", "এই সার্ভারে বর্তমানে কোনো active tournament নেই।", colour=COLOR_INFO)

    lines = []
    for index, tour in enumerate(tours, start=1):
        tour_type = format_tour_type(tour["tour_type"])
        badge = "🔥" if "scrim" in str(tour["tour_type"] or "").lower() else ("👑" if "champion" in str(tour["tour_type"] or "").lower() else "⚙️")
        lines.append(
            f"`{index:02}.` {badge} **{safe_text(tour['name'])}** (`ID: #{tour['id']}`)\n"
            f"     • **Type:** {tour_type} | **Mode:** `{safe_text(tour['mode'], 'Squad')}`\n"
            f"     • 🗓️ `{safe_text(tour['date_time'], 'TBA')}` | 💰 Fee: `{safe_text(tour['fee'], 'Free')}` | 👥 `{tour['total_slots']} Slots`"
        )
    embed = make_embed(
        "📋 Active Tournaments Schedule",
        f"**Server:** `{ctx.guild.name}` • **Active Events:** `{len(tours)}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n" + "\n\n".join(lines),
        colour=COLOR_INFO
    )
    embed.set_footer(text="PRO ST Esports • Use 'ppt' to manage tournaments")
    await ctx.send(embed=embed)


@bot.command(name="post_registration")
async def cmd_post_registration(ctx):
    """
    Force posts or refreshes the permanent registration announcement.
    """
    if not ctx.guild or not is_manager(ctx.author):
        return await reply_embed(ctx, "Permission Denied", "এই action করার permission নেই.", colour=COLOR_DANGER)
    msg = await post_tour_registration(ctx.guild)
    reg_ch = await ensure_registration_channel(ctx.guild)
    await reply_embed(
        ctx,
        "✅ Registration Announcement Posted",
        f"রেজিস্ট্রেশন অ্যানাউন্সমেন্ট {reg_ch.mention} চ্যানেলে সফলভাবে আপডেট করা হয়েছে।",
        colour=COLOR_SUCCESS
    )


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Payment screenshot submitted by DM
    if isinstance(message.channel, discord.DMChannel) and message.attachments:
        img = message.attachments[0]

        try:
            with db() as conn:
                pending = conn.execute("""
                    SELECT
                        r.id AS reg_id,
                        r.discord_user_id AS discord_user_id,
                        r.team_name,
                        r.p1_ign,
                        r.p2_ign,
                        r.p3_ign,
                        r.p4_ign,
                        t.name AS tour_name,
                        t.guild_id
                    FROM registrations r
                    JOIN tournaments t ON r.tournament_id = t.id
                    WHERE r.discord_user_id = ?
                      AND LOWER(r.status) = 'pending'
                    ORDER BY r.id DESC
                    LIMIT 1
                """, (message.author.id,)).fetchone()

                if not pending:
                    await message.channel.send(
                        "❌ আপনার কোনো Pending Registration পাওয়া যায়নি। "
                        "আগে Tournament-এ Register করুন।"
                    )
                    return

                columns = {
                    row[1] for row in
                    conn.execute("PRAGMA table_info(registrations)").fetchall()
                }

                if "screenshot_url" not in columns:
                    await message.channel.send(
                        "❌ Database-এ screenshot_url Column নেই। "
                        "Admin-কে Database Migration ঠিক করতে হবে।"
                    )
                    return

                conn.execute("""
                    UPDATE registrations
                    SET screenshot_url = ?
                    WHERE id = ?
                """, (img.url, pending["reg_id"]))

            guild_id = pending["guild_id"]
            guild = bot.get_guild(guild_id) if guild_id else None

            if not guild:
                await message.channel.send(
                    "⚠️ Screenshot সংরক্ষণ হয়েছে, কিন্তু Tournament Server "
                    "পাওয়া যায়নি। Admin-কে জানান।"
                )
                return

            review_data = dict(pending)
            review_data["payment_screenshot"] = img.url
            review_data["user_id"] = review_data["discord_user_id"]

            await forward_payment_verification(guild, review_data)

            await message.channel.send(
                "✅ Payment Screenshot গ্রহণ করা হয়েছে এবং "
                "Tournament Mod-দের কাছে যাচাইয়ের জন্য পাঠানো হয়েছে।"
            )
            return

        except Exception:
            logging.exception("Payment screenshot processing failed")
            await message.channel.send(
                "❌ Screenshot প্রসেস করা যায়নি। Admin-কে জানান।"
            )
            return

    # Plain text shortcuts
    content_lower = message.content.strip().lower()

    if content_lower == "ppt" and message.guild:
        ctx = await bot.get_context(message)
        await cmd_ppt(ctx)
        return

    await bot.process_commands(message)


@bot.event
async def on_ready():
    global views_loaded
    init_db()
    if not views_loaded:
        # Register persistent permanent views (Timeout=None)
        bot.add_view(RegistrationView())
        with db() as conn:
            pending = conn.execute("""
                SELECT id FROM registrations WHERE status='pending'
            """).fetchall()
        for row in pending:
            bot.add_view(ReviewView(row["id"]))
        views_loaded = True
    logger.info(f"Logged in successfully as {bot.user} (ID: {bot.user.id})")
    print(f"============================================================")
    print(f"  {PANEL_TITLE.upper()} IS NOW ONLINE AND READY!")
    print(f"  Connected as: {bot.user.name}#{bot.user.discriminator}")
    print(f"  Tournament Manager command: 'ppt'")
    print(f"  Temporary panel expiry: {PANEL_EXPIRY_SECONDS} seconds")
    print(f"  Multi-Server support: Enabled & probot.db preserved")
    print(f"============================================================")


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_BOT_TOKEN environment variable is missing!\n"
            "Please set your bot token in Windows CMD: set DISCORD_BOT_TOKEN=your_token_here\n"
            "or create a .env file containing: DISCORD_BOT_TOKEN=your_token_here"
        )

    init_db()
    bot.run(TOKEN)