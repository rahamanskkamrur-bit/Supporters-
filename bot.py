# =====================================================================
# PART 1 OF 2 — PASTE THIS FIRST AT THE TOP OF YOUR FILE
# 24/7 AI First-Responder (FAQ Deflector) & On-Call Ping Controller
# 100% Plain Chat Messages — Zero Embeds!
# =====================================================================
import asyncio, json, os, re, time, aiohttp
from aiohttp import web
import discord
from discord.ext import commands

TOKEN = os.getenv("BOT_TOKEN", "").strip().strip('"').strip("'")
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "").strip()
DATA_FILE = "support_oncall_data.json"
START, STATUS = time.time(), "Starting..."

# Cooldown tracker to prevent ping spam: {(guild_id, user_id): last_ping_timestamp}
PING_CD = {}

DEFAULT_FAQS = [
    {"q": "how do i verify bloxlink", "a": "Run `/verify` in the commands channel, link your Roblox account, then run `/update` to get your roles."},
    {"q": "how do i apply for staff or join", "a": "Check the applications or tryouts channel for open forms and follow the steps listed there."},
]


def load_data() -> dict:
    try:
        return json.load(open(DATA_FILE, encoding="utf-8")) if os.path.exists(DATA_FILE) else {}
    except Exception:
        return {}


def save_data() -> None:
    try:
        json.dump(DATA, open(DATA_FILE, "w", encoding="utf-8"), indent=2)
    except Exception:
        pass


DATA = load_data()


def gdata(gid: int) -> dict:
    return DATA.setdefault(
        str(gid),
        {
            "staff_role": 0,
            "support_ch": 0,
            "oncall": [],
            "pings_on": True,
            "cooldown": 120,
            "faqs": list(DEFAULT_FAQS),
        },
    )


def is_staff(m: discord.Member) -> bool:
    if not isinstance(m, discord.Member):
        return False
    p = m.guild_permissions
    srid = gdata(m.guild.id)["staff_role"]
    return p.administrator or p.manage_channels or p.moderate_members or bool(srid and any(r.id == srid for r in m.roles))


# --- 1. 24/7 KEEP-ALIVE WEB SERVER ---
async def run_web():
    app = web.Application()
    fn = lambda r: web.Response(text=f"AI FAQ & On-Call Bot 24/7 | {int((time.time()-START)//60)}m | {STATUS}")
    app.router.add_get("/", fn)
    app.router.add_get("/health", fn)
    r = web.AppRunner(app)
    await r.setup()
    await web.TCPSite(r, "0.0.0.0", int(os.environ.get("PORT", 10000))).start()


async def self_ping():
    await asyncio.sleep(25)
    u = os.environ.get("RENDER_EXTERNAL_URL") or f"http://127.0.0.1:{os.environ.get('PORT', 10000)}/"
    async with aiohttp.ClientSession() as s:
        while True:
            try:
                async with s.get(u, timeout=10):
                    pass
            except Exception:
                pass
            await asyncio.sleep(240)


# --- 2. AI FIRST-RESPONDER & FAQ DEFLECTOR ENGINE ---
def match_local_faq(gid: int, question: str):
    """Finds the best matching saved FAQ using keyword overlap."""
    q_words = set(re.findall(r"[a-z0-9]{3,}", question.lower()))
    best_a, best_score = None, 0
    for item in gdata(gid)["faqs"]:
        f_words = set(re.findall(r"[a-z0-9]{3,}", item["q"].lower()))
        score = len(q_words & f_words)
        if score > best_score and score >= 1:
            best_score, best_a = score, item["a"]
    return best_a


