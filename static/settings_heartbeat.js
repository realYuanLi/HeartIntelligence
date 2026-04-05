document.addEventListener("DOMContentLoaded", () => {
  if (!location.pathname.startsWith("/settings/heartbeat")) return;

  const form = document.getElementById("heartbeatForm");
  const statusEl = document.getElementById("heartbeatStatus");

  // ── Load config ──────────────────────────────────────────────────────────

  function loadConfig() {
    fetch("/api/heartbeat/config")
      .then((r) => r.json())
      .then((data) => {
        if (!data.success) return;
        const c = data.config;
        document.getElementById("hbEnabled").checked = c.enabled;
        document.getElementById("hbInterval").value = String(c.interval_minutes);
        document.getElementById("hbActiveStart").value = c.active_hours_start;
        document.getElementById("hbActiveEnd").value = c.active_hours_end;
        document.getElementById("hbDelivery").value = c.delivery_method;
        document.getElementById("hbMaxMessages").value = c.max_messages_per_day;
        document.getElementById("hbUsername").value = c.username || "";
        document.getElementById("hbSessionId").value = c.target_session_id || "";

        toggleDeliveryFields(c.delivery_method);
        if (c.target_jid) {
          // Try to select existing contact, fall back to manual
          const select = document.getElementById("hbTargetContact");
          let found = false;
          for (const opt of select.options) {
            if (opt.value === c.target_jid) {
              opt.selected = true;
              found = true;
              break;
            }
          }
          if (!found && c.target_jid) {
            document.getElementById("hbManualPhone").value = c.target_jid.replace("@s.whatsapp.net", "");
            document.getElementById("hbManualPhone").classList.remove("hidden");
          }
        }
      })
      .catch((err) => console.error("Failed to load heartbeat config:", err));
  }

  // ── Load status ──────────────────────────────────────────────────────────

  function loadStatus() {
    fetch("/api/heartbeat/status")
      .then((r) => r.json())
      .then((data) => {
        if (!data.success) {
          statusEl.innerHTML = '<div class="no-data">Failed to load status</div>';
          return;
        }
        const s = data.status;
        const enabled = s.enabled
          ? '<span class="job-status active">Active</span>'
          : '<span class="job-status inactive">Disabled</span>';

        const lastRun = s.last_run_at
          ? new Date(s.last_run_at).toLocaleString()
          : "Never";
        const lastMsg = s.last_message_at
          ? new Date(s.last_message_at).toLocaleString()
          : "None yet";
        const nextRun =
          s.next_run_in_minutes != null
            ? `~${s.next_run_in_minutes} min`
            : "N/A";

        statusEl.innerHTML = `
          <div class="heartbeat-stat">
            <div class="heartbeat-stat-label">Status</div>
            <div class="heartbeat-stat-value">${enabled}</div>
          </div>
          <div class="heartbeat-stat">
            <div class="heartbeat-stat-label">Last Check</div>
            <div class="heartbeat-stat-value">${lastRun}</div>
          </div>
          <div class="heartbeat-stat">
            <div class="heartbeat-stat-label">Last Message Sent</div>
            <div class="heartbeat-stat-value">${lastMsg}</div>
          </div>
          <div class="heartbeat-stat">
            <div class="heartbeat-stat-label">Messages Today</div>
            <div class="heartbeat-stat-value">${s.messages_today}</div>
          </div>
          <div class="heartbeat-stat">
            <div class="heartbeat-stat-label">Next Check In</div>
            <div class="heartbeat-stat-value">${nextRun}</div>
          </div>
          ${s.last_message_preview ? `
          <div class="heartbeat-stat heartbeat-stat-wide">
            <div class="heartbeat-stat-label">Last Message</div>
            <div class="heartbeat-stat-value heartbeat-preview">${escapeHtml(s.last_message_preview)}</div>
          </div>` : ""}
        `;
      })
      .catch((err) => {
        console.error("Failed to load heartbeat status:", err);
        statusEl.innerHTML = '<div class="error">Failed to load status</div>';
      });
  }

  // ── Load WhatsApp contacts ───────────────────────────────────────────────

  function loadContacts() {
    fetch("/api/whatsapp/contacts")
      .then((r) => r.json())
      .then((data) => {
        if (!data.success) return;
        const select = document.getElementById("hbTargetContact");
        select.innerHTML = '<option value="">Select a contact...</option>';
        (data.contacts || []).forEach((c) => {
          const opt = document.createElement("option");
          opt.value = c.jid;
          opt.textContent = c.name || c.jid;
          select.appendChild(opt);
        });
      })
      .catch(() => {});
  }

  // ── Delivery method toggle ───────────────────────────────────────────────

  function toggleDeliveryFields(method) {
    const waTarget = document.getElementById("hbWhatsappTarget");
    const webTarget = document.getElementById("hbWebTarget");
    if (method === "whatsapp") {
      waTarget.classList.remove("hidden");
      webTarget.classList.add("hidden");
    } else {
      waTarget.classList.add("hidden");
      webTarget.classList.remove("hidden");
    }
  }

  document.getElementById("hbDelivery").addEventListener("change", (e) => {
    toggleDeliveryFields(e.target.value);
  });

  // Manual phone toggle
  document.getElementById("hbToggleManual").addEventListener("click", (e) => {
    e.preventDefault();
    document.getElementById("hbManualPhone").classList.toggle("hidden");
  });

  // ── Save config ──────────────────────────────────────────────────────────

  form.addEventListener("submit", (e) => {
    e.preventDefault();

    const delivery = document.getElementById("hbDelivery").value;
    let targetJid = "";
    if (delivery === "whatsapp") {
      targetJid = document.getElementById("hbTargetContact").value;
      const manual = document.getElementById("hbManualPhone").value.trim();
      if (!targetJid && manual) {
        const cleaned = manual.replace(/\D/g, "");
        targetJid = cleaned ? cleaned + "@s.whatsapp.net" : "";
      }
    }

    const config = {
      enabled: document.getElementById("hbEnabled").checked,
      interval_minutes: parseInt(document.getElementById("hbInterval").value, 10),
      active_hours_start: document.getElementById("hbActiveStart").value,
      active_hours_end: document.getElementById("hbActiveEnd").value,
      delivery_method: delivery,
      target_jid: targetJid,
      target_session_id: document.getElementById("hbSessionId").value.trim(),
      max_messages_per_day: parseInt(document.getElementById("hbMaxMessages").value, 10),
      username: document.getElementById("hbUsername").value.trim(),
    };

    fetch("/api/heartbeat/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.success) {
          showToast("Configuration saved");
          loadStatus();
        } else {
          alert(data.message || "Failed to save");
        }
      })
      .catch((err) => {
        console.error("Failed to save heartbeat config:", err);
        alert("Failed to save configuration");
      });
  });

  // ── Helpers ──────────────────────────────────────────────────────────────

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function showToast(msg) {
    const toast = document.createElement("div");
    toast.className = "heartbeat-toast";
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => toast.classList.add("show"), 10);
    setTimeout(() => {
      toast.classList.remove("show");
      setTimeout(() => toast.remove(), 300);
    }, 2000);
  }

  // ── Init ─────────────────────────────────────────────────────────────────

  loadContacts();
  loadConfig();
  loadStatus();
  setInterval(loadStatus, 60000);
});
