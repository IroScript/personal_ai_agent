# 🤖 AI Productivity Agent

একটি intelligent productivity tracking system যা Google Sheets, Ollama Gemma AI এবং Telegram এর সাথে integrate করা।

## ✨ Features

- 📊 **Google Sheets Integration** - Planning এবং Tasklist থেকে data read করে
- 🤖 **AI Analysis** - Ollama Gemma 3 1B model দিয়ে productivity analysis
- 📱 **Telegram Notifications** - Multiple accounts এ automated reports
- 📈 **Tag-based Tracking** - Sleep, Productive activities, Time wasted - সব track করে
- 🎯 **Smart Comparisons** - Planned vs Actual tasks তুলনা করে motivational/strict feedback

## 🚀 Setup

### 1. Install Dependencies
```bash
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client requests
```

### 2. Setup Configuration
Copy `config.example.json` to `config.json` and fill in your credentials:

```bash
cp config.example.json config.json
```

তারপর `config.json` এ এই তথ্য গুলো add করো:
- Google Sheets API credentials
- Spreadsheet ID
- Telegram bot token
- Telegram chat IDs

### 3. Google Sheets Setup
1. Google Cloud Console এ যাও
2. Sheets API enable করো
3. Service Account তৈরি করো
4. Credentials download করো
5. তোমার Google Sheet এ service account email কে Editor access দাও

### 4. Telegram Bot Setup
1. Telegram এ @BotFather কে message করো
2. `/newbot` command দিয়ে bot তৈরি করো
3. Bot token copy করো
4. তোমার bot কে message পাঠাও
5. `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` এ যাও
6. Chat ID copy করো

## 📖 Usage

### Local Testing
```bash
python ai_agent.py --mode analyze
```

### Automatic Scheduling (GitHub Actions)

এই agent automatic run করাতে চাইলে GitHub Actions use করো।

**Setup Guide:** দেখো [`GITHUB_ACTIONS_SETUP.md`](./GITHUB_ACTIONS_SETUP.md)

**Schedule:** দিনে 4 বার automatic run (9 AM, 2 PM, 6 PM, 10 PM)

**Code Update করলে কী হবে?**
- তুমি যেকোনো code change করে `git push` করলে
- পরবর্তী scheduled run এ **automatically নতুন code use হবে!**
- কোনো manual update লাগবে না! ✅

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
- Column A: Serial
- Column B: -
- Column C: Date
- Column D: Task name with tag (e.g., "Sleep (Sleep)")
- Column E: Duration

## 🤝 Contributing

এই project টি personal use এর জন্য তৈরি, কিন্তু improvements এবং suggestions welcome!

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
