/**
 * Google Apps Script Web App for Job Application Tool resume management.
 *
 * Deployment instructions:
 *   1. Open script.google.com and create a new project.
 *   2. Paste this file contents.
 *   3. Deploy → New deployment → Web App
 *      - Execute as: Me
 *      - Who has access: Anyone
 *   4. Copy the deployment URL into .env as GOOGLE_APPS_SCRIPT_URL.
 *   5. On first run, authorize the script when prompted.
 *   6. Set the document ID in Script Properties:
 *      - Open Project Settings (gear icon)
 *      - Under "Script Properties", add a property:
 *        Key: DOCUMENT_ID
 *        Value: <your Google Doc resume document ID>
 *      - The document ID is the long string in the Doc URL:
 *        https://docs.google.com/document/d/<DOCUMENT_ID>/edit
 *
 * The Automator calls this endpoint via HTTPS POST with a JSON body:
 *   { "action": "read" | "write_and_export" | "export_pdf", "content": "..." }
 */

/**
 * Retrieves the configured Google Doc document ID from Script Properties.
 *
 * @returns {string} The document ID.
 * @throws {Error} If DOCUMENT_ID is not configured in Script Properties.
 */
function getDocumentId() {
  var props = PropertiesService.getScriptProperties();
  var docId = props.getProperty("DOCUMENT_ID");
  if (!docId) {
    throw new Error("DOCUMENT_ID not configured in Script Properties");
  }
  return docId;
}

/**
 * Handles POST requests from the Automator service.
 *
 * @param {Object} e - The event object from the Web App POST request.
 * @returns {ContentService.TextOutput} JSON response.
 */
function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return jsonResponse({ error: "Missing request body" });
    }

    var payload = JSON.parse(e.postData.contents);
    var action = payload.action;

    if (!action) {
      return jsonResponse({ error: "Missing required field: action" });
    }

    if (action === "read") {
      return handleRead();
    } else if (action === "write_and_export") {
      return handleWriteAndExport(payload.content);
    } else if (action === "tailor_and_export") {
      return handleTailorAndExport(payload.replacements);
    } else if (action === "export_pdf") {
      return handleExportPdf();
    } else {
      return jsonResponse({ error: "Unknown action: " + action });
    }
  } catch (err) {
    return jsonResponse({ error: err.toString() });
  }
}

/**
 * Reads the full text content of the resume document.
 *
 * @returns {ContentService.TextOutput} JSON with { content: string }.
 */
function handleRead() {
  var docId = getDocumentId();
  var doc = DocumentApp.openById(docId);
  var body = doc.getBody();
  var content = body.getText();
  return jsonResponse({ content: content });
}

/**
 * Creates a temporary document with the tailored content, exports it as PDF,
 * then deletes the temp document. The original resume document is never modified.
 *
 * @param {string} content - The tailored resume text to export as PDF.
 * @returns {ContentService.TextOutput} JSON with { pdf: base64, success: true }.
 */
function handleWriteAndExport(content) {
  if (content === undefined || content === null) {
    return jsonResponse({ error: "Missing required field: content" });
  }

  // Create a temporary document for the tailored resume
  var tempDoc = DocumentApp.create("_tailored_resume_temp");
  var tempDocId = tempDoc.getId();

  try {
    // Write the tailored content
    var body = tempDoc.getBody();
    body.setText(content);
    tempDoc.saveAndClose();

    // Export as PDF
    var file = DriveApp.getFileById(tempDocId);
    var pdfBlob = file.getAs("application/pdf");
    var pdfBytes = pdfBlob.getBytes();
    var base64 = Utilities.base64Encode(pdfBytes);

    // Delete the temp document
    DriveApp.getFileById(tempDocId).setTrashed(true);

    return jsonResponse({ pdf: base64, success: true });
  } catch (err) {
    // Clean up temp doc on error
    try {
      DriveApp.getFileById(tempDocId).setTrashed(true);
    } catch (cleanupErr) {
      // Ignore cleanup errors
    }
    throw err;
  }
}

/**
 * Copies the original resume document, applies find-and-replace pairs to
 * preserve formatting while optimizing for ATS, exports as PDF, then deletes
 * the copy. The original document is never modified.
 *
 * Uses element-level text replacement instead of body.replaceText() to avoid
 * formatting bleed across bold/non-bold boundaries.
 *
 * @param {Array<{find: string, replace: string}>} replacements - Text replacement pairs.
 * @returns {ContentService.TextOutput} JSON with { pdf: base64, success: true, replacements_applied: number }.
 */
