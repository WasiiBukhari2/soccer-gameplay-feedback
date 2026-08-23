// Base URL of the API. Empty = same-origin (frontend + /api function both on
// Vercel). You normally never need to change this.
const API_BASE = "";

// --- Frame extraction tuning (client-side) ---
// Kept modest so the uploaded JSON payload stays well under Vercel's ~4.5 MB
// serverless request-body limit (base64 inflates bytes by ~33%).
const MAX_FRAMES = 10;
const SAMPLE_INTERVAL_SEC = 1;
const FRAME_LONG_EDGE = 1280; // px; big enough to keep jersey numbers legible
const JPEG_QUALITY = 0.82;

const form = document.getElementById("analyze-form");
const submitBtn = document.getElementById("submit-btn");
const loadingEl = document.getElementById("loading");
const loadingText = document.getElementById("loading-text");
const errorEl = document.getElementById("error");
const resultsEl = document.getElementById("results");

function show(el) {
  el.classList.remove("hidden");
}
function hide(el) {
  el.classList.add("hidden");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}

function formatTimestamp(seconds) {
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

// --- Browser-side frame extraction ---

function loadVideo(file) {
  return new Promise((resolve, reject) => {
    const video = document.createElement("video");
    video.preload = "auto";
    video.muted = true;
    video.playsInline = true;
    // Attach off-screen: some browsers won't decode frames for a fully
    // detached <video>, which would make seeking hang.
    video.style.cssText =
      "position:fixed;left:-10000px;top:0;width:2px;height:2px;opacity:0;pointer-events:none;";
    document.body.appendChild(video);

    let settled = false;
    const fail = (msg) => {
      if (settled) return;
      settled = true;
      try {
        document.body.removeChild(video);
      } catch (_) {}
      reject(new Error(msg));
    };
    video.onloadedmetadata = () => {
      if (settled) return;
      settled = true;
      resolve(video);
    };
    video.onerror = () =>
      fail(
        "Could not read this video in your browser. Please try an MP4 (H.264) file."
      );
    // Hard timeout so a video that never reports metadata can't hang forever.
    setTimeout(
      () =>
        fail(
          "This video took too long to load in your browser. Please try an MP4 " +
            "(H.264) file."
        ),
      15000
    );
    video.src = URL.createObjectURL(file);
  });
}

// Seek to `time`, resolving on the 'seeked' event — but always resolve within a
// short fallback window so extraction can never hang (e.g. when seeking to a
// time we're already at, or on a codec the browser can't fully decode).
function seekTo(video, time) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      video.removeEventListener("seeked", finish);
      clearTimeout(timer);
      resolve();
    };
    video.addEventListener("seeked", finish);
    const timer = setTimeout(finish, 1500);

    const dur =
      isFinite(video.duration) && video.duration > 0
        ? video.duration
        : time + 0.1;
    let target = Math.min(time, Math.max(dur - 0.05, 0));
    // If we're already essentially at the target, setting currentTime fires no
    // 'seeked' — nudge slightly so a real seek happens.
    if (Math.abs(video.currentTime - target) < 0.001) {
      target = Math.min(target + 0.05, Math.max(dur - 0.01, 0));
    }
    video.currentTime = target;
  });
}

// Wait until a decoded frame is actually available to draw (raced with a short
// timeout so it can't hang if requestVideoFrameCallback never fires).
function nextFrame(video) {
  return new Promise((resolve) => {
    let done = false;
    const go = () => {
      if (done) return;
      done = true;
      resolve();
    };
    if (typeof video.requestVideoFrameCallback === "function") {
      video.requestVideoFrameCallback(() => go());
    }
    setTimeout(go, 120);
  });
}

function pickTimestamps(duration) {
  if (!isFinite(duration) || duration <= 0) return [0];
  let interval = SAMPLE_INTERVAL_SEC;
  if (duration / interval > MAX_FRAMES) {
    interval = duration / MAX_FRAMES;
  }
  const stamps = [];
  for (let t = 0; t < duration && stamps.length < MAX_FRAMES; t += interval) {
    stamps.push(t);
  }
  return stamps.length ? stamps : [0];
}

