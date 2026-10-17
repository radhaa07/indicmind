# Keep IndicMind awake on Render free tier

Render free web services spin down after ~15 minutes of inactivity.
UptimeRobot (free) pings your app every 5 minutes to keep it awake.

## 1. Deploy first
Get your Render URL, e.g. `https://indicmind.onrender.com`

## 2. Set up UptimeRobot (free)
1. Sign up at https://uptimerobot.com
2. Click **Add New Monitor**
3. Choose **HTTP(s)** monitor type
4. **Friendly name:** IndicMind keep-alive
5. **URL (or IP):** `https://indicmind.onrender.com/health`
6. **Monitoring interval:** 5 minutes
7. Click **Create Monitor**

That's it — UptimeRobot will GET `/health` every 5 minutes, which returns `200 OK` instantly without touching the database or loading heavy models.

## Why `/health`?
- Returns immediately (no DB, no spaCy, no Ollama)
- Won't count against Gemini rate limits
- Safe to hit every 5 minutes, 24/7

## Alternative free uptime monitors
- cron-job.org
- Better Stack Uptime
- HetrixTools
