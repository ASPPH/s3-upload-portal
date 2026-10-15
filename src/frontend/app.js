'use strict';

// API endpoint
const API_ENDPOINT = 'https://zuxxqyttq2.execute-api.us-east-1.amazonaws.com/prod/v1/upload';

// Google reCAPTCHA v3 site key (public). Must match the key in the api.js script tag
// in index.html and correspond to the secret stored in Secrets Manager.
const RECAPTCHA_SITE_KEY = '6Le45rAtAAAAAMhXhLXLgmRbxNF1wFmepV7apZC5';

// reCAPTCHA action name — used for score analytics in the Google admin console.
const RECAPTCHA_ACTION = 'upload';

// Used only for the "Your link will be" preview before upload. The real link comes
// back from the API (Lambda PUBLIC_BASE_URL + UPLOAD_PREFIX), so keep these in sync.
const PUBLIC_URL_BASE = 'https://media.aspph.org/shared/';

// Maximum file size: 50 MB in bytes
const MAX_FILE_SIZE = 52428800;

// Allowed content types — update this to match the Lambda's ALLOWED_CONTENT_TYPES env var
// Default: PDF only. To allow more types, add them here AND update the CloudFormation parameter.
const ALLOWED_CONTENT_TYPES = new Set([
  'application/pdf',
]);

// Session storage key for upload history
const HISTORY_KEY = 'aspph-upload-history';

// How long "Copied" shows on a copy button
const COPIED_MS = 1800;

// DOM references
const uploadForm = document.getElementById('upload-form');
const fileInput = document.getElementById('file-input');
const dropZone = document.getElementById('drop-zone');
const fileChosen = document.getElementById('file-chosen');
const fileNameEl = document.getElementById('file-name');
const fileSizeEl = document.getElementById('file-size');
const removeFileBtn = document.getElementById('remove-file-btn');
const urlBaseEl = document.getElementById('url-base');
const urlNameEl = document.getElementById('url-name');
const renamedNote = document.getElementById('renamed-note');
const errorContainer = document.getElementById('error-container');
const errorTitle = document.getElementById('error-title');
const errorText = document.getElementById('error-text');
const conflictContainer = document.getElementById('conflict-container');
const existingLink = document.getElementById('existing-link');
const replaceBtn = document.getElementById('replace-btn');
const keepBtn = document.getElementById('keep-btn');
const passwordStep = document.getElementById('password-step');
const passwordInput = document.getElementById('password-input');
const progressContainer = document.getElementById('progress-container');
const progressName = document.getElementById('progress-name');
const progressFill = document.getElementById('progress-fill');
const progressText = document.getElementById('progress-text');
const submitArea = document.getElementById('submit-area');
const uploadBtn = document.getElementById('upload-btn');
const resultContainer = document.getElementById('result-container');
const urlOutput = document.getElementById('url-output');
const copyBtn = document.getElementById('copy-btn');
const copyLabel = document.getElementById('copy-label');
const openFileLink = document.getElementById('open-file-link');
const uploadAnotherBtn = document.getElementById('upload-another-btn');
const historyContainer = document.getElementById('history-container');
const historyList = document.getElementById('history-list');
const clearHistoryBtn = document.getElementById('clear-history-btn');

// The file currently chosen (null when none)
var selectedFile = null;

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

function formatSize(bytes) {
  if (bytes < 1048576) {
    return Math.max(1, Math.round(bytes / 1024)) + ' KB';
  }
  return (bytes / 1048576).toFixed(1) + ' MB';
}

// --- UI helpers ---

function showError(title, message) {
  errorTitle.textContent = title;
  errorText.textContent = message || '';
  errorContainer.hidden = false;
}

function clearError() {
  errorTitle.textContent = '';
  errorText.textContent = '';
  errorContainer.hidden = true;
}

function showSelectedFile(file) {
  selectedFile = file;
  if (!file) {
    fileChosen.hidden = true;
    dropZone.hidden = false;
    updateUploadButtonState();
    return;
  }

  var sanitized = sanitizeFilename(file.name);
  fileNameEl.textContent = file.name;
  fileSizeEl.textContent = formatSize(file.size);
  urlBaseEl.textContent = PUBLIC_URL_BASE;
  urlNameEl.textContent = sanitized;
  renamedNote.hidden = sanitized === file.name;
  dropZone.hidden = true;
  fileChosen.hidden = false;
  updateUploadButtonState();
}

