# nalaris-book-keeping
Here is a highly professional, engaging, and "startup-ready" `README.md` for your GitHub repository. It highlights the massive enterprise value of what you've built, making it irresistible to developers, investors, or collaborators.

```markdown
# 🌌 Nalaris 
> **The Intelligent Enterprise FinOps & AI Bookkeeping Platform**

![Python](https://img.shields.io/badge/Python-3.12-blue?style=for-the-badge&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
![Google Gemini](https://img.shields.io/badge/Gemini_2.5_Flash-8E75B2?style=for-the-badge&logo=google)
![Status](https://img.shields.io/badge/Status-Beta_Ready-success?style=for-the-badge)

Nalaris is a next-generation expense management and bookkeeping platform. Instead of forcing employees to fill out clunky forms, Nalaris acts as a conversational AI financial controller. Users simply snap a photo of a receipt or talk to the app via voice memo, and Nalaris securely extracts, categorizes, policy-checks, and vaults the data instantly.

Designed with a **mobile-first Progressive Web App (PWA)** interface that seamlessly scales into a **professional desktop dashboard**.

---

## ✨ Enterprise Features

* **🎙️ Conversational AI Bookkeeper:** Two-way voice and text chat. Ask Nalaris *"How much did we spend on software this month?"* and get real-time answers with High-Fidelity Text-to-Speech (TTS) audio playback.
* **📄 Zero-Touch Extraction:** Upload receipts (Images, PDFs, HEIC). The AI instantly extracts Vendor, Date, Subtotal, Taxes (GST/QST), Total, and Line Items.
* **🛡️ Role-Based Access Control (RBAC):** Distinct views and permissions for **Employees**, **Managers**, and **Admins/CFOs**. 
* **🚦 Automated Policy Enforcement:** Set corporate rules (e.g., "Max $75 for meals" or "No alcohol"). AI automatically flags violations and routes them for manager approval.
* **🏦 Bank Reconciliation:** Upload raw bank statements and let the AI cross-reference and reconcile unpaid ledger entries automatically.
* **⚡ Intelligent Duplicate Detection:** Real-time SQL checks prevent users from accidentally uploading the same receipt twice.
* **🔌 Omnichannel Export & Sync:** 1-Click CSV Import/Export, with built-in UI architecture ready for QuickBooks Online, Xero, and Oracle NetSuite.

---

## 🏗️ Tech Stack

Nalaris was built for extreme speed and rapid iteration, keeping dependencies minimal while maximizing performance.

**Backend:**
* **Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Lightning-fast ASGI Python framework)
* **Database:** SQLite with **WAL (Write-Ahead Logging)** enabled for seamless concurrent API requests without locking.
* **AI Engine:** Google `genai` SDK (Powered by **Gemini 2.5 Flash** for vision and logic, and **Gemini 2.5 Flash Preview TTS** for voice generation).

**Frontend:**
* **Stack:** Pure Vanilla HTML5, CSS3, and JavaScript. Zero build-step required.
* **Architecture:** Custom CSS Grid system providing a responsive split-view for Desktop, and an edge-to-edge native app feel for Mobile (PWA ready).
* **Charts:** [Chart.js](https://www.chartjs.org/) for interactive financial dashboards.

---

## 🚀 Getting Started

Follow these steps to run Nalaris locally on your machine.

### 1. Clone the Repository
```bash
git clone [https://github.com/YourUsername/nalaris-finops.git](https://github.com/YourUsername/nalaris-finops.git)
cd nalaris-finops

```

### 2. Set Up Python Environment

It is highly recommended to use a virtual environment.

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate

```

### 3. Install Dependencies

```bash
pip install fastapi uvicorn python-dotenv google-genai pillow pillow-heif

```

### 4. Configure Environment Variables

Create a `.env` file in the root directory and add your Google Gemini API key:

```env
GEMINI_API_KEY="your_api_key_here"

```

### 5. Run the Server

```bash
python server.py

```

*The server will start on `http://0.0.0.0:8010`. Open `http://localhost:8010` in your browser.*

---

## 📱 Progressive Web App (PWA) Install

To install Nalaris as a native-feeling app on your smartphone:

1. Navigate to the hosted URL on your mobile browser (Safari/Chrome).
2. Tap the **Share** button.
3. Select **"Add to Home Screen"**.
4. Launch Nalaris directly from your app drawer!

---

## 🗺️ Scaling Architecture Roadmap

Nalaris is currently optimized for rapid prototyping and beta testing. To scale to **1,000+ concurrent live users**, the following roadmap is prepared:

* **Database Migration:** Swap SQLite for PostgreSQL (via Supabase or AWS RDS).
* **Cloud Storage:** Offload Base64 image storage to AWS S3.
* **Asynchronous Queues:** Implement Celery + Redis to handle massive bursts of concurrent Gemini API requests without rate-limiting the main thread.

---

## 🔒 Security & Privacy

* **Vaulting:** Images are highly compressed and secured before entering the ledger.
* **Access:** Secured via Omni-Auth (Private Keywords, PIN, and local Biometric passthrough).

---

*Built with passion for the future of finance.*

```

```