async def get_faq_reply(gid: int, user_name: str, question: str) -> tuple[str, bool]:
    """Answers the user using Gemini AI + Server FAQs, or falls back to local FAQ matching."""
    faqs = gdata(gid)["faqs"]
    faq_txt = "\n".join(f"Q: {f['q']}\nA: {f['a']}" for f in faqs) or "No custom FAQs added yet."

    if GEMINI_KEY:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
        sys_p = (
            "You are a fast, friendly Discord Support First-Responder. "
            "Answer the user's question in 1-3 short plain-text sentences using the SERVER FAQS below. "
            "Do NOT use embeds or long walls of text. If the FAQs do not cover it, give brief helpful guidance "
            "and tell them to click 'Still Need Human Staff' below."
        )
        body = {
            "contents": [{"parts": [{"text": f"SERVER FAQS:\n{faq_txt}\n\nUSER ({user_name}) ASKS: {question}"}]}],
            "systemInstruction": {"parts": [{"text": sys_p}]},
            "generationConfig": {"temperature": 0.2},
        }
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(url, json=body, timeout=15) as r:
                    if r.status == 200:
                        txt = (await r.json())["candidates"][0]["content"]["parts"][0]["text"].strip()
                        if txt:
                            return txt[:1200], True
        except Exception:
            pass

    hit = match_local_faq(gid, question)
    if hit:
        return hit[:1200], True
    return "I don't have an exact FAQ saved for that yet! Click **🙋‍♂️ Still Need Human Staff** below to ping an On-Call Support Agent.", False


# --- 3. ON-CALL PING CONTROLLER FORMATTERS & LOGIC ---
def format_oncall_board(guild: discord.Guild) -> str:
    """Builds the plain-text On-Call & Ping Controller status message (no embed)."""
    d = gdata(guild.id)
    agents = [f"<@{uid}>" for uid in d["oncall"]]
    agent_line = ", ".join(agents) if agents else "*None right now*"
    ping_state = "🔔 **ENABLED**" if d["pings_on"] else "🔕 **PAUSED BY STAFF**"
    return (
        f"🎧 **{guild.name.upper()} — ON-CALL SUPPORT & PING CONTROLLER**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 **Currently On-Call ({len(agents)}):** {agent_line}\n"
        f"📡 **Ping Controller:** {ping_state} • ⏱️ **Cooldown:** `{d['cooldown']}s`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"*Staff: Toggle yourself On-Call to receive live help pings, or Off-Call when busy/sleeping!*"
    )


def format_support_panel(guild: discord.Guild) -> str:
    """Builds the plain-text AI Support Desk message (no embed)."""
    d = gdata(guild.id)
    n_on = len(d["oncall"])
    status = f"🟢 `{n_on}` Support Agent(s) On-Call right now" if n_on else "🔴 No agents On-Call right now (AI First-Responder is online 24/7!)"
    return (
        f"🤖 **{guild.name.upper()} — INSTANT AI SUPPORT DESK**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Need help? Click **❓ Ask Support** below (or ping me in chat) for an instant answer from our FAQ & AI First-Responder!\n"
        f"If that doesn't solve it, you can ping our **On-Call Staff** in one tap.\n\n"
        f"📊 **Live Status:** {status}"
    )


async def route_oncall_ping(channel: discord.abc.Messageable, guild: discord.Guild, requester: discord.Member, issue: str) -> str:
    """Smart Ping Controller: checks pause state, cooldown, and pings ONLY On-Call staff."""
    d = gdata(guild.id)
    if not d["pings_on"]:
        return "🔕 **Support pings are currently PAUSED by staff.** Please check back shortly or check `/list_faqs`."

    now = time.time()
    last = PING_CD.get((guild.id, requester.id), 0)
    wait = int(d["cooldown"] - (now - last))
    if wait > 0 and not is_staff(requester):
        return f"⏳ **Ping Controller Cooldown:** Please wait **`{wait}s`** before pinging On-Call staff again."

    PING_CD[(guild.id, requester.id)] = now
    oncall_ids = d["oncall"]

    if not oncall_ids:
        await channel.send(
            f"🔴 **No Support Agents are currently On-Call.**\n"
            f"👤 **Requested By:** {requester.mention}\n"
            f"❓ **Issue:** {issue[:400]}\n"
            f"*Your request is saved in chat — an agent will assist as soon as someone goes On-Call!*",
            view=ClaimRequestView(),
        )
        return "🔴 No agents are On-Call right now, but your request has been posted in chat!"

    pings = " ".join(f"<@{uid}>" for uid in oncall_ids[:15])
    await channel.send(
        f"🔔 **HUMAN SUPPORT REQUESTED!**\n"
        f"🟢 **On-Call Staff:** {pings}\n"
        f"👤 **Member:** {requester.mention}\n"
        f"❓ **Issue:** {issue[:450]}\n"
        f"*Staff: Click **✅ Claim Request** below so other agents know you've got it!*",
        view=ClaimRequestView(),
    )
    return f"🔔 Pinged **`{len(oncall_ids)}`** On-Call support agent(s) in chat!"

