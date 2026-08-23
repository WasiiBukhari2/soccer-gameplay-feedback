// Base URL of the backend API. Empty = same-origin (frontend served by the
// FastAPI backend). Point this at your deployed backend if the frontend is
// hosted separately, e.g. "https://soccer-feedback-api.onrender.com".
const API_BASE = "";

const form = document.getElementById("analyze-form");
const submitBtn = document.getElementById("submit-btn");
const loadingEl = document.getElementById("loading");
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

  // Frame-by-frame breakdown
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

  // Overall assessment
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

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  hide(errorEl);
  hide(resultsEl);
  resultsEl.innerHTML = "";
  show(loadingEl);
  submitBtn.disabled = true;

  try {
    const formData = new FormData(form);
    const response = await fetch(`${API_BASE}/api/analyze`, {
      method: "POST",
      body: formData,
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