function showConflict(existingUrl) {
  existingLink.href = existingUrl;
  conflictContainer.hidden = false;
  passwordStep.hidden = true;
  submitArea.hidden = true;
}

function hideConflict() {
  conflictContainer.hidden = true;
  passwordStep.hidden = false;
  submitArea.hidden = false;
}

function showProgress() {
  progressName.textContent = sanitizeFilename(selectedFile.name);
  updateProgress(0);
  progressContainer.hidden = false;
  passwordStep.hidden = true;
  submitArea.hidden = true;
}

function updateProgress(percent) {
  var rounded = Math.round(percent);
  progressFill.style.width = rounded + '%';
  progressText.textContent = rounded + '%';
}

function hideProgress() {
  progressContainer.hidden = true;
  passwordStep.hidden = false;
  submitArea.hidden = false;
}

function showResult(publicUrl) {
  uploadForm.hidden = true;
  resultContainer.hidden = false;
  urlOutput.textContent = publicUrl;
  openFileLink.href = publicUrl;
  copyLabel.textContent = 'Copy link';
  copyBtn.focus();
}

function updateUploadButtonState() {
  uploadBtn.disabled = !selectedFile;
}

function setUploading(isUploading) {
  removeFileBtn.disabled = isUploading;
  passwordInput.disabled = isUploading;
  replaceBtn.disabled = isUploading;
  keepBtn.disabled = isUploading;
  uploadBtn.disabled = isUploading || !selectedFile;
}

function resetForm() {
  fileInput.value = '';
  showSelectedFile(null);
  clearError();
  hideConflict();
  hideProgress();
  resultContainer.hidden = true;
  uploadForm.hidden = false;
}

/**
 * Copy text and show "Copied" on the button's label for a moment.
 */
function copyWithFeedback(text, labelEl, idleLabel) {
  navigator.clipboard.writeText(text).then(function () {
    labelEl.textContent = 'Copied';
    setTimeout(function () {
      labelEl.textContent = idleLabel;
    }, COPIED_MS);
  }).catch(function () {
    labelEl.textContent = "Couldn't copy";
    setTimeout(function () {
      labelEl.textContent = idleLabel;
    }, COPIED_MS);
  });
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
  // A replaced file keeps its link, so drop the older entry for it
  var history = getHistory().filter(function (item) {
    return item.url !== publicUrl;
  });
  history.unshift({
    filename: filename,
    url: publicUrl,
    time: new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }),
  });
  // Keep last 20 items
  if (history.length > 20) {
    history = history.slice(0, 20);
  }
  try {
    sessionStorage.setItem(HISTORY_KEY, JSON.stringify(history));
  } catch (e) {
    // Storage unavailable (private window); the list just won't persist
  }
  renderHistory(history);
}

function renderHistory(history) {
  history = history || getHistory();
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
    time.textContent = item.time;

    var copy = document.createElement('button');
    copy.type = 'button';
    copy.className = 'btn';
    copy.textContent = 'Copy';
    copy.setAttribute('aria-label', 'Copy link to ' + item.filename);
    copy.addEventListener('click', function () {
      copyWithFeedback(item.url, copy, 'Copy');
    });

    li.appendChild(link);
    li.appendChild(time);
    li.appendChild(copy);
    historyList.appendChild(li);
  });
}

function clearHistory() {
  try {
    sessionStorage.removeItem(HISTORY_KEY);
  } catch (e) {
    // Nothing stored
  }
  renderHistory([]);
}

// --- File validation ---

/**
 * Returns [title, message] for an invalid file, or null if it's fine.
 */
function validateFile(file) {
  if (!file) {
    return ['Choose a PDF first.', ''];
  }

  if (!ALLOWED_CONTENT_TYPES.has(file.type)) {
    return ['Only PDF files can be uploaded.', '"' + file.name + '" isn\'t a PDF. Save it as a PDF first, then try again.'];
  }

  if (file.size === 0) {
    return ['That file is empty.', 'Check the PDF opens correctly, then try again.'];
  }

  if (file.size > MAX_FILE_SIZE) {
    return ['That file is over 50 MB.', 'Try compressing the PDF, or contact the helpdesk for large files.'];
  }

  return null;
}

function takeFile(file) {
  clearError();
  hideConflict();
  if (!file) {
    return;
  }

  var problem = validateFile(file);
  if (problem) {
    fileInput.value = '';
    showSelectedFile(null);
    showError(problem[0], problem[1]);
    return;
  }

  showSelectedFile(file);
}

// --- API + upload ---

