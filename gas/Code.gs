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
  // Use the original resume's name so the PDF metadata title is correct
  var docId = getDocumentId();
  var originalName = DriveApp.getFileById(docId).getName();
  var tempDoc = DocumentApp.create(originalName);
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
  // Use the original name so the exported PDF metadata title is correct
  var copy = originalFile.makeCopy(originalFile.getName());
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

    // Nuclear underline cleanup: the source document has NO underlined text.
    // Paragraph bottom borders can cause spurious underline inheritance during
    // insertText that setUnderline(false) in safeReplace may not fully clear.
    // Walk every text element and force-clear underline on the entire content.
    var cleared = clearAllUnderlines(body);

    doc.saveAndClose();

    // Export the copy as PDF
    var pdfBlob = DriveApp.getFileById(copyId).getAs("application/pdf");
    var pdfBytes = pdfBlob.getBytes();
    var base64 = Utilities.base64Encode(pdfBytes);

    // Delete the temp copy
    DriveApp.getFileById(copyId).setTrashed(true);

    return jsonResponse({ pdf: base64, success: true, replacements_applied: applied, underlines_cleared: cleared });
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
 * Walks every text element in the document body and forces underline to false.
 * Also clears any paragraph-level underline attributes. This is safe because
 * the source resume contains no underlined text — any underline present after
 * replacements is a spurious artifact from GAS insertText inheriting from
 * paragraph borders or adjacent elements.
 *
 * @param {Body} body - The document body.
 */
function clearAllUnderlines(body) {
  var numChildren = body.getNumChildren();
  var count = 0;
  for (var i = 0; i < numChildren; i++) {
    var child = body.getChild(i);
    count += clearUnderlineInElement(child);
  }
  return count;
}

/**
 * Recursively clears underline on text within an element.
 * Handles paragraphs, list items, and their child text elements.
 * Also clears paragraph-level attributes that might cause underline inheritance.
 *
 * @param {Element} element - A document element (paragraph, list item, etc.)
 */
function clearUnderlineInElement(element) {
  var type = element.getType();
  var count = 0;

  if (type === DocumentApp.ElementType.TEXT) {
    var text = element.asText();
    var content = text.getText();
    if (content.length > 0) {
      // Use range-based setUnderline to clear per-character underline attributes.
      // The blanket text.setUnderline(false) only sets the default attribute and
      // does NOT override per-character overrides inherited during insertText.
      text.setUnderline(0, content.length - 1, false);
      count++;
    }
  } else if (type === DocumentApp.ElementType.PARAGRAPH ||
             type === DocumentApp.ElementType.LIST_ITEM) {
    // Check if this is a section header (ALL CAPS, short text).
    // Section headers like "SUMMARY", "CORE SKILLS & CERTIFICATIONS",
    // "WORK EXPERIENCE" are intentionally underlined — skip them.
    var paraText = element.getText().trim();
    var isHeader = paraText.length > 0 &&
                   paraText.length < 50 &&
                   paraText === paraText.toUpperCase() &&
                   /[A-Z]/.test(paraText);

    if (!isHeader) {
      // Clear paragraph-level underline attribute
      var attrs = {};
      attrs[DocumentApp.Attribute.UNDERLINE] = false;
      element.setAttributes(attrs);
      count++;

      var numChildren = element.getNumChildren();
      for (var i = 0; i < numChildren; i++) {
        count += clearUnderlineInElement(element.getChild(i));
      }
    }
  }
  return count;
}

/**
 * Safely replaces text within a document body without disrupting formatting.
 * Preserves bold and italic from the original text, but ALWAYS forces underline
 * to false — the source resume uses no underlines, and paragraph bottom borders
 * can cause GAS insertText to inherit spurious underline attributes.
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

  // Sample formatting at start and end to detect boundaries.
  // GAS returns null for "inherited" formatting — treat null as false.
  var startBold = textObj.isBold(startOffset) || false;
  var startItalic = textObj.isItalic(startOffset) || false;
  var endBold = textObj.isBold(endOffset) || false;
  var endItalic = textObj.isItalic(endOffset) || false;

  // If formatting is uniform, use it. If it spans a boundary, use the END
  // (body text) to avoid bleeding heading styles into plain text.
  var applyBold = (startBold === endBold) ? startBold : endBold;
  var applyItalic = (startItalic === endItalic) ? startItalic : endItalic;

  // Perform the replacement
  textObj.deleteText(startOffset, endOffset);
  textObj.insertText(startOffset, replaceWith);

  // Force-clear ALL formatting first, then re-apply only bold/italic.
  // This two-step approach prevents underline from being re-inherited
  // when bold+italic are set on text adjacent to paragraph borders.
  var replaceEnd = startOffset + replaceWith.length - 1;

  // Step 1: Clear everything
  var clearAttrs = {};
  clearAttrs[DocumentApp.Attribute.BOLD] = false;
  clearAttrs[DocumentApp.Attribute.ITALIC] = false;
  clearAttrs[DocumentApp.Attribute.UNDERLINE] = false;
  clearAttrs[DocumentApp.Attribute.STRIKETHROUGH] = false;
  textObj.setAttributes(startOffset, replaceEnd, clearAttrs);

  // Step 2: Re-apply only bold and italic as needed
  if (applyBold) {
    textObj.setBold(startOffset, replaceEnd, true);
  }
  if (applyItalic) {
    textObj.setItalic(startOffset, replaceEnd, true);
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
