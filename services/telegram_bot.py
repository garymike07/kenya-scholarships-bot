import os
import re
import logging
import html as html_lib
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from config import (
    TELEGRAM_TOKEN, TELEGRAM_CHANNEL_ID, SERVICES, SITE_URL, CONVEX_SITE_URL
)
from services.database import (
    register_user, get_user_count,
    get_opportunities_by_category, get_unsent_opportunities, mark_sent,
    validate_access_code_remote, activate_subscription,
    has_active_subscription, get_user_subscriptions
)
from services.ai_chat import (
    chat_completion, generate_ats_resume, SYSTEM_PROMPT,
    async_chat_completion, async_generate_ats_resume
)
from services.resume_export import export_pdf, export_docx, export_txt

log = logging.getLogger(__name__)

CATEGORY_LABELS = {
    "business_grants": "Business Grants",
    "student_scholarships": "Student Scholarships",
    "nonprofit_funding": "Non-Profit Funding",
}
MAX_MSG_LEN = 4000
GREETING_WORDS = {"hi", "hello", "hey", "yo", "good morning", "good afternoon", "good evening"}
SEARCH_STOPWORDS = {
    "a", "an", "and", "are", "for", "from", "help", "i", "in", "latest", "list", "looking",
    "me", "need", "new", "of", "on", "please", "show", "tell", "that", "the", "to", "want",
    "with", "find", "opportunity", "opportunities", "grant", "grants", "scholarship", "scholarships",
    "funding", "fully", "funded",
}

BUY_URL = SITE_URL or "https://your-site.vercel.app"


def escape(text: str) -> str:
    if not text:
        return ""
    return html_lib.escape(str(text))


def _buy_button(service_id: str) -> InlineKeyboardMarkup:
    svc = SERVICES.get(service_id, {})
    name = svc.get("name", service_id)
    url = f"{BUY_URL}/services/{service_id.replace('_', '-')}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Get {name}", url=url)]
    ])


def _needs_subscription(user_id: int, service_type: str) -> bool:
    if not CONVEX_SITE_URL:
        return False
    return not has_active_subscription(user_id, service_type)


def format_opportunity_full(opp: dict) -> str:
    cat_label = CATEGORY_LABELS.get(opp.get("category", ""), opp.get("category", ""))
    title = escape(opp.get("title", ""))
    url = opp.get("url", "")
    source = escape(opp.get("source", ""))
    parts = [f"<b>{title}</b>", ""]
    summary = opp.get("summary") or opp.get("description", "")
    if summary:
        parts.extend([escape(summary), ""])
    if opp.get("level"):
        parts.append(f"<b>Level:</b> {escape(opp['level'])}")
    if opp.get("host_country"):
        parts.append(f"<b>Study In:</b> {escape(opp['host_country'])}")
    if opp.get("amount"):
        parts.append(f"<b>Award:</b> {escape(opp['amount'])}")
    if opp.get("deadline"):
        parts.append(f"<b>Deadline:</b> {escape(opp['deadline'])}")
    if opp.get("eligibility"):
        parts.append(f"\n<b>Eligibility:</b>\n{escape(opp['eligibility'])}")
    if opp.get("benefits"):
        parts.append(f"\n<b>Benefits:</b>\n{escape(opp['benefits'])}")
    parts.append(f"\n<b>Category:</b> {escape(cat_label)}")
    parts.append(f"<b>Source:</b> {escape(source)}")
    parts.append(f'\n<a href="{escape(url)}">Apply Here / View Full Details</a>')
    return "\n".join(parts)


