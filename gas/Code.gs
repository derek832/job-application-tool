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
 *   6. Set the document ID in Script Properties:
 *      - Open Project Settings (gear icon)
 *      - Under "Script Properties", add a property:
 *        Key: DOCUMENT_ID
 *        Value: <your Google Doc resume document ID>
 *      - The document ID is the long string in the Doc URL:
 *        https://docs.google.com/document/d/<DOCUMENT_ID>/edit
 *
 * The Automator calls this endpoint via HTTPS POST with a JSON body:
 *   { "action": "read" | "write" | "export_pdf", "content": "..." }
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
    } else if (action === "write") {
      return handleWrite(payload.content);
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
 * Overwrites the resume document body with new content.
 *
 * @param {string} content - The new plain-text resume content.
 * @returns {ContentService.TextOutput} JSON with { success: true }.
 */
function handleWrite(content) {
  if (content === undefined || content === null) {
    return jsonResponse({ error: "Missing required field: content" });
  }

  var docId = getDocumentId();
  var doc = DocumentApp.openById(docId);
  var body = doc.getBody();
  body.clear();
  body.setText(content);
  doc.saveAndClose();
  return jsonResponse({ success: true });
}

/**
 * Exports the resume document as a PDF and returns it base64-encoded.
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
