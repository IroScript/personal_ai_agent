# 🤖 AI Productivity Agent

An intelligent productivity tracking system integrated with Google Sheets, Ollama Gemma AI, and Telegram.

## ✨ Features

- 📊 **Google Sheets Integration** - Reads data from planning and tasklist sheets
- 🤖 **AI Analysis** - Productivity analysis powered by Ollama Gemma 3 1B model (and online providers fallback)
- 📱 **Telegram Notifications** - Automated reports sent to multiple accounts/chat IDs
- 📈 **Tag-based Tracking** - Tracks sleep, productive activities, and time wasted
- 🎯 **Smart Comparisons** - Compares planned vs actual tasks to provide motivational/strict feedback

## 🚀 Setup

### 1. Install Dependencies
```bash
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client requests schedule
```

### 2. Setup Configuration
Copy `config.example.json` to `config.json` and fill in your credentials:

```bash
cp config.example.json config.json
```

Then add the following information in `config.json`:
- Google Sheets API credentials
- Spreadsheet ID
- Telegram bot token
- Telegram chat IDs

### 3. Google Sheets Setup
1. Go to Google Cloud Console
2. Enable the Sheets API
3. Create a Service Account
4. Download the credentials JSON file
5. Share your Google Sheet with the service account email giving it Editor access

### 4. Telegram Bot Setup
1. Message @BotFather on Telegram
2. Create a new bot using the `/newbot` command
3. Copy the Bot token
4. Message your bot
5. Go to `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
6. Copy your Chat ID

## 📖 Usage

### Local Testing
```bash
python ai_agent.py --mode analyze
```

### Automatic Scheduling (GitHub Actions)

If you want to run this agent automatically, use GitHub Actions.

**Setup Guide:** See [`GITHUB_ACTIONS_SETUP.md`](./GITHUB_ACTIONS_SETUP.md)

**Schedule:** Automatically runs 4 times a day (9 AM, 2 PM, 6 PM, 10 PM Bangladesh Time)

**What happens when you update code?**
- Whenever you make changes to the code and do `git push`
- The next scheduled run will **automatically use the new code!**
- No manual server updates required! ✅

## 📁 File Structure

```
Agent_AI/
├── ai_agent.py           # Main program
├── config.json           # Your private configuration (not in git)
├── config.example.json   # Example configuration template
├── README.md            # This file
└── .gitignore          # Git ignore rules
```

## 🔧 Configuration Structure

### Google Sheets Structure

**TASKS_PLAN Sheet:**
- Column A: Serial number
- Column B: Task name
- Column C: Tag
- Column D: Target time (minutes)
- Column E: Frequency
- Column F: Description
- Column G: When (Today/Weekly)

**TASKLIST Sheet:**
- Column C: Date
- Column D: Task name with tag in brackets (e.g., "Sleeping (Sleep)")
- Column F: Start time
- Column G: End time
- Column J: Duration in decimal hours (calculated by formula)

## 🤝 Contributing

This project is built for personal use, but improvements and suggestions are welcome!

## 📝 License

Personal project - use at your own discretion.

## 🙏 Credits

Built with:
- Python
- Google Sheets API
- Ollama Gemma 3 1B
- Telegram Bot API

---
**Made with ❤️ for better productivity tracking**
