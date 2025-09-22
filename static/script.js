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

/** Start a breathing dots thinking animation. */
function startThinking() {
  stopThinking();                 // ensure clean state

  const chat = document.getElementById("chatContent");
  const div = document.createElement("div");
  div.className = "message assistant thinking-dots";
  
  // Create breathing dots
  const dotsContainer = document.createElement("div");
  dotsContainer.className = "breathing-dots";
  for (let i = 0; i < thinkingDotCount; i++) {
    const dot = document.createElement("span");
    dot.className = "breathing-dot";
    dot.style.animationDelay = `${i * 0.2}s`;
    dotsContainer.appendChild(dot);
  }
  
  div.appendChild(dotsContainer);
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

/** Cancel timers and remove all thinking bubbles. */
function stopThinking() {
  thinkingTimers.forEach(t => clearTimeout(t));
  thinkingTimers = [];
  document.querySelectorAll(".thinking-dots").forEach(n => n.remove());
  currentSteps = [];
}

/** Show a waiting message while processing user input */
function showWaitingMessage() {
  const chat = document.getElementById("chatContent");
  const div = document.createElement("div");
  div.className = "message assistant waiting-message";
  
  // Create breathing dots instead of emoji and text
  const dotsContainer = document.createElement("div");
  dotsContainer.className = "breathing-dots";
  for (let i = 0; i < thinkingDotCount; i++) {
    const dot = document.createElement("span");
    dot.className = "breathing-dot";
    dot.style.animationDelay = `${i * 0.2}s`;
    dotsContainer.appendChild(dot);
  }
  
  div.appendChild(dotsContainer);
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

/** Remove the waiting message */
function removeWaitingMessage() {
  const waitingMsg = document.querySelector(".waiting-message");
  if (waitingMsg) {
    waitingMsg.remove();
  }
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
            linkText.length < 100 && // Increased from 50 to 100
            // Additional checks for domain-like patterns
            (linkText.match(/^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/) || // Standard domain
             linkText.match(/^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\/[a-zA-Z0-9.-]*$/) || // Domain with path
             linkText.match(/^[a-zA-Z0-9.-]+\.(com|org|net|edu|gov|io|co|uk|de|fr|jp|cn|au|ca|us)$/i))) { // Common TLDs
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
          
          // Move citations to end of sentences (after periods)
          processedText = processedText.replace(/([^.!?])\s*\[([^\]]+)\]\(([^)]+)\)\s*([.!?])/g, '$1$4 [$2]($3)');
          
          // Remove utm_source=openai parameter from URLs
          processedText = processedText.replace(/\[([^\]]+)\]\(([^)]*)\?utm_source=openai([^)]*)\)/g, '[$1]($2$3)');
          processedText = processedText.replace(/\[([^\]]+)\]\(([^)]*)\&utm_source=openai([^)]*)\)/g, '[$1]($2$3)');
          
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
    
    box.appendChild(div);
    
    // Force a reflow to ensure the message is immediately visible and positioned correctly
    div.offsetHeight;
    
    // Scroll to bottom after positioning is applied
    box.scrollTop = box.scrollHeight;
  }
});
