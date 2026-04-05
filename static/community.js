(function () {
  "use strict";

  const communityList = document.getElementById("communityList");
  const detailPanel = document.getElementById("communityDetail");
  const detailName = document.getElementById("detailName");
  const detailTopic = document.getElementById("detailTopic");
  const detailDesc = document.getElementById("detailDesc");
  const detailMembers = document.getElementById("detailMembers");
  const feedList = document.getElementById("feedList");
  const postForm = document.getElementById("postForm");

  let activeCommunityId = null;

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

  const topicColors = {
    fitness: "#e06030",
    nutrition: "#30a060",
    "mental-health": "#6050c0",
    "chronic-care": "#c05080",
    "weight-management": "#b08020",
    general: "#607090",
  };

  // ── Load community list ─────────────────────────────────────────────────

  async function loadList() {
    const data = await api("/api/community/list");
    renderList(data.communities || []);
  }

  function renderList(communities) {
    if (!communities.length) {
      communityList.innerHTML =
        '<div class="empty-state">No communities yet. Create one above!</div>';
      return;
    }
    communityList.innerHTML = communities
      .map(
        (c) => `
      <div class="community-row" data-id="${c.id}">
        <div class="community-row-info">
          <span class="community-name">${escapeHtml(c.name)}</span>
          <span class="topic-badge" style="background:${topicColors[c.topic] || topicColors.general}">${escapeHtml(c.topic)}</span>
          <span class="member-count">${c.member_count} member${c.member_count !== 1 ? "s" : ""}</span>
        </div>
        <div class="community-row-desc">${escapeHtml(c.description)}</div>
        <div class="community-row-actions">
          ${
            c.is_member
              ? `<button class="community-btn small" data-open="${c.id}">Open</button>
                 <button class="community-btn danger small" data-leave="${c.id}">Leave</button>`
              : `<button class="community-btn primary small" data-join="${c.id}">Join</button>`
          }
        </div>
      </div>`
      )
      .join("");

    communityList.querySelectorAll("[data-join]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api(`/api/community/${btn.dataset.join}/join`, { method: "POST" });
        loadList();
      });
    });
    communityList.querySelectorAll("[data-leave]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api(`/api/community/${btn.dataset.leave}/leave`, { method: "POST" });
        activeCommunityId = null;
        detailPanel.hidden = true;
        loadList();
      });
    });
    communityList.querySelectorAll("[data-open]").forEach((btn) => {
      btn.addEventListener("click", () => openCommunity(Number(btn.dataset.open)));
    });
  }

  // ── Open community detail & feed ────────────────────────────────────────

  async function openCommunity(cid) {
    activeCommunityId = cid;
    detailPanel.hidden = false;
    const data = await api(`/api/community/${cid}/feed`);
    const c = data.community;
    detailName.textContent = c.name;
    detailTopic.textContent = c.topic;
    detailTopic.style.background = topicColors[c.topic] || topicColors.general;
    detailDesc.textContent = c.description;
    detailMembers.textContent = `${c.member_count} member${c.member_count !== 1 ? "s" : ""}`;
    renderFeed(data.posts || []);
    detailPanel.scrollIntoView({ behavior: "smooth" });
  }

  function renderFeed(posts) {
    if (!posts.length) {
      feedList.innerHTML =
        '<div class="empty-state">No posts yet. Be the first to share!</div>';
      return;
    }
    feedList.innerHTML = posts
      .map(
        (p) => `
      <div class="feed-post">
        <div class="feed-meta"><strong>${escapeHtml(p.author)}</strong> &middot; ${relTime(p.created_at)}</div>
        <div class="feed-content">${escapeHtml(p.content)}</div>
      </div>`
      )
      .join("");
  }

  // ── Form handlers ───────────────────────────────────────────────────────

  document.getElementById("createCommunityForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = document.getElementById("communityName").value.trim();
    const topic = document.getElementById("communityTopic").value;
    const description = document.getElementById("communityDesc").value.trim();
    if (!name) return;
    const res = await api("/api/community/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, topic, description }),
    });
    if (res.success) {
      document.getElementById("communityName").value = "";
      document.getElementById("communityDesc").value = "";
      loadList();
    } else {
      alert(res.message || "Failed to create community");
    }
  });

  postForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!activeCommunityId) return;
    const content = document.getElementById("postContent").value.trim();
    if (!content) return;
    const res = await api(`/api/community/${activeCommunityId}/post`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (res.success) {
      document.getElementById("postContent").value = "";
      openCommunity(activeCommunityId);
    } else {
      alert(res.message || "Failed to post");
    }
  });

  // ── Init ────────────────────────────────────────────────────────────────
  loadList();
})();
