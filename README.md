# Sync2Meet — AI Meeting Agent

Turn any meeting recording into structured, actionable intelligence — automatically.

Sync2Meet takes a meeting audio file or transcript, extracts what matters, and delivers it where your team works — no manual notes, no follow-up emails, no missed action items.

---

## What it does

1. **Transcribes** meeting audio using OpenAI Whisper
2. **Extracts** structured insights using GPT-4o:
   - Meeting summary
   - Action items (with assignee and deadline when mentioned)
   - Decisions made
   - Risks and open issues
3. **Creates a Notion page** automatically with all the above, formatted and ready to share
4. **Sends personalised email notifications** to each assignee with their specific tasks

All in one API call. Zero manual handling.

---

## Demo

![Sync2Meet demo](demo/)

---

## Tech stack

| Layer | Tools |
|---|---|
| API framework | FastAPI + Pydantic |
| Transcription | OpenAI Whisper |
| AI extraction | GPT-4o (structured JSON output) |
| Storage | Notion API |
| Notifications | Email (SMTP) |
| Language | Python 3.11+ |

---

## Getting started

### 1. Clone the repo

```bash
git clone https://github.com/iabarracho/sync2meet-ai-meeting-agent.git
cd sync2meet-ai-meeting-agent
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set up environment variables

Copy the example file and fill in your keys:

```bash
cp .env.example .env
```

Open `.env` and add:

```
OPENAI_API_KEY=sk-...
NOTION_API_KEY=secret_...
NOTION_PARENT_PAGE_ID=your-page-id-here
```

**How to get these:**
- **OpenAI API key:** [platform.openai.com](https://platform.openai.com)
- **Notion integration + key:** Go to [notion.so/my-integrations](https://notion.so/my-integrations), create an integration, and share your parent page with it
- **Notion parent page ID:** The ID is in the URL of the page where you want notes to be created

### 4. Run the server

```bash
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`

---

## API endpoints

### POST `/process-meeting`
Send a text transcript directly.

```json
{
  "transcript": "Alice: Let's ship the new dashboard by Friday. Bob: I'll handle the API. ...",
  "meeting_date": "2025-04-23",
  "participants": [
    { "name": "Alice", "email": "alice@company.com" },
    { "name": "Bob", "email": "bob@company.com" }
  ]
}
```

### POST `/process-meeting-audio`
Send an audio file (mp3, mp4, wav, m4a). The system transcribes it first, then runs the same analysis.

```bash
curl -X POST http://localhost:8000/process-meeting-audio \
  -F "audio=@meeting.mp3" \
  -F "meeting_date=2025-04-23" \
  -F 'participants=[{"name":"Alice","email":"alice@company.com"}]'
```

### Response (both endpoints)

```json
{
  "meeting_title": "Product Sprint Planning — Q2 Roadmap",
  "meeting_date": "2025-04-23",
  "summary": "• Team aligned on Q2 priorities\n• Dashboard feature prioritised for Friday release\n• Budget approval pending finance sign-off",
  "action_items": [
    {
      "task": "Deliver API integration for new dashboard",
      "assignee": "Bob",
      "deadline": "Friday"
    }
  ],
  "decisions": ["Ship dashboard feature by end of week"],
  "risks": ["Finance sign-off not yet confirmed"],
  "notion_page_url": "https://notion.so/..."
}
```

---

## Prompt engineering approach

The extraction prompt is designed to prevent hallucination:
- Only outputs facts **explicitly stated** in the transcript
- Uses empty arrays when nothing relevant is found
- Handles ambiguous transcripts, missing dates, and multiple languages
- Never fabricates names, deadlines, or commitments

---

## Project structure

```
sync2meet-ai-meeting-agent/
├── main.py              # FastAPI app, endpoints, Notion integration
├── notifications.py     # Email notification logic
├── app.py               # Streamlit demo interface
├── requirements.txt
├── .env.example
└── demo/                # Screenshots and demo assets
```

---

## Built by

**Inês Barracho** — AI Implementation Specialist  
[LinkedIn](https://linkedin.com/in/inesbarracho) · [GitHub](https://github.com/iabarracho)
