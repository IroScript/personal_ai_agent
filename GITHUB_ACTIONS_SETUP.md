# 🚀 GitHub Actions Setup Guide

এই guide follow করে তুমি GitHub Actions এ AI agent automatic run করাতে পারবে।

## 📋 Step-by-Step Setup

### Step 1: GitHub Repository তে যাও
```
https://github.com/IroScript/personal_ai_agent
```

### Step 2: Repository Secrets Add করো

1. Repository page এ যাও
2. **Settings** > **Secrets and variables** > **Actions** এ ক্লিক করো
3. **New repository secret** button ক্লিক করো

#### Secret Name: `CONFIG_JSON`

**Value:** তোমার `config.json` file এর পুরো content copy করে paste করো

```json
{
  "google_sheets": {
    "spreadsheet_id": "1q5FYRmURurN5RX5E8cIht6YR9x6VSSNlcsWOx45UCko",
    ...পুরো config...
  }
}
```

⚠️ **Important:** পুরো `config.json` content একবারে paste করো!

### Step 3: Code Push করো

```bash
cd C:\Users\Irak\Desktop\Agent_AI
git add .
git commit -m "Add GitHub Actions workflow for automatic scheduling"
git push origin main
```

### Step 4: Verify Setup

1. GitHub repository এ যাও
2. **Actions** tab click করো
3. "AI Productivity Agent" workflow দেখতে পাবে
4. Manual test করতে:
   - Workflow select করো
   - **Run workflow** button click করো
   - Branch: `main` select করো
   - **Run workflow** click করো

---

## ⏰ Schedule Details

Workflow **দিনে 4 বার** automatic run হবে:

| Time (UTC) | Bangladesh Time | Purpose |
|------------|----------------|---------|
| 3:30 AM | 9:00 AM | Morning planning |
| 8:30 AM | 2:00 PM | Afternoon check |
| 12:30 PM | 6:00 PM | Evening review |
| 4:30 PM | 10:00 PM | Night summary |

### ⏱️ Timezone Adjust করতে:

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

## 🔄 Code Update করলে কী হবে?

### ✅ **Automatic Update!**

যখনই তুমি code update করে push করবে, GitHub Actions **automatically** নতুন code ব্যবহার করবে!

**Process:**

1. তুমি local এ code edit করো
2. Git commit + push করো:
   ```bash
   git add .
   git commit -m "Updated AI analysis logic"
   git push origin main
   ```
3. **পরবর্তী scheduled run এ নতুন code automatic use হবে!**

**Example Timeline:**
```
10:00 AM - তুমি code update করলে
10:05 AM - GitHub এ push করলে
2:00 PM - Next scheduled run → ✅ New code automatically used!
```

### 🔧 Config Update করলে?

যদি **শুধু config.json** update করো (API keys, settings etc):

**Option A: Quick Update (Recommended)**
1. GitHub এ যাও: Settings > Secrets > Actions
2. `CONFIG_JSON` secret edit করো
3. নতুন config paste করো
4. ✅ পরবর্তী run এই নতুন config use করবে

**Option B: Via Code Push**
1. Local এ `config.json` update করো
2. Git push করো (কিন্তু `.gitignore` এ আছে তাই push হবে না)
3. Manually secret update করতে হবে

⚠️ **Important:** `config.json` git এ যায় না (security জন্য), তাই config change করলে GitHub Secret manually update করতে হবে।

---

## 🧪 Manual Testing

যেকোনো সময় manual test করতে পারো:

1. GitHub > Actions tab
2. "AI Productivity Agent" workflow select
3. **Run workflow** button
4. **Run workflow** confirm
5. Workflow execution দেখতে পাবে

---

## 📊 Monitor Workflow

### Workflow Status দেখতে:
```
https://github.com/IroScript/personal_ai_agent/actions
```

### Log দেখতে:
1. Actions tab > Latest workflow run click করো
2. "run-agent" job click করো
3. প্রতিটা step এর detailed log দেখবে

---

## ❓ Troubleshooting

### ❌ Workflow Failed?

**Check করো:**

1. **Secrets:** `CONFIG_JSON` ঠিকমতো set আছে কিনা
2. **API Keys:** Groq/Gemini API keys valid কিনা
3. **Logs:** Actions tab এ error message পড়ো

### 🔍 Common Issues:

**Issue 1: "config.json not found"**
- Solution: `CONFIG_JSON` secret add করো

**Issue 2: "API key invalid"**
- Solution: Config এ API key ঠিক আছে কিনা check করো

**Issue 3: "Sheet access denied"**
- Solution: Service account email কে sheet এ access দিয়েছো কিনা check করো

---

## 💡 Pro Tips

### 1. **Test Before Scheduling**
প্রথমবার setup করার পর manual run করে test করো:
```
Actions > Run workflow > Run workflow
```

### 2. **Monitor First Few Runs**
প্রথম ২-৩ দিন logs check করো সব ঠিক আছে কিনা

### 3. **Adjust Schedule as Needed**
যদি frequency বাড়াতে বা কমাতে চাও, `.github/workflows/productivity-agent.yml` edit করো

### 4. **Backup Config**
`config.json` এর একটা backup রাখো (local এ, password protected folder এ)

---

## ✅ Setup Checklist

- [ ] GitHub repository তে code push করেছি
- [ ] `CONFIG_JSON` secret add করেছি
- [ ] Workflow file (`.github/workflows/productivity-agent.yml`) আছে
- [ ] Manual test করে দেখেছি কাজ করছে
- [ ] Schedule timing ঠিক আছে (timezone adjust করেছি)
- [ ] First scheduled run এর পর notification পেয়েছি

---

## 🎯 Summary

✅ **Code update:** শুধু git push করো → Automatic update  
✅ **Config update:** GitHub Secret manually update করো  
✅ **Schedule:** দিনে 4 বার automatic run  
✅ **Cost:** সম্পূর্ণ ফ্রি! (GitHub Actions free tier: 2000 min/month)  
✅ **Monitoring:** Actions tab এ সব logs দেখতে পাবে  

---

**Questions?** GitHub Actions logs check করো বা এই file reference করো! 🚀
