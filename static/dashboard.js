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
  
  // Also load mobile health data
  loadMobileHealthData();
}

function loadMobileHealthData() {
  fetch("/api/mobile_health_data")
    .then(r => r.json())
    .then(response => {
      if (response.success && response.data) {
        renderAppleHealthSections(response.data);
      } else {
        const activitySection = document.getElementById("activitySection");
        const heartSection = document.getElementById("heartHealthSection");
        if (activitySection) {
          activitySection.innerHTML = '<div class="no-data">No activity data available</div>';
        }
        if (heartSection) {
          heartSection.innerHTML = '<div class="no-data">No heart health data available</div>';
        }
      }
    })
    .catch(err => {
      console.error("Failed to load mobile health data:", err);
      const activitySection = document.getElementById("activitySection");
      const heartSection = document.getElementById("heartHealthSection");
      if (activitySection) {
        activitySection.innerHTML = '<div class="info">Activity data not available</div>';
      }
      if (heartSection) {
        heartSection.innerHTML = '<div class="info">Heart health data not available</div>';
      }
    });
}

function renderDashboard(data) {
  const container = document.getElementById("dashboardData");
  let html = '';
  
  // Primary Cardiac Diagnosis section (HEART CONDITION)
  if (data.diagnosis) {
    html += renderDiagnosisPanel(data.diagnosis);
  }
  
  // Comorbidities section
  if (data.comorbidities) {
    html += renderComorbiditiesPanel(data.comorbidities);
  }
  
  // Medications section
  if (data.medications) {
    html += renderMedicationsPanel(data.medications);
  }
  
  // Symptoms section
  if (data.symptoms) {
    html += renderSymptomsPanel(data.symptoms);
  }
  
  // Wearable data section
  if (data.wearable_data) {
    html += renderWearableDataPanel(data.wearable_data);
  }
  
  // Recent healthcare section
  if (data.recent_care) {
    html += renderRecentCarePanel(data.recent_care);
  }
  
  container.innerHTML = html;
}

/* ========================================================= */
/*  Patient Profile Summary Panel                            */
/* ========================================================= */

function renderPatientSummary(summary, demographics) {
  let html = '<div class="summary-panel">';
  html += '<h2>📋 Patient Profile</h2>';
  
  if (demographics) {
    html += '<div class="summary-demographics">';
    html += `<div class="demo-item"><strong>Name:</strong> ${demographics.name || 'N/A'}</div>`;
    html += `<div class="demo-item"><strong>Age:</strong> ${demographics.age || 'N/A'}</div>`;
    html += `<div class="demo-item"><strong>Sex:</strong> ${demographics.sex || 'N/A'}</div>`;
    if (demographics.living_situation) {
      html += `<div class="demo-item"><strong>Living Situation:</strong> ${demographics.living_situation}</div>`;
    }
    if (demographics.baseline_functional_status) {
      html += `<div class="demo-item"><strong>Functional Status:</strong> ${demographics.baseline_functional_status}</div>`;
    }
    html += '</div>';
  }
  
  if (summary && summary.ui_summary) {
    html += '<div class="patient-summary-text">';
    html += `<p><strong>Summary:</strong> ${summary.ui_summary}</p>`;
    html += '</div>';
  }
  
  html += '</div>';
  
  return html;
}

/* ========================================================= */
/*  Primary Cardiac Diagnosis Panel (HEART CONDITION)       */
/* ========================================================= */

