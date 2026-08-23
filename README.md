# ⚽ Soccer Gameplay Feedback

A web app that gives honest, AI-generated coaching feedback on **one specific
player** in a soccer clip, identified manually by jersey number and jersey color
(no OCR / auto-detection).

**Runs entirely on Vercel.** Frames are extracted in the browser, so only a
handful of small JPEGs are ever uploaded — no big video upload, no server-side
OpenCV, no persistent storage. A single Python serverless function calls Claude
vision and returns a structured report.

## How it works

1. You enter a jersey number, jersey color, and pick a video.
2. **In your browser**, the video is decoded locally: up to `MAX_FRAMES`
   (default 10) frames are sampled with a `<video>` + `<canvas>`, resized (long
   edge ≤ 1280px), and JPEG-encoded. The video file itself never leaves your
   machine.
3. Those small frames (a few hundred KB total) are POSTed as JSON to
   `/api/analyze`.
4. The serverless function sends them to Claude (`claude-opus-4-8`) as
   alternating text-label + image blocks, with a tuned coaching system prompt
   that tracks the player primarily by jersey color and reports honestly when the
   player can't be identified.
5. Claude returns a structured report (JSON schema via `output_config`), which
   the frontend renders: frame-by-frame breakdown, overall assessment, strengths,
   weaknesses, improvement suggestions.

## Project structure

```
public/
  index.html      # frontend (browser-side frame extraction)
  main.js
  styles.css
api/
  analyze.py      # Vercel Python serverless function → Claude
dev_server.py     # local dev: serves public/ + routes /api/analyze (stdlib only)
requirements.txt  # anthropic (the only server dependency)
vercel.json       # sets the function's maxDuration to 60s
.env.example
```

## Deploy to Vercel

1. Push this repo to GitHub (already done if you cloned it from there).
2. On [vercel.com](https://vercel.com): **Add New → Project** → import the repo.
   Vercel auto-detects `public/` (static) and `api/analyze.py` (Python function)
   — no build step, no framework preset needed.
3. In **Project Settings → Environment Variables**, add:
   - `ANTHROPIC_API_KEY` = your key (required)
   - `ANTHROPIC_MODEL` = optional override (e.g. `claude-sonnet-5` if you hit the
     timeout on longer clips)
4. Deploy. Every push to the connected branch auto-deploys.

That's it — frontend and API live on the same Vercel domain, so no CORS setup
and no separate backend host.

### Notes / limits

- **Video format:** browsers reliably decode **MP4 (H.264)**. Some MOV/AVI codecs
  won't decode client-side; the app shows a clear message if extraction fails.
- **Payload size:** frame count/size are tuned to stay under Vercel's ~4.5 MB
  request-body limit. Raising `MAX_FRAMES` or `FRAME_LONG_EDGE` in
  `public/main.js` can exceed it.
- **Timeout:** the function is capped at 60s (Vercel Hobby max). If Opus is slow
  on a given clip, set `ANTHROPIC_MODEL` to a faster model.

## Local development

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt python-dotenv
copy .env.example .env            # then fill in ANTHROPIC_API_KEY
python dev_server.py              # open http://localhost:8000
```

`dev_server.py` reuses the exact `run_analysis` from `api/analyze.py`, so local
behavior matches production. (`python-dotenv` is only needed locally, to load
`.env`; it is not required by the Vercel function.)

## Scope

No user accounts/auth, no database/history, no video trimming UI, no real-time
analysis, no automatic jersey OCR (manual entry only), one player per analysis.
