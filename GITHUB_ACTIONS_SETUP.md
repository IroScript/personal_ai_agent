# 🚀 GitHub Actions Setup Guide

Follow this guide to set up automatic runs for your AI agent using GitHub Actions.

## 📋 Step-by-Step Setup

### Step 1: Go to your GitHub Repository
```
https://github.com/IroScript/personal_ai_agent
```

### Step 2: Add Repository Secrets

1. Go to your repository page on GitHub.
2. Click on **Settings** > **Secrets and variables** > **Actions**.
3. Click the **New repository secret** button.

#### Secret Name: `CONFIG_JSON`

**Value:** Copy the entire content of your local `config.json` file and paste it here.

```json
{
  "google_sheets": {
    "spreadsheet_id": "1q5FYRmURurN5RX5E8cIht6YR9x6VSSNlcsWOx45UCko",
    ...full config...
  }
}
```

⚠️ **Important:** Paste the entire `config.json` content all at once!

### Step 3: Push Your Code

```bash
cd C:\Users\Irak\Desktop\Agent_AI
git add .
git commit -m "Add GitHub Actions workflow for automatic scheduling"
git push origin main
```

### Step 4: Verify the Setup

1. Go to your GitHub repository.
2. Click on the **Actions** tab.
3. You should see the "AI Productivity Agent" workflow.
4. To test manually:
   - Select the workflow.
   - Click the **Run workflow** dropdown button.
   - Select Branch: `main`.
   - Click the green **Run workflow** button.

---

## ⏰ Schedule Details

The workflow will run automatically **4 times a day**:

| Time (UTC) | Bangladesh Time | Purpose |
|------------|----------------|---------|
| 3:30 AM | 9:00 AM | Morning planning |
| 8:30 AM | 2:00 PM | Afternoon check |
| 12:30 PM | 6:00 PM | Evening review |
| 4:30 PM | 10:00 PM | Night summary |

### ⏱️ To Adjust Timezone:

File: `.github/workflows/productivity-agent.yml`

```yaml
- cron: '30 3 * * *'   # 9:00 AM Bangladesh = 3:30 AM UTC
```

**Formula:** Bangladesh Time - 5:30 = UTC Time

Example:
- 9:00 AM BD → 3:30 AM UTC
- 2:00 PM BD (14:00) → 8:30 AM UTC
- 6:00 PM BD (18:00) → 12:30 PM UTC

---

## 🔄 What happens when you update code?

### ✅ **Automatic Update!**

Whenever you update your code locally and push it to GitHub, GitHub Actions will **automatically** use your latest code!

**Process:**

1. Edit the code locally.
2. Commit and push the changes:
   ```bash
   git add .
   git commit -m "Updated AI analysis logic"
   git push origin main
   ```
3. **The next scheduled run will automatically use the new code!**

**Example Timeline:**
```
10:00 AM - You update the code locally
10:05 AM - You push it to GitHub
2:00 PM - Next scheduled run → ✅ New code automatically used!
```

### 🔧 What if you update config.json?

If you **only change settings inside config.json** (such as API keys, chat IDs, etc.):

**Option A: Quick Update (Recommended)**
1. Go to GitHub: Settings > Secrets > Actions
2. Edit the `CONFIG_JSON` secret
3. Paste the new config details
4. ✅ The next run will immediately use this new config

**Option B: Via Code Push**
1. Update `config.json` locally
2. Try pushing (but since it is ignored in `.gitignore`, it will not push)
3. You must update the secret manually on GitHub

⚠️ **Important:** `config.json` is not tracked by Git for security reasons. Therefore, when you update config settings, you must manually update the GitHub Secret.

---

## 🧪 Manual Testing

You can run manual tests at any time:

1. GitHub > Actions tab
2. Select "AI Productivity Agent" workflow
3. Click the **Run workflow** button
4. Confirm **Run workflow**
5. Monitor the workflow execution details

---

## 📊 Monitor Workflow

### To view Workflow Status:
```
https://github.com/IroScript/personal_ai_agent/actions
```

### To view logs:
1. Click the latest workflow run inside the Actions tab.
2. Click the "run-agent" job.
3. Review the detailed logs for each step.

---

## ❓ Troubleshooting

### ❌ Workflow Failed?

**Please check:**

1. **Secrets:** Make sure `CONFIG_JSON` is set up correctly.
2. **API Keys:** Make sure Groq/Gemini API keys are valid.
3. **Logs:** Read the error messages in the Actions tab.

### 🔍 Common Issues:

**Issue 1: "config.json not found"**
- Solution: Add the `CONFIG_JSON` secret to your repository.

**Issue 2: "API key invalid"**
- Solution: Verify that the API keys inside your config details are correct.

**Issue 3: "Sheet access denied"**
- Solution: Check if you shared your Google Sheet with the service account email and granted Editor permission.

---

## 💡 Pro Tips

### 1. **Test Before Scheduling**
After setting up for the first time, trigger a manual run to test:
```
Actions > Run workflow > Run workflow
```

### 2. **Monitor First Few Runs**
Check the logs of the first 2-3 runs to ensure everything behaves as expected.

### 3. **Adjust Schedule as Needed**
To change how often or when the agent runs, edit `.github/workflows/productivity-agent.yml`.

### 4. **Backup Config**
Keep a local backup of `config.json` in a safe, password-protected directory.

---

## ✅ Setup Checklist

- [ ] Code pushed to GitHub repository
- [ ] `CONFIG_JSON` secret added
- [ ] Workflow file (`.github/workflows/productivity-agent.yml`) exists
- [ ] Manual test verified and working
- [ ] Schedule timing set correctly (timezone adjusted)
- [ ] Received Telegram notification after the first run

---

## 🎯 Summary

✅ **Code update:** Just run git push → Automatic update  
✅ **Config update:** Manually update the GitHub Secret  
✅ **Schedule:** Automatically runs 4 times a day  
✅ **Cost:** 100% Free! (GitHub Actions free tier provides 2000 min/month)  
✅ **Monitoring:** Access all execution logs in the Actions tab  

---

**Questions?** Check GitHub Actions logs or refer to this setup file! 🚀