# =====================================================================
# PART 2 OF 2 — PASTE THIS DIRECTLY BELOW PART 1
# =====================================================================
class ClaimRequestView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim Request", style=discord.ButtonStyle.success, emoji="✅", custom_id="oc:claim")
    async def b_claim(self, i: discord.Interaction, b: discord.ui.Button):
        if not is_staff(i.user):
            return await i.response.send_message("❌ Staff only.", ephemeral=True)
        b.disabled = True
        b.label = f"Claimed by {i.user.display_name}"[:75]
        b.style = discord.ButtonStyle.secondary
        updated = f"{i.message.content}\n\n✅ **Claimed by {i.user.mention}!**"
        await i.response.edit_message(content=updated[:1990], view=self)


class DeflectActionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="That Fixed It!", style=discord.ButtonStyle.success, emoji="✅", custom_id="faq:ok")
    async def b_ok(self, i: discord.Interaction, b: discord.ui.Button):
        for c in self.children:
            c.disabled = True
        await i.response.edit_message(
            content=f"{i.message.content}\n\n✅ **Marked as Resolved by {i.user.mention}!** *(No staff ping needed)*"[:1990],
            view=self,
        )

    @discord.ui.button(label="Still Need Human Staff", style=discord.ButtonStyle.danger, emoji="🙋‍♂️", custom_id="faq:staff")
    async def b_staff(self, i: discord.Interaction, b: discord.ui.Button):
        b.disabled = True
        b.label = "Staff Notified"
        m = re.search(r"\*\*Question:\*\*\s*(.+)", i.message.content or "")
        issue = m.group(1).strip() if m else "Needs human staff assistance"
        await i.response.edit_message(view=self)
        note = await route_oncall_ping(i.channel, i.guild, i.user, issue)
        await i.followup.send(note, ephemeral=True)


class AskSupportModal(discord.ui.Modal, title="❓ Ask Instant Support"):
    q = discord.ui.TextInput(
        label="What do you need help with?",
        placeholder="e.g. How do I verify with Bloxlink or appeal a warning?",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=400,
    )

    async def on_submit(self, i: discord.Interaction):
        await i.response.defer()
        ans, _ = await get_faq_reply(i.guild.id, i.user.display_name, self.q.value)
        await i.followup.send(
            content=(
                f"🤖 **AI First-Responder** for {i.user.mention}\n"
                f"❓ **Question:** {self.q.value}\n"
                f"💬 **Answer:** {ans}\n\n"
                f"*Did this fix your issue? Tap a button below:*"
            )[:1990],
            view=DeflectActionView(),
        )


