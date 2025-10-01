/*********************************************************************
 *  dashboard.js  —  Dashboard-specific functionality
 *
 *  • Load and display health data
 *  • Render vital signs with status indicators
 *  • Handle input box for starting new chats from dashboard
 *********************************************************************/

/* ========================================================= */
/*  Dashboard Data Loading and Rendering                     */
/* ========================================================= */

function loadDashboardData() {
  fetch("/api/dashboard_data")
    .then(r => r.json())
    .then(response => {
      const container = document.getElementById("dashboardData");
      if (response.success && response.data) {
        renderDashboard(response.data);
      } else {
        container.innerHTML = '<div class="no-data">No health data available</div>';
      }
    })
    .catch(err => {
      console.error("Failed to load dashboard data:", err);
      const container = document.getElementById("dashboardData");
      container.innerHTML = '<div class="error">Failed to load health data</div>';
    });
}

function renderDashboard(data) {
  const container = document.getElementById("dashboardData");
  let html = '';
  
  // Render demographics section
  if (data.demographics && Object.keys(data.demographics).length > 0) {
    html += renderDemographics(data.demographics);
  }
  
  // Render vital signs section
  if (data.vital_signs && data.vital_signs.length > 0) {
    html += renderVitalSigns(data.vital_signs);
  }
  
  // Render activity section
  if (data.activity && Object.keys(data.activity).length > 0) {
    html += renderActivity(data.activity);
  }
  
  // Render cardiovascular section
  if (data.cardiovascular && Object.keys(data.cardiovascular).length > 0) {
    html += renderCardiovascular(data.cardiovascular);
  }
  
  // Render mobility section
  if (data.mobility && Object.keys(data.mobility).length > 0) {
    html += renderMobility(data.mobility);
  }
  
  // Render medications section
  if (data.medications && data.medications.length > 0) {
    html += renderMedications(data.medications);
  }
  
  // Render lab results section
  if (data.lab_results && data.lab_results.length > 0) {
    html += renderLabResults(data.lab_results);
  }
  
  // Render clinical section (allergies & conditions)
  if (data.clinical && (data.clinical.allergies || data.clinical.conditions)) {
    html += renderClinical(data.clinical);
  }
  
  container.innerHTML = html;
}

/* ========================================================= */
/*  Demographics Rendering                                    */
/* ========================================================= */

function renderDemographics(demographics) {
  let html = '<div class="dashboard-card demographics-card">';
  html += '<div class="card-icon">👤</div>';
  html += '<div class="card-content">';
  html += '<h2>Patient Information</h2>';
  html += '<div class="demographics-info">';
  
  html += `<div class="demo-item">
    <span class="demo-label">Name:</span> 
    <span class="demo-value">${demographics.name || 'N/A'}</span>
  </div>`;
  
  html += `<div class="demo-item">
    <span class="demo-label">Age:</span> 
    <span class="demo-value">${demographics.age || 'N/A'}</span>
  </div>`;
  
  html += `<div class="demo-item">
    <span class="demo-label">Sex:</span> 
    <span class="demo-value">${demographics.sex || 'N/A'}</span>
  </div>`;
  
  html += `<div class="demo-item">
    <span class="demo-label">Birth Date:</span> 
    <span class="demo-value">${demographics.birth_date || 'N/A'}</span>
  </div>`;
  
  html += '</div></div></div>';
  return html;
}

/* ========================================================= */
/*  Vital Signs Rendering                                     */
/* ========================================================= */

// Icon mapping for vital signs
const VITAL_ICONS = {
  'Heart Rate': '❤️',
  'Blood Pressure': '🩺',
  'Body Temperature': '🌡️',
  'Respiratory Rate': '🫁',
  'Oxygen Saturation': '💨'
};

function renderVitalSigns(vitalSigns) {
  let html = '<h2 class="section-title">Vital Signs</h2>';
  html += '<div class="vitals-grid">';
  
  vitalSigns.forEach(vital => {
    html += renderVitalCard(vital);
  });
  
  html += '</div>';
  return html;
}