function renderDiagnosisPanel(diagnosis) {
  let html = '<div class="category-panel diagnosis-panel">';
  html += '<div class="category-header">';
  html += '<h2>🫀 Primary Cardiac Diagnosis</h2>';
  html += '</div>';
  
  html += '<div class="category-content">';
  
  if (diagnosis.condition) {
    html += '<div class="diagnosis-condition">';
    html += `<h3>${diagnosis.condition}</h3>`;
    html += '</div>';
  }
  
  if (diagnosis.echocardiogram) {
    html += '<div class="echocardiogram-data">';
    html += '<h4>Echocardiogram Findings:</h4>';
    html += '<div class="metrics-grid">';
    
    const echo = diagnosis.echocardiogram;
    
    if (echo.lvef_percent) {
      html += '<div class="metric-card">';
      html += '<h4>LVEF</h4>';
      html += `<div class="metric-value">${echo.lvef_percent}<span class="metric-unit">%</span></div>`;
      html += '<div class="metric-label">Left Ventricular Ejection Fraction</div>';
      html += '</div>';
    }
    
    if (echo.diastolic_function) {
      html += '<div class="metric-card">';
      html += '<h4>Diastolic Function</h4>';
      html += `<div class="metric-value-text">${echo.diastolic_function}</div>`;
      html += '</div>';
    }
    
    if (echo.left_atrial_size) {
      html += '<div class="metric-card">';
      html += '<h4>Left Atrial Size</h4>';
      html += `<div class="metric-value-text">${echo.left_atrial_size}</div>`;
      html += '</div>';
    }
    
    if (echo.pulmonary_artery_systolic_pressure) {
      html += '<div class="metric-card">';
      html += '<h4>PA Systolic Pressure</h4>';
      html += `<div class="metric-value-text">${echo.pulmonary_artery_systolic_pressure}</div>`;
      html += '</div>';
    }
    
    html += '</div>';
    html += '</div>';
  }
  
  html += '</div>';
  html += '</div>';
  
  return html;
}

/* ========================================================= */
/*  Comorbidities Panel                                      */
/* ========================================================= */

function renderComorbiditiesPanel(comorbidities) {
  let html = '<div class="category-panel comorbidities-panel">';
  html += '<div class="category-header">';
  html += '<h2>🏥 Comorbidities</h2>';
  html += '</div>';
  
  html += '<div class="category-content">';
  html += '<div class="comorbidities-grid">';
  
  if (comorbidities.cardiovascular && comorbidities.cardiovascular.length > 0) {
    html += '<div class="comorbidity-category">';
    html += '<h4>Cardiovascular</h4>';
    html += '<ul>';
    comorbidities.cardiovascular.forEach(condition => {
      html += `<li>${condition}</li>`;
    });
    html += '</ul>';
    html += '</div>';
  }
  
  if (comorbidities.metabolic_systemic && comorbidities.metabolic_systemic.length > 0) {
    html += '<div class="comorbidity-category">';
    html += '<h4>Metabolic/Systemic</h4>';
    html += '<ul>';
    comorbidities.metabolic_systemic.forEach(condition => {
      html += `<li>${condition}</li>`;
    });
    html += '</ul>';
    html += '</div>';
  }
  
  if (comorbidities.respiratory_sleep && comorbidities.respiratory_sleep.length > 0) {
    html += '<div class="comorbidity-category">';
    html += '<h4>Respiratory/Sleep</h4>';
    html += '<ul>';
    comorbidities.respiratory_sleep.forEach(condition => {
      html += `<li>${condition}</li>`;
    });
    html += '</ul>';
    html += '</div>';
  }
  
  if (comorbidities.other && comorbidities.other.length > 0) {
    html += '<div class="comorbidity-category">';
    html += '<h4>Other</h4>';
    html += '<ul>';
    comorbidities.other.forEach(condition => {
      html += `<li>${condition}</li>`;
    });
    html += '</ul>';
    html += '</div>';
  }
  
  html += '</div>';
  html += '</div>';
  html += '</div>';
  
  return html;
}

/* ========================================================= */
/*  Medications Panel                                        */
/* ========================================================= */

