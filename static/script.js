/*********************************************************************
 *  script.js  —  Front-end logic for DREAM Assistant
 *
 *  • Login / logout / load history
 *  • Create new session or continue a chat
 *  • Sequential “thinking” bubbles during long back-end calls
 *      – each step appears every 6 s
 *      – only the newest bubble pulses (CSS animation)
 *********************************************************************/

/* ========================================================= */
/*  Thinking animation helpers                                */
/* ========================================================= */
let thinkingTimers = [];          // timeout handles
let currentSteps   = [];          // active sequence (array of strings)
let isErpThinking  = false;       // distinguishes ERP vs. profile sequence

const profileThinkingSteps = [
  "🔎 Reviewing patient’s triggers, obsessions, and feared consequences",
  "🔁 Reviewing patient’s compulsive behaviors and avoidance strategies",
  "🩺 Reviewing possibly relevant symptoms",
  "🧠 Reviewing possibly relevant internal triggers and beliefs",
  "🔢 Ranking and selecting most likely related symptoms",
  "🧪 Performing functional analysis of compulsions and avoidance strategies",
  "📝 Generating a personalized symptom summary"
];

const erpThinkingSteps = [
  "🔍 Analyzing patient’s symptoms",
  "📚 Reviewing expert ERP hierarchies",
  "🛠️ Generating personalized ERP activities",
  "🔢 Sorting ERP activities by difficulty",
  "🧠 Checking for imaginal exposure opportunities",
  "🔟 Selecting 10 best ERP activities",
  "📝 Constructing full ERP hierarchy"
];

/** Start a sequential thinking animation. */
function startThinking(steps) {
  stopThinking();                 // ensure clean state
  currentSteps = steps.slice();

  const chat = document.getElementById("chatContent");

  steps.forEach((text, idx) => {
    const timer = setTimeout(() => {
      const prev = document.querySelector(".thinking-emoji.active");
      if (prev) prev.classList.remove("active");

      const div       = document.createElement("div");
      div.className   = "message assistant thinking-step";
      div.innerHTML   = `<span class="thinking-emoji active">${text}</span>`;
      chat.appendChild(div);
      chat.scrollTop = chat.scrollHeight;
    }, idx * 6000);
    thinkingTimers.push(timer);
  });
}

/** Cancel timers and remove all thinking bubbles. */
function stopThinking() {
  thinkingTimers.forEach(t => clearTimeout(t));
  thinkingTimers = [];
  document.querySelectorAll(".thinking-step").forEach(n => n.remove());
  currentSteps = [];
}

/** Return true for strings that begin with “y” (yes-like answers). */
function isYesLike(str) {
  return str.trim().toLowerCase().startsWith("y");
}

