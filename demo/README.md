# AI Meeting Agent — demo

Use this folder to **verify the stack** and **show the product** without hunting for sample data.

## What’s here

| File | Purpose |
|------|---------|
| `sample_transcript.txt` | Short fictional meeting (Alice & Bob tasks, one decision, one risk) |
| `sample_request.json` | `meeting_date` + `participants` for the demo |
| `check_env.py` | Prints OK/MISSING for OpenAI + Notion vars (no secrets) |
| `call_process_meeting_demo.py` | Calls `POST /process-meeting` with the samples (needs API running) |

## Before you demo

1. Copy `.env.example` to `.env` in the **project root** and fill `OPENAI_API_KEY`, Notion integration token, and parent page ID.
2. From the project root:

   ```bash
   python demo/check_env.py
   ```

   Fix anything marked `[MISSING]`.

3. Install deps: `pip install -r requirements.txt`

## Path A — API only (good for a quick technical demo)

Terminal 1:

```bash
cd /path/to/ai-meeting-agent
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2:

```bash
cd /path/to/ai-meeting-agent
python demo/call_process_meeting_demo.py
```

You should get HTTP 200 and a **Notion URL** in the output. Open it in the browser to show the generated page.

Optional: open `http://127.0.0.1:8000/docs` and run **Try it out** on `POST /process-meeting` with the same JSON body the script sends.

## Path B — Streamlit (good for a stakeholder demo)

Terminal 1: start the API as above.

Terminal 2:

```bash
cd /path/to/ai-meeting-agent
streamlit run app.py
```

Use an **MP3 or MP4** recording, add participants if you want, click **Process meeting**, then show summary + Notion link.

## Recording a video

1. Start API + Streamlit.
2. Use a short real or test audio clip.
3. Show: upload → process → results → click through to Notion.
4. Tools: OBS, Windows Game Bar (Win+G), or Teams screen record.

## Troubleshooting

| Symptom | Check |
|--------|--------|
| 500 Notion required | `.env` has both Notion token and parent page ID; parent page is shared with the integration |
| Connection refused | API is running on the URL Streamlit uses (sidebar default `http://127.0.0.1:8000`) |
| 502 OpenAI | Key, billing, model name |