function renderMedicationsPanel(medications) {
  let html = '<div class="category-panel medications-panel">';
  html += '<div class="category-header">';
  html += '<h2>💊 Medications</h2>';
  html += '</div>';
  
  html += '<div class="category-content">';
  html += '<div class="medications-grid">';
  
  if (medications.cardiovascular_hf && medications.cardiovascular_hf.length > 0) {
    html += '<div class="medication-category">';
    html += '<h4>Cardiovascular/Heart Failure</h4>';
    medications.cardiovascular_hf.forEach(med => {
      html += '<div class="medication-item">';
      html += `<div class="med-name">${med.name}</div>`;
      html += `<div class="med-dose">${med.dose}</div>`;
      html += `<div class="med-indication">${med.indication}</div>`;
      html += '</div>';
    });
    html += '</div>';
  }
  
  if (medications.metabolic && medications.metabolic.length > 0) {
    html += '<div class="medication-category">';
    html += '<h4>Metabolic</h4>';
    medications.metabolic.forEach(med => {
      html += '<div class="medication-item">';
      html += `<div class="med-name">${med.name}</div>`;
      html += `<div class="med-dose">${med.dose}</div>`;
      html += `<div class="med-indication">${med.indication}</div>`;
      html += '</div>';
    });
    html += '</div>';
  }
  
  if (medications.other && medications.other.length > 0) {
    html += '<div class="medication-category">';
    html += '<h4>Other</h4>';
    medications.other.forEach(med => {
      html += '<div class="medication-item">';
      html += `<div class="med-name">${med.name}</div>`;
      html += `<div class="med-dose">${med.dose}</div>`;
      html += `<div class="med-indication">${med.indication}</div>`;
      html += '</div>';
    });
    html += '</div>';
  }
  
  if (medications.supplements && medications.supplements.length > 0) {
    html += '<div class="medication-category">';
    html += '<h4>Supplements</h4>';
    html += '<ul>';
    medications.supplements.forEach(supp => {
      html += `<li>${supp}</li>`;
    });
    html += '</ul>';
    html += '</div>';
  }
  
  html += '</div>';
  html += '</div>';
  html += '</div>';
  
  return html;
}

/* ========================================================= */
/*  Symptoms Panel                                           */
/* ========================================================= */

function renderSymptomsPanel(symptoms) {
  let html = '<div class="category-panel symptoms-panel">';
  html += '<div class="category-header">';
  html += '<h2>🩺 Symptoms</h2>';
  html += '</div>';
  
  html += '<div class="category-content">';
  html += '<div class="symptoms-grid">';
  
  if (symptoms.chronic_baseline && symptoms.chronic_baseline.length > 0) {
    html += '<div class="symptom-category">';
    html += '<h4>Chronic Baseline Symptoms</h4>';
    html += '<ul>';
    symptoms.chronic_baseline.forEach(symptom => {
      html += `<li>${symptom}</li>`;
    });
    html += '</ul>';
    html += '</div>';
  }
  
  if (symptoms.intermittent_recent && symptoms.intermittent_recent.length > 0) {
    html += '<div class="symptom-category">';
    html += '<h4>Intermittent/Recent Symptoms</h4>';
    html += '<ul>';
    symptoms.intermittent_recent.forEach(symptom => {
      html += `<li>${symptom}</li>`;
    });
    html += '</ul>';
    html += '</div>';
  }
  
  if (symptoms.negative_findings && symptoms.negative_findings.length > 0) {
    html += '<div class="symptom-category">';
    html += '<h4>Negative Findings</h4>';
    html += '<ul>';
    symptoms.negative_findings.forEach(finding => {
      html += `<li>${finding}</li>`;
    });
    html += '</ul>';
    html += '</div>';
  }
  
  html += '</div>';
  html += '</div>';
  html += '</div>';
  
  return html;
}

/* ========================================================= */
/*  Wearable Data Panel                                      */
/* ========================================================= */

function renderWearableDataPanel(wearable) {
  let html = '<div class="category-panel wearable-panel">';
  html += '<div class="category-header">';
  html += '<h2>⌚ Wearable Data Summary</h2>';
  html += '</div>';
  
  html += '<div class="category-content">';
  
  if (wearable.ecg && wearable.ecg.length > 0) {
    html += '<div class="wearable-section">';
    html += '<h4>ECG Findings:</h4>';
    html += '<ul>';
    wearable.ecg.forEach(finding => {
      html += `<li>${finding}</li>`;
    });
    html += '</ul>';
    html += '</div>';
  }
  
  if (wearable.activity) {
    html += '<div class="wearable-section">';
    html += '<h4>Activity:</h4>';
    html += `<p>${wearable.activity}</p>`;
    html += '</div>';
  }
  
  if (wearable.sleep) {
    html += '<div class="wearable-section">';
    html += '<h4>Sleep:</h4>';
    html += `<p>${wearable.sleep}</p>`;
    html += '</div>';
  }
  
  html += '</div>';
  html += '</div>';
  
  return html;
}

/* ========================================================= */
/*  Recent Healthcare Utilization Panel                      */
/* ========================================================= */