def format_opportunity_preview(opp: dict) -> str:
    title = escape(opp.get("title", ""))
    deadline = opp.get("deadline", "")
    level = opp.get("level", "")
    country = opp.get("host_country", "")
    summary = (opp.get("summary") or opp.get("description") or "")[:200]

    parts = [f"<b>{title}</b>", ""]
    if summary:
        parts.append(escape(summary) + "...")
    if level:
        parts.append(f"<b>Level:</b> {escape(level)}")
    if country:
        parts.append(f"<b>Study In:</b> {escape(country)}")
    if deadline:
        parts.append(f"<b>Deadline:</b> {escape(deadline)}")
    parts.append("")
    parts.append("Want full details, eligibility info, and direct apply links?")
    parts.append("Subscribe to <b>ScholarshipFinder Pro</b> for unlimited access!")
    return "\n".join(parts)


def split_message(text: str) -> list[str]:
    if len(text) <= MAX_MSG_LEN:
        return [text]
    chunks = []
    while text:
        if len(text) <= MAX_MSG_LEN:
            chunks.append(text)
            break
        cut = text[:MAX_MSG_LEN]
        split_pos = cut.rfind("\n\n")
        if split_pos < 500:
            split_pos = cut.rfind("\n")
        if split_pos < 500:
            split_pos = MAX_MSG_LEN
        chunks.append(text[:split_pos].rstrip())
        text = text[split_pos:].lstrip()
    return chunks


