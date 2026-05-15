/**
 * Google Apps Script Web App for Job Application Tool resume management.
 *
 * Deployment instructions:
 *   1. Open script.google.com and create a new project.
 *   2. Paste this file contents.
 *   3. Deploy → New deployment → Web App
 *      - Execute as: Me
 *      - Who has access: Only myself
 *   4. Copy the deployment URL into .env as GOOGLE_APPS_SCRIPT_URL.
 *   5. On first run, authorize the script when prompted.
 *
 * The Automator calls this endpoint via HTTPS POST with a JSON body:
 *   { "action": "read" | "write" | "export_pdf", "content": "..." }
 *
 * Replace DOCUMENT_ID below with the ID of your Google Doc resume.
 * The document ID is the long string in the Doc URL:
 *   https://docs.google.com/document/d/<DOCUMENT_ID>/edit
 */

// TODO: Replace with your Google Doc resume document ID.
var DOCUMENT_ID = "YOUR_DOCUMENT_ID_HERE";

/**
 * Handles POST requests from the Automator service.
 *
 * @param {Object} e - The event object from the Web App POST request.
 * @returns {ContentService.TextOutput} JSON response.
 */
function doPost(e) {
  try {
    var payload = JSON.parse(e.postData.contents);
    var action = payload.action;

    if (action === "read") {
      return handleRead();
    } else if (action === "write") {
      return handleWrite(payload.content);
    } else if (action === "export_pdf") {
      return handleExportPdf();
    } else {
      return jsonResponse({ error: "unknown_action", message: "Unknown action: " + action });
    }
  } catch (err) {
    return jsonResponse({ error: "internal_error", message: err.toString() });
  }
}

/**
 * Reads the full text content of the resume document.
 *
 * @returns {ContentService.TextOutput} JSON with { content: string }.
 */
function handleRead() {
  var doc = DocumentApp.openById(DOCUMENT_ID);
  var body = doc.getBody();
  var content = body.getText();
  return jsonResponse({ content: content });
}

/**
 * Overwrites the resume document body with new content.
 *
 * @param {string} content - The new plain-text resume content.
 * @returns {ContentService.TextOutput} JSON with { success: true }.
 */
function handleWrite(content) {
  var doc = DocumentApp.openById(DOCUMENT_ID);
  var body = doc.getBody();
  body.clear();
  body.setText(content);
  doc.saveAndClose();
  return jsonResponse({ success: true });
}

/**
 * Exports the resume document as a PDF and returns it base64-encoded.
 *
 * @returns {ContentService.TextOutput} JSON with { pdf_base64: string }.
 */
function handleExportPdf() {
  var file = DriveApp.getFileById(DOCUMENT_ID);
  var pdfBlob = file.getAs("application/pdf");
  var pdfBytes = pdfBlob.getBytes();
  var base64 = Utilities.base64Encode(pdfBytes);
  return jsonResponse({ pdf_base64: base64 });
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
