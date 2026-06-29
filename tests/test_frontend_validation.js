'use strict';

const assert = require('assert');

// ============================================================
// Replicate validation constants and logic from src/frontend/app.js
// (app.js uses DOM references, so we extract the pure logic here)
// ============================================================

const MAX_FILE_SIZE = 52428800; // 50 MB in bytes

const ALLOWED_CONTENT_TYPES = new Set([
  'application/pdf',
  'image/jpeg',
  'image/png',
  'image/gif',
  'image/webp',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.ms-powerpoint',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
]);

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

// ============================================================
// Test helpers
// ============================================================

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    passed++;
    console.log('  PASS: ' + name);
  } catch (err) {
    failed++;
    console.log('  FAIL: ' + name);
    console.log('        ' + err.message);
  }
}

// ============================================================
// Tests: File size validation (Req 4.1, 4.2)
// ============================================================

console.log('\nFile size validation:');

test('rejects file with size 0 (empty file)', function () {
  const result = validateFile({ size: 0, type: 'application/pdf' });
  assert.strictEqual(result, 'Empty files are not permitted.');
});

test('rejects file exceeding 50 MB', function () {
  const result = validateFile({ size: 52428801, type: 'application/pdf' });
  assert.strictEqual(result, 'File exceeds maximum size of 50 MB.');
});

test('accepts file with size 1 byte (minimum valid)', function () {
  const result = validateFile({ size: 1, type: 'application/pdf' });
  assert.strictEqual(result, null);
});

test('accepts file at exactly 50 MB (boundary)', function () {
  const result = validateFile({ size: 52428800, type: 'application/pdf' });
  assert.strictEqual(result, null);
});

// ============================================================
// Tests: File type validation (Req 4.5)
// ============================================================

console.log('\nFile type validation:');

test('accepts application/pdf', function () {
  const result = validateFile({ size: 1024, type: 'application/pdf' });
  assert.strictEqual(result, null);
});

test('accepts image/jpeg', function () {
  const result = validateFile({ size: 1024, type: 'image/jpeg' });
  assert.strictEqual(result, null);
});

test('accepts image/png', function () {
  const result = validateFile({ size: 1024, type: 'image/png' });
  assert.strictEqual(result, null);
});

test('accepts image/gif', function () {
  const result = validateFile({ size: 1024, type: 'image/gif' });
  assert.strictEqual(result, null);
});

test('accepts image/webp', function () {
  const result = validateFile({ size: 1024, type: 'image/webp' });
  assert.strictEqual(result, null);
});

test('accepts application/msword', function () {
  const result = validateFile({ size: 1024, type: 'application/msword' });
  assert.strictEqual(result, null);
});

test('accepts docx content type', function () {
  const result = validateFile({ size: 1024, type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' });
  assert.strictEqual(result, null);
});

test('rejects application/x-msdownload (executable)', function () {
  const result = validateFile({ size: 1024, type: 'application/x-msdownload' });
  assert.ok(result !== null);
  assert.ok(result.includes('File type not allowed'));
});

test('rejects empty string content type', function () {
  const result = validateFile({ size: 1024, type: '' });
  assert.ok(result !== null);
  assert.ok(result.includes('File type not allowed'));
});

// ============================================================
// Tests: Null/missing file (Req 4.1)
// ============================================================

console.log('\nNull/missing file:');

test('rejects null file', function () {
  const result = validateFile(null);
  assert.strictEqual(result, 'Please select a file to upload.');
});

test('rejects undefined file', function () {
  const result = validateFile(undefined);
  assert.strictEqual(result, 'Please select a file to upload.');
});

// ============================================================
// Summary
// ============================================================

console.log('\n---');
console.log('Results: ' + passed + ' passed, ' + failed + ' failed, ' + (passed + failed) + ' total');

if (failed > 0) {
  process.exit(1);
} else {
  console.log('All tests passed.\n');
  process.exit(0);
}
