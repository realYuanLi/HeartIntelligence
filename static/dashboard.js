/*********************************************************************
 *  dashboard.js  —  Comprehensive Health Dashboard
 *
 *  • Load and display health analytics
 *  • Show trends, statistics, and comparisons
 *  • Display medications, lab results, conditions
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
  
  // Cardiovascular section
  if (data.cardiovascular) {
    html += renderCategoryPanel('Cardiovascular Health', '🫀', data.cardiovascular, 'cardiovascular');
  }
  
  // Activity section
  if (data.activity) {
    html += renderCategoryPanel('Physical Activity', '💪', data.activity, 'activity');
  }
  
  // Mobility section
  if (data.mobility) {
    html += renderCategoryPanel('Mobility & Movement', '🚶', data.mobility, 'mobility');
  }
  
  // Clinical section (medications, labs, conditions, allergies)
  if (data.clinical) {
    html += renderClinicalPanel(data.clinical);
  }
  
  container.innerHTML = html;
}

/* ========================================================= */
/*  Summary Panel                                            */
/* ========================================================= */

function renderSummaryPanel(summary, demographics) {
  let html = '<div class="summary-panel">';
  html += '<h2>Health Summary</h2>';
  
  if (demographics && demographics.name) {
    html += '<div class="summary-demographics">';
    html += `<div class="demo-item"><strong>Name:</strong> ${demographics.name}</div>`;
    html += `<div class="demo-item"><strong>Age:</strong> ${demographics.age || 'N/A'}</div>`;
    html += `<div class="demo-item"><strong>Sex:</strong> ${demographics.sex || 'N/A'}</div>`;
    html += '</div>';
  }
  
  html += '<div class="summary-stats">';
  html += `<div class="stat-item">`;
  html += `<div class="stat-value">${summary.total_data_points?.toLocaleString() || '0'}</div>`;
  html += `<div class="stat-label">Total Records</div>`;
  html += `</div>`;
  
  html += `<div class="stat-item">`;
  html += `<div class="stat-value">${summary.categories_tracked?.length || '0'}</div>`;
  html += `<div class="stat-label">Categories Tracked</div>`;
  html += `</div>`;
  
  if (summary.date_range && summary.date_range.earliest) {
    const earliest = new Date(summary.date_range.earliest);
    const latest = new Date(summary.date_range.latest);
    const days = Math.floor((latest - earliest) / (1000 * 60 * 60 * 24));
    html += `<div class="stat-item">`;
    html += `<div class="stat-value">${days}</div>`;
    html += `<div class="stat-label">Days of Data</div>`;
    html += `</div>`;
  }
  
  html += '</div>';
  html += '</div>';
  
  return html;
}

/* ========================================================= */
/*  Category Panel (Cardiovascular, Activity, Mobility)      */
/* ========================================================= */

function renderCategoryPanel(title, icon, data, categoryId) {
  let html = `<div class="category-panel" id="${categoryId}-panel">`;
  html += `<div class="category-header">`;
  html += `<h2>${icon} ${title}</h2>`;
  html += `</div>`;
  
  html += `<div class="category-content">`;
  html += `<div class="metrics-grid">`;
  
  // Render each metric
  for (const [key, metric] of Object.entries(data)) {
    if (metric && metric.name) {
      html += renderMetricCard(metric);
    }
  }
  
  html += `</div>`;
  html += `</div>`;
  html += `</div>`;
  
  return html;
}

