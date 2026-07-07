'use strict';

// API endpoint
const API_ENDPOINT = 'https://zuxxqyttq2.execute-api.us-east-1.amazonaws.com/prod/v1/upload';

// Maximum file size: 50 MB in bytes
const MAX_FILE_SIZE = 52428800;

// Allowed content types — update this to match the Lambda's ALLOWED_CONTENT_TYPES env var
// Default: PDF only. To allow more types, add them here AND update the CloudFormation parameter.
const ALLOWED_CONTENT_TYPES = new Set([
  'application/pdf',
]);

// Session storage key for upload history
const HISTORY_KEY = 'aspph-upload-history';

// DOM references
const fileInput = document.getElementById('file-input');
const passwordInput = document.getElementById('password-input');
const uploadBtn = document.getElementById('upload-btn');
const uploadForm = document.getElementById('upload-form');
const errorContainer = document.getElementById('error-container');
const errorText = document.getElementById('error-text');
const progressContainer = document.getElementById('progress-container');
const progressBar = document.getElementById('progress-bar');
const progressText = document.getElementById('progress-text');
const resultContainer = document.getElementById('result-container');
const urlOutput = document.getElementById('url-output');
const copyBtn = document.getElementById('copy-btn');
const copyConfirmation = document.getElementById('copy-confirmation');
const uploadAnotherBtn = document.getElementById('upload-another-btn');
const dropZone = document.getElementById('drop-zone');
const filenamePreview = document.getElementById('filename-preview');
const filenameOriginal = document.getElementById('filename-original');
const filenameArrow = document.getElementById('filename-arrow');
const filenameSanitized = document.getElementById('filename-sanitized');
const historyContainer = document.getElementById('history-container');
const historyList = document.getElementById('history-list');
const clearHistoryBtn = document.getElementById('clear-history-btn');

// --- Filename sanitization (mirrors Lambda logic) ---

/**
 * Sanitize filename for URL-safe display.
 * Mirrors the Lambda's sanitize_filename() function.
 */
function sanitizeFilename(filename) {
  var ext = '';
  var name = filename;

  if (filename.indexOf('.') !== -1) {
    var lastDot = filename.lastIndexOf('.');
    name = filename.substring(0, lastDot);
    ext = '.' + filename.substring(lastDot + 1).toLowerCase();
  }

  // Lowercase and replace spaces with hyphens
  name = name.toLowerCase().replace(/ /g, '-');

  // Remove URL-unsafe characters (keep alphanumeric, hyphens, underscores, dots)
  name = name.replace(/[^a-z0-9\-_.]/g, '');

  // Collapse multiple hyphens or underscores
  name = name.replace(/-{2,}/g, '-');
  name = name.replace(/_{2,}/g, '_');

  // Strip leading/trailing hyphens or underscores
  name = name.replace(/^[-_]+|[-_]+$/g, '');

  if (!name) {
    name = 'file';
  }

  return name + ext;
}

/**
 * Show filename preview with sanitized version if different.
 */
function showFilenamePreview(file) {
  if (!file) {
    filenamePreview.hidden = true;
    return;
  }

  var sanitized = sanitizeFilename(file.name);
  filenameOriginal.textContent = file.name;
  filenamePreview.hidden = false;

  if (sanitized !== file.name) {
    filenameArrow.hidden = false;
    filenameSanitized.hidden = false;
    filenameSanitized.textContent = sanitized;
  } else {
    filenameArrow.hidden = true;
    filenameSanitized.hidden = true;
  }
}

// --- UI helpers ---

function showError(message) {
  errorText.textContent = message;
  errorContainer.hidden = false;
}

function clearError() {
  errorText.textContent = '';
  errorContainer.hidden = true;
}

function showProgress() {
  progressContainer.hidden = false;
  progressBar.value = 0;
  progressText.textContent = '0%';
}

function updateProgress(percent) {
  var rounded = Math.round(percent);
  progressBar.value = rounded;
  progressText.textContent = rounded + '%';
}

function hideProgress() {
  progressContainer.hidden = true;
}

function showResult(publicUrl) {
  resultContainer.hidden = false;
  urlOutput.textContent = publicUrl;
  urlOutput.href = publicUrl;
}

function hideResult() {
  resultContainer.hidden = true;
  urlOutput.textContent = '';
  urlOutput.href = '';
}

function updateUploadButtonState() {
  var hasFile = fileInput.files && fileInput.files.length > 0;
  uploadBtn.disabled = !hasFile;
  uploadBtn.setAttribute('aria-disabled', String(!hasFile));
}

function resetForm() {
  fileInput.value = '';
  hideResult();
  hideProgress();
  clearError();
  filenamePreview.hidden = true;
  updateUploadButtonState();
}

// --- Upload history (sessionStorage) ---

function getHistory() {
  try {
    var data = sessionStorage.getItem(HISTORY_KEY);
    return data ? JSON.parse(data) : [];
  } catch (e) {
    return [];
  }
}

function saveToHistory(filename, publicUrl) {
  var history = getHistory();
  history.unshift({
    filename: filename,
    url: publicUrl,
    time: new Date().toLocaleTimeString(),
  });
  // Keep last 20 items
  if (history.length > 20) {
    history = history.slice(0, 20);
  }
  sessionStorage.setItem(HISTORY_KEY, JSON.stringify(history));
  renderHistory();
}