function renderVitalCard(vital) {
  const icon = VITAL_ICONS[vital.name] || '📊';
  const value = vital.value || 'N/A';
  const unit = vital.unit || '';
  
  // Determine status (normal/abnormal)
  const status = getVitalStatus(vital);
  
  let html = `<div class="vital-card ${status.className}">`;
  html += `<div class="vital-icon">${icon}</div>`;
  html += `<div class="vital-info">`;
  html += `<div class="vital-name">${vital.name}</div>`;
  html += `<div class="vital-value">${value} <span class="vital-unit">${unit}</span></div>`;
  
  // Display normal range
  if (vital.normal_range) {
    html += renderNormalRange(vital.normal_range);
  }
  
  // Display status indicator
  if (status.text) {
    html += `<div class="vital-status">${status.text}</div>`;
  }
  
  html += '</div></div>';
  return html;
}

function getVitalStatus(vital) {
  let statusClass = '';
  let statusText = '';
  
  if (!vital.value || !vital.normal_range) {
    return { className: statusClass, text: statusText };
  }
  
  // Handle blood pressure specially (has systolic/diastolic)
  if (vital.normal_range.systolic && vital.normal_range.diastolic) {
    const [systolic, diastolic] = String(vital.value).split('/').map(Number);
    if (systolic && diastolic) {
      const systolicNormal = systolic >= vital.normal_range.systolic.min && 
                            systolic <= vital.normal_range.systolic.max;
      const diastolicNormal = diastolic >= vital.normal_range.diastolic.min && 
                             diastolic <= vital.normal_range.diastolic.max;
      
      if (systolicNormal && diastolicNormal) {
        statusClass = 'status-normal';
        statusText = '✓ Normal';
      } else {
        statusClass = 'status-abnormal';
        statusText = '⚠ Check';
      }
    }
  } 
  // Handle regular numeric values
  else if (vital.normal_range.min !== undefined && vital.normal_range.max !== undefined) {
    const numValue = parseFloat(vital.value);
    if (!isNaN(numValue)) {
      if (numValue >= vital.normal_range.min && numValue <= vital.normal_range.max) {
        statusClass = 'status-normal';
        statusText = '✓ Normal';
      } else {
        statusClass = 'status-abnormal';
        statusText = '⚠ Check';
      }
    }
  }
  
  return { className: statusClass, text: statusText };
}

function renderNormalRange(normalRange) {
  if (normalRange.systolic && normalRange.diastolic) {
    return `<div class="vital-range">Normal: ${normalRange.systolic.min}-${normalRange.systolic.max}/${normalRange.diastolic.min}-${normalRange.diastolic.max} ${normalRange.unit}</div>`;
  } else if (normalRange.min !== undefined && normalRange.max !== undefined) {
    const unit = normalRange.unit || '';
    return `<div class="vital-range">Normal: ${normalRange.min}-${normalRange.max} ${unit}</div>`;
  }
  return '';
}

/* ========================================================= */
/*  Activity Rendering                                        */
/* ========================================================= */

function renderActivity(activity) {
  let html = '<h2 class="section-title">Activity</h2>';
  html += '<div class="activity-grid">';
  
  if (activity.steps) {
    html += renderActivityCard('Steps', '🚶', activity.steps.value, activity.steps.unit);
  }
  
  if (activity.active_energy) {
    html += renderActivityCard('Active Energy', '🔥', activity.active_energy.value, activity.active_energy.unit);
  }
  
  if (activity.exercise_time) {
    html += renderActivityCard('Exercise Time', '💪', activity.exercise_time.value, activity.exercise_time.unit);
  }
  
  html += '</div>';
  return html;
}