function renderMetricCard(metric) {
  // Special handling for blood pressure
  if (metric.name === "Blood Pressure") {
    return renderBloodPressureCard(metric);
  }
  
  const statusClass = getMetricStatus(metric);
  const trendArrow = getTrendArrow(metric.trend, metric.change_pct);
  
  let html = `<div class="metric-card ${statusClass}">`;
  html += `<h3>${metric.name}</h3>`;
  
  // Current value with trend
  html += `<div class="metric-value">`;
  html += `${metric.current || 'N/A'} <span class="metric-unit">${metric.unit || ''}</span>`;
  if (metric.change_pct !== undefined && metric.change_pct !== 0) {
    html += `<span class="metric-trend ${metric.trend}">${trendArrow} ${Math.abs(metric.change_pct)}%</span>`;
  }
  html += `</div>`;
  
  // Statistics
  html += `<div class="metric-stats">`;
  if (metric.avg_7d) {
    html += `<div class="stat-row"><span class="stat-label">7-day avg:</span> <span class="stat-value">${metric.avg_7d} ${metric.unit}</span></div>`;
  }
  if (metric.avg_30d) {
    html += `<div class="stat-row"><span class="stat-label">30-day avg:</span> <span class="stat-value">${metric.avg_30d} ${metric.unit}</span></div>`;
  }
  if (metric.min_30d && metric.max_30d) {
    html += `<div class="stat-row"><span class="stat-label">Range (30d):</span> <span class="stat-value">${metric.min_30d}-${metric.max_30d}</span></div>`;
  }
  html += `</div>`;
  
  // Normal range / Goal
  if (metric.normal_range) {
    html += `<div class="metric-reference">`;
    html += `<span class="ref-label">Normal:</span> `;
    html += `${metric.normal_range.min}-${metric.normal_range.max} ${metric.unit}`;
    html += ` ${getStatusBadge(metric)}`;
    html += `</div>`;
  } else if (metric.goal) {
    html += `<div class="metric-reference">`;
    html += `<span class="ref-label">Goal:</span> ${metric.goal} ${metric.unit}`;
    html += `</div>`;
  }
  
  // Data points
  if (metric.data_points) {
    html += `<div class="metric-footer">${metric.data_points} measurements in last 30 days</div>`;
  }
  
  html += `</div>`;
  
  return html;
}

function renderBloodPressureCard(metric) {
  let html = `<div class="metric-card blood-pressure-card">`;
  html += `<h3>${metric.name}</h3>`;
  
  // Current reading
  html += `<div class="metric-value">`;
  html += `${metric.current || 'N/A'} <span class="metric-unit">${metric.unit || ''}</span>`;
  html += `</div>`;
  
  html += `<div class="bp-date">Latest: ${formatDate(metric.date)}</div>`;
  
  // Recent readings
  if (metric.recent_readings && metric.recent_readings.length > 0) {
    html += `<div class="bp-history">`;
    html += `<h4>Recent Readings</h4>`;
    metric.recent_readings.forEach(reading => {
      html += `<div class="bp-reading">`;
      html += `<span class="bp-value">${reading.value}</span>`;
      html += `<span class="bp-date">${formatDate(reading.date)}</span>`;
      html += `</div>`;
    });
    html += `</div>`;
  }
  
  // Normal range
  if (metric.normal_range) {
    html += `<div class="metric-reference">`;
    html += `<span class="ref-label">Normal:</span> `;
    html += `${metric.normal_range.systolic.min}-${metric.normal_range.systolic.max}/`;
    html += `${metric.normal_range.diastolic.min}-${metric.normal_range.diastolic.max} ${metric.unit}`;
    html += `</div>`;
  }
  
  html += `</div>`;
  
  return html;
}

/* ========================================================= */
/*  Clinical Panel (Medications, Labs, Conditions, Allergies)*/
/* ========================================================= */

function renderClinicalPanel(clinical) {
  let html = `<div class="category-panel clinical-panel">`;
  html += `<div class="category-header">`;
  html += `<h2>🏥 Clinical Records</h2>`;
  html += `</div>`;
  
  html += `<div class="category-content">`;
  
  // Medications
  if (clinical.medications && clinical.medications.length > 0) {
    html += renderMedicationsSection(clinical.medications);
  }
  
  // Lab Results
  if (clinical.lab_results && clinical.lab_results.length > 0) {
    html += renderLabResultsSection(clinical.lab_results);
  }
  
  // Conditions and Allergies in two columns
  html += `<div class="clinical-grid">`;
  
  if (clinical.conditions && clinical.conditions.length > 0) {
    html += renderConditionsSection(clinical.conditions);
  }
  
  if (clinical.allergies && clinical.allergies.length > 0) {
    html += renderAllergiesSection(clinical.allergies);
  }
  
  html += `</div>`;
  
  html += `</div>`;
  html += `</div>`;
  
  return html;
}