function renderRecentCarePanel(recent_care) {
  let html = '<div class="category-panel recent-care-panel">';
  html += '<div class="category-header">';
  html += '<h2>🏥 Recent Healthcare Utilization</h2>';
  html += '</div>';
  
  html += '<div class="category-content">';
  
  if (recent_care.last_hospitalization) {
    const hosp = recent_care.last_hospitalization;
    html += '<div class="care-section">';
    html += `<h4>Last Hospitalization (${hosp.time_ago || 'N/A'})</h4>`;
    html += `<p><strong>Reason:</strong> ${hosp.reason || 'N/A'}</p>`;
    html += `<p><strong>Length of Stay:</strong> ${hosp.length_of_stay_days || 'N/A'} days</p>`;
    if (hosp.treatments && hosp.treatments.length > 0) {
      html += '<p><strong>Treatments:</strong></p>';
      html += '<ul>';
      hosp.treatments.forEach(treatment => {
        html += `<li>${treatment}</li>`;
      });
      html += '</ul>';
    }
    html += '</div>';
  }
  
  if (recent_care.last_cardiology_clinic_visit) {
    const visit = recent_care.last_cardiology_clinic_visit;
    html += '<div class="care-section">';
    html += `<h4>Last Cardiology Clinic Visit (${visit.time_ago || 'N/A'})</h4>`;
    html += `<p><strong>Status:</strong> ${visit.status_at_visit || 'N/A'}</p>`;
    html += '</div>';
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
  // Filter out N/A values
  const filteredLabs = labs.filter(lab => lab.value && lab.value !== 'N/A');
  
  if (filteredLabs.length === 0) {
    return '';
  }
  
  let html = `<div class="clinical-section lab-results-section">`;
  html += `<h3>🔬 Lab Results (${filteredLabs.length})</h3>`;
  html += `<div class="lab-results-list">`;
  
  filteredLabs.forEach(lab => {
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
/*  Apple Health Data Sections Rendering                     */
/* ========================================================= */

function renderAppleHealthSections(data) {
  renderActivitySection(data);
  renderHeartHealthSection(data);
}

function renderActivitySection(data) {
  const container = document.getElementById("activitySection");
  if (!container) return;
  
  let html = '<div class="category-panel activity-panel">';
  html += '<div class="category-header">';
  html += '<h2>🏃 Activity & Steps</h2>';
  html += '</div>';
  
  html += '<div class="category-content">';
  
  // Date range
  if (data.date_range && data.date_range.start) {
    html += `<div class="data-period"><em>Data from Apple Health: ${data.date_range.start} to ${data.date_range.end}</em></div>`;
  }
  
  html += '<div class="metrics-grid">';
  
  // Activity/Steps Cards
  if (data.activity && data.activity.has_data) {
    const steps = data.activity.daily_steps;
    
    if (steps.length > 0) {
      // Latest steps
      const latest = steps[steps.length - 1];
      
      html += '<div class="metric-card">';
      html += '<h4>👟 Today\'s Steps</h4>';
      html += `<div class="metric-value">${Math.round(latest.sum).toLocaleString()}<span class="metric-unit">steps</span></div>`;
      html += `<div class="metric-label">On ${latest.date}</div>`;
      html += '</div>';
      
      // 7-day average
      const recentSteps = steps.slice(-7);
      const avgSteps = Math.round(recentSteps.reduce((sum, d) => sum + d.sum, 0) / recentSteps.length);
      
      html += '<div class="metric-card">';
      html += '<h4>📊 7-Day Average</h4>';
      html += `<div class="metric-value">${avgSteps.toLocaleString()}<span class="metric-unit">steps/day</span></div>`;
      html += `<div class="metric-label">Last 7 days</div>`;
      html += '</div>';
      
      // Best day in last 30 days
      const last30 = steps.slice(-30);
      const bestDay = last30.reduce((max, d) => d.sum > max.sum ? d : max, last30[0]);
      
      html += '<div class="metric-card">';
      html += '<h4>🏆 Best Day (30d)</h4>';
      html += `<div class="metric-value">${Math.round(bestDay.sum).toLocaleString()}<span class="metric-unit">steps</span></div>`;
      html += `<div class="metric-label">On ${bestDay.date}</div>`;
      html += '</div>';
      
      // Total steps in last 30 days
      const totalSteps = last30.reduce((sum, d) => sum + d.sum, 0);
      
      html += '<div class="metric-card">';
      html += '<h4>📈 30-Day Total</h4>';
      html += `<div class="metric-value">${Math.round(totalSteps).toLocaleString()}<span class="metric-unit">steps</span></div>`;
      html += `<div class="metric-label">Last 30 days</div>`;
      html += '</div>';
    }
  } else {
    html += '<div class="no-data">No activity data available</div>';
  }
  
  html += '</div>'; // Close metrics-grid
  html += '</div>'; // Close category-content
  html += '</div>'; // Close category-panel
  
  container.innerHTML = html;
}

function renderHeartHealthSection(data) {
  const container = document.getElementById("heartHealthSection");
  if (!container) return;
  
  let html = '<div class="category-panel heart-health-panel">';
  html += '<div class="category-header">';
  html += '<h2>❤️ Heart Health</h2>';
  html += '</div>';
  
  html += '<div class="category-content">';
  html += '<div class="metrics-grid">';
  
  // Heart Rate Cards
  if (data.heart_rate && data.heart_rate.has_data) {
    const hrStats = data.heart_rate.daily_stats;
    const trends = data.heart_rate.trends;
    
    if (hrStats.length > 0) {
      const latest = hrStats[hrStats.length - 1];
      
      // Average Heart Rate
      html += '<div class="metric-card">';
      html += '<h4>💗 Avg Heart Rate</h4>';
      html += `<div class="metric-value">${Math.round(latest.avg)}<span class="metric-unit">bpm</span></div>`;
      html += `<div class="metric-label">On ${latest.date}</div>`;
      if (trends.trend) {
        html += `<div class="metric-details">Trend: ${trends.trend}</div>`;
      }
      html += '</div>';
      
      // Resting Heart Rate (min)
      html += '<div class="metric-card">';
      html += '<h4>😴 Resting HR</h4>';
      html += `<div class="metric-value">${Math.round(latest.min)}<span class="metric-unit">bpm</span></div>`;
      html += `<div class="metric-label">Lowest on ${latest.date}</div>`;
      html += '</div>';
      
      // Max Heart Rate
      html += '<div class="metric-card">';
      html += '<h4>🔥 Peak HR</h4>';
      html += `<div class="metric-value">${Math.round(latest.max)}<span class="metric-unit">bpm</span></div>`;
      html += `<div class="metric-label">Highest on ${latest.date}</div>`;
      html += '</div>';
    }
  }
  
  // HRV Card
  if (data.hrv && data.hrv.has_data) {
    const hrvAvgs = data.hrv.daily_averages;
    const trends = data.hrv.trends;
    
    if (hrvAvgs.length > 0) {
      const latest = hrvAvgs[hrvAvgs.length - 1];
      
      html += '<div class="metric-card">';
      html += '<h4>📉 HRV</h4>';
      html += `<div class="metric-value">${Math.round(latest.avg)}<span class="metric-unit">ms</span></div>`;
      html += `<div class="metric-label">Heart Rate Variability</div>`;
      if (trends.trend) {
        html += `<div class="metric-details">Trend: ${trends.trend}</div>`;
      }
      html += '</div>';
    }
  }
  
  // Blood Pressure (if available)
  if (data.blood_pressure && data.blood_pressure.has_data && data.blood_pressure.readings.length > 0) {
    const latest = data.blood_pressure.readings[0];
    
    html += '<div class="metric-card">';
    html += '<h4>🩺 Blood Pressure</h4>';
    if (latest.systolic && latest.diastolic) {
      html += `<div class="metric-value">${latest.systolic}/${latest.diastolic}<span class="metric-unit">mmHg</span></div>`;
    } else if (latest.systolic) {
      html += `<div class="metric-value">${latest.systolic}<span class="metric-unit">mmHg</span></div>`;
    }
    const readingDate = latest.date.split('T')[0];
    html += `<div class="metric-label">On ${readingDate}</div>`;
    html += '</div>';
  }
  
  if (!data.heart_rate?.has_data && !data.hrv?.has_data) {
    html += '<div class="no-data">No heart health data available</div>';
  }
  
  html += '</div>'; // Close metrics-grid
  html += '</div>'; // Close category-content
  html += '</div>'; // Close category-panel
  
  container.innerHTML = html;
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
