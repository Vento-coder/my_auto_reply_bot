# Telegram Userbot Bot

Multi-language Telegram bot with userbot functionality for auto-reply.

## Features

- **Multi-language Support**: Uzbek, Russian, English, Turkish, Kazakh
- **Admin Panel**: User management, ban/unban, admin management
- **Mandatory Channels**: Require users to subscribe to channels before using the bot
- **Auto-Reply**: Reply to specific users automatically with buffer text
- **Random Delay**: Optional random delay for replies (±20% of set delay)
- **Buffer System**: Store and manage reply text
- **Speed Control**: Adjustable reply delay (0.04s - 0.5s)

## Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with your values
   ```

## Configuration (.env)

Required environment variables:
- `API_ID`: Your Telegram API ID (from my.telegram.org)
- `API_HASH`: Your Telegram API Hash (from my.telegram.org)
- `BOT_TOKEN`: Your Telegram Bot Token (from @BotFather)
- `ENCRYPTION_KEY`: Random encryption key for session storage
- `DB_URL`: Database URL (default: sqlite:///userbot.db)
- `OWNER_ID`: Telegram User ID of the bot owner (admin)

## Running

```bash
python main.py
```

## User Flow

1. User starts bot with `/start`
2. Selects language
3. Subscribes to mandatory channels (if configured)
4. Waits for admin approval
5. Connects Telegram account (phone → code → 2FA)
6. Uses bot features

## Admin Commands

- `/admin` - Open admin panel
- `/ban <user_id|@username>` - Ban user
- `/unban <user_id|@username>` - Unban user
- `/add_admin <user_id|@username>` - Add admin
- `/del_admin <user_id|@username>` - Remove admin

## Admin Panel Features

- View all users
- View banned users
- View admins
- Manage mandatory channels (add/remove)
- View user details
- Edit user buffer
- Toggle ban status
- Add/remove admin status

## Bot Features

- **Buffer**: Store text for auto-reply
- **Auto-Reply**: Reply to specific users automatically
- **Speed Control**: Adjust reply delay
- **Random Delay**: Toggle random delay variation
- **Language Selection**: Change bot language anytime

## Userbot Commands (in Telegram)

- `.bufer` - Send buffer text to chat
- `.bufer` (reply to message) - Set auto-reply to that user
- `.stop` - Stop auto-reply in current chat

## Security Notes

- Sessions are encrypted before storage
- Never share session files or `.env` file
- Each user connects their own Telegram account
- Bot does not collect other people's credentials

## Database Migrations

Run migration scripts when updating:
```bash
python migrate_add_language.py
python migrate_add_random_delay.py
python migrate_add_channels.py
```

## License

Use responsibly. Respect Telegram's Terms of Service.
