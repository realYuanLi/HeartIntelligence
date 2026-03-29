document.addEventListener("DOMContentLoaded", () => {
  if (!location.pathname.startsWith("/settings/whatsapp")) return;

  const statusEl = document.getElementById("waStatus");
  let pollTimer = null;
  let eventSource = null;

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
        <div class="wa-qr-instructions">
          <p><strong>Step 1:</strong> Open WhatsApp on your phone</p>
          <p><strong>Step 2:</strong> Tap <strong>Settings</strong> &gt; <strong>Linked Devices</strong></p>
          <p><strong>Step 3:</strong> Tap <strong>Link a Device</strong> and point your camera at the code below</p>
        </div>
        <img id="waQrImage" src="${qrDataUrl}" alt="WhatsApp QR Code"
             style="max-width:300px;border-radius:8px;background:#fff;padding:8px;margin-top:12px;" />
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
      <div class="heartbeat-stat heartbeat-stat-wide" style="margin-top:8px;color:#a0a0b0;font-size:0.9em;">
        Your WhatsApp is linked. Messages you send to yourself will be answered by the health assistant.
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
          startSseStream();
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
    closeSseStream();
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

  // ── SSE stream ─────────────────────────────────────────────────────────

  function startSseStream() {
    closeSseStream();
    stopPolling();

    try {
      eventSource = new EventSource("/api/whatsapp/qr-stream");

      eventSource.addEventListener("qr", (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data.qr_data_url) {
            renderQr(data.qr_data_url);
          }
        } catch (err) {
          console.error("Failed to parse QR event:", err);
        }
      });

      eventSource.addEventListener("status", (e) => {
        try {
          const data = JSON.parse(e.data);
          switch (data.status) {
            case "connected":
              closeSseStream();
              renderConnected(data.phone_number);
              break;
            case "qr":
              // QR without data URL — wait for next qr event
              break;
            case "connecting":
              renderConnecting();
              break;
            case "disconnected":
              closeSseStream();
              renderDisconnected(data.warning);
              break;
          }
        } catch (err) {
          console.error("Failed to parse status event:", err);
        }
      });

      eventSource.onerror = () => {
        console.warn("SSE connection error, falling back to polling");
        closeSseStream();
        startPolling();
      };
    } catch {
      // EventSource not supported or failed — fall back to polling
      console.warn("SSE not available, falling back to polling");
      startPolling();
    }
  }

  function closeSseStream() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  }

  // ── Polling (fallback) ─────────────────────────────────────────────────

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
            closeSseStream();
            renderConnected(data.phone_number);
            break;
          case "qr":
            if (!pollTimer && !eventSource) startPolling();
            renderQr(data.qr_data_url);
            break;
          case "connecting":
            if (!pollTimer && !eventSource) startPolling();
            renderConnecting();
            break;
          case "disconnected":
          default:
            stopPolling();
            closeSseStream();
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

  // On initial load, check status. If already in connecting/qr state, use SSE.
  fetch("/api/whatsapp/status")
    .then((r) => r.json())
    .then((data) => {
      const status = data.status || "disconnected";

      // Render current state
      switch (status) {
        case "connected":
          renderConnected(data.phone_number);
          break;
        case "qr":
          renderQr(data.qr_data_url);
          startSseStream();
          break;
        case "connecting":
          renderConnecting();
          startSseStream();
          break;
        case "disconnected":
        default:
          renderDisconnected(data.warning);
          break;
      }
    })
    .catch((err) => {
      console.error("Status check failed:", err);
      renderDisconnected("Failed to check status");
    });
});
