/*********************************************************************
 *  script.js  —  Front-end logic for MyDataHelps Integration
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

// Simple breathing dots animation instead of step-by-step thinking
const thinkingDotCount = 3;

// Status polling variables
let statusPollingInterval = null;
let currentStatusContainer = null;

/** Start a real-time status label. */
function startThinking() {
  stopThinking();                 // ensure clean state

  const chat = document.getElementById("chatContent");
  const div = document.createElement("div");
  div.className = "message assistant status-label";
  
  // Create status label
  const statusContainer = document.createElement("div");
  statusContainer.className = "status-container processing";
  statusContainer.textContent = "";
  
  div.appendChild(statusContainer);
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  
  // Start polling for status updates
  startStatusPolling(statusContainer);
}

/** Cancel timers and remove all thinking bubbles. */
function stopThinking() {
  thinkingTimers.forEach(t => clearTimeout(t));
  thinkingTimers = [];
  // Remove all status indicators and stop animations
  document.querySelectorAll(".thinking-dots, .status-label").forEach(n => n.remove());
  currentSteps = [];
  stopStatusPolling();
}

/** Start polling for status updates */
function startStatusPolling(statusContainer) {
  currentStatusContainer = statusContainer;
  
  // Poll every 500ms for status updates
  statusPollingInterval = setInterval(() => {
    fetch("/api/status")
      .then(response => response.json())
      .then(data => {
        if (data.success && currentStatusContainer) {
          const label = data.label;
          if (label === "Processing...") {
            currentStatusContainer.className = "status-container processing";
            currentStatusContainer.textContent = "";
          } else {
            currentStatusContainer.className = "status-container";
            currentStatusContainer.textContent = label;
          }
        }
      })
      .catch(error => {
        console.error("Status polling error:", error);
      });
  }, 500);
}

/** Stop status polling */
function stopStatusPolling() {
  if (statusPollingInterval) {
    clearInterval(statusPollingInterval);
    statusPollingInterval = null;
  }
  currentStatusContainer = null;
}

/** Show a waiting message while processing user input */
function showWaitingMessage() {
  const chat = document.getElementById("chatContent");
  const div = document.createElement("div");
  div.className = "message assistant waiting-message status-label";
  
  // Create status label
  const statusContainer = document.createElement("div");
  statusContainer.className = "status-container processing";
  statusContainer.textContent = "";
  
  div.appendChild(statusContainer);
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  
  // Start polling for status updates
  startStatusPolling(statusContainer);
  
  return div;
}

/** Remove the waiting message */
function removeWaitingMessage() {
  const waitingMsg = document.querySelector(".waiting-message");
  if (waitingMsg) {
    waitingMsg.remove();
  }
  stopStatusPolling();
}

/** Return true for strings that begin with "y" (yes-like answers). */
function isYesLike(str) {
  return str.trim().toLowerCase().startsWith("y");
}

/** Format timestamp to relative time (e.g., "2 hours ago", "yesterday") */
function formatRelativeTime(timestamp) {
  const now = new Date();
  const time = new Date(timestamp);
  const diffMs = now - time;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays >= 1) return time.toLocaleString();
  return time.toLocaleDateString();
}

/* ========================================================= */
/*  Enhanced Markdown test function                          */
/* ========================================================= */
function testMarkdownRendering() {
  const testMarkdown = `# ChatGPT-like Rendering Test

This is a comprehensive test of **bold text** and *italic text* formatting. The text should have proper spacing and line breaks.

## Code Examples
Here's some \`inline code\` and a code block:

\`\`\`javascript
function hello() {
  console.log("Hello, World!");
  return "Success!";
}
\`\`\`

## Enhanced Lists
- **Bold item** with proper spacing
- *Italic item* with good line height
  - Nested bullet point
  - Another nested item
    - Third level nesting
- Final top-level item

## Numbered Lists
1. **First item** with bold text
2. *Second item* with italic text
3. Third item with \`inline code\`

## Blockquotes
> This is a blockquote with proper styling and spacing. It should look clean and readable.

> Nested blockquote
> > Double nested blockquote

## Tables
| Feature | Status | Notes |
|---------|--------|-------|
| Bold text | ✅ | Enhanced weight |
| Lists | ✅ | Better spacing |
| Code | ✅ | Improved styling |
| Tables | ✅ | ChatGPT-like |

---

**Test completed successfully!** All formatting should now look like ChatGPT.`;

  console.log('Testing enhanced markdown rendering...');
  console.log('Test markdown content:', testMarkdown);
  
  if (typeof marked !== 'undefined') {
    try {
      const html = marked.parse(testMarkdown);
      console.log('Enhanced markdown HTML output:', html);
      return true;
    } catch (error) {
      console.error('Markdown parsing error:', error);
      return false;
    }
  } else {
    console.error('Marked.js not available');
    return false;
  }
}