function renderHistory() {
  var history = getHistory();
  if (history.length === 0) {
    historyContainer.hidden = true;
    return;
  }

  historyContainer.hidden = false;
  historyList.innerHTML = '';

  history.forEach(function (item) {
    var li = document.createElement('li');
    var link = document.createElement('a');
    link.href = item.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = item.filename;
    var time = document.createElement('span');
    time.className = 'history-time';
    time.textContent = ' (' + item.time + ')';
    li.appendChild(link);
    li.appendChild(time);
    historyList.appendChild(li);
  });
}

function clearHistory() {
  sessionStorage.removeItem(HISTORY_KEY);
  renderHistory();
}

// --- File validation ---

function validateFile(file) {
  if (!file) {
    return 'Please select a file to upload.';
  }

  if (file.size === 0) {
    return 'Empty files are not permitted.';
  }

  if (file.size > MAX_FILE_SIZE) {
    return 'File exceeds maximum size of 50 MB.';
  }

  if (!ALLOWED_CONTENT_TYPES.has(file.type)) {
    return 'File type not allowed. Only PDF files are accepted.';
  }

  return null;
}

// --- API + upload ---

async function requestPresignedUrl(file, password, confirmOverwrite) {
  var body = JSON.stringify({
    password: password,
    filename: file.name,
    contentType: file.type,
    fileSize: file.size,
    confirmOverwrite: confirmOverwrite || false,
  });

  var response = await fetch(API_ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body,
  });

  var data = await response.json();

  if (response.status === 409) {
    data._conflict = true;
    return data;
  }

  if (!response.ok) {
    throw new Error(data.message || 'Upload request failed.');
  }

  return data;
}

function uploadToS3(file, uploadUrl, contentType) {
  return new Promise(function (resolve, reject) {
    var xhr = new XMLHttpRequest();
    xhr.open('PUT', uploadUrl);
    xhr.setRequestHeader('Content-Type', contentType);

    xhr.upload.onprogress = function (event) {
      if (event.lengthComputable) {
        var percent = (event.loaded / event.total) * 100;
        updateProgress(percent);
      }
    };

    xhr.onload = function () {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(new Error('Upload failed with status ' + xhr.status));
      }
    };

    xhr.onerror = function () {
      reject(new Error('Network error during file upload.'));
    };

    xhr.send(file);
  });
}

function setUploading(isUploading) {
  uploadBtn.disabled = isUploading;
  uploadBtn.setAttribute('aria-disabled', String(isUploading));
  fileInput.disabled = isUploading;
  passwordInput.disabled = isUploading;
}

// --- Drag and drop ---

function handleFileDrop(file) {
  // Create a new DataTransfer to set files on the input
  var dt = new DataTransfer();
  dt.items.add(file);
  fileInput.files = dt.files;

  updateUploadButtonState();
  showFilenamePreview(file);
  clearError();
  hideResult();
}

dropZone.addEventListener('dragover', function (event) {
  event.preventDefault();
  dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', function () {
  dropZone.classList.remove('drag-over');
});

dropZone.addEventListener('drop', function (event) {
  event.preventDefault();
  dropZone.classList.remove('drag-over');

  var files = event.dataTransfer.files;
  if (files.length > 0) {
    handleFileDrop(files[0]);
  }
});

// Click on drop zone triggers file input
dropZone.addEventListener('click', function () {
  fileInput.click();
});

// Keyboard accessibility for drop zone
dropZone.addEventListener('keydown', function (event) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    fileInput.click();
  }
});

// --- Event handlers ---

fileInput.addEventListener('change', function () {
  updateUploadButtonState();
  clearError();
  hideResult();
  var file = fileInput.files[0];
  showFilenamePreview(file);
});

// Form submit handler — full upload flow
uploadForm.addEventListener('submit', async function (event) {
  event.preventDefault();

  var file = fileInput.files[0];
  var password = passwordInput.value;

  clearError();
  hideResult();
  hideProgress();

  var validationError = validateFile(file);
  if (validationError) {
    showError(validationError);
    return;
  }

  setUploading(true);
  showProgress();

  try {
    var data = await requestPresignedUrl(file, password, false);

    if (data._conflict) {
      hideProgress();
      var confirmed = confirm(
        'A file named "' + sanitizeFilename(file.name) + '" already exists.\n\n' +
        'Existing URL: ' + data.existingUrl + '\n\n' +
        'Do you want to overwrite it?'
      );
      if (!confirmed) {
        setUploading(false);
        updateUploadButtonState();
        return;
      }
      showProgress();
      data = await requestPresignedUrl(file, password, true);
    }

    await uploadToS3(file, data.uploadUrl, file.type);

    hideProgress();
    showResult(data.publicUrl);
    saveToHistory(sanitizeFilename(file.name), data.publicUrl);
  } catch (error) {
    hideProgress();
    showError(error.message || 'An unexpected error occurred.');
  } finally {
    setUploading(false);
    updateUploadButtonState();
  }
});

// Upload another button
uploadAnotherBtn.addEventListener('click', function () {
  resetForm();
});

// Copy-to-clipboard handler
copyBtn.addEventListener('click', function () {
  var url = urlOutput.textContent;

  navigator.clipboard.writeText(url).then(function () {
    copyConfirmation.hidden = false;
    copyBtn.classList.add('copied');

    setTimeout(function () {
      copyConfirmation.hidden = true;
      copyBtn.classList.remove('copied');
    }, 2000);
  }).catch(function () {
    showError('Failed to copy URL to clipboard');
  });
});

// Clear history button
clearHistoryBtn.addEventListener('click', clearHistory);

// Initialize on page load
updateUploadButtonState();
renderHistory();