class SupportDeskView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ask Support (Instant Answer)", style=discord.ButtonStyle.primary, emoji="❓", custom_id="sd:ask")
    async def b_ask(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.send_modal(AskSupportModal())

    @discord.ui.button(label="Check On-Call Staff", style=discord.ButtonStyle.secondary, emoji="🟢", custom_id="sd:who")
    async def b_who(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.send_message(format_oncall_board(i.guild), ephemeral=True)


class OnCallControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Go On-Call", style=discord.ButtonStyle.success, emoji="🟢", custom_id="occ:on", row=0)
    async def b_on(self, i: discord.Interaction, b: discord.ui.Button):
        if not is_staff(i.user):
            return await i.response.send_message("❌ Staff only.", ephemeral=True)
        d = gdata(i.guild.id)
        if i.user.id not in d["oncall"]:
            d["oncall"].append(i.user.id)
            save_data()
        await i.response.edit_message(content=format_oncall_board(i.guild), view=self)
        await i.followup.send("🟢 You are now **ON-CALL** and will be pinged for human support requests.", ephemeral=True)

    @discord.ui.button(label="Go Off-Call", style=discord.ButtonStyle.danger, emoji="🔴", custom_id="occ:off", row=0)
    async def b_off(self, i: discord.Interaction, b: discord.ui.Button):
        if not is_staff(i.user):
            return await i.response.send_message("❌ Staff only.", ephemeral=True)
        d = gdata(i.guild.id)
        if i.user.id in d["oncall"]:
            d["oncall"].remove(i.user.id)
            save_data()
        await i.response.edit_message(content=format_oncall_board(i.guild), view=self)
        await i.followup.send("🔴 You are now **OFF-CALL** — you will not be pinged.", ephemeral=True)

    @discord.ui.button(label="Pause / Resume Pings", style=discord.ButtonStyle.secondary, emoji="🔔", custom_id="occ:tog", row=1)
    async def b_tog(self, i: discord.Interaction, b: discord.ui.Button):
        if not is_staff(i.user):
            return await i.response.send_message("❌ Staff only.", ephemeral=True)
        d = gdata(i.guild.id)
        d["pings_on"] = not d["pings_on"]
        save_data()
        await i.response.edit_message(content=format_oncall_board(i.guild), view=self)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="occ:ref", row=1)
    async def b_ref(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.edit_message(content=format_oncall_board(i.guild), view=self)


# --- 5. BOT CORE & SLASH COMMANDS ---
class SupportOnCallBot(commands.Bot):
    def __init__(self, mi: bool = True):
        it = discord.Intents.default()
        it.message_content = mi
        super().__init__(command_prefix="!", intents=it, help_command=None)
        self._synced = False

    async def setup_hook(self):
        for v in (ClaimRequestView(), DeflectActionView(), SupportDeskView(), OnCallControlView()):
            self.add_view(v)
        if not self._synced:
            try:
                await self.tree.sync()
                self._synced = True
            except Exception as e:
                print(f"Sync: {e}")

    async def on_ready(self):
        global STATUS
        STATUS = f"ONLINE as {self.user}"
        print(f"✅ AI FAQ & On-Call Ping Controller ONLINE: {self.user}")

    async def on_message(self, msg: discord.Message):
        if msg.author.bot or not msg.guild:
            return
        await self.process_commands(msg)

        d = gdata(msg.guild.id)
        txt = (msg.content or "").strip()
        if not txt or txt.startswith("!"):
            return

        # 1. Ping Controller: if someone manually pings the Staff Role, route cleanly to On-Call staff
        srid = d["staff_role"]
        if srid and any(r.id == srid for r in msg.role_mentions) and not is_staff(msg.author):
            if not d["pings_on"]:
                return await msg.reply("🔕 **Ping Controller:** Staff pings are currently paused. Ask your question here or use `/ask` for instant AI help!")
            if d["oncall"]:
                pings = " ".join(f"<@{u}>" for u in d["oncall"][:15])
                return await msg.reply(f"🎧 **On-Call Router:** Routing your ping to On-Call agents: {pings}", view=ClaimRequestView())

        # 2. AI First-Responder: replies when pinged OR inside the configured support channel
        pinged = self.user in msg.mentions
        in_sup_ch = d["support_ch"] and msg.channel.id == d["support_ch"] and not is_staff(msg.author)
        if not (pinged or in_sup_ch):
            return

        clean = re.sub(rf"<@!?{self.user.id}>", "", txt).strip()
        if not clean:
            return await msg.reply("🤖 Ping me with your question (or use `/ask`), and I'll check our FAQs right away!")

        async with msg.channel.typing():
            ans, matched = await get_faq_reply(msg.guild.id, msg.author.display_name, clean)
        if in_sup_ch and not pinged and not matched and not clean.endswith("?"):
            return

        await msg.reply(
            content=(
                f"🤖 **AI First-Responder** for {msg.author.mention}\n"
                f"❓ **Question:** {clean[:300]}\n"
                f"💬 **Answer:** {ans}\n\n"
                f"*Did this fix your issue?*"
            )[:1990],
            view=DeflectActionView(),
        )


def reg_cmds(bot: SupportOnCallBot):
    @bot.tree.command(name="support_setup", description="Set Staff Role, optional auto-answer Support Channel & Ping Cooldown")
    async def s_set(i: discord.Interaction, staff_role: discord.Role, support_channel: discord.TextChannel = None, ping_cooldown_seconds: int = 120):
        if not i.user.guild_permissions.administrator:
            return await i.response.send_message("❌ Administrators only.", ephemeral=True)
        d = gdata(i.guild.id)
        d["staff_role"] = staff_role.id
        d["support_ch"] = support_channel.id if support_channel else 0
        d["cooldown"] = max(15, min(ping_cooldown_seconds, 3600))
        save_data()
        await i.response.send_message(
            f"✅ **Support & Ping Controller Configured!**\n"
            f"🛡️ **Staff Role:** {staff_role.mention}\n"
            f"💬 **Auto-Answer Channel:** {support_channel.mention if support_channel else '*Ping/Command Only*'}\n"
            f"⏱️ **Ping Cooldown:** `{d['cooldown']}s`\n\n"
            f"👉 Next: Run `/oncall_panel` in staff chat and `/support_panel` in your support channel!",
            ephemeral=True,
        )

    @bot.tree.command(name="oncall_panel", description="Post the plain-text On-Call & Ping Controller panel")
    async def s_ocp(i: discord.Interaction):
        if not is_staff(i.user):
            return await i.response.send_message("❌ Staff only.", ephemeral=True)
        await i.response.send_message(content=format_oncall_board(i.guild), view=OnCallControlView())

    @bot.tree.command(name="support_panel", description="Post the plain-text AI Support Desk panel")
    async def s_sp(i: discord.Interaction):
        if not is_staff(i.user):
            return await i.response.send_message("❌ Staff only.", ephemeral=True)
        await i.response.send_message(content=format_support_panel(i.guild), view=SupportDeskView())

    @bot.tree.command(name="oncall", description="Quickly toggle yourself On-Call or Off-Call")
    async def s_oc(i: discord.Interaction):
        if not is_staff(i.user):
            return await i.response.send_message("❌ Staff only.", ephemeral=True)
        d = gdata(i.guild.id)
        if i.user.id in d["oncall"]:
            d["oncall"].remove(i.user.id)
            msg = f"🔴 {i.user.mention} is now **OFF-CALL**."
        else:
            d["oncall"].append(i.user.id)
            msg = f"🟢 {i.user.mention} is now **ON-CALL** for support pings!"
        save_data()
        await i.response.send_message(msg)

    @bot.tree.command(name="ping_control", description="Pause/Resume On-Call pings or update cooldown seconds")
    async def s_pc(i: discord.Interaction, pings_enabled: bool, cooldown_seconds: int = None):
        if not is_staff(i.user):
            return await i.response.send_message("❌ Staff only.", ephemeral=True)
        d = gdata(i.guild.id)
        d["pings_on"] = pings_enabled
        if cooldown_seconds is not None:
            d["cooldown"] = max(15, min(cooldown_seconds, 3600))
        save_data()
        state = "🔔 ENABLED" if d["pings_on"] else "🔕 PAUSED"
        await i.response.send_message(f"⚙️ **Ping Controller Updated:** {state} • Cooldown: `{d['cooldown']}s`")

    @bot.tree.command(name="ask", description="Ask the AI First-Responder & FAQ Deflector a question")
    async def s_ask(i: discord.Interaction, question: str):
        await i.response.defer()
        ans, _ = await get_faq_reply(i.guild.id, i.user.display_name, question)
        await i.followup.send(
            content=(
                f"🤖 **AI First-Responder** for {i.user.mention}\n"
                f"❓ **Question:** {question[:300]}\n"
                f"💬 **Answer:** {ans}\n\n"
                f"*Did this fix your issue?*"
            )[:1990],
            view=DeflectActionView(),
        )

    @bot.tree.command(name="ping_staff", description="Ping only On-Call staff through the Smart Ping Controller")
    async def s_ps(i: discord.Interaction, issue: str):
        await i.response.defer(ephemeral=True)
        note = await route_oncall_ping(i.channel, i.guild, i.user, issue)
        await i.followup.send(note, ephemeral=True)

    @bot.tree.command(name="add_faq", description="Add a Q&A entry to the AI First-Responder's knowledge base")
    async def s_af(i: discord.Interaction, question_keywords: str, answer: str):
        if not is_staff(i.user):
            return await i.response.send_message("❌ Staff only.", ephemeral=True)
        d = gdata(i.guild.id)
        d["faqs"].append({"q": question_keywords.strip()[:150], "a": answer.strip()[:600]})
        save_data()
        await i.response.send_message(f"✅ **FAQ Added (#{len(d['faqs'])})!**\n❓ `{question_keywords[:120]}`\n💬 {answer[:300]}", ephemeral=True)

    @bot.tree.command(name="remove_faq", description="Remove a saved FAQ by its number from /list_faqs")
    async def s_rf(i: discord.Interaction, number: int):
        if not is_staff(i.user):
            return await i.response.send_message("❌ Staff only.", ephemeral=True)
        faqs = gdata(i.guild.id)["faqs"]
        if number < 1 or number > len(faqs):
            return await i.response.send_message(f"❌ Choose a number between `1` and `{len(faqs)}`.", ephemeral=True)
        removed = faqs.pop(number - 1)
        save_data()
        await i.response.send_message(f"🗑️ Removed FAQ #{number}: `{removed['q']}`", ephemeral=True)

    @bot.tree.command(name="list_faqs", description="Show all saved Server FAQs in plain chat text")
    async def s_lf(i: discord.Interaction):
        faqs = gdata(i.guild.id)["faqs"]
        if not faqs:
            return await i.response.send_message("📋 No FAQs saved yet! Staff can add them with `/add_faq`.", ephemeral=True)
        lines = [f"**{n}. {f['q']}**\n> {f['a']}" for n, f in enumerate(faqs, 1)]
        await i.response.send_message("📋 **SAVED SERVER FAQS**\n━━━━━━━━━━━━━━━━━━━━━━\n" + "\n\n".join(lines)[:1850], ephemeral=True)


async def main():
    global STATUS
    await run_web()
    asyncio.create_task(self_ping())
    if not TOKEN:
        STATUS = "MISSING BOT_TOKEN"
        while True:
            await asyncio.sleep(3600)
    mi, w = True, 90
    while True:
        bot = SupportOnCallBot(mi)
        reg_cmds(bot)
        try:
            await bot.start(TOKEN)
            break
        except discord.PrivilegedIntentsRequired:
            await bot.close()
            mi = False
        except discord.HTTPException as e:
            await bot.close()
            if e.status == 429:
                STATUS = f"429 wait {w}s"
                await asyncio.sleep(w)
                w = min(w + 60, 300)
            else:
                await asyncio.sleep(60)
        except Exception as e:
            await bot.close()
            STATUS = f"Retry ({type(e).__name__})"
            await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
    