/* ========================================================= */
/*  AI Output Pattern Test Function                          */
/* ========================================================= */
function testAIOutputRendering() {
  const aiOutputPattern = `In 2025, notable competitions for the 100-meter freestyle event produced several winners:

1. **NCAA Division I Men's Swimming and Diving Championships**: Florida's Josh Liendo won the 100-yard freestyle with a time of 39.99 seconds at the championships held from March 26 to 29, 2025. This victory marked his third consecutive NCAA title in this event. Tennessee's Jordan Crooks finished in second place with a time of 40.06 seconds, while his teammate Gui Caribe took third with a time of 40.15 seconds.

2. **World Aquatics Championships**: At the World Aquatics Championships held in Singapore from July 30 to 31, 2025, Romania's David Popovici clinched the gold medal in the men's 100-meter freestyle with a time of 46.51 seconds. The silver medal was awarded to the USA's Jack Alexy, who finished in 46.92 seconds, and Australia's Kyle Chalmers secured the bronze with a time of 47.17 seconds.

3. **USA Swimming Championships**: In June 2025, Jack Alexy won the national title in the 100-meter freestyle at the USA Swimming Championships with a time of 47.17 seconds.

These events showcased some of the top talents in competitive swimming for the year.`;

  console.log('Testing AI output pattern rendering...');
  console.log('AI output pattern:', aiOutputPattern);
  
  if (typeof marked !== 'undefined') {
    try {
      const html = marked.parse(aiOutputPattern);
      console.log('AI pattern HTML output:', html);
      return true;
    } catch (error) {
      console.error('AI pattern parsing error:', error);
      return false;
    }
  } else {
    console.error('Marked.js not available for AI pattern test');
    return false;
  }
}

/* ========================================================= */
/*  Citation Format Test Function                            */
/* ========================================================= */
function testCitationRendering() {
  const citationTestPattern = `Here are some medical guidelines with citations:

The American Heart Association recommends regular exercise [heart.org](https://www.heart.org/en/healthy-living/fitness) for cardiovascular health. According to recent studies [pubmed.ncbi.nlm.nih.gov](https://pubmed.ncbi.nlm.nih.gov/example), regular physical activity can reduce the risk of heart disease by up to 30%.

Additional resources include:
- [mayoclinic.org](https://www.mayoclinic.org/healthy-lifestyle/fitness) for comprehensive health information
- [cdc.gov](https://www.cdc.gov/physicalactivity) for government guidelines
- [webmd.com](https://www.webmd.com/fitness-exercise) for patient education

These sources provide evidence-based recommendations for maintaining cardiovascular health.`;

  console.log('Testing citation rendering...');
  console.log('Citation test pattern:', citationTestPattern);
  
  if (typeof marked !== 'undefined') {
    try {
      const html = marked.parse(citationTestPattern);
      console.log('Citation test HTML output:', html);
      
      // Count citation badges
      const tempDiv = document.createElement('div');
      tempDiv.innerHTML = html;
      const citationBadges = tempDiv.querySelectorAll('.citation-badge');
      console.log(`📊 Found ${citationBadges.length} citation badges in test`);
      
      // Log each citation
      citationBadges.forEach((badge, index) => {
        console.log(`  Citation ${index + 1}: "${badge.textContent}" -> "${badge.href}"`);
      });
      
      return true;
    } catch (error) {
      console.error('Citation test parsing error:', error);
      return false;
    }
  } else {
    console.error('Marked.js not available for citation test');
    return false;
  }
}

