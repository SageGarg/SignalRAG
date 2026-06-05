# SignalRAG

> An AI-powered RAG (Retrieval-Augmented Generation) platform for traffic signal research, NCHRP clearinghouse data, and related datasets.

---

## Project Structure

```
signalRAG/
├── backend/
│   ├── app/
│   │   ├── main.py              # Flask app entry point
│   │   ├── routes/              # Blueprint route handlers
│   │   │   ├── nchrp.py
│   │   │   ├── nchrp_sql.py
│   │   │   ├── bdib.py
│   │   │   └── signalverse.py
│   │   ├── services/            # Business logic
│   │   │   ├── llm.py           # LLM / vectorstore / RAG pipeline
│   │   │   └── db.py            # MySQL connection factory
│   │   ├── models/              # Data models / schemas (future)
│   │   └── utils/               # Shared helper functions (future)
│   ├── requirements.txt
│   └── .env.example
│
├── frontend/
│   ├── src/
│   │   ├── pages/               # Jinja2 HTML templates
│   │   ├── components/          # Reusable HTML partials (future)
│   │   ├── assets/
│   │   │   ├── css/             # Tailwind output + custom CSS
│   │   │   ├── js/              # Client-side scripts
│   │   │   └── images/          # Static images / icons
│   │   ├── services/
│   │   │   └── api.js           # Centralized API service layer
│   │   └── utils/               # Frontend utility functions (future)
│   ├── public/                  # Public static files (favicon, etc.)
│   ├── package.json
│   └── .env.example
│
├── docs/
│   └── architecture.md          # System design and architecture notes
│
├── README.md
├── .gitignore
└── docker-compose.yml           # (optional) containerized deployment
```

---

## Tech Stack

| Layer      | Technology                                       |
|------------|--------------------------------------------------|
| Backend    | Python 3.10+, Flask 3.0, LangChain, ChromaDB    |
| LLM        | OpenAI GPT-4o, text-embedding-ada-002           |
| Database   | MySQL (local / AWS RDS)                          |
| Frontend   | HTML, Vanilla CSS, Tailwind CSS, Vanilla JS      |
| Hosting    | AWS EC2 (backend), AWS Amplify (frontend)        |

---

## Prerequisites

- Python ≥ 3.10
- Node.js ≥ 14.0
- MySQL (local or remote)
- OpenAI API key

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/SageGarg/SignalRAG.git
cd SignalRAG
```

### 2. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Create your .env from the example
cp .env.example .env
# → Fill in OPENAI_API_KEY, DB_PASSWORD, FLASK_SECRET_KEY, etc.
```

### 3. Frontend (Tailwind build)

```bash
cd frontend
npm install
npm run tailwind     # watches and rebuilds output.css on changes
```

### 4. Run the application

```bash
# From backend/
python app/main.py
```

Access the app at `http://localhost:5000`.

---

## Environment Variables

All secrets live in `.env` files — **never commit real `.env` files**.  
See `backend/.env.example` and `frontend/.env.example` for the required variables.

| Variable              | Description                                    |
|-----------------------|------------------------------------------------|
| `OPENAI_API_KEY`      | OpenAI API key                                 |
| `AWS_ACCESS_KEY_ID`   | AWS credentials for S3 / other services        |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key                               |
| `DB_HOST`             | MySQL host (default: `localhost`)              |
| `DB_USER`             | MySQL username                                 |
| `DB_PASSWORD`         | MySQL password                                 |
| `DB_NAME_SIGNALVERSE` | DB name for SignalVerse module                 |
| `DB_NAME_BDIB`        | DB name for BDIB module                        |
| `DB_NAME_NCHRP`       | DB name for NCHRP module                       |
| `FLASK_SECRET_KEY`    | Flask session secret                           |
| `FLASK_DEBUG`         | `true` / `false`                               |
| `ALLOWED_EMAILS`      | Comma-separated list of authorized user emails |

---

## Deployment

### Backend — AWS EC2

1. SSH into your EC2 instance.
2. Install Python, pip, and MySQL.
3. Clone the repo and set up the virtual environment.
4. Copy `.env.example` → `.env` and fill in production values.
5. Run with `gunicorn` behind `nginx`:

```bash
gunicorn -w 4 -b 0.0.0.0:5000 "app.main:app"
```

### Frontend — AWS Amplify

1. Connect your GitHub repository to AWS Amplify.
2. Set build output directory to `frontend/src/assets/css`.
3. Add environment variables (`VITE_API_BASE_URL`, etc.) in the Amplify console.
4. Amplify auto-deploys on every push to `main`.

### Local Development

```bash
# Terminal 1 — backend
cd backend && python app/main.py

# Terminal 2 — Tailwind watcher
cd frontend && npm run tailwind
```

---

## Modules

| Module       | URL Prefix    | Description                                              |
|--------------|---------------|----------------------------------------------------------|
| SignalVerse  | `/`           | General traffic signal RAG chatbot                      |
| BDIB         | `/bdib_bp`    | Before/During/In the Beginning knowledge assistant      |
| NCHRP        | `/nchrp_bp`   | NCHRP clearinghouse PDF + Excel data explorer           |

---

## Security Notes

- `.env` is in `.gitignore` — **never push it**.
- The `.pem` key file (`signalverse.pem`) is also gitignored.
- `ALLOWED_EMAILS` gates access to the NCHRP module.
- All API keys must be rotated if accidentally exposed.
