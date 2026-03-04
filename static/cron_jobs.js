/**
 * cron_jobs.js — Frontend logic for the Cron Jobs dashboard page.
 */

document.addEventListener("DOMContentLoaded", () => {
  if (!location.pathname.startsWith("/cron-jobs")) return;

  const form = document.getElementById("createJobForm");
  const jobsList = document.getElementById("jobsList");
  const scheduleType = document.getElementById("scheduleType");
  const onceOptions = document.getElementById("onceOptions");
  const recurringOptions = document.getElementById("recurringOptions");
  const frequency = document.getElementById("frequency");
  const dayOfWeekGroup = document.getElementById("dayOfWeekGroup");
  const toggleManualInput = document.getElementById("toggleManualInput");
  const targetContact = document.getElementById("targetContact");
  const manualPhone = document.getElementById("manualPhone");

  let useManualInput = false;
  let currentJobs = [];

  toggleManualInput.addEventListener("click", (e) => {
    e.preventDefault();
    useManualInput = !useManualInput;
    if (useManualInput) {
      targetContact.classList.add("hidden");
      manualPhone.classList.remove("hidden");
      toggleManualInput.textContent = "select from contacts";
    } else {
      targetContact.classList.remove("hidden");
      manualPhone.classList.add("hidden");
      toggleManualInput.textContent = "enter phone number manually";
    }
  });

  scheduleType.addEventListener("change", () => {
    if (scheduleType.value === "once") {
      onceOptions.classList.remove("hidden");
      recurringOptions.classList.add("hidden");
    } else {
      onceOptions.classList.add("hidden");
      recurringOptions.classList.remove("hidden");
    }
  });

  frequency.addEventListener("change", () => {
    dayOfWeekGroup.classList.toggle("hidden", frequency.value !== "weekly");
  });

  function loadContacts() {
    fetch("/api/whatsapp/contacts")
      .then((r) => r.json())
      .then((data) => {
        if (data.success && data.contacts) {
          data.contacts.forEach((c) => {
            const option = document.createElement("option");
            option.value = c.jid;
            option.textContent = `${c.name} (${c.jid.split("@")[0]})`;
            targetContact.appendChild(option);
          });
        }
      })
      .catch((err) => console.error("Failed to load contacts:", err));
  }

  function loadJobs() {
    fetch("/api/cron-jobs")
      .then((r) => r.json())
      .then((data) => {
        if (!data.success) {
          jobsList.innerHTML = '<div class="no-data">Failed to load jobs</div>';
          return;
        }
        currentJobs = data.jobs || [];
        renderJobs(currentJobs);
      })
      .catch((err) => {
        console.error("Failed to load jobs:", err);
        jobsList.innerHTML = '<div class="error">Failed to load jobs</div>';
      });
  }

  function renderJobs(jobs) {
    if (!jobs || jobs.length === 0) {
      jobsList.innerHTML =
        '<div class="no-data">No scheduled jobs yet. Create one above!</div>';
      return;
    }

    jobsList.innerHTML = "";
    jobs.forEach((job) => jobsList.appendChild(createJobCard(job)));
  }

  function createJobCard(job) {
    const card = document.createElement("div");
    card.className = `job-card ${job.enabled ? "" : "disabled"}`;
    card.dataset.jobId = job.job_id;

    const scheduleDesc = getScheduleDescription(job);
    const delivery = job.delivery_method || "whatsapp";
    const targetName =
      delivery === "web"
        ? `Web chat (${job.user || "unknown"})`
        : (job.target_jid || "").split("@")[0] || "unknown";
    const statusClass = job.enabled ? "active" : "inactive";
    const statusText = job.enabled ? "Active" : "Disabled";

    const createdFrom =
      job.created_from === "chat"
        ? '<span class="badge badge-chat">From Chat</span>'
        : '<span class="badge badge-dashboard">Manual</span>';
    const deliveryBadge =
      delivery === "web"
        ? '<span class="badge badge-web">Web</span>'
        : '<span class="badge badge-wa">WhatsApp</span>';

    card.innerHTML = `
      <div class="job-card-header">
        <div class="job-info">
          <div class="job-message">${escapeHtml(job.message)}</div>
          <div class="job-meta">
            <span class="job-target">To: ${escapeHtml(targetName)}</span>
            <span class="job-schedule">${scheduleDesc}</span>
            ${createdFrom}
            ${deliveryBadge}
          </div>
        </div>
        <div class="job-actions">
          <span class="job-status ${statusClass}">${statusText}</span>
          <button class="job-edit-btn" title="Edit">✎</button>
          <button class="job-toggle-btn" title="${job.enabled ? "Disable" : "Enable"}">
            ${job.enabled ? "⏸" : "▶"}
          </button>
          <button class="job-delete-btn" title="Delete">✕</button>
        </div>
      </div>
      ${
        job.last_executed_at
          ? `<div class="job-last-run">Last run: ${formatTime(job.last_executed_at)}</div>`
          : ""
      }
    `;

    card.querySelector(".job-edit-btn").addEventListener("click", () => openEditPanel(card, job));
    card.querySelector(".job-toggle-btn").addEventListener("click", () => toggleJob(job.job_id));
    card.querySelector(".job-delete-btn").addEventListener("click", () => deleteJob(job.job_id));

    return card;
  }

  // ── Inline edit panel ──────────────────────────────────────────────────────

  function openEditPanel(card, job) {
    if (card.querySelector(".job-edit-panel")) return;

    const panel = document.createElement("div");
    panel.className = "job-edit-panel";

    const isOnce = job.schedule_type === "once";
    const scheduledLocal = job.scheduled_at
      ? toLocalDatetimeValue(job.scheduled_at)
      : "";

    panel.innerHTML = `
      <div class="edit-row">
        <label>Message</label>
        <textarea class="edit-message" rows="2">${escapeHtml(job.message)}</textarea>
      </div>
      <div class="edit-row">
        <label>Schedule</label>
        <select class="edit-schedule-type">
          <option value="once" ${isOnce ? "selected" : ""}>One-time</option>
          <option value="recurring" ${!isOnce ? "selected" : ""}>Recurring</option>
        </select>
      </div>
      <div class="edit-once-opts ${isOnce ? "" : "hidden"}">
        <div class="edit-row">
          <label>Date & Time</label>
          <input type="datetime-local" class="edit-scheduled-at" value="${scheduledLocal}" />
        </div>
      </div>
      <div class="edit-recurring-opts ${!isOnce ? "" : "hidden"}">
        <div class="edit-row">
          <label>Frequency</label>
          <select class="edit-frequency">
            <option value="daily" ${job.frequency === "daily" ? "selected" : ""}>Daily</option>
            <option value="weekly" ${job.frequency === "weekly" ? "selected" : ""}>Weekly</option>
            <option value="hourly" ${job.frequency === "hourly" ? "selected" : ""}>Hourly</option>
          </select>
        </div>
        <div class="edit-row">
          <label>Time</label>
          <input type="time" class="edit-time-of-day" value="${job.time_of_day || "09:00"}" />
        </div>
        <div class="edit-row ${job.frequency === "weekly" ? "" : "hidden"}" data-edit-dow>
          <label>Day</label>
          <select class="edit-day-of-week">
            ${["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
              .map((d) => `<option value="${d}" ${job.day_of_week === d ? "selected" : ""}>${capitalize(d)}</option>`)
              .join("")}
          </select>
        </div>
      </div>
      <div class="edit-actions">
        <button class="edit-save-btn">Save</button>
        <button class="edit-cancel-btn">Cancel</button>
      </div>
    `;

    card.appendChild(panel);

    const schedTypeSelect = panel.querySelector(".edit-schedule-type");
    const freqSelect = panel.querySelector(".edit-frequency");

    schedTypeSelect.addEventListener("change", () => {
      panel.querySelector(".edit-once-opts").classList.toggle("hidden", schedTypeSelect.value !== "once");
      panel.querySelector(".edit-recurring-opts").classList.toggle("hidden", schedTypeSelect.value === "once");
    });

    freqSelect.addEventListener("change", () => {
      panel.querySelector("[data-edit-dow]").classList.toggle("hidden", freqSelect.value !== "weekly");
    });

    panel.querySelector(".edit-cancel-btn").addEventListener("click", () => panel.remove());
    panel.querySelector(".edit-save-btn").addEventListener("click", () => saveEdit(job.job_id, panel));
  }

  function saveEdit(jobId, panel) {
    const payload = {
      message: panel.querySelector(".edit-message").value.trim(),
      schedule_type: panel.querySelector(".edit-schedule-type").value,
    };

    if (payload.schedule_type === "once") {
      const raw = panel.querySelector(".edit-scheduled-at").value;
      if (!raw) {
        alert("Please select a date and time.");
        return;
      }
      payload.scheduled_at = new Date(raw).toISOString().slice(0, 19);
      payload.enabled = true;
    } else {
      payload.frequency = panel.querySelector(".edit-frequency").value;
      payload.time_of_day = panel.querySelector(".edit-time-of-day").value;
      if (payload.frequency === "weekly") {
        payload.day_of_week = panel.querySelector(".edit-day-of-week").value;
      }
    }

    if (!payload.message) {
      alert("Message cannot be empty.");
      return;
    }

    fetch(`/api/cron-jobs/${jobId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.success) {
          loadJobs();
        } else {
          alert(data.message || "Failed to update job");
        }
      })
      .catch((err) => {
        console.error("Failed to update job:", err);
        alert("Failed to update job");
      });
  }

  function toLocalDatetimeValue(iso) {
    try {
      const d = new Date(iso);
      const pad = (n) => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    } catch {
      return "";
    }
  }

  // ── Schedule description helpers ───────────────────────────────────────────

  function getScheduleDescription(job) {
    if (job.schedule_type === "once") {
      if (job.scheduled_at) return `Once at ${formatTime(job.scheduled_at)}`;
      return "One-time (no date set)";
    }
    const freq = job.frequency || "daily";
    const time = job.time_of_day || "09:00";
    if (freq === "hourly") return `Every hour at :${time.split(":")[1] || "00"}`;
    if (freq === "daily") return `Daily at ${time}`;
    if (freq === "weekly") return `Weekly on ${capitalize(job.day_of_week || "monday")} at ${time}`;
    return `${capitalize(freq)} at ${time}`;
  }

  function formatTime(isoString) {
    try {
      return new Date(isoString).toLocaleString();
    } catch {
      return isoString;
    }
  }

  function capitalize(s) {
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  // ── Create job ─────────────────────────────────────────────────────────────

  form.addEventListener("submit", (e) => {
    e.preventDefault();

    const targetJid = useManualInput
      ? manualPhone.value.trim()
      : targetContact.value;
    const message = document.getElementById("jobMessage").value.trim();
    const type = scheduleType.value;

    if (!targetJid || !message) {
      alert("Please fill in all required fields.");
      return;
    }

    const payload = {
      target_jid: targetJid,
      message: message,
      schedule_type: type,
    };

    if (type === "once") {
      const scheduledAt = document.getElementById("scheduledAt").value;
      if (!scheduledAt) {
        alert("Please select a date and time.");
        return;
      }
      payload.scheduled_at = new Date(scheduledAt).toISOString().slice(0, 19);
    } else {
      payload.frequency = frequency.value;
      payload.time_of_day = document.getElementById("timeOfDay").value;
      if (frequency.value === "weekly") {
        payload.day_of_week = document.getElementById("dayOfWeek").value;
      }
    }

    const btn = form.querySelector(".create-job-btn");
    btn.disabled = true;
    btn.textContent = "Creating...";

    fetch("/api/cron-jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.success) {
          form.reset();
          scheduleType.dispatchEvent(new Event("change"));
          loadJobs();
        } else {
          alert(data.message || "Failed to create job");
        }
      })
      .catch((err) => {
        console.error("Failed to create job:", err);
        alert("Failed to create job");
      })
      .finally(() => {
        btn.disabled = false;
        btn.textContent = "Create Job";
      });
  });

  // ── Toggle / Delete ────────────────────────────────────────────────────────

  function toggleJob(jobId) {
    fetch(`/api/cron-jobs/${jobId}/toggle`, { method: "POST" })
      .then((r) => r.json())
      .then((data) => {
        if (data.success) loadJobs();
        else alert(data.message || "Failed to toggle job");
      })
      .catch((err) => console.error("Failed to toggle job:", err));
  }

  function deleteJob(jobId) {
    if (!confirm("Delete this scheduled job?")) return;
    fetch(`/api/cron-jobs/${jobId}`, { method: "DELETE" })
      .then((r) => r.json())
      .then((data) => {
        if (data.success) loadJobs();
        else alert(data.message || "Failed to delete job");
      })
      .catch((err) => console.error("Failed to delete job:", err));
  }

  // ── Init ───────────────────────────────────────────────────────────────────

  loadContacts();
  loadJobs();
  setInterval(loadJobs, 30000);
});