async function extractFrames(file, onProgress) {
  const video = await loadVideo(file);
  const timestamps = pickTimestamps(video.duration);

  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  const frames = [];

  try {
    for (let i = 0; i < timestamps.length; i++) {
      const t = timestamps[i];
      await seekTo(video, t);
      await nextFrame(video);

      const vw = video.videoWidth;
      const vh = video.videoHeight;
      if (!vw || !vh) {
        throw new Error(
          "The video has no readable image data. Please try an MP4 (H.264) file."
        );
      }
      const longEdge = Math.max(vw, vh);
      const scale = longEdge > FRAME_LONG_EDGE ? FRAME_LONG_EDGE / longEdge : 1;
      canvas.width = Math.round(vw * scale);
      canvas.height = Math.round(vh * scale);
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

      const dataUrl = canvas.toDataURL("image/jpeg", JPEG_QUALITY);
      frames.push({
        timestamp: formatTimestamp(t),
        data: dataUrl.split(",")[1],
      });
      if (onProgress) onProgress(i + 1, timestamps.length);
    }
  } finally {
    URL.revokeObjectURL(video.src);
    try {
      document.body.removeChild(video);
    } catch (_) {}
  }

  return frames;
}

// --- Rendering ---

function listSection(title, items) {
  const safeItems = Array.isArray(items) ? items : [];
  const body = safeItems.length
    ? `<ul>${safeItems.map((i) => `<li>${escapeHtml(i)}</li>`).join("")}</ul>`
    : `<p class="muted">None noted.</p>`;
  return `<section class="result-section"><h2>${escapeHtml(
    title
  )}</h2>${body}</section>`;
}

function renderReport(report) {
  const parts = [];

  if (!report.player_identified) {
    parts.push(
      `<div class="warn-box"><strong>Player could not be confidently identified.</strong><br>${escapeHtml(
        report.identification_note
      )}</div>`
    );
  } else if (report.identification_note) {
    parts.push(
      `<section class="result-section"><h2>Identification</h2><p>${escapeHtml(
        report.identification_note
      )}</p></section>`
    );
  }

  const frames = Array.isArray(report.frame_by_frame)
    ? report.frame_by_frame
    : [];
  let framesBody;
  if (frames.length) {
    framesBody = frames
      .map(
        (f) =>
          `<div class="frame-card"><div class="frame-label">Frame ${escapeHtml(
            f.frame_number
          )} — ${escapeHtml(f.timestamp)}</div><div>${escapeHtml(
            f.feedback
          )}</div></div>`
      )
      .join("");
  } else {
    framesBody = `<p class="muted">No frame-by-frame breakdown available.</p>`;
  }
  parts.push(
    `<section class="result-section"><h2>Frame-by-frame breakdown</h2>${framesBody}</section>`
  );

  parts.push(
    `<section class="result-section"><h2>Overall assessment</h2><p>${escapeHtml(
      report.overall_assessment
    )}</p></section>`
  );

  parts.push(listSection("Strengths", report.strengths));
  parts.push(listSection("Weaknesses", report.weaknesses));
  parts.push(
    listSection("Improvement suggestions", report.improvement_suggestions)
  );

  resultsEl.innerHTML = parts.join("");
  show(resultsEl);
}

// --- Submit flow ---

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  hide(errorEl);
  hide(resultsEl);
  resultsEl.innerHTML = "";
  submitBtn.disabled = true;

  const file = document.getElementById("video").files[0];
  const jersey_number = document.getElementById("jersey_number").value.trim();
  const jersey_color = document.getElementById("jersey_color").value.trim();

  try {
    if (!file) throw new Error("Please choose a video file.");

    show(loadingEl);
    loadingText.textContent = "Extracting frames in your browser...";
    const frames = await extractFrames(file, (done, total) => {
      loadingText.textContent = `Extracting frames (${done}/${total})...`;
    });

    if (!frames.length) {
      throw new Error(
        "No frames could be extracted. Please try an MP4 (H.264) file."
      );
    }

    loadingText.textContent =
      "Analyzing gameplay — this can take up to a minute...";
    const response = await fetch(`${API_BASE}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jersey_number, jersey_color, frames }),
    });

    if (!response.ok) {
      let detail = "Something went wrong analyzing the video.";
      try {
        const err = await response.json();
        if (err && err.detail) detail = err.detail;
      } catch (_) {
        // non-JSON error body; keep fallback
      }
      throw new Error(detail);
    }

    const report = await response.json();
    renderReport(report);
  } catch (err) {
    errorEl.textContent = err.message || "Something went wrong.";
    show(errorEl);
  } finally {
    hide(loadingEl);
    submitBtn.disabled = false;
  }
});
