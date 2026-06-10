# Manus Slack Bot

A lightweight Slack bot that bridges your Slack workspace to the [Manus AI API](https://manus.ai). 
With this bot, you can chat with Manus directly from Slack by sending it a direct message or mentioning it in a channel.

## Features

- **Direct Messages**: Chat with Manus 1-on-1 in a DM.
- **Channel Mentions**: Mention `@Manus` in any channel to get a response.
- **Conversation Memory**: Remembers the context of your conversation within a specific channel or DM thread.
- **Background Processing**: Handles Manus's thinking time gracefully without timing out Slack.

## Setup Instructions

To get this running, you need to do three things:
1. Create a Slack App in your workspace.
2. Deploy this code to a hosting provider (like Render or Railway).
3. Connect the Slack App to your deployed server.

---

### Step 1: Create the Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App**.
2. Choose **From scratch**, give it a name (e.g., "Manus"), and select your workspace.
3. In the left sidebar, go to **OAuth & Permissions**.
4. Scroll down to **Scopes** → **Bot Token Scopes** and add these three scopes:
   - `app_mentions:read` (Allows the bot to see when it's mentioned)
   - `chat:write` (Allows the bot to send messages)
   - `im:history` (Allows the bot to read direct messages)
5. Scroll up to the top of the **OAuth & Permissions** page and click **Install to Workspace**.
6. Once installed, copy the **Bot User OAuth Token** (it starts with `xoxb-`). You will need this later.
7. Go to **Basic Information** in the left sidebar.
8. Scroll down to **App Credentials** and click "Show" next to **Signing Secret**. Copy this secret. You will need it later.

---

### Step 2: Deploy the Server

You can deploy this code for free on [Render](https://render.com) or [Railway](https://railway.app). 

**Prerequisite:** Push this code folder to a new GitHub repository.

#### Option A: Deploy on Render (Recommended)
1. Go to [Render](https://dashboard.render.com/) and create a new **Web Service**.
2. Connect your GitHub repository.
3. Render will automatically detect the `render.yaml` file in this repository and configure the build/start commands.
4. Under **Environment Variables**, add the following three keys:
   - `MANUS_API_KEY`: Your Manus API key (e.g., `sk-...`)
   - `SLACK_BOT_TOKEN`: The token from Step 1 (starts with `xoxb-`)
   - `SLACK_SIGNING_SECRET`: The secret from Step 1
5. Click **Create Web Service**.
6. Once deployed, copy your app's public URL (e.g., `https://manus-bot-abc.onrender.com`).

#### Option B: Deploy on Railway
1. Go to [Railway](https://railway.app/) and click **New Project** → **Deploy from GitHub repo**.
2. Select your repository.
3. Railway will detect the `railway.json` and `Procfile`.
4. Go to the **Variables** tab and add:
   - `MANUS_API_KEY`: Your Manus API key
   - `SLACK_BOT_TOKEN`: Your Slack Bot Token
   - `SLACK_SIGNING_SECRET`: Your Slack Signing Secret
5. Go to the **Settings** tab, scroll down to **Networking**, and click **Generate Domain**.
6. Copy the generated domain URL.

---

### Step 3: Connect Slack to Your Server

Now that your server is running, you need to tell Slack where to send the messages.

1. Go back to your app settings at [api.slack.com/apps](https://api.slack.com/apps).
2. In the left sidebar, click **Event Subscriptions**.
3. Toggle **Enable Events** to **On**.
4. In the **Request URL** field, paste your deployed server's URL and append `/slack/events` to the end.
   - *Example:* `https://manus-bot-abc.onrender.com/slack/events`
   - Slack will verify the URL immediately. It should say "Verified" in green.
5. Scroll down to **Subscribe to bot events** and click **Add Bot User Event**.
6. Add these two events:
   - `app_mention`
   - `message.im`
7. Click **Save Changes** at the bottom of the page.
8. Slack will prompt you with a yellow banner at the top saying you need to reinstall your app. Click **reinstall your app**.

### Step 4: Start Chatting!

You're done! 
- Go to Slack, find the "Manus" bot under the **Apps** section in the sidebar, and send it a direct message.
- Or, invite the bot to a channel (type `/invite @Manus`) and tag it: `@Manus hello!`
