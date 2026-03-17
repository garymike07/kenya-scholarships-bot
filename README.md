# Kenya Scholarships Bot

An automated Telegram bot that scrapes **unlimited scholarships, grants, and funding opportunities** for Kenyan citizens from around the globe every hour. Each opportunity is summarized in simple English using AI and posted directly to your Telegram channel.

**No hosting required** — runs for free on GitHub Actions.

---

## Features

- **10 scholarship sources** scraped with unlimited pagination:
  - scholars4dev.com — Scholarships for Kenyans, Africa, developing countries
  - opportunitiesforafricans.com — Scholarships, fellowships, grants for Africa
  - scholarshipskenya.com — Kenya-specific scholarship portal
  - afterschoolafrica.com — African student opportunities
  - scholarshipsads.com — Fully funded scholarships for Kenyan students
  - advance-africa.com — Scholarships in USA, UK, Canada, Germany, Australia
  - fundsforngos.org — NGO and non-profit funding
  - grants.gov — US federal grants
  - openphilanthropy.org — Philanthropy grants
  - NSF RSS feeds — Science and research funding

- **Deep detail scraping** — follows every link to extract:
  - Deadline
  - Eligibility criteria
  - Benefits and award amount
  - Host country
  - Study level (Bachelors, Masters, PhD, Fellowship)

- **AI summaries** — uses free Nvidia/Meta/Google/Mistral models via OpenRouter to rewrite each opportunity in plain English

- **3 categories**: Student Scholarships, Business Grants, Non-Profit Funding

- **Telegram bot commands**:
  - `/start` — Welcome message
  - `/browse` — Browse by category
  - `/latest` — Latest opportunities
  - `/scholarships` — Student scholarships
  - `/grants` — Business grants
  - `/nonprofit` — Non-profit funding
  - `/search <keyword>` — Search opportunities (e.g., `/search DAAD`)
  - `/premium` — Upgrade info
  - `/stats` — Bot statistics

- **Paywall system** — Free users get 3 views/day, premium users get unlimited access

- **Auto-restart** — crash recovery with `run.sh`

---

## Quick Setup

### 1. Set GitHub Secrets

Go to your repo **Settings → Secrets and variables → Actions** and add:

| Secret | Value |
|--------|-------|
| `OPENROUTER_API_KEY` | Your OpenRouter API key (free at openrouter.ai) |
| `TELEGRAM_TOKEN` | Your Telegram bot token from @BotFather |
| `TELEGRAM_CHANNEL_ID` | Your Telegram channel ID (e.g., `-1001234567890`) |

### 2. Enable GitHub Actions

The scraper runs automatically **every hour** via `.github/workflows/scrape.yml`.
You can also trigger it manually from the Actions tab.

### 3. (Optional) Run Locally

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/kenya-scholarships-bot.git
cd kenya-scholarships-bot

# Install dependencies
pip install -r requirements.txt

# Create .env file
cat > .env << EOF
OPENROUTER_API_KEY=your_key_here
TELEGRAM_TOKEN=your_token_here
TELEGRAM_CHANNEL_ID=your_channel_id_here
EOF

# Run the bot
python3 main.py

# Or use the auto-restart wrapper
chmod +x run.sh
./run.sh
```

---

## Deployment Options (Free)

| Platform | Type | Setup |
|----------|------|-------|
| **GitHub Actions** | Hourly scraper | Already configured — just push and set secrets |
| **Render.com** | 24/7 bot | Connect repo → deploy as Worker service |
| **Railway.app** | 24/7 bot | Connect repo → auto-deploy |
| **Docker** | Anywhere | `docker build -t grants-bot . && docker run grants-bot` |

---

## Project Structure

```
kenya-scholarships-bot/
├── main.py                    # Entry point — bot + scheduler
├── scrape_and_post.py         # Standalone script for GitHub Actions
├── config.py                  # Configuration and categories
├── run.sh                     # Auto-restart wrapper
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Docker deployment
├── render.yaml                # Render.com config
├── Procfile                   # Heroku/Railway config
├── scrapers/
│   ├── base.py                # Base scraper with rate limiting + rotating user agents
│   ├── scholars4dev.py        # scholars4dev.com scraper
│   ├── opportunitiesforafricans.py
│   ├── scholarshipskenya.py
│   ├── afterschoolafrica.py
│   ├── scholarshipsads.py
│   ├── advance_africa.py
│   ├── fundsforngos.py
│   ├── grants_gov.py
│   ├── grantwatch.py
│   ├── scholarships_com.py
│   ├── open_philanthropy.py
│   ├── rss_feeds.py
│   └── detail_scraper.py     # Deep scraper — follows links for full details
├── services/
│   ├── database.py            # SQLite database
│   ├── summarizer.py          # AI summarization via OpenRouter
│   ├── categorizer.py         # Auto-categorization
│   ├── scrape_engine.py       # Orchestrates all scrapers
│   └── telegram_bot.py        # Telegram bot handlers
└── .github/
    └── workflows/
        ├── scrape.yml         # Hourly scrape + post (GitHub Actions)
        └── bot.yml            # Hosting info
```

---

## How It Works

1. **Every hour**, GitHub Actions triggers `scrape_and_post.py`
2. All 10 scrapers run with **unlimited pagination** — no caps
3. Each new opportunity's URL is visited to extract full details (deadline, eligibility, benefits, country, study level)
4. AI summarizes the opportunity in 2-3 simple sentences
5. New opportunities are posted to your Telegram channel with full info + apply link
6. Users interact with the bot via commands to browse, search, and filter

---

## License

MIT
