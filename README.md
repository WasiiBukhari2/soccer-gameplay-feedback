# ⚽ Soccer Gameplay Feedback

A web app that takes a soccer gameplay video and returns honest, AI-generated
coaching feedback on **one specific player**, identified manually by jersey
number and jersey color (no OCR / auto-detection).

The backend samples frames from the uploaded clip with OpenCV, sends them to
Claude (vision) with a coaching system prompt, and returns a structured JSON
report. The frontend renders a frame-by-frame breakdown, overall assessment,
strengths, weaknesses, and improvement suggestions.

## How it works

1. You enter a jersey number, jersey color, and pick a video (MP4/MOV/AVI).
2. The backend extracts up to `MAX_FRAMES` frames (default 20), one every
   `SAMPLE_INTERVAL_SEC` seconds (default 1s), widening the interval on longer
   clips so cost/latency stay bounded. Frames are resized (long edge ≤ 1568px)
   and JPEG-encoded.
3. Frames are sent to Claude (`claude-opus-4-8`) as alternating
   text-label + image blocks. A tuned system prompt tells the model to track
   the player primarily by jersey color, using the number as confirmation, and
   to say so honestly if the player can't be identified rather than fabricating
   feedback.
4. Claude returns a structured report via `output_config` (JSON schema), which
   the frontend renders.

## Tech stack

- **Backend:** Python 3.12, FastAPI, uvicorn. No database — local filesystem
  only, nothing persists across requests.
- **Frames:** `opencv-python-headless` (works on headless Linux hosts).
- **AI:** Anthropic Python SDK, model `claude-opus-4-8`, structured output via
  `output_config.format` (`json_schema`).
- **Frontend:** plain HTML/CSS/JS, dark theme, no build step.

## Project structure

```
app/
  main.py                  # FastAPI app, CORS, static mount, serves index.html
  config.py                # env config
  routers/analyze.py       # POST /api/analyze
  services/video_frames.py # OpenCV frame sampling
  services/ai_analysis.py  # Claude prompt + call + parse
  models/schemas.py        # Pydantic models + JSON schema
static/                    # frontend served by FastAPI
deploy/index.html          # standalone single-file frontend for static hosts
render.yaml                # Render Blueprint for the backend
netlify.toml               # Netlify static-site config for static/
requirements.txt
.env.example
```

## Local development

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows (use: source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
copy .env.example .env      # then fill in ANTHROPIC_API_KEY
uvicorn app.main:app --reload --port 8000
```

Then open http://localhost:8000.

## Configuration (`.env`)

| Variable              | Required | Default | Notes                                             |
|-----------------------|----------|---------|---------------------------------------------------|
| `ANTHROPIC_API_KEY`   | yes      | —       | Your Anthropic API key.                           |
| `ALLOWED_ORIGINS`     | no       | `*`     | Comma-separated CORS origins for a split deploy.  |
| `MAX_FRAMES`          | no       | `20`    | Max frames sampled per analysis.                  |
| `SAMPLE_INTERVAL_SEC` | no       | `1`     | Seconds between sampled frames.                   |
| `MAX_UPLOAD_MB`       | no       | `100`   | Max upload size.                                  |

The model (`claude-opus-4-8`) is hardcoded, not env-configurable.

## Deployment

### Backend on Render

The included `render.yaml` is a Blueprint. Create a new Blueprint on Render
pointing at this repo, then set `ANTHROPIC_API_KEY` and (optionally)
`ALLOWED_ORIGINS` to your frontend's URL in the dashboard.

### Frontend on Vercel (recommended split)

The backend cannot run on Vercel — Vercel's serverless functions cap the request
body at ~4.5 MB, have no persistent filesystem, and time out around 60s, none of
which suit large video uploads and minute-long AI calls. So the recommended
setup is **frontend on Vercel + backend on Render, from one repo**:

1. **Deploy the backend on Render first** (see above) and copy its URL, e.g.
   `https://soccer-feedback-api.onrender.com`.
2. **Point the frontend at it:** edit `deploy/index.html` and set the `API_BASE`
   constant near the top of the `<script>` block to that Render URL. Commit and
   push.
3. **Import the repo on Vercel** (New Project → this repo). `vercel.json` already
   configures it as a static site served from `deploy/` — no build step. Every
   push to the connected branch auto-deploys.
4. **Allow the Vercel origin on the backend:** set `ALLOWED_ORIGINS` on Render to
   your Vercel URL (e.g. `https://your-app.vercel.app`) so the browser's
   cross-origin request is accepted.

`vercel.json` deploys the self-contained `deploy/index.html`; `.vercelignore`
keeps the Python backend out of the Vercel build.

### Other frontend options

- **Same origin:** the backend already serves the frontend from `static/` at
  `/`, so deploying the backend alone (on Render) is enough.
- **Netlify:** `netlify.toml` publishes the `static/` folder as a Netlify static
  site, or drag `deploy/index.html` onto Netlify Drop.

## Scope

No user accounts/auth, no database/history, no video trimming UI, no real-time
analysis, no automatic jersey OCR (manual entry only), one player per analysis.
