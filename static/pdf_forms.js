/*********************************************************************
 *  pdf_forms.js  —  PDF Form Filling functionality
 *
 *  • Upload PDF form
 *  • AI-powered field extraction
 *  • Edit and review form fields
 *  • Generate filled PDF
 *********************************************************************/

// State management
let currentPdfId = null;
let currentFields = [];

// DOM elements
const uploadSection = document.getElementById('uploadSection');
const processingSection = document.getElementById('processingSection');
const formFieldsSection = document.getElementById('formFieldsSection');
const downloadSection = document.getElementById('downloadSection');
const pdfFileInput = document.getElementById('pdfFileInput');
const uploadBtn = document.getElementById('uploadBtn');
const fileName = document.getElementById('fileName');
const processingStatus = document.getElementById('processingStatus');
const formFieldsList = document.getElementById('formFieldsList');
const cancelBtn = document.getElementById('cancelBtn');
const generatePdfBtn = document.getElementById('generatePdfBtn');
const downloadBtn = document.getElementById('downloadBtn');
const newFormBtn = document.getElementById('newFormBtn');

// Initialize event listeners
function init() {
  // Upload button
  uploadBtn.addEventListener('click', () => {
    pdfFileInput.click();
  });

  // File input change
  pdfFileInput.addEventListener('change', handleFileSelect);

  // Drag and drop
  const uploadBox = document.querySelector('.upload-box');
  uploadBox.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadBox.style.borderColor = '#ff6850';
    uploadBox.style.backgroundColor = '#fff5f0';
  });

  uploadBox.addEventListener('dragleave', (e) => {
    e.preventDefault();
    uploadBox.style.borderColor = '#d1d5db';
    uploadBox.style.backgroundColor = 'transparent';
  });

  uploadBox.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadBox.style.borderColor = '#d1d5db';
    uploadBox.style.backgroundColor = 'transparent';
    
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      handleFile(files[0]);
    }
  });

  // Cancel button
  cancelBtn.addEventListener('click', resetForm);

  // Generate PDF button
  generatePdfBtn.addEventListener('click', generateFilledPdf);

  // Download button
  downloadBtn.addEventListener('click', downloadPdf);

  // New form button
  newFormBtn.addEventListener('click', resetForm);
}

// Handle file selection
function handleFileSelect(e) {
  const file = e.target.files[0];
  if (file) {
    handleFile(file);
  }
}

// Handle file upload
async function handleFile(file) {
  // Validate file type
  if (!file.name.endsWith('.pdf')) {
    alert('Please select a PDF file');
    return;
  }

  // Show file name
  fileName.textContent = `Selected: ${file.name}`;
  fileName.style.display = 'block';

  // Show processing section
  showSection('processing');
  processingStatus.textContent = 'Uploading PDF...';

  // Create form data
  const formData = new FormData();
  formData.append('file', file);

  try {
    // Upload PDF
    processingStatus.textContent = 'Analyzing form fields...';
    const response = await fetch('/api/pdf/upload', {
      method: 'POST',
      body: formData
    });

    // Show AI generation status
    processingStatus.textContent = 'AI is generating field values...';

    const data = await response.json();

    if (data.success) {
      currentPdfId = data.pdf_id;
      currentFields = data.fields;
      
      // Display fields
      displayFields(data.fields);
      showSection('fields');
    } else {
      alert('Error: ' + (data.message || 'Failed to process PDF'));
      showSection('upload');
    }
  } catch (error) {
    console.error('Upload error:', error);
    alert('Failed to upload PDF. Please try again.');
    showSection('upload');
  }
}

// Display form fields
function displayFields(fields) {
  formFieldsList.innerHTML = '';

  // Count AI-filled fields
  const aiFilledCount = fields.filter(f => f.field_value && f.field_value.trim() !== '').length;
  const totalFields = fields.length;
  
  // Show AI summary
  const aiSummary = document.getElementById('aiSummary');
  if (aiFilledCount > 0) {
    aiSummary.style.display = 'block';
    aiSummary.innerHTML = `<strong> Health Assistant:</strong> ${aiFilledCount} of ${totalFields} fields have been automatically filled based on your health records.`;
  } else {
    aiSummary.style.display = 'none';
  }

  fields.forEach((field, index) => {
    const fieldDiv = document.createElement('div');
    fieldDiv.className = 'form-field';

    const label = document.createElement('label');
    label.textContent = field.field_name;
    
    // Add AI badge if field has a value
    if (field.field_value && field.field_value.trim() !== '') {
      const aiBadge = document.createElement('span');
      aiBadge.className = 'ai-badge';
      aiBadge.textContent = '✨ AI';
      aiBadge.title = 'This value was generated by AI';
      label.appendChild(aiBadge);
    }
    
    fieldDiv.appendChild(label);

    let input;
    if (field.field_type === 'textarea') {
      input = document.createElement('textarea');
      input.rows = 3;
    } else {
      input = document.createElement('input');
      input.type = 'text';
    }

    input.value = field.field_value || '';
    input.dataset.fieldIndex = index;
    input.addEventListener('input', (e) => {
      currentFields[index].field_value = e.target.value;
    });

    fieldDiv.appendChild(input);
    formFieldsList.appendChild(fieldDiv);
  });
}

// Generate filled PDF
async function generateFilledPdf() {
  // Validate fields
  const emptyFields = currentFields.filter(f => !f.field_value || f.field_value.trim() === '');
  if (emptyFields.length > 0) {
    const confirmMsg = `${emptyFields.length} field(s) are empty. Continue anyway?`;
    if (!confirm(confirmMsg)) {
      return;
    }
  }

  // Show processing
  showSection('processing');
  processingStatus.textContent = 'Generating filled PDF...';

  try {
    const response = await fetch('/api/pdf/generate', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        pdf_id: currentPdfId,
        fields: currentFields
      })
    });

    const data = await response.json();

    if (data.success) {
      showSection('download');
    } else {
      alert('Error: ' + (data.message || 'Failed to generate PDF'));
      showSection('fields');
    }
  } catch (error) {
    console.error('Generation error:', error);
    alert('Failed to generate PDF. Please try again.');
    showSection('fields');
  }
}

// Download PDF
async function downloadPdf() {
  try {
    // Trigger download
    window.location.href = '/api/pdf/download';
  } catch (error) {
    console.error('Download error:', error);
    alert('Failed to download PDF. Please try again.');
  }
}

// Show section
function showSection(section) {
  uploadSection.style.display = 'none';
  processingSection.style.display = 'none';
  formFieldsSection.style.display = 'none';
  downloadSection.style.display = 'none';

  switch (section) {
    case 'upload':
      uploadSection.style.display = 'block';
      break;
    case 'processing':
      processingSection.style.display = 'block';
      break;
    case 'fields':
      formFieldsSection.style.display = 'block';
      break;
    case 'download':
      downloadSection.style.display = 'block';
      break;
  }
}

// Reset form
function resetForm() {
  currentPdfId = null;
  currentFields = [];
  pdfFileInput.value = '';
  fileName.style.display = 'none';
  fileName.textContent = '';
  formFieldsList.innerHTML = '';
  showSection('upload');
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', init);

