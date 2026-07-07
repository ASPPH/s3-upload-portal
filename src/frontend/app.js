'use strict';

// API endpoint — will be set after first CloudFormation deployment
// Format: https://{api-id}.execute-api.us-east-1.amazonaws.com/prod/v1/upload
const API_ENDPOINT = 'https://zuxxqyttq2.execute-api.us-east-1.amazonaws.com/prod/v1/upload';

// Maximum file size: 50 MB in bytes
const MAX_FILE_SIZE = 52428800;

// Allowed content types — update this to match the Lambda's ALLOWED_CONTENT_TYPES env var
// Default: PDF only. To allow more types, add them here AND update the CloudFormation parameter.
const ALLOWED_CONTENT_TYPES = new Set([
  'application/pdf',
]);

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

/**
 * Show an error message to the user.
 */
function showError(message) {
  errorText.textContent = message;
  errorContainer.hidden = false;
}

/**
 * Clear any displayed error message.
 */
function clearError() {
  errorText.textContent = '';
  errorContainer.hidden = true;
}

/**
 * Show the progress container and reset to 0%.
 */
function showProgress() {
  progressContainer.hidden = false;
  progressBar.value = 0;
  progressText.textContent = '0%';
}

/**
 * Update progress indicator with percentage.
 */
function updateProgress(percent) {
  const rounded = Math.round(percent);
  progressBar.value = rounded;
  progressText.textContent = rounded + '%';
}

/**
 * Hide the progress container.
 */
function hideProgress() {
  progressContainer.hidden = true;
}

/**
 * Show the result container with the public URL as a clickable link.
 */
function showResult(publicUrl) {
  resultContainer.hidden = false;
  urlOutput.textContent = publicUrl;
  urlOutput.href = publicUrl;
}

/**
 * Hide the result container.
 */
function hideResult() {
  resultContainer.hidden = true;
  urlOutput.textContent = '';
  urlOutput.href = '';
}

/**
 * Enable or disable the upload button based on file selection.
 */
function updateUploadButtonState() {
  const hasFile = fileInput.files && fileInput.files.length > 0;
  uploadBtn.disabled = !hasFile;
  uploadBtn.setAttribute('aria-disabled', String(!hasFile));
}

/**
 * Validate the selected file before upload.
 * Returns an error message string, or null if valid.
 */
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
    const allowed = Array.from(ALLOWED_CONTENT_TYPES).join(', ');
    return 'File type not allowed. Allowed types: ' + allowed;
  }

  return null;
}

/**
 * Request a presigned upload URL from the API.
 * Returns the parsed JSON response or throws an error.
 *
 * CORS preflight (OPTIONS) is handled by API Gateway mock integration.
 * Lambda adds CORS headers (Access-Control-Allow-Origin, Methods, Headers)
 * to all responses for the configured CloudFront origin.
 */
async function requestPresignedUrl(file, password, confirmOverwrite) {
  const body = JSON.stringify({
    password: password,
    filename: file.name,
    contentType: file.type,
    fileSize: file.size,
    confirmOverwrite: confirmOverwrite || false,
  });

  const response = await fetch(API_ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body,
  });

  const data = await response.json();

  if (response.status === 409) {
    // File exists — return data with conflict flag for caller to handle
    data._conflict = true;
    return data;
  }

  if (!response.ok) {
    throw new Error(data.message || 'Upload request failed.');
  }

  return data;
}

/**
 * Upload the file directly to S3 using the presigned PUT URL.
 * Uses XMLHttpRequest for progress tracking.
 * Returns a promise that resolves on success or rejects on failure.
 */
function uploadToS3(file, uploadUrl, contentType) {
  return new Promise(function (resolve, reject) {
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', uploadUrl);
    xhr.setRequestHeader('Content-Type', contentType);

    xhr.upload.onprogress = function (event) {
      if (event.lengthComputable) {
        const percent = (event.loaded / event.total) * 100;
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

/**
 * Set the form to a loading/uploading state.
 */
function setUploading(isUploading) {
  uploadBtn.disabled = isUploading;
  uploadBtn.setAttribute('aria-disabled', String(isUploading));
  fileInput.disabled = isUploading;
  passwordInput.disabled = isUploading;
}

// File selection handler — enable/disable button, clear errors (Req 1.5)
fileInput.addEventListener('change', function () {
  updateUploadButtonState();
  clearError();
  hideResult();
});

// Form submit handler — full upload flow
uploadForm.addEventListener('submit', async function (event) {
  event.preventDefault();

  const file = fileInput.files[0];
  const password = passwordInput.value;

  // Clear previous state
  clearError();
  hideResult();
  hideProgress();

  // Client-side validation
  const validationError = validateFile(file);
  if (validationError) {
    showError(validationError);
    return;
  }

  // Begin upload flow
  setUploading(true);
  showProgress();

  try {
    // Step 1: Request presigned URL from API
    var data = await requestPresignedUrl(file, password, false);

    // Step 1b: Handle overwrite confirmation
    if (data._conflict) {
      hideProgress();
      var confirmed = confirm(
        'A file named "' + file.name + '" already exists.\n\n' +
        'Existing URL: ' + data.existingUrl + '\n\n' +
        'Do you want to overwrite it?'
      );
      if (!confirmed) {
        setUploading(false);
        updateUploadButtonState();
        return;
      }
      // Re-request with overwrite confirmed
      showProgress();
      data = await requestPresignedUrl(file, password, true);
    }

    // Step 2: Upload file directly to S3
    await uploadToS3(file, data.uploadUrl, file.type);

    // Step 3: Show success result
    hideProgress();
    showResult(data.publicUrl);
  } catch (error) {
    // On failure: display error, retain file selection for retry
    hideProgress();
    showError(error.message || 'An unexpected error occurred.');
  } finally {
    setUploading(false);
    updateUploadButtonState();
  }
});

// Copy-to-clipboard handler (Req 3.2, 3.3, 3.4, 3.5)
copyBtn.addEventListener('click', function () {
  var url = urlOutput.textContent;

  navigator.clipboard.writeText(url).then(function () {
    // Success: show confirmation for at least 2 seconds (Req 3.3, 3.5)
    copyConfirmation.hidden = false;
    copyBtn.classList.add('copied');

    setTimeout(function () {
      copyConfirmation.hidden = true;
      copyBtn.classList.remove('copied');
    }, 2000);
  }).catch(function () {
    // Failure: show error, URL remains visible and selectable (Req 3.4)
    showError('Failed to copy URL to clipboard');
  });
});

// Initialize button state on page load
updateUploadButtonState();
