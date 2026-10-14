# VIKMO DealerDesk

A high-reliability B2B automotive spare parts commerce platform and intelligence engine built with Django, PostgreSQL, and LLM-powered dealer assistance.

---

## ⚡ Quickstart Guide

### 1. Prerequisites
- **Python**: 3.11+
- **PostgreSQL**: 14+
- **pip** and **virtualenv**

---

### 2. Installation

Navigate into the project directory and create a virtual environment:

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Linux/macOS:
source venv/bin/activate
# On Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# On Windows (Git Bash):
source venv/Scripts/activate

# Install required dependencies
pip install -r requirements.txt
```

---

### 3. Environment Configuration

Create a `.env` file from the provided `.env.example`:

```bash
cp .env.example .env
```

Configure your `.env` variables:

| Variable | Description | Default / Example |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection URL | `postgres://postgres:postgres@localhost:5432/dealerdesk` |
| `TRACK` | Assignment track (`aiml` or `django`) | `aiml` |
| `DJANGO_SECRET_KEY` | Django secret key | `dev-secret-key-change-in-prod` |
| `SUPPLIER_API_URL` | Supplier mock API endpoint | `http://127.0.0.1:8099` |
| `SUPPLIER_API_KEY` | Supplier authentication key | `dev-supplier-key` |
| `GEMINI_API_KEY` | *(Optional)* Google Gemini API Key | `AIza...` |
| `OPENAI_API_KEY` | *(Optional)* OpenAI API Key | `sk-...` |
| `ANTHROPIC_API_KEY`| *(Optional)* Anthropic API Key | `sk-ant-...` |
| `GROQ_API_KEY` | *(Optional)* Groq Cloud API Key | `gsk_...` |

> **Note**: If no external LLM key is set, the assistant runs in offline grounded mode using the local database.

---

### 4. Database Setup & Data Seeding

Ensure your PostgreSQL service is running and the database (e.g. `dealerdesk`) is created, then run:

```bash
# Apply schema migrations
python manage.py migrate

# Seed initial catalogue (600 SKUs) and dealers (25 dealers)
python manage.py seed_data
```

---

### 5. Running the Application

#### A. Start the Mock Supplier Service (Terminal 1)
```bash
python supplier_mock/mock_supplier.py
```
*Runs at `http://127.0.0.1:8099`.*

#### B. Start the Django Server (Terminal 2)
```bash
python manage.py runserver
```
*Access the Web Dashboard & API at `http://127.0.0.1:8000/`.*

---

### 6. Demand Forecasting (ML Pipeline)

To train the demand forecasting model and generate 4-week reorder recommendations:

```bash
python ml/train_forecast.py
```
*Generates predictions saved to `ml/forecast.csv`.*

---

### 7. Running Tests & Smoke Tests

Ensure both the supplier mock and Django server are running, then execute:

```bash
# Run contract smoke test suite
python smoke_test.py --base-url http://localhost:8000 --all

# Run Django unit and concurrency test suite
python manage.py test
```

---

## 📁 Project Structure

```text
├── core/                # Django app (models, views, serializers, services)
│   ├── services/        # Order, assistant, sync & forecasting services
├── data/                # Seed CSV datasets (catalogue, dealers, sales history)
├── dealerdesk/          # Project settings & URL routing
├── ml/                  # ML forecasting pipeline & training scripts
├── static/              # Dashboard frontend styles (CSS) & scripts (JS)
├── supplier_mock/       # Supplier API mock service
├── templates/           # Dashboard HTML interface
├── manage.py            # Django management CLI
├── requirements.txt     # Python package requirements
├── smoke_test.py        # Automated contract verification script
├── API_CONTRACT.md      # Detailed API specification
└── DECISIONS.md         # Architectural decisions and justifications
```
