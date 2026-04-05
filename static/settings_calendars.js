document.addEventListener("DOMContentLoaded", () => {
  if (!location.pathname.startsWith("/settings/calendars")) return;

  const feedsList = document.getElementById("feedsList");
  const eventsPreview = document.getElementById("eventsPreview");
  const addFeedBtn = document.getElementById("addFeedBtn");
  const feedNameInput = document.getElementById("feedName");
  const feedUrlInput = document.getElementById("feedUrl");
  const addFeedStatus = document.getElementById("addFeedStatus");
  const refreshPreviewBtn = document.getElementById("refreshPreviewBtn");

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function showStatus(msg, isError) {
    addFeedStatus.textContent = msg;
    addFeedStatus.className = "calendar-status " + (isError ? "error" : "success");
    addFeedStatus.hidden = false;
    setTimeout(() => { addFeedStatus.hidden = true; }, 5000);
  }

  // --- Load feeds ---
  function loadFeeds() {
    fetch("/api/settings/calendars")
      .then((r) => r.json())
      .then((data) => {
        if (!data.success) {
          feedsList.innerHTML = '<div class="no-data">Failed to load calendars</div>';
          return;
        }
        renderFeeds(data.feeds || []);
      })
      .catch(() => {
        feedsList.innerHTML = '<div class="error">Failed to load calendars</div>';
      });
  }

  function renderFeeds(feeds) {
    if (!feeds.length) {
      feedsList.innerHTML = '<div class="no-data">No calendars connected yet. Add one above.</div>';
      return;
    }

    feedsList.innerHTML = "";
    feeds.forEach((feed) => {
      const card = document.createElement("div");
      card.className = `job-card ${feed.enabled ? "" : "disabled"}`;
      card.innerHTML = `
        <div class="job-card-header">
          <div class="job-info">
            <div class="job-message">${escapeHtml(feed.name || "Calendar")}</div>
            <div class="job-meta">
              <span class="job-target">${escapeHtml(feed.domain || "unknown")}</span>
              <span class="job-schedule">${feed.added_at ? "Added " + feed.added_at.split("T")[0] : ""}</span>
            </div>
          </div>
          <div class="job-actions">
            <span class="job-status ${feed.enabled ? "active" : "inactive"}">${feed.enabled ? "Active" : "Paused"}</span>
            <button class="job-toggle-btn" title="${feed.enabled ? "Pause" : "Resume"}">
              ${feed.enabled ? "\u23F8" : "\u25B6"}
            </button>
            <button class="job-delete-btn" title="Remove calendar">\u2715</button>
          </div>
        </div>
      `;
      card.querySelector(".job-toggle-btn").addEventListener("click", () => {
        toggleFeed(feed.feed_id, !feed.enabled);
      });
      card.querySelector(".job-delete-btn").addEventListener("click", () => {
        if (confirm(`Remove "${feed.name || "this calendar"}"?`)) {
          deleteFeed(feed.feed_id);
        }
      });
      feedsList.appendChild(card);
    });
  }

  // --- Add feed ---
  addFeedBtn.addEventListener("click", () => {
    const url = feedUrlInput.value.trim();
    const name = feedNameInput.value.trim() || "My Calendar";

    if (!url) {
      showStatus("Please paste a calendar URL.", true);
      return;
    }

    addFeedBtn.disabled = true;
    addFeedBtn.textContent = "Verifying...";

    fetch("/api/settings/calendars", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, name }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.success) {
          showStatus(`Connected! Found ${data.event_count} upcoming events.`, false);
          feedUrlInput.value = "";
          feedNameInput.value = "";
          loadFeeds();
          loadPreview();
        } else {
          showStatus(data.message || "Failed to add calendar.", true);
        }
      })
      .catch(() => {
        showStatus("Network error. Please try again.", true);
      })
      .finally(() => {
        addFeedBtn.disabled = false;
        addFeedBtn.textContent = "Add Calendar";
      });
  });

  // --- Toggle feed ---
  function toggleFeed(feedId, enabled) {
    fetch(`/api/settings/calendars/${encodeURIComponent(feedId)}/toggle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.success) {
          loadFeeds();
          loadPreview();
        }
      });
  }

  // --- Delete feed ---
  function deleteFeed(feedId) {
    fetch(`/api/settings/calendars/${encodeURIComponent(feedId)}`, {
      method: "DELETE",
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.success) {
          loadFeeds();
          loadPreview();
        }
      });
  }

  // --- Event preview ---
  function loadPreview() {
    eventsPreview.innerHTML = '<div class="loading">Loading events...</div>';
    fetch("/api/settings/calendars/preview")
      .then((r) => r.json())
      .then((data) => {
        if (!data.success) {
          eventsPreview.innerHTML = '<div class="no-data">Could not load events</div>';
          return;
        }
        renderPreview(data.events || []);
      })
      .catch(() => {
        eventsPreview.innerHTML = '<div class="error">Failed to load events</div>';
      });
  }

  function renderPreview(events) {
    if (!events.length) {
      eventsPreview.innerHTML = '<div class="no-data">No upcoming events found. Connect a calendar above to see your schedule here.</div>';
      return;
    }

    let html = "";
    let currentDate = "";
    const today = new Date().toISOString().split("T")[0];
    const tomorrow = new Date(Date.now() + 86400000).toISOString().split("T")[0];

    events.slice(0, 30).forEach((ev) => {
      const dateStr = ev.start.split("T")[0];
      if (dateStr !== currentDate) {
        currentDate = dateStr;
        let label = dateStr;
        if (dateStr === today) label = "Today";
        else if (dateStr === tomorrow) label = "Tomorrow";
        else {
          const d = new Date(dateStr + "T00:00:00");
          label = d.toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" });
        }
        html += `<div class="calendar-preview-date">${escapeHtml(label)}</div>`;
      }

      let timeStr = "All day";
      if (!ev.is_all_day) {
        const start = new Date(ev.start);
        timeStr = start.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
        if (ev.end) {
          const end = new Date(ev.end);
          timeStr += " - " + end.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
        }
      }

      html += `<div class="calendar-preview-event">
        <span class="calendar-preview-time">${escapeHtml(timeStr)}</span>
        <span class="calendar-preview-summary">${escapeHtml(ev.summary)}</span>
        ${ev.location ? `<span class="calendar-preview-location">@ ${escapeHtml(ev.location)}</span>` : ""}
        ${ev.calendar ? `<span class="calendar-preview-cal">[${escapeHtml(ev.calendar)}]</span>` : ""}
      </div>`;
    });

    eventsPreview.innerHTML = html;
  }

  refreshPreviewBtn.addEventListener("click", loadPreview);

  // Initial load
  loadFeeds();
  loadPreview();
});
