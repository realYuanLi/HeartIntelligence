document.addEventListener("DOMContentLoaded", () => {
  if (!location.pathname.startsWith("/settings/skills")) return;

  const skillsList = document.getElementById("skillsList");
  if (!skillsList) return;

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function loadSkills() {
    fetch("/api/settings/skills")
      .then((r) => r.json())
      .then((data) => {
        if (!data.success) {
          skillsList.innerHTML = '<div class="no-data">Failed to load skills</div>';
          return;
        }
        renderSkills(data.skills || []);
      })
      .catch((err) => {
        console.error("Failed to load skills:", err);
        skillsList.innerHTML = '<div class="error">Failed to load skills</div>';
      });
  }

  function renderSkills(skills) {
    if (!skills.length) {
      skillsList.innerHTML = '<div class="no-data">No skills found.</div>';
      return;
    }

    skillsList.innerHTML = "";
    skills.forEach((skill) => {
      const card = document.createElement("div");
      card.className = `job-card settings-skill-card ${skill.enabled ? "" : "disabled"}`;
      card.innerHTML = `
        <div class="job-card-header">
          <div class="job-info">
            <div class="job-message">${escapeHtml(skill.name || skill.id)}</div>
            <div class="job-meta">
              <span class="job-target">${escapeHtml(skill.description || "No description")}</span>
            </div>
          </div>
          <div class="job-actions">
            <span class="job-status ${skill.enabled ? "active" : "inactive"}">${skill.enabled ? "Enabled" : "Disabled"}</span>
            <button class="job-toggle-btn" title="${skill.enabled ? "Disable" : "Enable"}">
              ${skill.enabled ? "⏸" : "▶"}
            </button>
          </div>
        </div>
      `;
      card.querySelector(".job-toggle-btn").addEventListener("click", () => {
        toggleSkill(skill.id, !skill.enabled);
      });
      skillsList.appendChild(card);
    });
  }

  function toggleSkill(skillId, enabled) {
    fetch(`/api/settings/skills/${encodeURIComponent(skillId)}/toggle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.success) loadSkills();
        else alert(data.message || "Failed to toggle skill");
      })
      .catch((err) => {
        console.error("Failed to toggle skill:", err);
        alert("Failed to toggle skill");
      });
  }

  loadSkills();
  setInterval(loadSkills, 30000);
});