function handleTailorAndExport(replacements) {
  if (!replacements || !Array.isArray(replacements)) {
    return jsonResponse({ error: "Missing or invalid 'replacements' array" });
  }

  var docId = getDocumentId();
  var originalFile = DriveApp.getFileById(docId);

  // Copy the original document (preserves all formatting)
  var copy = originalFile.makeCopy("_tailored_resume_temp");
  var copyId = copy.getId();

  try {
    var doc = DocumentApp.openById(copyId);
    var body = doc.getBody();

    var applied = 0;
    for (var i = 0; i < replacements.length; i++) {
      var pair = replacements[i];
      if (pair.find && pair.replace) {
        var success = safeReplace(body, pair.find, pair.replace);
        if (success) applied++;
      }
    }

    doc.saveAndClose();

    // Export the copy as PDF
    var pdfBlob = DriveApp.getFileById(copyId).getAs("application/pdf");
    var pdfBytes = pdfBlob.getBytes();
    var base64 = Utilities.base64Encode(pdfBytes);

    // Delete the temp copy
    DriveApp.getFileById(copyId).setTrashed(true);

    return jsonResponse({ pdf: base64, success: true, replacements_applied: applied });
  } catch (err) {
    // Clean up on error
    try {
      DriveApp.getFileById(copyId).setTrashed(true);
    } catch (cleanupErr) {
      // Ignore
    }
    throw err;
  }
}

/**
 * Safely replaces text within a document body without disrupting formatting.
 * Instead of body.replaceText() which can bleed bold/italic across boundaries,
 * this finds the text element containing the match and replaces only within
 * that element's text, preserving all character-level formatting.
 *
 * @param {Body} body - The document body.
 * @param {string} findText - Exact text to find.
 * @param {string} replaceWith - Text to replace it with.
 * @returns {boolean} True if a replacement was made.
 */
function safeReplace(body, findText, replaceWith) {
  // Escape regex special characters for findText search
  var escaped = findText.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  var searchResult = body.findText(escaped);

  if (!searchResult) return false;

  var element = searchResult.getElement();
  var startOffset = searchResult.getStartOffset();
  var endOffset = searchResult.getEndOffsetInclusive();

  // Get the Text object
  var textObj = element.asText();

  // Delete the found text range and insert the replacement at the same position.
  // This preserves the formatting of the surrounding text.
  // The replacement inherits formatting from the character at startOffset.
  // To avoid bold bleed: check if the start is bold but the content shouldn't be.
  var isBoldAtStart = textObj.isBold(startOffset);
  var fullText = textObj.getText();

  // Build new full text with the replacement spliced in
  var before = fullText.substring(0, startOffset);
  var after = fullText.substring(endOffset + 1);
  var newFullText = before + replaceWith + after;

  // Set the text (this preserves formatting for unchanged portions)
  var isUnderlineAtStart = textObj.isUnderline(startOffset);
  textObj.deleteText(startOffset, endOffset);
  textObj.insertText(startOffset, replaceWith);

  // The inserted text inherits formatting from the character at startOffset.
  // If the original text was NOT underlined, clear underline on the replacement
  // to prevent formatting bleed from adjacent underlined text.
  if (!isUnderlineAtStart) {
    textObj.setUnderline(startOffset, startOffset + replaceWith.length - 1, false);
  }

  // If the character BEFORE the start is not bold but start is bold,
  // the replacement is at a boundary — keep the replacement non-bold
  // to match the majority of the replaced content's style.
  if (startOffset > 0) {
    var isBoldBefore = textObj.isBold(startOffset - 1);
    if (!isBoldBefore && isBoldAtStart) {
      // The find text started at a bold boundary — make replacement non-bold
      textObj.setBold(startOffset, startOffset + replaceWith.length - 1, false);
    }
  }

  return true;
}

/**
 * Exports the original resume document as a PDF and returns it base64-encoded.
 *
 * @returns {ContentService.TextOutput} JSON with { pdf: string }.
 */
function handleExportPdf() {
  var docId = getDocumentId();
  var file = DriveApp.getFileById(docId);
  var pdfBlob = file.getAs("application/pdf");
  var pdfBytes = pdfBlob.getBytes();
  var base64 = Utilities.base64Encode(pdfBytes);
  return jsonResponse({ pdf: base64 });
}

/**
 * Helper to return a JSON ContentService response.
 *
 * @param {Object} data - The object to serialize as JSON.
 * @returns {ContentService.TextOutput}
 */
function jsonResponse(data) {
  return ContentService
    .createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}
