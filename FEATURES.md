# DREAM-Chat (HeartIntelligence) — Features Overview

A personal health assistant with EHR integration, mobile health data, exercise guidance, and multi-channel delivery.

---

## Chat & AI Skills

### Personalized Health Chat
AI-powered conversations grounded in the user's medical record (EHR) and Apple HealthKit data. Covers medications, lab results, exercise, nutrition, symptoms, and sleep. Responds in warm, plain-language tone with clinical accuracy.

### Web Search (auto-triggered)
Fetches current medical guidelines, drug info, research, and safety alerts when the query needs up-to-date or external evidence. Uses OpenAI `gpt-4o-search-preview` with citation extraction.

### Personal Health Context (auto-triggered)
Retrieves relevant slices of the user's EHR and mobile health data (heart rate, activity, sleep, ECG) to personalize responses. Only activates when the query touches the user's own records.

### Workout Guidance (auto-triggered)
Searches a local database of 800+ exercises. Understands muscle groups, equipment, difficulty levels, exercise categories, and body-region queries ("upper body", "at home", "without equipment"). Returns up to 8 results with instructions and demo images served locally.

### Reminders (auto-triggered)
Detects reminder intent in natural language ("remind me in 2 hours about pills"). Creates one-time or recurring scheduled jobs delivered via WhatsApp or web chat.

---

## App Pages

| Page | Route | Description |
|------|-------|-------------|
| Welcome | `/` | Landing page with chat input |
| Chat | `/chat/<session_id>` | Main conversation interface with markdown rendering |
| Dashboard | `/dashboard` | Health summary — activity, heart rate, ECG, medical imaging |
| My Body | `/my-body` | Interactive CT/MRI viewer with organ segmentation overlays |
| PDF Forms | `/pdf-forms` | Upload a PDF form; AI auto-fills fields from EHR data |
| Cron Jobs | `/settings/cron-jobs` | Create, edit, toggle, delete scheduled reminders |
| Skills | `/settings/skills` | Enable/disable individual AI skills |

---

## Data Sources

| Source | Location | Contents |
|--------|----------|----------|
| Patient EHR | `personal_data/test_file/` | Demographics, diagnoses, medications, comorbidities, symptoms, wearable summary |
| Mobile Health | `personal_data/raw_mobile/`, `personal_data/processed_mobile_data.json` | Apple HealthKit export — heart rate, steps, sleep, ECG, exercise, SpO2, BP |
| Medical Imaging | `personal_data/my_body/` | NIfTI CT/MRI files with organ segmentation masks |
| Health Info | `personal_data/health_info.json` | Organ-level health context |
| Exercise DB | `resources/exercises/exercises.json` | 873 exercises with muscles, equipment, instructions, images |
| Exercise Images | `resources/exercises/images/` | On-demand cached demo images (gitignored) |

---

## Messaging Integrations

### WhatsApp
Node.js bridge (`whatsapp/`) using Baileys. Per-contact session isolation, persistent history in `chat_history/whatsapp_bot/`. Supports both inbound chat and outbound scheduled messages.

### Web Chat
Browser-based interface with session management, voice input (Whisper STT), and markdown rendering.

---

## Scheduling System

- **One-time**: execute at a specific datetime, auto-disable after
- **Recurring**: hourly (at minute), daily (at time), weekly (day + time)
- **Delivery**: WhatsApp (via outbound queue) or web chat (session append)
- **Storage**: `personal_data/cron_data/jobs.json`, `personal_data/cron_data/outbound_queue.json`
- **Scheduler**: daemon thread checks every 30 seconds

---

## Configuration

| File | Purpose |
|------|---------|
| `config/configs.json` | LLM model, system prompt |
| `config/skills_settings.json` | Per-skill enabled/disabled state |
| `config/context_settings.json` | Context file toggles |
| `context/*.md` | System prompt personality, boundaries, response instructions |
| `skills/*.md` | Skill definitions with routing keywords |

---

## Models Used

| Purpose | Model |
|---------|-------|
| Main chat | gpt-4o (configurable) |
| Web search | gpt-4o-search-preview |
| Skill gate decisions | gpt-4o |
| Reminder extraction | gpt-4o-mini |
| PDF form analysis | gpt-4o |
| Session summarization | gpt-4o-mini |

---

## Tech Stack

- **Backend**: Python / Flask
- **Frontend**: HTML + vanilla JS, marked.js for markdown
- **WhatsApp bridge**: Node.js / TypeScript, Baileys
- **Voice**: pywhispercpp (base.en model)
- **Medical imaging**: nibabel, PIL
- **PDF**: pypdf, reportlab
