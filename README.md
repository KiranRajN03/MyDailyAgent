# 🚀 Engineering Manager Platform v2.0

> **myDailyAgent** — A production-grade, multi-tenant engineering management system with AI-powered agents, REST API, and database persistence.

## Features

- 🤖 **AI Agents** — Data Analyst, Automation, Jira Status, and Engineering Manager agents powered by LangGraph + LangChain
- 📊 **Sprint Analytics** — Automated sprint performance tracking and reporting
- 📅 **Meeting Management** — Recurring meetings, calendar invites, transcription, and summarization
- 👥 **Team Management** — Multi-tenant projects with RBAC (Admin, Manager, Team Lead, Member)
- 🔒 **Enterprise Security** — JWT auth, bcrypt hashing, Fernet field-level encryption
- 📧 **Email Notifications** — HTML emails with .ics calendar attachments
- 🔗 **Integrations** — Jira Cloud, Microsoft Teams, Azure Cognitive Services, OpenAI

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Web Framework | FastAPI |
| Database | SQLite (dev) / PostgreSQL (prod) |
| ORM | SQLAlchemy 2.0 |
| AI | LangGraph, LangChain, GPT-4o / Claude |
| Auth | JWT (PyJWT), bcrypt |
| Encryption | Fernet (cryptography) |

## Quick Start

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your keys

# 4. Run the server
python -m daily_agents.api.server

# 5. Open API docs
open http://localhost:8000/docs
```

## Project Structure

```
myDailyAgent/
├── daily_agents/
│   ├── config/          # Settings & environment config
│   ├── database/        # Models, encryption, DB config
│   ├── api/             # FastAPI routes & middleware
│   ├── agents/          # AI agents (LangGraph)
│   ├── services/        # Business logic services
│   ├── integrations/    # External API clients
│   ├── tools/           # Agent tools
│   └── graph.py         # LangGraph orchestration
├── tests/               # Test suite
├── requirements.txt
└── .env.example
```

## Development Status

- [x] **Phase 1** — Foundation & Data Model
- [x] **Phase 2** — Authentication & RBAC
- [x] **Phase 3** — Core API Endpoints (CRUD)
- [x] **Phase 4** — AI Agents & LangGraph Orchestration
- [x] **Phase 5** — External Integrations & Bot Logic
