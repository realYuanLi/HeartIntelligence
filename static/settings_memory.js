document.addEventListener("DOMContentLoaded", () => {
  if (!location.pathname.startsWith("/settings/memory")) return;

  const longTermList = document.getElementById("longTermList");
  const shortTermList = document.getElementById("shortTermList");
  const addForm = document.getElementById("addMemoryForm");

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function formatTimeRemaining(ts, ttl) {
    if (ttl === null || ttl === undefined) return "permanent";
    const expiresAt = (ts + ttl) * 1000;
    const remaining = expiresAt - Date.now();
    if (remaining <= 0) return "expired";
    const days = Math.floor(remaining / 86400000);
    const hours = Math.floor((remaining % 86400000) / 3600000);
    if (days > 0) return `expires in ${days}d ${hours}h`;
    const mins = Math.floor((remaining % 3600000) / 60000);
    if (hours > 0) return `expires in ${hours}h ${mins}m`;
    return `expires in ${mins}m`;
  }

  function loadMemories() {
    fetch("/api/memory")
      .then((r) => r.json())
      .then((data) => {
        if (!data.success) {
          longTermList.innerHTML = '<div class="no-data">Failed to load</div>';
          return;
        }
        renderLongTerm(data.memory.long_term || []);
        renderShortTerm(data.memory.short_term || {});
      })
      .catch((err) => {
        console.error("Failed to load memories:", err);
        longTermList.innerHTML = '<div class="error">Failed to load memories</div>';
      });
  }

  function renderLongTerm(entries) {
    if (!entries.length) {
      longTermList.innerHTML = '<div class="no-data">No long-term memories stored.</div>';
      return;
    }
    // Group by category
    const grouped = {};
    entries.forEach((e) => {
      const cat = e.category || "unknown";
      if (!grouped[cat]) grouped[cat] = [];
      grouped[cat].push(e);
    });

    longTermList.innerHTML = "";
    for (const [cat, items] of Object.entries(grouped)) {
      const header = document.createElement("div");
      header.style.cssText = "font-weight:600;margin:12px 0 6px;text-transform:capitalize;color:#aaa;font-size:0.85em;";
      header.textContent = cat;
      longTermList.appendChild(header);

      items.forEach((entry) => {
        const card = document.createElement("div");
        card.className = "job-card";
        const ttlText = formatTimeRemaining(entry.ts, entry.ttl);
        const notesHtml = entry.notes ? `<div style="color:#888;font-size:0.85em;margin-top:2px;">${escapeHtml(entry.notes)}</div>` : "";
        const contextHtml = entry.context ? `<div style="color:#7a7adb;font-size:0.82em;margin-top:2px;">Context: ${escapeHtml(entry.context)}</div>` : "";
        const evergreenBadge = entry.evergreen ? `<span style="background:#2d6a4f;color:#b7e4c7;font-size:0.7em;padding:2px 6px;border-radius:4px;margin-left:6px;vertical-align:middle;">Evergreen</span>` : "";
        const accessCount = entry.access_count || 0;
        card.innerHTML = `
          <div class="job-card-header">
            <div class="job-info">
              <div class="job-message">${escapeHtml(entry.value)}${evergreenBadge}</div>
              ${notesHtml}
              ${contextHtml}
              <div class="job-meta">
                <span class="job-target">${escapeHtml(entry.key)} &middot; ${ttlText} &middot; accessed ${accessCount} times</span>
              </div>
            </div>
            <div class="job-actions">
              <button class="job-delete-btn" title="Delete">&#x2715;</button>
            </div>
          </div>
        `;
        card.querySelector(".job-delete-btn").addEventListener("click", () => {
          deleteMemory(entry.key);
        });
        longTermList.appendChild(card);
      });
    }
  }

  function renderShortTerm(shortTerm) {
    const allEntries = [];
    for (const [cat, entries] of Object.entries(shortTerm)) {
      entries.forEach((e) => allEntries.push({ ...e, _category: cat }));
    }
    if (!allEntries.length) {
      shortTermList.innerHTML = '<div class="no-data">No short-term memories.</div>';
      return;
    }
    // Sort by timestamp descending
    allEntries.sort((a, b) => (b.ts || 0) - (a.ts || 0));

    shortTermList.innerHTML = "";
    allEntries.forEach((entry) => {
      const card = document.createElement("div");
      card.className = "job-card";
      const ttlText = formatTimeRemaining(entry.ts, entry.ttl);
      card.innerHTML = `
        <div class="job-card-header">
          <div class="job-info">
            <div class="job-message">${escapeHtml(entry.value)}</div>
            <div class="job-meta">
              <span class="job-target">${escapeHtml(entry._category)} &middot; ${ttlText}</span>
            </div>
          </div>
        </div>
      `;
      shortTermList.appendChild(card);
    });
  }

  function addMemory() {
    const category = document.getElementById("memCategory").value;
    const value = document.getElementById("memValue").value.trim();
    const notes = document.getElementById("memNotes").value.trim();
    const context = document.getElementById("memContext").value.trim();
    const evergreen = document.getElementById("memEvergreen").checked;
    if (!value) {
      alert("Please enter a value.");
      return;
    }
    fetch("/api/memory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category, value, notes: notes || undefined, context: context || undefined, evergreen }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.success) {
          document.getElementById("memValue").value = "";
          document.getElementById("memNotes").value = "";
          document.getElementById("memContext").value = "";
          document.getElementById("memEvergreen").checked = false;
          loadMemories();
        } else {
          alert(data.message || "Failed to add memory");
        }
      })
      .catch((err) => {
        console.error("Failed to add memory:", err);
        alert("Failed to add memory");
      });
  }

  function deleteMemory(key) {
    if (!confirm("Delete this memory?")) return;
    fetch(`/api/memory/${encodeURIComponent(key)}`, { method: "DELETE" })
      .then((r) => r.json())
      .then((data) => {
        if (data.success) loadMemories();
        else alert(data.message || "Failed to delete");
      })
      .catch((err) => {
        console.error("Failed to delete memory:", err);
        alert("Failed to delete memory");
      });
  }

  if (addForm) {
    addForm.addEventListener("submit", (e) => {
      e.preventDefault();
      addMemory();
    });
  }

  loadMemories();
});
