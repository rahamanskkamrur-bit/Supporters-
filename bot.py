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
