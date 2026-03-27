document.addEventListener("DOMContentLoaded", () => {
  if (!location.pathname.startsWith("/settings/whatsapp")) return;

  const statusEl = document.getElementById("waStatus");
  let pollTimer = null;

  // ── Render status ───────────────────────────────────────────────────────

  function renderDisconnected(warning) {
    let warningHtml = "";
    if (warning) {
      warningHtml = `
        <div class="heartbeat-stat heartbeat-stat-wide">
          <div class="heartbeat-stat-value" style="color:#f59e0b;">${escapeHtml(warning)}</div>
        </div>`;
    }
    statusEl.innerHTML = `
      <div class="heartbeat-stat">
        <div class="heartbeat-stat-label">Status</div>
        <div class="heartbeat-stat-value">
          <span class="job-status inactive">Disconnected</span>
        </div>
      </div>
      ${warningHtml}
      <div class="heartbeat-stat heartbeat-stat-wide" style="margin-top:12px;">
        <button id="waConnectBtn" class="create-job-btn">Connect WhatsApp</button>
      </div>
    `;
    document.getElementById("waConnectBtn").addEventListener("click", doConnect);
  }

  function renderConnecting() {
    statusEl.innerHTML = `
      <div class="heartbeat-stat">
        <div class="heartbeat-stat-label">Status</div>
        <div class="heartbeat-stat-value">
          <span class="job-status" style="background:#3b82f6;">Connecting...</span>
        </div>
      </div>
      <div class="heartbeat-stat heartbeat-stat-wide" style="margin-top:12px;">
        <div class="loading">Waiting for QR code...</div>
      </div>
    `;
  }

  function renderQr(qrDataUrl) {
    statusEl.innerHTML = `
      <div class="heartbeat-stat">
        <div class="heartbeat-stat-label">Status</div>
        <div class="heartbeat-stat-value">
          <span class="job-status" style="background:#8b5cf6;">Scan QR Code</span>
        </div>
      </div>
      <div class="heartbeat-stat heartbeat-stat-wide" style="text-align:center;margin-top:12px;">
        <p style="color:#a0a0b0;margin-bottom:12px;">Open WhatsApp on your phone, go to <strong>Linked Devices</strong>, and scan this QR code.</p>
        <img id="waQrImage" src="${qrDataUrl}" alt="WhatsApp QR Code"
             style="max-width:300px;border-radius:8px;background:#fff;padding:8px;" />
      </div>
      <div class="heartbeat-stat heartbeat-stat-wide" style="margin-top:12px;">
        <button id="waCancelBtn" class="create-job-btn" style="background:#ef4444;">Cancel</button>
      </div>
    `;
    document.getElementById("waCancelBtn").addEventListener("click", doDisconnect);
  }

  function renderConnected(phoneNumber) {
    statusEl.innerHTML = `
      <div class="heartbeat-stat">
        <div class="heartbeat-stat-label">Status</div>
        <div class="heartbeat-stat-value">
          <span class="job-status active">Connected</span>
        </div>
      </div>
      <div class="heartbeat-stat">
        <div class="heartbeat-stat-label">Phone Number</div>
        <div class="heartbeat-stat-value">${escapeHtml(phoneNumber || "Unknown")}</div>
      </div>
      <div class="heartbeat-stat heartbeat-stat-wide" style="margin-top:12px;">
        <button id="waDisconnectBtn" class="create-job-btn" style="background:#ef4444;">Disconnect</button>
      </div>
    `;
    document.getElementById("waDisconnectBtn").addEventListener("click", () => {
      if (confirm("Disconnect your WhatsApp account?")) {
        doDisconnect();
      }
    });
  }

  // ── Actions ─────────────────────────────────────────────────────────────

  function doConnect() {
    renderConnecting();
    fetch("/api/whatsapp/connect", { method: "POST" })
      .then((r) => r.json())
      .then((data) => {
        if (data.success) {
          startPolling();
        } else {
          renderDisconnected(data.message || "Failed to connect");
        }
      })
      .catch((err) => {
        console.error("Connect failed:", err);
        renderDisconnected("Failed to connect to server");
      });
  }

  function doDisconnect() {
    stopPolling();
    fetch("/api/whatsapp/disconnect", { method: "POST" })
      .then((r) => r.json())
      .then(() => {
        renderDisconnected();
      })
      .catch((err) => {
        console.error("Disconnect failed:", err);
        loadStatus();
      });
  }

  // ── Polling ─────────────────────────────────────────────────────────────

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(loadStatus, 2000);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function loadStatus() {
    fetch("/api/whatsapp/status")
      .then((r) => r.json())
      .then((data) => {
        const status = data.status || "disconnected";

        switch (status) {
          case "connected":
            stopPolling();
            renderConnected(data.phone_number);
            break;
          case "qr":
            if (!pollTimer) startPolling();
            renderQr(data.qr_data_url);
            break;
          case "connecting":
            if (!pollTimer) startPolling();
            renderConnecting();
            break;
          case "disconnected":
          default:
            stopPolling();
            renderDisconnected(data.warning);
            break;
        }
      })
      .catch((err) => {
        console.error("Status check failed:", err);
        stopPolling();
        renderDisconnected("Failed to check status");
      });
  }

  // ── Helpers ─────────────────────────────────────────────────────────────

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  // ── Init ────────────────────────────────────────────────────────────────

  loadStatus();
});
