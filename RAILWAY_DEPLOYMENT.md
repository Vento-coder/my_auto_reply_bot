# Railway Deployment Guide

## Overview
This bot can be deployed to Railway, but requires specific configuration for persistent storage.

## Important Notes

### Database Storage
Railway's filesystem is **ephemeral** - files are lost on redeploy. You MUST use a persistent volume for the database.

**Recommended**: Use PostgreSQL instead of SQLite for Railway deployment.

## Railway Configuration

### 1. Create a New Project
- Go to [railway.app](https://railway.app)
- Click "New Project" → "Deploy from GitHub repo"
- Select your repository

### 2. Environment Variables

Add these variables in Railway Settings → Variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `API_ID` | Your Telegram API ID | `123456` |
| `API_HASH` | Your Telegram API Hash | `a1b2c3d4...` |
| `BOT_TOKEN` | Bot token from @BotFather | `123456:ABC...` |
| `ENCRYPTION_KEY` | Encryption key (generate new one) | Use: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `OWNER_ID` | Your Telegram User ID | `123456789` |
| `DB_URL` | Database connection string | See below |

### 3. Database Setup (Recommended: PostgreSQL)

#### Option A: Use Railway PostgreSQL (Recommended)
1. In Railway project, click "New Service" → "Database" → "PostgreSQL"
2. Railway will create a PostgreSQL instance
3. Click on the PostgreSQL service → "Variables" tab
4. Copy the `DATABASE_URL` variable
5. In your bot service, add variable:
   - Name: `DB_URL`
   - Value: Paste the PostgreSQL URL (Railway will auto-reference it as `${{Postgres.DATABASE_URL}}`)

#### Option B: Use SQLite with Persistent Volume (Not Recommended)
1. Add a volume to your bot service:
   - Service Settings → "Volumes" → "Add Volume"
   - Mount path: `/data`
2. Change `DB_URL` to: `sqlite:////data/userbot.db`
3. **Warning**: SQLite on Railway with volume can have performance issues

### 4. Build Configuration

Railway should auto-detect Python. If not, add `railway.toml`:

```toml
[build]
builder = "NIXPACKS"

[deploy]
healthcheckPath = "/"
healthcheckTimeout = 300
restartPolicyType = "ON_FAILURE"
```

### 5. Start Command

Railway should auto-detect the start command. If not, add:

```toml
[deploy]
startCommand = "python main.py"
```

## Volume Configuration (If Using SQLite)

If you must use SQLite with a volume:

1. Go to your bot service
2. Settings → Volumes
3. Click "Add Volume"
4. Name: `data`
5. Mount path: `/data`
6. Size: 1GB (minimum)

Then update `.env`:
```
DB_URL=sqlite:////data/userbot.db
```

## Migration Scripts

After deployment, you may need to run migrations. Railway doesn't have a built-in migration runner. Options:

### Option 1: Railway Console
1. Go to your service → "Console" tab
2. Run: `python migrate_add_language.py`
3. Run: `python migrate_add_random_delay.py`
4. Run: `python migrate_add_channels.py`

### Option 2: Add to main.py
Add migration check at startup (recommended for production):

```python
# At the top of main.py, after db initialization
def run_migrations():
    from models import Base
    Base.metadata.create_all(db.engine)
    
    # Check and run specific migrations if needed
    # This is a simplified approach

# Call this before starting the bot
```

## Health Checks

Railway requires a health check. Since this is a bot (not a web server), you can:

1. Disable health checks in Railway settings
2. Or add a simple HTTP endpoint (requires code changes)

## Troubleshooting

### Bot crashes on restart
- **Cause**: Database files lost (ephemeral filesystem)
- **Fix**: Use PostgreSQL or persistent volume

### "Database locked" errors
- **Cause**: SQLite concurrency issues
- **Fix**: Use PostgreSQL instead

### High memory usage
- **Cause**: Multiple Telethon clients
- **Fix**: Limit concurrent users or upgrade Railway plan

## Recommended Railway Plan

- **Free Plan**: Good for testing, but has sleep timeout
- **Starter Plan ($5/month)**: No sleep, better for production
- **Database**: Use Railway PostgreSQL ($5/month included in Starter)

## Final Checklist

- [ ] Add all environment variables
- [ ] Set up PostgreSQL database
- [ ] Update `DB_URL` to use PostgreSQL
- [ ] Run migration scripts via console
- [ ] Test bot functionality
- [ ] Monitor logs in Railway dashboard

## Alternative: Render.com

If Railway doesn't work well, consider Render.com which has better free tier for bots with persistent disks.