function renderMedicationsSection(medications) {
  let html = `<div class="clinical-section medications-section">`;
  html += `<h3>💊 Medications (${medications.length})</h3>`;
  html += `<div class="medications-list">`;
  
  medications.forEach(med => {
    html += `<div class="medication-item">`;
    html += `<div class="med-header">`;
    html += `<span class="med-name">${med.name}</span>`;
    if (med.category && med.category !== 'N/A') {
      html += `<span class="med-category">${med.category}</span>`;
    }
    html += `</div>`;
    html += `<div class="med-date">Prescribed: ${formatDate(med.date)}</div>`;
    html += `</div>`;
  });
  
  html += `</div>`;
  html += `</div>`;
  
  return html;
}

function renderLabResultsSection(labs) {
  // Filter out labs with N/A values
  const validLabs = labs.filter(lab => lab.value && lab.value !== 'N/A');
  
  if (validLabs.length === 0) {
    return '';
  }
  
  let html = `<div class="clinical-section lab-results-section">`;
  html += `<h3>🔬 Lab Results (${validLabs.length})</h3>`;
  html += `<div class="lab-results-list">`;
  
  validLabs.forEach(lab => {
    html += `<div class="lab-item">`;
    html += `<div class="lab-header">`;
    html += `<span class="lab-name">${lab.name}</span>`;
    if (lab.status) {
      html += `<span class="lab-status ${lab.status.toLowerCase()}">${lab.status}</span>`;
    }
    html += `</div>`;
    html += `<div class="lab-value">${lab.value} ${lab.unit || ''}</div>`;
    html += `<div class="lab-date">${formatDate(lab.date)}</div>`;
    html += `</div>`;
  });
  
  html += `</div>`;
  html += `</div>`;
  
  return html;
}

function renderConditionsSection(conditions) {
  let html = `<div class="clinical-subsection conditions-section">`;
  html += `<h3>🩺 Conditions (${conditions.length})</h3>`;
  html += `<div class="conditions-list">`;
  
  conditions.forEach(cond => {
    html += `<div class="condition-item">`;
    html += `<div class="condition-name">${cond.name}</div>`;
    html += `<div class="condition-date">${formatDate(cond.date)}</div>`;
    html += `</div>`;
  });
  
  html += `</div>`;
  html += `</div>`;
  
  return html;
}

function renderAllergiesSection(allergies) {
  let html = `<div class="clinical-subsection allergies-section">`;
  html += `<h3>⚠️ Allergies (${allergies.length})</h3>`;
  html += `<div class="allergies-list">`;
  
  allergies.forEach(allergy => {
    html += `<div class="allergy-item">`;
    html += `<div class="allergy-name">${allergy.name}</div>`;
    html += `<div class="allergy-date">${formatDate(allergy.date)}</div>`;
    html += `</div>`;
  });
  
  html += `</div>`;
  html += `</div>`;
  
  return html;
}

/* ========================================================= */
/*  Helper Functions                                         */
/* ========================================================= */

function getMetricStatus(metric) {
  if (!metric.normal_range || metric.current === null) {
    return '';
  }
  
  const val = metric.current;
  const range = metric.normal_range;
  
  if (val >= range.min && val <= range.max) {
    return 'status-normal';
  } else if (val < range.min * 0.9 || val > range.max * 1.1) {
    return 'status-alert';
  } else {
    return 'status-borderline';
  }
}

function getStatusBadge(metric) {
  if (!metric.normal_range || metric.current === null) {
    return '';
  }
  
  const val = metric.current;
  const range = metric.normal_range;
  
  if (val >= range.min && val <= range.max) {
    return '<span class="status-badge normal">✓ Normal</span>';
  } else if (val < range.min * 0.9 || val > range.max * 1.1) {
    return '<span class="status-badge alert">⚡ Alert</span>';
  } else {
    return '<span class="status-badge borderline">⚠️ Borderline</span>';
  }
}

function getTrendArrow(trend, change_pct) {
  if (!trend || change_pct === 0) return '';
  
  if (trend === 'up') {
    return '↑';
  } else if (trend === 'down') {
    return '↓';
  } else {
    return '→';
  }
}

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
