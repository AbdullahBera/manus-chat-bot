"""
Manus Slack Bot
---------------
A bridge between Slack and the Manus AI API.
Users can DM the bot or mention it in a channel to chat with Manus.
"""

import os
import time
import threading
import logging
from flask import Flask, request, jsonify
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.signature import SignatureVerifier
import requests

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
MANUS_API_KEY        = os.environ["MANUS_API_KEY"]
SLACK_BOT_TOKEN      = os.environ["SLACK_BOT_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
MANUS_API_BASE       = "https://api.manus.ai/v2"

# ── Clients ───────────────────────────────────────────────────────────────────
app = Flask(__name__)
slack_client = WebClient(token=SLACK_BOT_TOKEN)
verifier = SignatureVerifier(SLACK_SIGNING_SECRET)

# ── In-memory conversation store  (channel_id → manus task_id) ───────────────
# For production, replace with Redis or a database.
conversation_store: dict[str, str] = {}
# Dedup processed Slack event IDs
processed_events: set[str] = set()

# Cache bot user ID so we don't call auth_test on every message
_bot_user_id: str = ""

# ── Manus API helpers ─────────────────────────────────────────────────────────

HEADERS = {
    "x-manus-api-key": MANUS_API_KEY,
    "Content-Type": "application/json",
}


def manus_create_task(user_message: str) -> str | None:
    """Create a new Manus task and return its task_id."""
    payload = {
        "message": {
            "role": "user",
            "content": user_message,
        }
    }
    try:
        resp = requests.post(f"{MANUS_API_BASE}/task.create", json=payload, headers=HEADERS, timeout=30)
        data = resp.json()
        if data.get("ok"):
            return data["data"]["task_id"]
        log.error("task.create failed: %s", data)
    except Exception as e:
        log.error("task.create exception: %s", e)
    return None


def manus_send_message(task_id: str, user_message: str) -> None:
    """Continue an existing Manus task with a follow-up message."""
    payload = {
        "task_id": task_id,
        "message": {
            "role": "user",
            "content": user_message,
        }
    }
    try:
        resp = requests.post(f"{MANUS_API_BASE}/task.sendMessage", json=payload, headers=HEADERS, timeout=30)
        data = resp.json()
        if not data.get("ok"):
            log.error("task.sendMessage failed: %s", data)
    except Exception as e:
        log.error("task.sendMessage exception: %s", e)


def manus_poll_result(task_id: str, timeout: int = 300) -> str:
    """
    Poll task.listMessages until the agent stops or times out.
    Returns the last assistant message text.
    """
    deadline = time.time() + timeout
    last_seen_cursor = None
    result_parts: list[str] = []

    while time.time() < deadline:
        params = {"task_id": task_id, "order": "asc", "limit": 50}
        if last_seen_cursor:
            params["cursor"] = last_seen_cursor

        try:
            resp = requests.get(f"{MANUS_API_BASE}/task.listMessages", params=params, headers=HEADERS, timeout=30)
            data = resp.json()
        except Exception as e:
            log.error("task.listMessages exception: %s", e)
            time.sleep(5)
            continue

        if not data.get("ok"):
            log.error("task.listMessages failed: %s", data)
            return "Sorry, I encountered an error fetching the response from Manus."

        messages = data.get("data", {}).get("messages", [])
        agent_status = "running"

        for msg in messages:
            last_seen_cursor = msg.get("id")
            msg_type = msg.get("type")

            if msg_type == "assistant_message":
                content = msg.get("assistant_message", {}).get("content", "")
                if content:
                    result_parts.append(content)

            elif msg_type == "status_update":
                su = msg.get("status_update", {})
                agent_status = su.get("agent_status", "running")

                # If agent is asking a question, treat it as a response
                if agent_status == "waiting":
                    detail = su.get("status_detail", {})
                    if detail.get("waiting_for_event_type") == "messageAskUser":
                        desc = detail.get("waiting_description", "")
                        if desc:
                            result_parts.append(desc)
                        return "\n\n".join(result_parts) if result_parts else "Manus is waiting for your input."

        if agent_status == "stopped":
            log.info("Task %s stopped, collected %d parts", task_id, len(result_parts))
            break
        if agent_status == "error":
            return "Manus encountered an error while processing your request."

        time.sleep(3)

    if result_parts:
        # Truncate to Slack's message limit (~3000 chars to be safe)
        full_text = "\n\n".join(result_parts)
        if len(full_text) > 3000:
            full_text = full_text[:2950] + "\n\n_(Response truncated — ask Manus to continue)_"
        return full_text

    return "Manus did not return a response in time. Please try again."


def post_to_slack(channel: str, text: str) -> bool:
    """Post a message to Slack. Returns True on success."""
    try:
        result = slack_client.chat_postMessage(channel=channel, text=text)
        log.info("Posted message to %s, ts=%s", channel, result.get("ts"))
        return True
    except SlackApiError as e:
        log.error("chat_postMessage failed for channel %s: %s", channel, e)
        return False


# ── Core handler (runs in background thread) ──────────────────────────────────

def handle_message(channel: str, user: str, text: str, bot_user_id: str) -> None:
    """Process an incoming Slack message and reply with Manus's response."""
    # Strip bot mention from text (e.g. "<@U123> hello" → "hello")
    clean_text = text.replace(f"<@{bot_user_id}>", "").strip()
    if not clean_text:
        clean_text = "Hello!"

    log.info("Handling message from %s in %s: %s", user, channel, clean_text[:80])

    # Post a "thinking" indicator immediately
    post_to_slack(channel, ":hourglass_flowing_sand: Thinking... (this may take up to 60 seconds)")

    # Create or continue Manus task
    task_id = conversation_store.get(channel)
    if task_id:
        log.info("Continuing existing task %s for channel %s", task_id, channel)
        manus_send_message(task_id, clean_text)
    else:
        log.info("Creating new task for channel %s", channel)
        task_id = manus_create_task(clean_text)
        if not task_id:
            post_to_slack(channel, "Sorry, I couldn't reach Manus. Please try again.")
            return
        conversation_store[channel] = task_id
        log.info("New Manus task %s for channel %s", task_id, channel)

    # Poll for result
    log.info("Polling for result on task %s", task_id)
    reply = manus_poll_result(task_id)
    log.info("Got reply for task %s, length=%d chars", task_id, len(reply))

    # Post the reply as a fresh message
    post_to_slack(channel, reply)


# ── Slack Events endpoint ─────────────────────────────────────────────────────

@app.route("/slack/events", methods=["POST"])
def slack_events():
    global _bot_user_id

    # Verify Slack signature
    if not verifier.is_valid_request(request.get_data(), request.headers):
        return jsonify({"error": "invalid signature"}), 403

    payload = request.json

    # URL verification challenge (one-time setup)
    if payload.get("type") == "url_verification":
        return jsonify({"challenge": payload["challenge"]})

    event = payload.get("event", {})
    event_id = payload.get("event_id", "")

    # Deduplicate events
    if event_id in processed_events:
        return jsonify({"ok": True})
    processed_events.add(event_id)
    # Keep the set bounded
    if len(processed_events) > 10000:
        processed_events.clear()

    event_type = event.get("type")
    subtype = event.get("subtype")

    # Only handle real user messages (not bot messages, edits, etc.)
    if event_type not in ("message", "app_mention"):
        return jsonify({"ok": True})
    if subtype in ("bot_message", "message_changed", "message_deleted"):
        return jsonify({"ok": True})
    if event.get("bot_id"):
        return jsonify({"ok": True})

    channel = event.get("channel", "")
    user    = event.get("user", "")
    text    = event.get("text", "")

    # Cache bot user ID
    if not _bot_user_id:
        try:
            bot_info = slack_client.auth_test()
            _bot_user_id = bot_info["user_id"]
            log.info("Bot user ID: %s", _bot_user_id)
        except SlackApiError as e:
            log.error("auth_test failed: %s", e)

    # For channel messages, only respond if the bot is mentioned
    channel_type = event.get("channel_type", "")
    if channel_type in ("channel", "group") and _bot_user_id and f"<@{_bot_user_id}>" not in text:
        return jsonify({"ok": True})

    # Run in background so Slack doesn't time out waiting for us
    thread = threading.Thread(
        target=handle_message,
        args=(channel, user, text, _bot_user_id),
        daemon=True
    )
    thread.start()

    return jsonify({"ok": True})


# ── Reset conversation endpoint ───────────────────────────────────────────────

@app.route("/slack/reset", methods=["POST"])
def reset_conversation():
    """Optional: POST {"channel": "C123"} to reset the conversation for a channel."""
    data = request.json or {}
    channel = data.get("channel")
    if channel and channel in conversation_store:
        del conversation_store[channel]
        return jsonify({"ok": True, "message": f"Conversation reset for {channel}"})
    return jsonify({"ok": False, "message": "Channel not found"}), 404


# ── Health check ──────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    log.info("Starting Manus Slack Bot on port %d", port)
    app.run(host="0.0.0.0", port=port)