function recaptchaError() {
  var error = new Error('reCAPTCHA token unavailable');
  error.isRecaptcha = true;
  return error;
}

/**
 * Fetch a fresh reCAPTCHA v3 token. Tokens are single-use and expire after
 * ~2 minutes, so we request one immediately before each upload attempt.
 * Returns the token string, or rejects if reCAPTCHA failed to load.
 */
function getRecaptchaToken() {
  return new Promise(function (resolve, reject) {
    if (typeof grecaptcha === 'undefined' || !grecaptcha.ready) {
      reject(recaptchaError());
      return;
    }
    grecaptcha.ready(function () {
      grecaptcha
        .execute(RECAPTCHA_SITE_KEY, { action: RECAPTCHA_ACTION })
        .then(resolve)
        .catch(function () {
          reject(recaptchaError());
        });
    });
  });
}

async function requestPresignedUrl(file, password, confirmOverwrite, recaptchaToken) {
  var body = JSON.stringify({
    password: password,
    filename: file.name,
    contentType: file.type,
    fileSize: file.size,
    confirmOverwrite: confirmOverwrite || false,
    recaptchaToken: recaptchaToken,
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
    var error = new Error(data.message || 'Upload request failed.');
    error.status = response.status;
    throw error;
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

// The API's messages are written for developers, so show our own wording by status.
var RETRY_MESSAGE = "Try again in a minute, or contact the helpdesk if it keeps happening.";
var BOT_CHECK_MESSAGE = "We couldn't confirm you're not a bot. Refresh the page and try again.";

function showUploadError(error) {
  if (error.status === 401) {
    showError("That password didn't work.", 'Check it and try again, or ask the helpdesk.');
    passwordInput.focus();
    return;
  }
  if (error.status === 403) {
    showError("The upload didn't go through.", BOT_CHECK_MESSAGE);
    return;
  }
  if (error.status === 413) {
    showError('That file is over 50 MB.', 'Try compressing the PDF, or contact the helpdesk for large files.');
    return;
  }
  if (error.status === 415) {
    showError('Only PDF files can be uploaded.', 'Save it as a PDF first, then try again.');
    return;
  }
  showError("The upload didn't go through.", error.isRecaptcha ? BOT_CHECK_MESSAGE : RETRY_MESSAGE);
}

/**
 * Upload the selected file. First attempt sends confirmOverwrite=false; if the
 * file already exists the API returns 409 and we show the replace prompt.
 */
async function runUpload(confirmOverwrite) {
  var file = selectedFile;
  var password = passwordInput.value;

  clearError();
  hideConflict();

  var problem = validateFile(file);
  if (problem) {
    showError(problem[0], problem[1]);
    return;
  }

  if (!password) {
    showError('Enter the staff upload password.', "It's one password shared by all staff, not your own login. Ask the helpdesk if you don't have it.");
    passwordInput.focus();
    return;
  }

  setUploading(true);
  showProgress();

  try {
    // reCAPTCHA tokens are single-use, so every request gets a fresh one.
    var token = await getRecaptchaToken();
    var data = await requestPresignedUrl(file, password, confirmOverwrite, token);

    if (data._conflict) {
      hideProgress();
      showConflict(data.existingUrl);
      return;
    }

    await uploadToS3(file, data.uploadUrl, file.type);

    hideProgress();
    showResult(data.publicUrl);
    saveToHistory(sanitizeFilename(file.name), data.publicUrl);
  } catch (error) {
    hideProgress();
    showUploadError(error);
  } finally {
    setUploading(false);
  }
}

// --- Drag and drop ---

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
    takeFile(files[0]);
  }
});

// --- Event handlers ---

fileInput.addEventListener('change', function () {
  takeFile(fileInput.files[0]);
});

removeFileBtn.addEventListener('click', function () {
  fileInput.value = '';
  clearError();
  hideConflict();
  showSelectedFile(null);
  fileInput.focus();
});

uploadForm.addEventListener('submit', function (event) {
  event.preventDefault();
  runUpload(false);
});

replaceBtn.addEventListener('click', function () {
  runUpload(true);
});

keepBtn.addEventListener('click', function () {
  hideConflict();
});

uploadAnotherBtn.addEventListener('click', function () {
  resetForm();
  fileInput.focus();
});

copyBtn.addEventListener('click', function () {
  copyWithFeedback(urlOutput.textContent, copyLabel, 'Copy link');
});

clearHistoryBtn.addEventListener('click', clearHistory);

// Initialize on page load
updateUploadButtonState();
renderHistory();