/* ========================================================= */
/*  DOM ready                                                 */
/* ========================================================= */
document.addEventListener("DOMContentLoaded", () => {
  /* ---------- Test markdown rendering ---------- */
  // Test markdown functionality on page load
  setTimeout(() => {
    testMarkdownRendering();
    
    // Also test with actual AI output pattern
    if (location.pathname.startsWith("/chat/")) {
      testAIOutputRendering();
      testCitationRendering(); // Test citation detection
    }
  }, 1000);

  /* ---------- Grab common DOM elements ---------- */
  const loginBtn    = document.getElementById("loginBtn");
  const logoutBtn   = document.getElementById("logoutBtn");
  const overlay     = document.getElementById("overlay");
  const loginSubmit = document.getElementById("loginSubmit");
  const recentsList = document.getElementById("recentsList");
  const newChatBtn  = document.getElementById("newChatBtn");


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

    const contentDiv = document.createElement("div");
    contentDiv.className = "recent-content";

    const titleSpan = document.createElement("span");
    titleSpan.className = "recent-title";
    titleSpan.textContent = item.title;
    contentDiv.appendChild(titleSpan);

    const timeSpan = document.createElement("span");
    timeSpan.className = "recent-time";
    timeSpan.textContent = formatRelativeTime(item.updated_at);
    contentDiv.appendChild(timeSpan);

    wrapper.appendChild(contentDiv);

    const more = document.createElement("button");
    more.className = "more-btn";
    more.textContent = "⋮";
    wrapper.appendChild(more);

    // Make the entire conversation block clickable
    wrapper.addEventListener("click", (e) => {
      // Don't navigate if clicking on the more button or its dropdown
      if (e.target.closest('.more-btn') || e.target.closest('.dropdown-menu')) {
        return;
      }
      window.location.href = `/chat/${item.session_id}`;
    });

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

  newChatBtn.addEventListener("click", () => {
    // Navigate to new chat page
    window.location.href = "/new";
  });

  const dashboardBtn = document.getElementById("dashboardBtn");
  if (dashboardBtn) {
    dashboardBtn.addEventListener("click", () => {
      // Navigate to dashboard page
      window.location.href = "/dashboard";
    });
  }

  const digitalTwinBtn = document.getElementById("digitalTwinBtn");
  if (digitalTwinBtn) {
    digitalTwinBtn.addEventListener("click", () => {
      // Navigate to my body page
      window.location.href = "/my-body";
    });
  }

  const pdfFormsBtn = document.getElementById("pdfFormsBtn");
  if (pdfFormsBtn) {
    pdfFormsBtn.addEventListener("click", () => {
      // Navigate to PDF forms page
      window.location.href = "/pdf-forms";
    });
  }

  /* ==================================================== */
  /*  Welcome page functionality                           */
  /* ==================================================== */
  
  // Handle suggestion card clicks on welcome page
  document.addEventListener("click", (e) => {
    if (e.target.closest(".suggestion-card")) {
      const card = e.target.closest(".suggestion-card");
      if (location.pathname === "/" || location.pathname === "/new") {
        // Create new chat
        createNewChatWithMessage();
      }
    }
  });

  function createNewChatWithMessage() {
    // Create a new session and redirect to chat page
    fetch("/api/new_session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    })
    .then(r => r.json())
    .then(d => {
      if (!d || !d.success) throw new Error(d && d.message || "Failed to start session");
      const sid = d.session_id;
      // Redirect to chat page
      window.location.href = `/chat/${sid}`;
    })
    .catch(err => {
      console.error(err);
      alert("Failed to start new chat: " + err.message);
    });
  }

  /* ==================================================== */
  /*  Input box functionality for welcome page            */
  /* ==================================================== */
  
  // Initialize input box functionality if on welcome page
  if (location.pathname === "/" || location.pathname === "/new") {
    const messageInput = document.getElementById("messageInput");
    const sendButton = document.getElementById("sendButton");
    
    if (messageInput && sendButton) {
      // Auto-resize functionality
      function autoResize() {
        // Reset height to auto to get the natural height
        messageInput.style.height = 'auto';
        
        // Calculate the natural scroll height
        const scrollHeight = messageInput.scrollHeight;
        
        // Calculate max height for 8 rows (8 * 1.5rem = 12rem = 192px at 16px base font size)
        const lineHeight = parseFloat(getComputedStyle(messageInput).lineHeight) || 24; // 1.5rem = 24px
        const maxHeight = lineHeight * 8; // 8 rows maximum
        
        // Set the new height, limited to max height
        const newHeight = Math.min(scrollHeight, maxHeight);
        messageInput.style.height = newHeight + 'px';
        
        // Show scrollbar if content exceeds max height
        if (scrollHeight > maxHeight) {
          messageInput.style.overflowY = 'auto';
        } else {
          messageInput.style.overflowY = 'hidden';
        }
        
      }
      
      // Handle send button click
      sendButton.addEventListener('click', handleSendMessage);
      
      // Handle Enter key (Shift+Enter for new line)
      messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          handleSendMessage();
        }
      });
      
      // Update send button state and auto-resize based on input
      messageInput.addEventListener('input', () => {
        const hasText = messageInput.value.trim().length > 0;
        sendButton.disabled = !hasText;
        autoResize();
      });
      
      // Also trigger auto-resize on keyup to handle paste events
      messageInput.addEventListener('keyup', autoResize);
      messageInput.addEventListener('paste', () => {
        setTimeout(autoResize, 10); // Small delay to allow paste to complete
      });
      
      // Initial state and setup
      sendButton.disabled = true;
      autoResize(); // Set initial height
    }
  }
  
  function handleSendMessage() {
    const messageInput = document.getElementById("messageInput");
    const sendButton = document.getElementById("sendButton");
    
    if (!messageInput || !sendButton) return;
    
    const message = messageInput.value.trim();
    if (!message) return;
    
    // Disable input while processing
    messageInput.disabled = true;
    sendButton.disabled = true;
    messageInput.style.height = 'auto'; // Reset height
    
    // Create new session and immediately redirect with message
    fetch("/api/new_session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    })
    .then(r => r.json())
    .then(d => {
      if (!d || !d.success) throw new Error(d && d.message || "Failed to start session");
      const sessionId = d.session_id;
      
      // Immediately redirect to chat page with the message as URL parameter
      const encodedMessage = encodeURIComponent(message);
      window.location.href = `/chat/${sessionId}?message=${encodedMessage}`;
    })
    .catch(err => {
      console.error(err);
      alert("Failed to start new chat: " + err.message);
      
      // Re-enable input
      messageInput.disabled = false;
      sendButton.disabled = false;
    });
  }



  /* ==================================================== */
  /*  Render conversation on page load                     */
  /* ==================================================== */
  if (location.pathname.startsWith("/chat/")) {
    const session_id = location.pathname.split("/").pop();
    
    // Check for message parameter from welcome page
    const urlParams = new URLSearchParams(window.location.search);
    const initialMessage = urlParams.get('message');
    
    // Initialize chat input functionality
    const messageInput = document.getElementById("messageInput");
    const sendButton = document.getElementById("sendButton");
    
    if (messageInput && sendButton) {
      // Auto-resize textarea
      function autoResize() {
        // Reset height to auto to get the natural height
        messageInput.style.height = 'auto';
        
        // Calculate the natural scroll height
        const scrollHeight = messageInput.scrollHeight;
        
        // Calculate max height for 8 rows (8 * 1.5rem = 12rem = 192px at 16px base font size)
        const lineHeight = parseFloat(getComputedStyle(messageInput).lineHeight) || 24; // 1.5rem = 24px
        const maxHeight = lineHeight * 8; // 8 rows maximum
        
        // Set the new height, limited to max height
        const newHeight = Math.min(scrollHeight, maxHeight);
        messageInput.style.height = newHeight + 'px';
        
        // Show scrollbar if content exceeds max height
        if (scrollHeight > maxHeight) {
          messageInput.style.overflowY = 'auto';
        } else {
          messageInput.style.overflowY = 'hidden';
        }
        
      }
      
      // Handle send button click
      sendButton.addEventListener('click', () => handleChatMessage(session_id));
      
      // Handle Enter key (Shift+Enter for new line)
      messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          handleChatMessage(session_id);
        }
      });
      
      // Update send button state and auto-resize based on input
      messageInput.addEventListener('input', () => {
        const hasText = messageInput.value.trim().length > 0;
        sendButton.disabled = !hasText;
        autoResize();
      });
      
      // Also trigger auto-resize on keyup to handle paste events
      messageInput.addEventListener('keyup', autoResize);
      messageInput.addEventListener('paste', () => {
        setTimeout(autoResize, 10); // Small delay to allow paste to complete
      });
      
      // Initial state and setup
      sendButton.disabled = true;
      autoResize(); // Set initial height
    }
    
    fetch(`/api/session/${session_id}`)
      .then(r => r.json())
      .then(data => {
        const box = document.getElementById("chatContent");
        box.innerHTML = "";
        data.conversation.forEach(m => appendMsg(m.content, m.role));
        logoutBtn.hidden = loginBtn.textContent.trim() === "Login";
        
        // If there's an initial message from welcome page, send it automatically
        if (initialMessage) {
          // Clear the URL parameter to avoid resending on refresh
          window.history.replaceState({}, document.title, window.location.pathname);
          
          // Add user message to chat immediately
          appendMsg(initialMessage, "user");
          
          // Show thinking animation
          startThinking();
          
          // Send message to server
          fetch("/api/message", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              session_id: session_id,
              message: initialMessage
            })
          })
          .then(r => r.json())
          .then(d => {
            stopThinking();
            
            if (d.success) {
              // Add assistant response
              appendMsg(d.assistant_message, "assistant");
            } else {
              // Show error message
              appendMsg(d.assistant_message || "Sorry, there was an error processing your message.", "assistant");
            }
          })
          .catch(err => {
            stopThinking();
            console.error(err);
            appendMsg("Sorry, there was an error processing your message.", "assistant");
          });
        }
      });
  }

  /* ==================================================== */
  /*  Chat message handling                                */
  /* ==================================================== */
  function handleChatMessage(sessionId) {
    const messageInput = document.getElementById("messageInput");
    const sendButton = document.getElementById("sendButton");
    
    if (!messageInput || !sendButton) return;
    
    const message = messageInput.value.trim();
    if (!message) return;
    
    // Add user message to chat immediately
    appendMsg(message, "user");
    
    // Clear input and disable
    messageInput.value = "";
    messageInput.style.height = 'auto';
    messageInput.disabled = true;
    sendButton.disabled = true;
    
    // Show thinking animation
    startThinking();
    
    // Send message to server
    fetch("/api/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        message: message
      })
    })
    .then(r => r.json())
    .then(d => {
      stopThinking();
      
      if (d.success) {
        // Add assistant response
        appendMsg(d.assistant_message, "assistant");
      } else {
        // Show error message
        appendMsg(d.assistant_message || "Sorry, there was an error processing your message.", "assistant");
      }
    })
    .catch(err => {
      stopThinking();
      console.error(err);
      appendMsg("Sorry, there was an error processing your message.", "assistant");
    })
    .finally(() => {
      // Re-enable input
      messageInput.disabled = false;
      sendButton.disabled = false;
      messageInput.focus();
    });
  }


  /* ==================================================== */
  /*  Sources functionality                                 */
  /* ==================================================== */
  
  /** Extract sources from a message element */
  function extractSourcesFromMessage(messageElement) {
    const sources = [];
    const links = messageElement.querySelectorAll('a[href]');
    
    links.forEach(link => {
      const href = link.getAttribute('href');
      const text = link.textContent.trim();
      
      // Only include external links that look like sources
      if (href && href.startsWith('http') && text.includes('.')) {
        try {
          const url = new URL(href);
          const domain = url.hostname.replace('www.', '');
          
          // Generate smart title from URL path
          let title = generateTitleFromUrl(url);
          
          // Generate preview from surrounding context
          let preview = generatePreviewFromContext(link);
          
          sources.push({
            url: href,
            domain: domain,
            title: title,
            favicon: `https://www.google.com/s2/favicons?domain=${url.hostname}&sz=32`,
            preview: preview
          });
        } catch (e) {
          // Skip invalid URLs
        }
      }
    });
    
    // Remove duplicates based on URL
    const uniqueSources = [];
    const seenUrls = new Set();
    
    sources.forEach(source => {
      if (!seenUrls.has(source.url)) {
        seenUrls.add(source.url);
        uniqueSources.push(source);
      }
    });
    
    return uniqueSources;
  }
  
  /** Generate title from URL path */
  function generateTitleFromUrl(url) {
    const path = url.pathname;
    const segments = path.split('/').filter(s => s && s !== 'index.html');
    
    if (segments.length === 0) {
      return url.hostname.replace('www.', '');
    }
    
    // Use the last meaningful segment
    const lastSegment = segments[segments.length - 1];
    
    // Clean up the segment
    let title = lastSegment
      .replace(/[-_]/g, ' ')           // Replace dashes/underscores with spaces
      .replace(/\.[^.]+$/, '')         // Remove file extension
      .replace(/^\d+[-_]/, '')         // Remove leading numbers
      .toLowerCase()
      .split(' ')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
    
    return title || url.hostname.replace('www.', '');
  }
  
  /** Generate preview from link context */
  function generatePreviewFromContext(link) {
    // Look for surrounding text in the same paragraph or nearby elements
    let context = '';
    
    // Try to get text from the same paragraph
    const paragraph = link.closest('p');
    if (paragraph) {
      context = paragraph.textContent.trim();
    } else {
      // Look at parent elements for context
      let parent = link.parentElement;
      while (parent && !context) {
        const text = parent.textContent.trim();
        if (text.length > link.textContent.length + 20) {
          context = text;
          break;
        }
        parent = parent.parentElement;
      }
    }
    
    // Clean up and truncate
    if (context) {
      context = context.replace(/\s+/g, ' ').trim();
      return context.length > 120 ? context.substring(0, 120) + '...' : context;
    }
    
    return 'Source page content';
  }
  
  /** Create sources button */
  function createSourcesButton(sources) {
    const button = document.createElement('button');
    button.className = 'sources-button';
    button.innerHTML = `
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2"/>
        <line x1="2" y1="12" x2="22" y2="12" stroke="currentColor" stroke-width="2"/>
        <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" stroke="currentColor" stroke-width="2"/>
      </svg>
      <span>Sources</span>
    `;
    
    button.addEventListener('click', () => {
      openSourcesSidebar(sources);
    });
    
    return button;
  }
  
  /** Open sources sidebar */
  function openSourcesSidebar(sources) {
    // Create or get existing sidebar
    let sidebar = document.getElementById('sourcesSidebar');
    if (!sidebar) {
      sidebar = createSourcesSidebar();
    }
    
    // Populate sources
    populateSourcesSidebar(sidebar, sources);
    
    // Show sidebar
    sidebar.classList.add('active');
    document.body.classList.add('sources-sidebar-open');
    
    // Focus management
    const firstButton = sidebar.querySelector('.source-card');
    if (firstButton) {
      firstButton.focus();
    }
  }
  
  /** Create sources sidebar element */
  function createSourcesSidebar() {
    const sidebar = document.createElement('div');
    sidebar.id = 'sourcesSidebar';
    sidebar.className = 'sources-sidebar';
    sidebar.innerHTML = `
      <div class="sources-header">
        <h3>Sources</h3>
        <button class="sources-close" aria-label="Close sources">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <line x1="18" y1="6" x2="6" y2="18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            <line x1="6" y1="6" x2="18" y2="18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </button>
      </div>
      <div class="sources-content">
        <div class="sources-list"></div>
      </div>
    `;
    
    // Add close functionality
    const closeBtn = sidebar.querySelector('.sources-close');
    closeBtn.addEventListener('click', closeSourcesSidebar);
    
    // Add escape key handler
    const handleKeydown = (e) => {
      if (e.key === 'Escape' && sidebar.classList.contains('active')) {
        closeSourcesSidebar();
      }
    };
    document.addEventListener('keydown', handleKeydown);
    
    // Add backdrop click handler
    sidebar.addEventListener('click', (e) => {
      if (e.target === sidebar) {
        closeSourcesSidebar();
      }
    });
    
    document.body.appendChild(sidebar);
    return sidebar;
  }
  
  /** Populate sources sidebar with source cards */
  function populateSourcesSidebar(sidebar, sources) {
    const sourcesList = sidebar.querySelector('.sources-list');
    sourcesList.innerHTML = '';
    
    if (sources.length === 0) {
      sourcesList.innerHTML = '<div class="no-sources">No sources available</div>';
      return;
    }
    
    sources.forEach((source, index) => {
      const sourceCard = createSourceCard(source, index);
      sourcesList.appendChild(sourceCard);
    });
  }
  
  /** Create individual source card */
  function createSourceCard(source, index) {
    const card = document.createElement('div');
    card.className = 'source-card';
    card.tabIndex = 0;
    card.dataset.url = source.url;
    card.innerHTML = `
      <div class="source-favicon">
        <img src="${source.favicon}" alt="" onerror="this.style.display='none'">
      </div>
      <div class="source-content">
        <div class="source-domain-line">
          <span class="source-domain">${source.domain}</span>
        </div>
        <div class="source-title">${source.title}</div>
        <div class="source-preview">${source.preview}</div>
      </div>
    `;
    
    // Add click handler to card for URL redirection
    card.addEventListener('click', (e) => {
      e.preventDefault();
      window.open(source.url, '_blank', 'noopener,noreferrer');
    });
    
    // Add keyboard navigation
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        window.open(source.url, '_blank', 'noopener,noreferrer');
      }
    });
    
    return card;
  }
  
  /** Close sources sidebar */
  function closeSourcesSidebar() {
    const sidebar = document.getElementById('sourcesSidebar');
    if (sidebar) {
      sidebar.classList.remove('active');
      document.body.classList.remove('sources-sidebar-open');
    }
  }
  
  /** Highlight source in message when clicked from sidebar */
  function highlightSourceInMessage(sourceUrl, messageElement) {
    // Remove any existing highlights
    const existingHighlights = messageElement.querySelectorAll('.source-highlight');
    existingHighlights.forEach(highlight => {
      highlight.classList.remove('source-highlight');
    });
    
    // Find the link with matching URL
    const links = messageElement.querySelectorAll('a[href]');
    let targetLink = null;
    
    links.forEach(link => {
      if (link.getAttribute('href') === sourceUrl) {
        targetLink = link;
      }
    });
    
    if (targetLink) {
      // Add highlight class
      targetLink.classList.add('source-highlight');
      
      // Scroll to the message if it's not fully visible
      const rect = messageElement.getBoundingClientRect();
      const chatContent = document.getElementById('chatContent');
      const chatRect = chatContent.getBoundingClientRect();
      
      if (rect.top < chatRect.top || rect.bottom > chatRect.bottom) {
        messageElement.scrollIntoView({ 
          behavior: 'smooth', 
          block: 'center' 
        });
      }
      
      // Remove highlight after a few seconds
      setTimeout(() => {
        targetLink.classList.remove('source-highlight');
      }, 3000);
    }
  }

  /* ==================================================== */
  /*  Speech-to-Text functionality                         */
  /* ==================================================== */
  let isRecording = false;
  let recordingPollInterval = null;
  
  const micButton = document.getElementById("micButton");
  
  if (micButton) {
    micButton.addEventListener("click", handleMicClick);
  }
  
  function handleMicClick() {
    if (!isRecording) {
      startRecording();
    } else {
      stopRecording();
    }
  }
  
  function startRecording() {
    // Call backend to start recording
    fetch("/api/speech/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" }
    })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        isRecording = true;
        
        // Update UI
        const micButton = document.getElementById("micButton");
        const inputWrapper = document.querySelector(".input-wrapper");
        const messageInput = document.getElementById("messageInput");
        
        if (micButton) {
          micButton.classList.add("recording");
          micButton.title = "Stop recording";
        }
        
        if (inputWrapper) {
          inputWrapper.classList.add("recording");
        }
        
        if (messageInput) {
          messageInput.placeholder = "Listening...";
        }
        
        // Start polling for transcribed text
        startRecordingPoll();
      } else {
        alert(data.message || "Failed to start recording");
      }
    })
    .catch(err => {
      console.error("Failed to start recording:", err);
      alert("Failed to start recording. Make sure the speech-to-text module is installed.");
    });
  }
  
  function stopRecording() {
    // Stop polling first
    stopRecordingPoll();
    
    // Call backend to stop recording
    fetch("/api/speech/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" }
    })
    .then(r => r.json())
    .then(data => {
      isRecording = false;
      
      // Update UI
      const micButton = document.getElementById("micButton");
      const inputWrapper = document.querySelector(".input-wrapper");
      const messageInput = document.getElementById("messageInput");
      
      if (micButton) {
        micButton.classList.remove("recording");
        micButton.title = "Voice input";
      }
      
      if (inputWrapper) {
        inputWrapper.classList.remove("recording");
      }
      
      if (messageInput) {
        messageInput.placeholder = "Ask anything";
      }
      
      if (data.success && data.transcribed_text) {
        // Insert transcribed text into input box
        if (messageInput) {
          const currentText = messageInput.value.trim();
          if (currentText) {
            messageInput.value = currentText + " " + data.transcribed_text;
          } else {
            messageInput.value = data.transcribed_text;
          }
          
          // Trigger input event to update send button state and auto-resize
          messageInput.dispatchEvent(new Event('input'));
          messageInput.focus();
        }
      } else if (!data.success) {
        console.error("Failed to stop recording:", data.message);
      }
    })
    .catch(err => {
      console.error("Failed to stop recording:", err);
      isRecording = false;
      
      // Reset UI
      const micButton = document.getElementById("micButton");
      const inputWrapper = document.querySelector(".input-wrapper");
      const messageInput = document.getElementById("messageInput");
      
      if (micButton) {
        micButton.classList.remove("recording");
        micButton.title = "Voice input";
      }
      
      if (inputWrapper) {
        inputWrapper.classList.remove("recording");
      }
      
      if (messageInput) {
        messageInput.placeholder = "Ask anything";
      }
    });
  }
  
  function startRecordingPoll() {
    // Poll every 1 second for new transcribed text
    recordingPollInterval = setInterval(() => {
      fetch("/api/speech/poll")
        .then(r => r.json())
        .then(data => {
          if (data.success && data.is_recording && data.text) {
            const messageInput = document.getElementById("messageInput");
            if (messageInput) {
              // Append transcribed text to existing text
              const currentText = messageInput.value.trim();
              if (currentText) {
                messageInput.value = currentText + " " + data.text;
              } else {
                messageInput.value = data.text;
              }
              
              // Trigger input event to update send button state and auto-resize
              messageInput.dispatchEvent(new Event('input'));
            }
          } else if (!data.is_recording) {
            // Recording stopped on server side
            stopRecordingPoll();
            isRecording = false;
            
            const micButton = document.getElementById("micButton");
            const inputWrapper = document.querySelector(".input-wrapper");
            const messageInput = document.getElementById("messageInput");
            
            if (micButton) {
              micButton.classList.remove("recording");
              micButton.title = "Voice input";
            }
            
            if (inputWrapper) {
              inputWrapper.classList.remove("recording");
            }
            
            if (messageInput) {
              messageInput.placeholder = "Ask anything";
            }
          }
        })
        .catch(err => {
          console.error("Polling error:", err);
        });
    }, 1000);
  }
  
  function stopRecordingPoll() {
    if (recordingPollInterval) {
      clearInterval(recordingPollInterval);
      recordingPollInterval = null;
    }
  }

  /* ==================================================== */
  /*  Helper: render a bubble                              */
  /* ==================================================== */
  function appendMsg(text, role) {
    if (!text || !text.trim()) return;
    const box = document.getElementById("chatContent");
    const div = document.createElement("div");
    div.className = "message" + (role === "user" ? " user" : "");
    
    // Configure marked for better security and formatting
    if (typeof marked !== 'undefined') {
      console.log('Marked.js loaded successfully');
      
      // Configure marked options for AI output rendering
      const renderer = new marked.Renderer();
      
      // Override link renderer to add target="_blank" and detect citations
      renderer.link = function(href, title, text) {
        const titleAttr = title ? ` title="${title}"` : '';
        
        // Check if this looks like a citation link (domain name as text, external URL)
        const linkText = text.trim();
        let citationClass = '';
        
        // Improved citation detection logic
        if (href && href.startsWith('http') && 
            linkText.includes('.') && 
            !linkText.includes(' ') && 
            linkText.length > 3 && 
            linkText.length < 100 && 
            // More comprehensive domain-like patterns
            (linkText.match(/^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/) || // Standard domain
             linkText.match(/^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\/[a-zA-Z0-9.-]*$/) || // Domain with path
             linkText.match(/^[a-zA-Z0-9.-]+\.(com|org|net|edu|gov|io|co|uk|de|fr|jp|cn|au|ca|us|mil|int|info|biz|name|pro|aero|coop|museum)$/i) || // Extended TLDs
             linkText.match(/^[a-zA-Z0-9.-]+\.(ac|ad|ae|af|ag|ai|al|am|ao|aq|ar|as|at|aw|ax|az|ba|bb|bd|be|bf|bg|bh|bi|bj|bm|bn|bo|br|bs|bt|bv|bw|by|bz|cc|cd|cf|cg|ch|ci|ck|cl|cm|cn|cr|cu|cv|cx|cy|cz|dj|dk|dm|do|dz|ec|ee|eg|eh|er|es|et|fi|fj|fk|fm|fo|fr|ga|gb|gd|ge|gf|gg|gh|gi|gl|gm|gn|gp|gq|gr|gs|gt|gu|gw|gy|hk|hm|hn|hr|ht|hu|id|ie|il|im|in|io|iq|ir|is|it|je|jm|jo|ke|kg|kh|ki|km|kn|kp|kr|kw|ky|kz|la|lb|lc|li|lk|lr|ls|lt|lu|lv|ly|ma|mc|md|me|mg|mh|mk|ml|mm|mn|mo|mp|mq|mr|ms|mt|mu|mv|mw|mx|my|mz|na|nc|ne|nf|ng|ni|nl|no|np|nr|nu|nz|om|pa|pe|pf|pg|ph|pk|pl|pm|pn|pr|ps|pt|pw|py|qa|re|ro|rs|ru|rw|sa|sb|sc|sd|se|sg|sh|si|sj|sk|sl|sm|sn|so|sr|st|sv|sy|sz|tc|td|tf|tg|th|tj|tk|tl|tm|tn|to|tr|tt|tv|tw|tz|ua|ug|um|us|uy|uz|va|vc|ve|vg|vi|vn|vu|wf|ws|ye|yt|za|zm|zw)$/i))) { // All country codes
          citationClass = ' class="citation-badge"';
          console.log('Detected citation in renderer:', linkText);
        }
        
        return `<a href="${href}"${titleAttr}${citationClass} target="_blank" rel="noopener noreferrer">${text}</a>`;
      };
      
      
      marked.setOptions({
        breaks: true,       // Convert \n to <br> for proper line break handling
        gfm: true,          // GitHub Flavored Markdown
        smartLists: true,
        smartypants: true,
        headerIds: false,   // Disable header IDs for cleaner HTML
        mangle: false,      // Don't mangle email addresses
        sanitize: false,    // Allow HTML (we'll handle security separately)
        silent: true,       // Don't throw on malformed markdown
        pedantic: false,    // Use more relaxed markdown parsing
        renderer: renderer,
        xhtml: false        // Don't force XHTML compliance which might escape HTML 
      });
      
      // For assistant messages, render as markdown
      if (role === "assistant") {
        try {
          // Process text to handle line breaks properly
          let processedText = text;
          
          // Normalize excessive line breaks: convert 3+ consecutive \n to just \n\n
          processedText = processedText.replace(/\n{3,}/g, '\n\n');
          
          // Fix citation format: convert ([domain](url)) to [domain](url)
          const originalText = processedText;
          processedText = processedText.replace(/\(\[([^\]]+)\]\(([^)]+)\)\)/g, '[$1]($2)');
          
          // Additional citation format fixes
          // Fix cases where AI might use different citation formats
          processedText = processedText.replace(/\[([^\]]+)\]\(([^)]+)\)\s*\(([^)]+)\)/g, '[$1]($2)'); // Remove trailing parentheses
          processedText = processedText.replace(/\[([^\]]+)\]\(([^)]+)\)\s*\[([^\]]+)\]\(([^)]+)\)/g, '[$1]($2) [$3]($4)'); // Fix double citations
          
          // Fix malformed citations with extra brackets or parentheses
          processedText = processedText.replace(/\[\[([^\]]+)\]\]\(([^)]+)\)/g, '[$1]($2)'); // Double brackets
          processedText = processedText.replace(/\[([^\]]+)\]\(\(([^)]+)\)\)/g, '[$1]($2)'); // Double parentheses
          processedText = processedText.replace(/\[([^\]]+)\]\(([^)]+)\)\s*\)/g, '[$1]($2)'); // Trailing closing parenthesis
          
          // Move citations to end of sentences (after periods)
          processedText = processedText.replace(/([^.!?])\s*\[([^\]]+)\]\(([^)]+)\)\s*([.!?])/g, '$1$4 [$2]($3)');
          
          // Remove utm_source=openai parameter from URLs
          processedText = processedText.replace(/\[([^\]]+)\]\(([^)]*)\?utm_source=openai([^)]*)\)/g, '[$1]($2$3)');
          processedText = processedText.replace(/\[([^\]]+)\]\(([^)]*)\&utm_source=openai([^)]*)\)/g, '[$1]($2$3)');
          
          // Clean up URLs with other tracking parameters
          processedText = processedText.replace(/\[([^\]]+)\]\(([^)]*)\?utm_[^)]*\)/g, '[$1]($2)');
          processedText = processedText.replace(/\[([^\]]+)\]\(([^)]*)\&utm_[^)]*\)/g, '[$1]($2)');
          
          if (originalText !== processedText) {
            console.log('🔧 Fixed citation format:', originalText.substring(0, 100), '->', processedText.substring(0, 100));
          }
          
          const htmlContent = marked.parse(processedText);
          div.innerHTML = htmlContent;
          
          // Check if citation badges were added
          const citationBadges = div.querySelectorAll('.citation-badge');
          console.log(`📊 Found ${citationBadges.length} citation badges in message`);
          
          // Debug: Log all links to help troubleshoot citation detection
          const allLinks = div.querySelectorAll('a');
          console.log(`🔗 Total links found: ${allLinks.length}`);
          allLinks.forEach((link, index) => {
            const href = link.getAttribute('href');
            const text = link.textContent;
            const isCitation = link.classList.contains('citation-badge');
            console.log(`  Link ${index + 1}: "${text}" -> "${href}" (citation: ${isCitation})`);
          });
          
          console.log('Markdown rendered successfully');
        } catch (error) {
          console.error('Error rendering markdown:', error);
          div.textContent = text; // Fallback to plain text
        }
      } else {
        // For user messages, handle line breaks without excessive spacing
        // Convert \n to <br> and \n\n to <br><br> for proper rendering
        let processedText = text
          .replace(/\n{3,}/g, '\n\n')  // Normalize excessive line breaks
          .replace(/\n\n/g, '<br><br>') // Convert double line breaks to double <br>
          .replace(/\n/g, '<br>');     // Convert single line breaks to <br>
        
        div.innerHTML = processedText;
      }
    } else {
      console.warn('Marked.js not loaded, using fallback');
      // Fallback if marked is not loaded
      if (role === "assistant") {
        // Simple fallback with basic line break handling
        let processedText = text
          .replace(/\n{3,}/g, '\n\n')  // Normalize excessive line breaks
          .replace(/\n\n/g, '<br><br>') // Convert double line breaks to double <br>
          .replace(/\n/g, '<br>');     // Convert single line breaks to <br>
        div.innerHTML = processedText;
      } else {
        // For user messages, handle line breaks without excessive spacing
        let processedText = text
          .replace(/\n{3,}/g, '\n\n')  // Normalize excessive line breaks
          .replace(/\n\n/g, '<br><br>') // Convert double line breaks to double <br>
          .replace(/\n/g, '<br>');     // Convert single line breaks to <br>
        div.innerHTML = processedText;
      }
    }
    
    // Add Sources button for assistant messages with citations
    if (role === "assistant") {
      const sources = extractSourcesFromMessage(div);
      if (sources.length > 0) {
        const sourcesBtn = createSourcesButton(sources);
        div.appendChild(sourcesBtn);
      }
    }
    
    box.appendChild(div);
    
    // Force a reflow to ensure the message is immediately visible and positioned correctly
    div.offsetHeight;
    
    // Scroll to bottom after positioning is applied
    box.scrollTop = box.scrollHeight;
  }
});
