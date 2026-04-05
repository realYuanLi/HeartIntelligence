(function () {
  "use strict";

  const membersList = document.getElementById("membersList");
  const invitationsCard = document.getElementById("invitationsCard");
  const invitationsList = document.getElementById("invitationsList");
  const shareCard = document.getElementById("shareCard");
  const shareTo = document.getElementById("shareTo");
  const sharedList = document.getElementById("sharedList");

  // ── Helpers ──────────────────────────────────────────────────────────────

  async function api(url, opts) {
    const res = await fetch(url, opts);
    return res.json();
  }

  function relTime(iso) {
    const d = new Date(iso);
    const diff = Date.now() - d.getTime();
    if (diff < 60000) return "just now";
    if (diff < 3600000) return Math.floor(diff / 60000) + "m ago";
    if (diff < 86400000) return Math.floor(diff / 3600000) + "h ago";
    return d.toLocaleDateString();
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  // ── Load family data ────────────────────────────────────────────────────

  async function load() {
    const [membersData, sharedData] = await Promise.all([
      api("/api/family/members"),
      api("/api/family/shared"),
    ]);

    renderMembers(membersData);
    renderInvitations(membersData.invitations || []);
    renderShared(sharedData);
    populateShareDropdown(membersData.members || []);
  }

  // ── Render members ──────────────────────────────────────────────────────

  function renderMembers(data) {
    const members = (data.members || []).filter((m) => m.status === "accepted");
    if (!members.length) {
      membersList.innerHTML =
        '<div class="empty-state">No family members yet. Send an invite above.</div>';
      return;
    }
    membersList.innerHTML = members
      .map(
        (m) => `
      <div class="family-member-row">
        <div class="member-info">
          <span class="member-email">${escapeHtml(m.email)}</span>
          <span class="member-rel">${escapeHtml(m.relationship)}</span>
        </div>
        <button class="family-btn danger small" data-remove="${m.id}">Remove</button>
      </div>`
      )
      .join("");

    membersList.querySelectorAll("[data-remove]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api("/api/family/remove", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ link_id: Number(btn.dataset.remove) }),
        });
        load();
      });
    });
  }

  // ── Render pending invitations ──────────────────────────────────────────

  function renderInvitations(invitations) {
    if (!invitations.length) {
      invitationsCard.hidden = true;
      return;
    }
    invitationsCard.hidden = false;
    invitationsList.innerHTML = invitations
      .map(
        (inv) => `
      <div class="invitation-row">
        <div class="member-info">
          <span class="member-email">${escapeHtml(inv.from_email)}</span>
          <span class="member-rel">${escapeHtml(inv.relationship)}</span>
        </div>
        <div class="invitation-actions">
          <button class="family-btn primary small" data-accept="${inv.id}">Accept</button>
          <button class="family-btn danger small" data-decline="${inv.id}">Decline</button>
        </div>
      </div>`
      )
      .join("");

    invitationsList.querySelectorAll("[data-accept],[data-decline]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const action = btn.dataset.accept ? "accept" : "decline";
        const linkId = Number(btn.dataset.accept || btn.dataset.decline);
        await api("/api/family/respond", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ link_id: linkId, action }),
        });
        load();
      });
    });
  }

  // ── Populate share dropdown with accepted members ───────────────────────

  function populateShareDropdown(members) {
    const accepted = members.filter((m) => m.status === "accepted");
    if (!accepted.length) {
      shareCard.hidden = true;
      return;
    }
    shareCard.hidden = false;
    shareTo.innerHTML =
      '<option value="">Select a family member...</option>' +
      accepted.map((m) => `<option value="${escapeHtml(m.email)}">${escapeHtml(m.email)} (${escapeHtml(m.relationship)})</option>`).join("");
  }

  // ── Render shared summaries ─────────────────────────────────────────────

  function renderShared(data) {
    const received = data.received || [];
    const sent = data.sent || [];
    if (!received.length && !sent.length) {
      sharedList.innerHTML =
        '<div class="empty-state">No shared summaries yet.</div>';
      return;
    }
    let html = "";
    if (received.length) {
      html += '<div class="shared-section-label">Received</div>';
      html += received
        .map(
          (s) => `
        <div class="shared-item">
          <div class="shared-meta">From <strong>${escapeHtml(s.from_email)}</strong> &middot; ${relTime(s.created_at)}</div>
          <div class="shared-title">${escapeHtml(s.title)}</div>
          <div class="shared-body">${escapeHtml(s.body)}</div>
        </div>`
        )
        .join("");
    }
    if (sent.length) {
      html += '<div class="shared-section-label">Sent</div>';
      html += sent
        .map(
          (s) => `
        <div class="shared-item sent">
          <div class="shared-meta">To <strong>${escapeHtml(s.to_email)}</strong> &middot; ${relTime(s.created_at)}</div>
          <div class="shared-title">${escapeHtml(s.title)}</div>
          <div class="shared-body">${escapeHtml(s.body)}</div>
        </div>`
        )
        .join("");
    }
    sharedList.innerHTML = html;
  }

  // ── Form handlers ───────────────────────────────────────────────────────

  document.getElementById("inviteForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = document.getElementById("inviteEmail").value.trim();
    const relationship = document.getElementById("relationship").value;
    if (!email) return;
    const res = await api("/api/family/invite", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, relationship }),
    });
    if (res.success) {
      document.getElementById("inviteEmail").value = "";
      load();
    } else {
      alert(res.message || "Failed to send invite");
    }
  });

  document.getElementById("shareForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const toEmail = shareTo.value;
    const title = document.getElementById("shareTitle").value.trim();
    const body = document.getElementById("shareBody").value.trim();
    if (!toEmail || !title || !body) return;
    const res = await api("/api/family/share", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to_email: toEmail, title, body }),
    });
    if (res.success) {
      document.getElementById("shareTitle").value = "";
      document.getElementById("shareBody").value = "";
      load();
    } else {
      alert(res.message || "Failed to share");
    }
  });

  // ── Init ────────────────────────────────────────────────────────────────
  load();
})();