/* ========================================================= */
/*  DOM ready                                                 */
/* ========================================================= */
document.addEventListener("DOMContentLoaded", () => {
  /* ---------- Grab common DOM elements ---------- */
  const loginBtn    = document.getElementById("loginBtn");
  const logoutBtn   = document.getElementById("logoutBtn");
  const overlay     = document.getElementById("overlay");
  const loginSubmit = document.getElementById("loginSubmit");
  const recentsList = document.getElementById("recentsList");
  const newChatBtn  = document.getElementById("newChatBtn");
  const textInput   = document.getElementById("textInput");
  const sendBtn     = document.getElementById("sendBtn");

  /* ---------------- Theme toggle (light/dark) ---------------- */
  const themeSwitch = document.getElementById("themeSwitch");
  const savedTheme = localStorage.getItem("theme") || "dark";
  if (savedTheme === "light") {
    document.body.classList.add("light");
    if (themeSwitch) themeSwitch.checked = true;
  }
  if (themeSwitch) {
    themeSwitch.addEventListener("change", () => {
      const useLight = themeSwitch.checked;
      document.body.classList.toggle("light", useLight);
      localStorage.setItem("theme", useLight ? "light" : "dark");
    });
  }
  /* ----------------------------------------------------------- */

  /* ==================================================== */
  /*  Authentication                                      */
  /* ==================================================== */
  logoutBtn.hidden = loginBtn.textContent.trim() === "Login";

  loginBtn.addEventListener("click", () => {
    if (loginBtn.textContent.trim() === "Login") overlay.style.display = "flex";
  });
  overlay.addEventListener("click", e => {
    if (e.target === overlay) overlay.style.display = "none";
  });

  loginSubmit.addEventListener("click", () => {
    const username = document.getElementById("loginUser").value;
    const password = document.getElementById("loginPass").value;
    fetch("/api/login", {
      method : "POST",
      headers: { "Content-Type": "application/json" },
      body   : JSON.stringify({ username, password })
    })
    .then(r => r.json())
    .then(d => {
      if (d.success) {
        overlay.style.display = "none";
        loginBtn.textContent  = username;
        logoutBtn.hidden      = false;
        loadHistory();
      } else alert(d.message);
    });
  });

  logoutBtn.addEventListener("click", () => {
    fetch("/api/logout", { method: "POST" })
      .then(r => r.json())
      .then(d => {
        if (d.success) {
          loginBtn.textContent = "Login";
          logoutBtn.hidden     = true;
          recentsList.innerHTML = "";
        }
      });
  });

  /* ==================================================== */
  /*  Recent conversations sidebar                         */
  /* ==================================================== */
  function loadHistory() {
    fetch("/api/history")
      .then(r => r.json())
      .then(list => {
        recentsList.innerHTML = "";
        list.forEach(addRecentItem);
      });
  }

  function addRecentItem(item) {
    const wrapper = document.createElement("div");
    wrapper.className = "recent-item";

    const span = document.createElement("span");
    span.className = "recent-title";
    span.textContent = item.title;
    span.addEventListener("click", () =>
      window.location.href = `/chat/${item.session_id}`
    );
    wrapper.appendChild(span);

    const more = document.createElement("button");
    more.className = "more-btn";
    more.textContent = "⋮";
    wrapper.appendChild(more);

    const menu = document.createElement("div");
    menu.className = "dropdown-menu";
    menu.style.display = "none";

    const rename = document.createElement("div");
    rename.className = "dropdown-item";
    rename.textContent = "Rename";
    menu.appendChild(rename);

    const del = document.createElement("div");
    del.className = "dropdown-item delete-item";
    del.textContent = "Delete";
    menu.appendChild(del);

    wrapper.appendChild(menu);
    recentsList.appendChild(wrapper);

    more.addEventListener("click", e => {
      e.stopPropagation();
      document.querySelectorAll(".dropdown-menu")
              .forEach(m => m.style.display = "none");
      menu.style.display = menu.style.display === "block" ? "none" : "block";
    });
    document.addEventListener("click", () => { menu.style.display = "none"; });

    rename.addEventListener("click", () => {
      const newTitle = prompt("Enter new title:", item.title);
      if (!newTitle) return;
      fetch("/api/rename_session", {
        method : "POST",
        headers: { "Content-Type": "application/json" },
        body   : JSON.stringify({ session_id: item.session_id, new_title: newTitle })
      })
      .then(r => r.json())
      .then(d => { if (d.success) loadHistory(); else alert(d.message); });
    });

    del.addEventListener("click", () => {
      if (!confirm("Delete this conversation?")) return;
      fetch("/api/delete_session", {
        method : "POST",
        headers: { "Content-Type": "application/json" },
        body   : JSON.stringify({ session_id: item.session_id })
      })
      .then(r => r.json())
      .then(d => { if (d.success) loadHistory(); else alert(d.message); });
    });
  }
  loadHistory();

  newChatBtn.addEventListener("click", () => window.location.href = "/new-chat");

  /* ==================================================== */
  /*  Send message / create session                        */
  /* ==================================================== */
  function sendMsg() {
    const text = textInput.value.trim();

    if (location.pathname === "/new-chat") {
      const firstText = text;             // 用户必须先输入
      if (!firstText) {
        alert("Please enter a message to start the chat.");
        return;
      }
      // 1) 创建会话
      fetch("/api/new_session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({})
      })
      .then(r => r.json())
      .then(d => {
        if (!d || !d.success) throw new Error(d && d.message || "Failed to start session");
        const sid = d.session_id;
        // 2) 立刻把这条输入作为对问候语的第一条回复发送
        return fetch("/api/message", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sid, message: firstText })
        }).then(() => sid);
      })
      .then(sid => {
        // 3) 跳转到聊天页（此时会话里已有问候、用户首条、以及模型回复）
        window.location.href = `/chat/${sid}`;
      })
      .catch(err => {
        console.error(err);
        alert("Failed to start chat: " + err.message);
      });
      return;
    }

    /* ---- Chat page ---- */
    if (!text) return; // in chat page we need user message
    if (location.pathname.startsWith("/chat/")) {
      const session_id = location.pathname.split("/").pop();
      appendMsg(text, "user");

      const lastAssistant = Array.from(
        document.querySelectorAll('#chatContent .message:not(.user)')
      ).pop()?.textContent || "";

      if (/submit the assessment to generate a patient profile\?/i.test(lastAssistant)
          && isYesLike(text)) {
        startThinking(profileThinkingSteps);
        isErpThinking = false;
      }
      if (/generate the ERP hierarchy now\?/i.test(lastAssistant)
          && isYesLike(text)) {
        startThinking(erpThinkingSteps);
        isErpThinking = true;
      }

      fetch("/api/message", {
        method : "POST",
        headers: { "Content-Type": "application/json" },
        body   : JSON.stringify({ session_id, message: text })
      })
      .then(r => r.json())
      .then(data => {
        const delay = currentSteps.length * 6000 + 300;
        setTimeout(() => {
          stopThinking();

          const push = msg =>
            appendMsg(msg, data.success ? "assistant" : "assistant-error");

          if (data.assistant_messages) data.assistant_messages.forEach(push);
          else if (data.assistant_message) push(data.assistant_message);

          if (data.done) {
            textInput.disabled = true;
            sendBtn.disabled   = true;
          }
        }, currentSteps.length ? delay : 0);
      })
      .catch(err => { stopThinking(); console.error(err); });

      textInput.value = "";
    }
  }

  sendBtn.addEventListener("click", sendMsg);
  textInput.addEventListener("keypress", e => { if (e.key === "Enter") sendMsg(); });

  /* ==================================================== */
  /*  Render conversation on page load                     */
  /* ==================================================== */
  if (location.pathname.startsWith("/chat/")) {
    const session_id = location.pathname.split("/").pop();
    fetch(`/api/session/${session_id}`)
      .then(r => r.json())
      .then(data => {
        const box = document.getElementById("chatContent");
        box.innerHTML = "";
        data.conversation.forEach(m => appendMsg(m.content, m.role));
        logoutBtn.hidden = loginBtn.textContent.trim() === "Login";
      });
  }

  /* ==================================================== */
  /*  Helper: render a bubble                              */
  /* ==================================================== */
  function appendMsg(text, role) {
    if (!text || !text.trim()) return;
    const box = document.getElementById("chatContent");
    const div = document.createElement("div");
    div.className = "message" + (role === "user" ? " user" : "");
    div.innerHTML = text;   // assistant may contain HTML
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }
});