def normalize_user_text(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("/"):
        command, _, rest = text.partition(" ")
        command = command.lstrip("/").split("@", 1)[0].replace("_", " ")
        text = f"{command} {rest}".strip()
    return text


def search_tokens(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9+#-]+", text.lower())
    return [token for token in tokens if len(token) > 2 and token not in SEARCH_STOPWORDS][:6]


def detect_category(text: str) -> str | None:
    lower = text.lower()
    if any(word in lower for word in ["business", "startup", "entrepreneur", "sme", "seed fund"]):
        return "business_grants"
    if any(word in lower for word in ["ngo", "nonprofit", "non-profit", "charity", "community"]):
        return "nonprofit_funding"
    if any(word in lower for word in ["scholarship", "bursary", "masters", "phd", "undergraduate", "study"]):
        return "student_scholarships"
    return None


def is_simple_greeting(text: str) -> bool:
    lower = text.lower().strip()
    if lower in GREETING_WORDS:
        return True
    words = lower.split()
    return len(words) <= 3 and any(greet in lower for greet in GREETING_WORDS)


async def send_full_message(bot, chat_id, text, reply_markup=None):
    import asyncio, re as _re
    parts = split_message(text)
    for i, part in enumerate(parts):
        markup = reply_markup if i == len(parts) - 1 else None
        for attempt in range(3):
            try:
                await bot.send_message(chat_id=chat_id, text=part, parse_mode="HTML",
                                       disable_web_page_preview=True, reply_markup=markup)
                break
            except Exception as e:
                err_str = str(e)
                retry_match = _re.search(r'Retry in (\d+)', err_str)
                if retry_match:
                    wait = int(retry_match.group(1)) + 1
                    log.warning("Flood control, waiting %ds...", wait)
                    await asyncio.sleep(wait)
                elif attempt < 2:
                    try:
                        await bot.send_message(chat_id=chat_id, text=part,
                                               disable_web_page_preview=True, reply_markup=markup)
                        break
                    except Exception:
                        await asyncio.sleep(2)
                else:
                    log.error("Send failed after retries: %s", e)


async def send_opportunities(bot, chat_id, opps):
    if not opps:
        await bot.send_message(chat_id, "No opportunities found yet. I'm still gathering data - check back soon!")
        return
    for opp in opps:
        await send_full_message(bot, chat_id, format_opportunity_full(opp))


async def send_paywall_msg(bot, chat_id, service_type: str):
    svc = SERVICES.get(service_type, {})
    name = svc.get("name", service_type)
    await send_full_message(
        bot, chat_id,
        f"This feature requires an active <b>{escape(name)}</b> subscription.\n\n"
        f"Visit our website to subscribe and get instant access!",
        reply_markup=_buy_button(service_type),
    )


async def do_search(bot, chat_id, keyword, user_id: int = 0):
    from services.database import get_conn
    keyword = keyword.strip()
    tokens = search_tokens(keyword)
    conn = get_conn()
    rows = []
    if tokens:
        clauses = []
        params = []
        for token in tokens:
            clauses.append(
                "(lower(title) LIKE ? OR lower(description) LIKE ? OR lower(summary) LIKE ? OR lower(host_country) LIKE ? OR lower(level) LIKE ?)"
            )
            like = f"%{token}%"
            params.extend([like, like, like, like, like])
        rows = conn.execute(
            f"SELECT * FROM opportunities WHERE {' OR '.join(clauses)} ORDER BY posted_at DESC LIMIT 5",
            params,
        ).fetchall()
    if not rows and keyword:
        like = f"%{keyword.lower()}%"
        rows = conn.execute(
            "SELECT * FROM opportunities WHERE lower(title) LIKE ? OR lower(description) LIKE ? OR lower(summary) LIKE ? ORDER BY posted_at DESC LIMIT 5",
            (like, like, like),
        ).fetchall()
    conn.close()
    if not rows:
        await bot.send_message(chat_id, f"No results for '{escape(keyword)}'. Try different keywords.", parse_mode="HTML")
        return

    if _needs_subscription(user_id, "scholarship_finder"):
        await bot.send_message(chat_id, f"Found {len(rows)} result(s) for '<b>{escape(keyword)}</b>'.\nHere's a preview:", parse_mode="HTML")
        await send_full_message(bot, chat_id, format_opportunity_preview(dict(rows[0])),
                                reply_markup=_buy_button("scholarship_finder"))
        return

    await bot.send_message(chat_id, f"Found {len(rows)} result(s) for '<b>{escape(keyword)}</b>':", parse_mode="HTML")
    for row in rows:
        await send_full_message(bot, chat_id, format_opportunity_full(dict(row)))


async def handle_local_request(bot, chat_id, text: str, user_id: int = 0) -> bool:
    lower = text.lower()

    if is_simple_greeting(text):
        subs = get_user_subscriptions(user_id) if user_id else []
        active_services = [s["service_type"] for s in subs]
        greeting = "Hi! I can help you with:\n\n"
        greeting += "<b>1. ScholarshipFinder Pro</b> - Find scholarships, grants & funding\n"
        if "scholarship_finder" in active_services:
            greeting += "   (Active)\n"
        else:
            greeting += f"   <a href=\"{BUY_URL}/services/scholarship-finder\">Subscribe</a>\n"
        greeting += "\n<b>2. ResumeBuilder AI</b> - Build ATS-optimized resumes\n"
        if "resume_builder" in active_services:
            greeting += "   (Active)\n"
        else:
            greeting += f"   <a href=\"{BUY_URL}/services/resume-builder\">Subscribe</a>\n"
        greeting += "\nJust tell me what you need!"
        await send_full_message(bot, chat_id, greeting)
        return True

    if any(phrase in lower for phrase in ["latest", "new scholarships", "recent scholarships", "show latest"]):
        if _needs_subscription(user_id, "scholarship_finder"):
            from services.database import get_conn
            conn = get_conn()
            rows = conn.execute("SELECT * FROM opportunities ORDER BY posted_at DESC LIMIT 1").fetchall()
            conn.close()
            if rows:
                await bot.send_message(chat_id, "Here's a preview of our latest opportunity:", parse_mode="HTML")
                await send_full_message(bot, chat_id, format_opportunity_preview(dict(rows[0])),
                                        reply_markup=_buy_button("scholarship_finder"))
            else:
                await bot.send_message(chat_id, "No opportunities yet. Check back soon!")
            return True

        from services.database import get_conn
        conn = get_conn()
        rows = conn.execute("SELECT * FROM opportunities ORDER BY posted_at DESC LIMIT 5").fetchall()
        conn.close()
        await send_opportunities(bot, chat_id, [dict(r) for r in rows])
        return True

    category = detect_category(text)
    if category and any(word in lower for word in ["browse", "category", "list", "show", "latest"]):
        if _needs_subscription(user_id, "scholarship_finder"):
            opps = get_opportunities_by_category(category, limit=1)
            if opps:
                await send_full_message(bot, chat_id, format_opportunity_preview(opps[0]),
                                        reply_markup=_buy_button("scholarship_finder"))
            return True
        opps = get_opportunities_by_category(category, limit=5)
        await send_opportunities(bot, chat_id, opps)
        return True

    if category:
        await do_search(bot, chat_id, text, user_id)
        return True

    return False


# ─── DEEP-LINK ACTIVATION ───

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username or "")
    context.user_data.clear()
    context.user_data["chat_history"] = [{"role": "system", "content": SYSTEM_PROMPT}]

    args = context.args
    if args and len(args) > 0:
        code = args[0]
        await _handle_activation(update, code)
        return

    subs = get_user_subscriptions(user.id)
    active_services = [s["service_type"] for s in subs]

    welcome = (
        f"Hey {escape(user.first_name)}!\n\n"
        "Welcome to <b>GrantsFinder Bot</b> - your AI assistant for scholarships and resumes.\n\n"
        "<b>Our Services:</b>\n\n"
    )

    welcome += "1. <b>ScholarshipFinder Pro</b>\n"
    welcome += "   Find fully funded scholarships worldwide for Kenyan students.\n"
    if "scholarship_finder" in active_services:
        welcome += "   Status: Active\n"
        welcome += "   Just say something like \"find me scholarships in Germany\".\n"
    else:
        welcome += f"   <a href=\"{BUY_URL}/services/scholarship-finder\">Subscribe Now</a>\n"

    welcome += "\n2. <b>ResumeBuilder AI</b>\n"
    welcome += "   Build professional ATS-optimized resumes via chat.\n"
    if "resume_builder" in active_services:
        welcome += "   Status: Active\n"
        welcome += "   Just say \"help me write a resume\" to get started.\n"
    else:
        welcome += f"   <a href=\"{BUY_URL}/services/resume-builder\">Subscribe Now</a>\n"

    welcome += f"\nJoin our channel for free previews: @botmaster11"

    await send_full_message(update.effective_chat.bot, update.message.chat_id, welcome)


async def _handle_activation(update: Update, code: str):
    user = update.effective_user
    user_id = user.id

    # Determine service from code prefix
    service_type = None
    for svc_id, svc in SERVICES.items():
        if code.startswith(svc["access_prefix"] + "_"):
            service_type = svc_id
            break

    if not service_type:
        await update.message.reply_text("Invalid activation code. Please check your link and try again.")
        return

    svc_name = SERVICES[service_type]["name"]

    if has_active_subscription(user_id, service_type):
        await update.message.reply_text(
            f"Your <b>{escape(svc_name)}</b> subscription is already active! Just start using it.",
            parse_mode="HTML",
        )
        return

    data = validate_access_code_remote(code)
    if not data:
        if not CONVEX_SITE_URL:
            activate_subscription(user_id, service_type, code, 0)
            await update.message.reply_text(
                f"<b>{escape(svc_name)}</b> activated!\n\n"
                "You now have full access. Just start chatting!",
                parse_mode="HTML",
            )
            return

        await send_full_message(
            update.effective_chat.bot, update.message.chat_id,
            f"Could not verify this activation code.\n\n"
            f"Please make sure you've completed payment on our website first.",
            reply_markup=_buy_button(service_type),
        )
        return

    expires_at = data.get("expiresAt", 0)
    activate_subscription(user_id, service_type, code, expires_at)

    if service_type == "scholarship_finder":
        msg = (
            f"<b>{escape(svc_name)}</b> is now active!\n\n"
            "Here's how to use it:\n"
            '- Ask me: "Show me latest scholarships"\n'
            '- Search: "Find masters scholarships in UK"\n'
            '- Browse: "Show student scholarships"\n\n'
            "Join our channel for hourly updates: @botmaster11\n\n"
            "Go ahead, ask me anything about scholarships!"
        )
    else:
        msg = (
            f"<b>{escape(svc_name)}</b> is now active!\n\n"
            "Here's how to use it:\n"
            '- Say: "I want to create a resume"\n'
            "- I'll ask about your experience, education, and skills\n"
            "- I'll generate an ATS-optimized resume\n"
            "- Download as PDF, DOCX, or TXT\n\n"
            "Let's get started! Tell me about yourself."
        )

    await send_full_message(update.effective_chat.bot, update.message.chat_id, msg)


# ─── RESUME DOWNLOAD BUTTONS ───

async def resume_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.replace("resume:", "")

    resume = context.user_data.get("generated_resume")
    if not resume:
        await query.edit_message_text("No resume found. Tell me you'd like to build one!")
        return

    if action in ("pdf", "docx", "txt"):
        await context.bot.send_chat_action(query.message.chat_id, "upload_document")
        try:
            name = context.user_data.get("resume_data", {}).get("name", "resume").replace(" ", "_")
            if action == "pdf":
                path = export_pdf(resume, name)
            elif action == "docx":
                path = export_docx(resume, name)
            else:
                path = export_txt(resume, name)
            with open(path, "rb") as f:
                await context.bot.send_document(
                    chat_id=query.message.chat_id, document=f,
                    filename=os.path.basename(path),
                    caption=f"Your ATS resume ({action.upper()})",
                )
            os.unlink(path)
        except Exception as e:
            log.error("Export error: %s", e)
            await context.bot.send_message(query.message.chat_id, f"Error generating file: {e}")

    elif action == "download_all":
        await context.bot.send_chat_action(query.message.chat_id, "upload_document")
        name = context.user_data.get("resume_data", {}).get("name", "resume").replace(" ", "_")
        for fmt, fn in [("pdf", export_pdf), ("docx", export_docx), ("txt", export_txt)]:
            try:
                path = fn(resume, name)
                with open(path, "rb") as f:
                    await context.bot.send_document(
                        chat_id=query.message.chat_id, document=f,
                        filename=os.path.basename(path),
                        caption=f"Your ATS resume ({fmt.upper()})",
                    )
                os.unlink(path)
            except Exception as e:
                log.error("Export %s error: %s", fmt, e)


# ─── MAIN AI HANDLER ───

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username or "")
    text = normalize_user_text(update.message.text)
    log.info("Message from %s (%s): %s", user.first_name, user.id, text[:100])

    if not text:
        return

    if await handle_local_request(context.bot, update.message.chat_id, text, user.id):
        return

    # Check if user is asking about resume (needs resume_builder subscription)
    resume_keywords = ["resume", "cv", "cover letter", "job application"]
    is_resume_request = any(kw in text.lower() for kw in resume_keywords)

    if is_resume_request and _needs_subscription(user.id, "resume_builder"):
        await send_paywall_msg(context.bot, update.message.chat_id, "resume_builder")
        return

    # Check if user is asking about scholarships (needs scholarship_finder subscription)
    scholarship_keywords = [
        "scholarship", "grant", "funding", "bursary", "fellowship",
        "opportunity", "study abroad", "fully funded", "masters", "phd",
        "bachelors", "university", "college",
    ]
    is_scholarship_request = any(kw in text.lower() for kw in scholarship_keywords)

    if is_scholarship_request and _needs_subscription(user.id, "scholarship_finder"):
        await send_paywall_msg(context.bot, update.message.chat_id, "scholarship_finder")
        return

    try:
        await context.bot.send_chat_action(update.message.chat_id, "typing")
    except Exception:
        pass

    history = context.user_data.get("chat_history", [])
    if not history:
        history = [{"role": "system", "content": SYSTEM_PROMPT}]

    if is_scholarship_request:
        from services.database import get_conn
        conn = get_conn()
        count = conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
        conn.close()
        context_msg = f"[SYSTEM NOTE: The scholarship database currently has {count} opportunities. Use [SEARCH: keyword] to show results, [SHOW_LATEST] for latest, or [SHOW_CATEGORY: category] for category browsing.]"
        history.append({"role": "system", "content": context_msg})

    resume_data = context.user_data.get("resume_data", {})
    if resume_data:
        resume_info = "\n".join(f"{k}: {v}" for k, v in resume_data.items() if v)
        if resume_info:
            history.append({"role": "system", "content": f"[SYSTEM NOTE: Resume data collected so far:\n{resume_info}]"})

    history.append({"role": "user", "content": text})

    if len(history) > 30:
        history = [history[0]] + history[-28:]

    response = await async_chat_completion(history, max_tokens=1000)
    history.append({"role": "assistant", "content": response})
    context.user_data["chat_history"] = history

    if response.startswith("All AI models are cooling down") or response == "AI is not configured.":
        if await handle_local_request(context.bot, update.message.chat_id, text, user.id):
            return
        if is_resume_request:
            await update.message.reply_text(
                "The AI resume writer is temporarily busy. Please try again in a minute."
            )
            return

    # Parse AI actions from response
    clean_response = response
    actions_done = False

    # Handle [GENERATE_RESUME]
    if "[GENERATE_RESUME]" in response:
        if _needs_subscription(user.id, "resume_builder"):
            await send_paywall_msg(context.bot, update.message.chat_id, "resume_builder")
            return

        clean_response = response.replace("[GENERATE_RESUME]", "").strip()
        if clean_response:
            await send_full_message(context.bot, update.message.chat_id, escape(clean_response))

        await context.bot.send_message(update.message.chat_id, "Generating your ATS-optimized resume...")
        await context.bot.send_chat_action(update.message.chat_id, "typing")

        resume_data = await _async_extract_resume_data(history)
        context.user_data["resume_data"] = resume_data
        resume_text = await async_generate_ats_resume(resume_data)
        context.user_data["generated_resume"] = resume_text

        await send_full_message(context.bot, update.message.chat_id, f"<pre>{escape(resume_text)}</pre>")

        keyboard = [
            [InlineKeyboardButton("PDF", callback_data="resume:pdf"),
             InlineKeyboardButton("DOCX", callback_data="resume:docx"),
             InlineKeyboardButton("TXT", callback_data="resume:txt")],
            [InlineKeyboardButton("Download All Formats", callback_data="resume:download_all")],
        ]
        await update.message.reply_text(
            "<b>Resume ready!</b> Choose a download format:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        actions_done = True

    # Handle [SEARCH: keyword]
    search_match = re.search(r'\[SEARCH:\s*(.+?)\]', response)
    if search_match:
        keyword = search_match.group(1).strip()
        clean_response = re.sub(r'\[SEARCH:\s*.+?\]', '', clean_response).strip()
        if clean_response:
            await send_full_message(context.bot, update.message.chat_id, escape(clean_response))
        await do_search(context.bot, update.message.chat_id, keyword, user.id)
        actions_done = True

    # Handle [SHOW_LATEST]
    if "[SHOW_LATEST]" in response:
        clean_response = clean_response.replace("[SHOW_LATEST]", "").strip()
        if clean_response:
            await send_full_message(context.bot, update.message.chat_id, escape(clean_response))
        from services.database import get_conn
        conn = get_conn()
        rows = conn.execute("SELECT * FROM opportunities ORDER BY posted_at DESC LIMIT 5").fetchall()
        conn.close()
        if _needs_subscription(user.id, "scholarship_finder") and rows:
            await send_full_message(context.bot, update.message.chat_id,
                                    format_opportunity_preview(dict(rows[0])),
                                    reply_markup=_buy_button("scholarship_finder"))
        else:
            await send_opportunities(context.bot, update.message.chat_id, [dict(r) for r in rows])
        actions_done = True

    # Handle [SHOW_CATEGORY: xxx]
    cat_match = re.search(r'\[SHOW_CATEGORY:\s*(.+?)\]', response)
    if cat_match:
        category = cat_match.group(1).strip()
        clean_response = re.sub(r'\[SHOW_CATEGORY:\s*.+?\]', '', clean_response).strip()
        if clean_response:
            await send_full_message(context.bot, update.message.chat_id, escape(clean_response))
        if _needs_subscription(user.id, "scholarship_finder"):
            opps = get_opportunities_by_category(category, limit=1)
            if opps:
                await send_full_message(context.bot, update.message.chat_id,
                                        format_opportunity_preview(opps[0]),
                                        reply_markup=_buy_button("scholarship_finder"))
        else:
            opps = get_opportunities_by_category(category, limit=5)
            await send_opportunities(context.bot, update.message.chat_id, opps)
        actions_done = True

    # Regular AI response (no actions)
    if not actions_done:
        clean_response = re.sub(r'\[.*?\]', '', clean_response).strip()
        if clean_response:
            try:
                await send_full_message(context.bot, update.message.chat_id, escape(clean_response))
            except Exception as e:
                log.error("Failed to send response: %s", e)
                try:
                    await update.message.reply_text(clean_response[:4000])
                except Exception:
                    pass


async def _async_extract_resume_data(history: list[dict]) -> dict:
    full_text = "\n".join(
        m["content"] for m in history
        if m["role"] == "user"
    )

    data = {}
    for msg in history:
        if msg["role"] != "user":
            continue
        content = msg["content"]

        if "@" in content and not data.get("email"):
            emails = re.findall(r'[\w.+-]+@[\w.-]+\.\w+', content)
            if emails:
                data["email"] = emails[0]

        if re.search(r'\+?\d[\d\s-]{8,}', content) and not data.get("phone"):
            phones = re.findall(r'\+?\d[\d\s-]{8,}', content)
            if phones:
                data["phone"] = phones[0].strip()

    extract_prompt = f"""Extract resume information from this conversation. Return ONLY the data in this exact format (leave blank if not mentioned):

name: 
email: 
phone: 
location: 
target_job: 
summary: 
experience: 
education: 
skills: 

Conversation:
{full_text[-3000:]}"""

    messages = [{"role": "user", "content": extract_prompt}]
    result = await async_chat_completion(messages, max_tokens=800)

    for line in result.split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip().lower().replace(" ", "_")
            value = value.strip()
            if key in ["name", "email", "phone", "location", "target_job", "summary", "experience", "education", "skills"]:
                if value and value.lower() not in ["not provided", "not mentioned", "n/a", ""]:
                    data[key] = value

    return data


# ─── CHANNEL POSTING (preview-only for non-subscribers) ───

async def post_to_channel(app: Application):
    if not TELEGRAM_CHANNEL_ID:
        return
    import asyncio
    opps = get_unsent_opportunities(limit=20)
    if not opps:
        return
    bot_info = await app.bot.get_me()
    for opp in opps:
        try:
            text = format_opportunity_preview(opp)
            buttons = []
            if SITE_URL:
                buttons.append([InlineKeyboardButton(
                    "Get Full Details - Subscribe",
                    url=f"{BUY_URL}/services/scholarship-finder"
                )])
            buttons.append([InlineKeyboardButton(
                "Open Bot",
                url=f"https://t.me/{bot_info.username}"
            )])
            await send_full_message(app.bot, TELEGRAM_CHANNEL_ID, text,
                                    reply_markup=InlineKeyboardMarkup(buttons))
            mark_sent(opp["uid"])
            await asyncio.sleep(3)
        except Exception as e:
            log.error("Channel post error: %s", e)
            await asyncio.sleep(5)


# ─── BUILD APP ───

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Bot error: %s", context.error, exc_info=context.error)


def build_app() -> Application:
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(resume_callback, pattern=r"^resume:"))
    app.add_handler(MessageHandler(filters.COMMAND & ~filters.Regex(r"^/start(?:@\w+)?$"), handle_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    return app
