import logging
import os
import shlex
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from core import session_store, notifier, claude_runner, task_queue

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_IDS = set(int(x) for x in os.environ["ALLOWED_USER_IDS"].split(","))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://agent.enginchantier.ma")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

VALID_PROFILES = {"ceo", "architect", "developer", "reviewer"}

import json
SCHEDULES_FILE = str(Path.home() / ".claude" / "telegram_schedules.json")
schedules: dict[str, dict] = {}
scheduler = AsyncIOScheduler()


# ── schedule persistence ──────────────────────────────────────────────────────

def load_schedules() -> dict[str, dict]:
    try:
        with open(SCHEDULES_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_schedules():
    try:
        with open(SCHEDULES_FILE, "w") as f:
            json.dump(schedules, f)
    except Exception as e:
        logger.error(f"Failed to save schedules: {e}")


def next_job_id() -> str:
    if not schedules:
        return "1"
    return str(max(int(k) for k in schedules.keys()) + 1)


# ── helpers ───────────────────────────────────────────────────────────────────

def _uid(update: Update) -> str:
    return str(update.effective_user.id)


def _allowed(update: Update) -> bool:
    return update.effective_user.id in ALLOWED_IDS


async def _send(update: Update, text: str):
    for i in range(0, max(len(text), 1), 4096):
        await update.message.reply_text(text[i : i + 4096])


# ── scheduled job runner ──────────────────────────────────────────────────────

async def run_scheduled_prompt(bot, user_id: int, prompt: str, job_id: str):
    logger.info(f"Running scheduled job {job_id} for user {user_id}: {prompt}")
    uid = str(user_id)
    profile = session_store.get_profile(uid)
    session_id = session_store.get_session(uid, profile)
    result = await claude_runner.run(profile, prompt, session_id)
    if result.session_id and result.session_id != session_id:
        session_store.set_session(uid, profile, result.session_id)
    full = f"[Scheduled job {job_id} / {profile}]\n{result.text or 'Done (no output).'}"
    for i in range(0, len(full), 4096):
        await bot.send_message(chat_id=user_id, text=full[i : i + 4096])
    for msg in result.notifications:
        await bot.send_message(chat_id=user_id, text=f"🔔 {msg}")


# ── command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return
    profile = session_store.get_profile(_uid(update))
    await _send(update, (
        "DevAgent online.\n\n"
        f"Current profile: {profile}\n\n"
        "Agent profiles:\n"
        "  /profile <name> — switch agent (ceo, architect, developer, reviewer)\n"
        "  /new — reset current profile's conversation\n\n"
        "Background tasks:\n"
        "  /bg <task> — run task in background, notify when done\n"
        "  /tasks — list your running background tasks\n"
        "  /review <pr> — review & auto-merge a PR (background)\n\n"
        "Scheduled jobs:\n"
        '  /schedule "cron" prompt — add a scheduled job\n'
        "  /schedules — list active scheduled jobs\n"
        "  /unschedule <id> — remove a scheduled job\n\n"
        'Example: /schedule "0 9 * * 1" summarize open GitHub issues'
    ))


async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return
    args = context.args
    if not args or args[0].lower() not in VALID_PROFILES:
        await _send(update, f"Usage: /profile <{' | '.join(sorted(VALID_PROFILES))}>")
        return
    profile = args[0].lower()
    session_store.set_profile(_uid(update), profile)
    await _send(update, f"Switched to {profile} mode.")


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return
    uid = _uid(update)
    profile = session_store.get_profile(uid)
    session_store.delete_session(uid, profile)
    await _send(update, f"Conversation reset for {profile} profile.")


async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return
    running = task_queue.list_running(_uid(update))
    if not running:
        await _send(update, "No background tasks running.")
        return
    lines = [f"• [{t.task_id}] {t.profile}: {t.description}" for t in running]
    await _send(update, "Running tasks:\n" + "\n".join(lines))


async def cmd_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return
    uid = _uid(update)
    if not context.args:
        await _send(update, "Usage: /review <pr-number-or-url>")
        return
    pr_ref = " ".join(context.args)
    session_id = session_store.get_session(uid, "reviewer")
    task_queue.submit(
        user_id=uid,
        profile="reviewer",
        text=f"Review and merge {pr_ref}. If the code looks good, approve and merge. Output NOTIFY when done.",
        session_id=session_id,
        description=f"Review {pr_ref}",
    )
    await _send(update, f"Reviewer started on {pr_ref}. I'll notify you when done.")


async def cmd_bg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return
    uid = _uid(update)
    if not context.args:
        await _send(update, "Usage: /bg <task description>")
        return
    text = " ".join(context.args)
    profile = session_store.get_profile(uid)
    session_id = session_store.get_session(uid, profile)
    task_queue.submit(
        user_id=uid,
        profile=profile,
        text=text,
        session_id=session_id,
        description=text,
    )
    await _send(update, f"Background task started [{profile}]. I'll notify you when done.")


async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return
    user_id = update.effective_user.id
    args_text = update.message.text.partition(" ")[2].strip()
    if not args_text:
        await _send(update, 'Usage: /schedule "cron" prompt\nExample: /schedule "0 9 * * *" check open GitHub issues')
        return
    try:
        parts = shlex.split(args_text)
    except ValueError as e:
        await _send(update, f"Parse error: {e}")
        return
    if len(parts) < 2:
        await _send(update, 'Usage: /schedule "cron" prompt')
        return
    cron_str, prompt = parts[0], " ".join(parts[1:])
    try:
        trigger = CronTrigger.from_crontab(cron_str)
    except Exception as e:
        await _send(update, f"Invalid cron `{cron_str}`: {e}")
        return
    job_id = next_job_id()
    schedules[job_id] = {"user_id": user_id, "cron": cron_str, "prompt": prompt}
    save_schedules()
    scheduler.add_job(
        run_scheduled_prompt,
        trigger=trigger,
        kwargs={"bot": context.bot, "user_id": user_id, "prompt": prompt, "job_id": job_id},
        id=job_id,
    )
    job = scheduler.get_job(job_id)
    next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z") if job and job.next_run_time else "N/A"
    await _send(update, f"Scheduled job {job_id} added.\nCron: {cron_str}\nPrompt: {prompt}\nNext run: {next_run}")


async def cmd_schedules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return
    user_id = update.effective_user.id
    user_jobs = {jid: d for jid, d in schedules.items() if d["user_id"] == user_id}
    if not user_jobs:
        await _send(update, "No scheduled jobs.")
        return
    lines = []
    for jid, data in user_jobs.items():
        job = scheduler.get_job(jid)
        next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z") if job and job.next_run_time else "N/A"
        lines.append(f"[{jid}] {data['cron']}\n  {data['prompt']}\n  Next: {next_run}")
    await _send(update, "\n\n".join(lines))


async def cmd_unschedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        return
    if not context.args:
        await _send(update, "Usage: /unschedule <job_id>")
        return
    job_id = context.args[0]
    if job_id not in schedules or schedules[job_id]["user_id"] != update.effective_user.id:
        await _send(update, f"Job {job_id} not found.")
        return
    del schedules[job_id]
    save_schedules()
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
    await _send(update, f"Job {job_id} removed.")


# ── main message handler ──────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update):
        logger.warning(f"Unauthorized: user_id={update.effective_user.id}")
        return

    uid = _uid(update)
    text = update.message.text
    profile = session_store.get_profile(uid)
    session_id = session_store.get_session(uid, profile)

    logger.info(f"[{profile}] {uid}: {text[:80]}")
    thinking = await update.message.reply_text(f"[{profile}] Working on it...")

    result = await claude_runner.run(profile, text, session_id)

    # If resume failed, retry as a fresh session
    if session_id and result.returncode != 0:
        logger.warning(f"Resume failed for [{profile}] user {uid}, retrying fresh")
        session_store.delete_session(uid, profile)
        result = await claude_runner.run(profile, text, session_id=None)

    # Persist new/updated session ID
    if result.session_id and result.session_id != session_id:
        session_store.set_session(uid, profile, result.session_id)

    await thinking.delete()

    response = result.text or "Done (no output)."
    await _send(update, response)

    for msg in result.notifications:
        await _send(update, f"🔔 {msg}")


# ── startup ───────────────────────────────────────────────────────────────────

async def post_init(application: Application):
    global schedules
    schedules = load_schedules()
    for job_id, data in schedules.items():
        try:
            trigger = CronTrigger.from_crontab(data["cron"])
            scheduler.add_job(
                run_scheduled_prompt,
                trigger=trigger,
                kwargs={"bot": application.bot, "user_id": data["user_id"],
                        "prompt": data["prompt"], "job_id": job_id},
                id=job_id,
            )
        except Exception as e:
            logger.error(f"Failed to restore scheduled job {job_id}: {e}")
    scheduler.start()
    logger.info(f"Scheduler started, restored {len(schedules)} scheduled jobs")

    # Register Telegram notification channels for all allowed users
    for uid in ALLOWED_IDS:
        def make_send(u):
            async def send_fn(message: str):
                await application.bot.send_message(chat_id=u, text=message)
            return send_fn
        notifier.register(str(uid), make_send(uid))


def main():
    session_store.init()

    app = Application.builder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("bg", cmd_bg))
    app.add_handler(CommandHandler("tasks", cmd_tasks))
    app.add_handler(CommandHandler("review", cmd_review))
    app.add_handler(CommandHandler("schedule", cmd_schedule))
    app.add_handler(CommandHandler("schedules", cmd_schedules))
    app.add_handler(CommandHandler("unschedule", cmd_unschedule))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info(f"Starting webhook on {WEBHOOK_URL}/webhook")
    app.run_webhook(
        listen="0.0.0.0",
        port=8000,
        url_path="/webhook",
        webhook_url=f"{WEBHOOK_URL}/webhook",
        secret_token=WEBHOOK_SECRET if WEBHOOK_SECRET else None,
    )


if __name__ == "__main__":
    main()