function renderActivityCard(name, icon, value, unit) {
  return `
    <div class="activity-card">
      <div class="activity-icon">${icon}</div>
      <div class="activity-info">
        <div class="activity-name">${name}</div>
        <div class="activity-value">${value} <span class="activity-unit">${unit}</span></div>
      </div>
    </div>
  `;
}

/* ========================================================= */
/*  Cardiovascular Rendering                                 */
/* ========================================================= */

function renderCardiovascular(cardio) {
  let html = '<h2 class="section-title">Cardiovascular Health</h2>';
  html += '<div class="cardio-grid">';
  
  if (cardio.resting_hr) {
    html += renderCardioCard('Resting Heart Rate', '💓', cardio.resting_hr.value, cardio.resting_hr.unit);
  }
  
  if (cardio.hrv) {
    html += renderCardioCard('Heart Rate Variability', '📈', cardio.hrv.value, cardio.hrv.unit);
  }
  
  html += '</div>';
  return html;
}

function renderCardioCard(name, icon, value, unit) {
  return `
    <div class="cardio-card">
      <div class="cardio-icon">${icon}</div>
      <div class="cardio-info">
        <div class="cardio-name">${name}</div>
        <div class="cardio-value">${value} <span class="cardio-unit">${unit}</span></div>
      </div>
    </div>
  `;
}

/* ========================================================= */
/*  Mobility Rendering                                       */
/* ========================================================= */

function renderMobility(mobility) {
  let html = '<h2 class="section-title">Mobility</h2>';
  html += '<div class="mobility-grid">';
  
  if (mobility.walking_speed) {
    html += renderMobilityCard('Walking Speed', '🏃', mobility.walking_speed.value, mobility.walking_speed.unit);
  }
  
  if (mobility.step_length) {
    html += renderMobilityCard('Step Length', '👣', mobility.step_length.value, mobility.step_length.unit);
  }
  
  html += '</div>';
  return html;
}

function renderMobilityCard(name, icon, value, unit) {
  return `
    <div class="mobility-card">
      <div class="mobility-icon">${icon}</div>
      <div class="mobility-info">
        <div class="mobility-name">${name}</div>
        <div class="mobility-value">${value} <span class="mobility-unit">${unit}</span></div>
      </div>
    </div>
  `;
}

/* ========================================================= */
/*  Medications Rendering                                    */
/* ========================================================= */

function renderMedications(medications) {
  let html = '<div class="dashboard-card medications-card">';
  html += '<div class="card-icon">💊</div>';
  html += '<div class="card-content">';
  html += '<h2>Current Medications</h2>';
  html += '<div class="medications-list">';
  
  medications.forEach(med => {
    html += `<div class="med-item">
      <span class="med-name">${med.name}</span>
      <span class="med-date">${formatDate(med.date)}</span>
    </div>`;
  });
  
  html += '</div></div></div>';
  return html;
}

/* ========================================================= */
/*  Lab Results Rendering                                    */
/* ========================================================= */

function renderLabResults(labResults) {
  let html = '<div class="dashboard-card lab-results-card">';
  html += '<div class="card-icon">🔬</div>';
  html += '<div class="card-content">';
  html += '<h2>Recent Lab Results</h2>';
  html += '<div class="lab-results-list">';
  
  labResults.forEach(lab => {
    html += `<div class="lab-item">
      <div class="lab-name">${lab.name}</div>
      <div class="lab-value">${lab.value} ${lab.unit}</div>
      <div class="lab-date">${formatDate(lab.date)}</div>
    </div>`;
  });
  
  html += '</div></div></div>';
  return html;
}

/* ========================================================= */
/*  Clinical Rendering (Allergies & Conditions)             */
/* ========================================================= */

function renderClinical(clinical) {
  let html = '<div class="dashboard-card clinical-card">';
  html += '<div class="card-icon">⚕️</div>';
  html += '<div class="card-content">';
  html += '<h2>Clinical Information</h2>';
  
  // Render allergies
  if (clinical.allergies && clinical.allergies.length > 0) {
    html += '<div class="clinical-section">';
    html += '<h3>Allergies</h3>';
    html += '<div class="clinical-list">';
    clinical.allergies.forEach(allergy => {
      html += `<div class="clinical-item">
        <span class="clinical-name">${allergy.name}</span>
        <span class="clinical-date">${formatDate(allergy.date)}</span>
      </div>`;
    });
    html += '</div></div>';
  }
  
  // Render conditions
  if (clinical.conditions && clinical.conditions.length > 0) {
    html += '<div class="clinical-section">';
    html += '<h3>Conditions</h3>';
    html += '<div class="clinical-list">';
    clinical.conditions.forEach(condition => {
      html += `<div class="clinical-item">
        <span class="clinical-name">${condition.name}</span>
        <span class="clinical-date">${formatDate(condition.date)}</span>
      </div>`;
    });
    html += '</div></div>';
  }
  
  html += '</div></div>';
  return html;
}

/* ========================================================= */
/*  Utility Functions                                        */
/* ========================================================= */

function formatDate(dateString) {
  if (!dateString || dateString === 'N/A') return 'N/A';
  
  try {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', { 
      year: 'numeric', 
      month: 'short', 
      day: 'numeric' 
    });
  } catch (e) {
    return dateString;
  }
}

/* ========================================================= */
/*  Input Box Functionality                                   */
/* ========================================================= */

function initializeDashboardInput() {
  const messageInput = document.getElementById("messageInput");
  const sendButton = document.getElementById("sendButton");
  
  if (!messageInput || !sendButton) return;
  
  // Auto-resize functionality
  function autoResize() {
    messageInput.style.height = 'auto';
    const scrollHeight = messageInput.scrollHeight;
    const lineHeight = parseFloat(getComputedStyle(messageInput).lineHeight) || 24;
    const maxHeight = lineHeight * 8;
    const newHeight = Math.min(scrollHeight, maxHeight);
    messageInput.style.height = newHeight + 'px';
    
    if (scrollHeight > maxHeight) {
      messageInput.style.overflowY = 'auto';
    } else {
      messageInput.style.overflowY = 'hidden';
    }
  }
  
  // Handle send button click
  sendButton.addEventListener('click', handleDashboardMessage);
  
  // Handle Enter key (Shift+Enter for new line)
  messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleDashboardMessage();
    }
  });
  
  // Update send button state and auto-resize based on input
  messageInput.addEventListener('input', () => {
    const hasText = messageInput.value.trim().length > 0;
    sendButton.disabled = !hasText;
    autoResize();
  });
  
  // Also trigger auto-resize on keyup and paste
  messageInput.addEventListener('keyup', autoResize);
  messageInput.addEventListener('paste', () => {
    setTimeout(autoResize, 10);
  });
  
  // Initial state
  sendButton.disabled = true;
  autoResize();
}

function handleDashboardMessage() {
  const messageInput = document.getElementById("messageInput");
  const sendButton = document.getElementById("sendButton");
  
  if (!messageInput || !sendButton) return;
  
  const message = messageInput.value.trim();
  if (!message) return;
  
  // Disable input while processing
  messageInput.disabled = true;
  sendButton.disabled = true;
  messageInput.style.height = 'auto';
  
  // Create new session and redirect with message
  fetch("/api/new_session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({})
  })
  .then(r => r.json())
  .then(d => {
    if (!d || !d.success) {
      throw new Error(d && d.message || "Failed to start session");
    }
    const sessionId = d.session_id;
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

/* ========================================================= */
/*  Initialize Dashboard on Page Load                        */
/* ========================================================= */

document.addEventListener("DOMContentLoaded", () => {
  // Only run on dashboard page
  if (location.pathname === "/dashboard") {
    console.log("Initializing dashboard...");
    
    // Load dashboard data
    loadDashboardData();
    
    // Initialize input box
    initializeDashboardInput();
  }
});

