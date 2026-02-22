/**
 * PLAYWRIGHT Storyboard Plugin — code.js (plugin sandbox)
 *
 * Launch modes
 * ─────────────
 * 1. Deep link (from "Export to Figma" button in the web app):
 *      figma://run?pluginId=playwright-storyboard-exporter
 *             &pluginData={"storyboard_id":"abc","api_url":"http://localhost:8000"}
 *    → UI opens with storyboard_id and api_url pre-filled and import starts automatically.
 *
 * 2. Manual (Plugins → Development → PLAYWRIGHT Storyboard):
 *    → UI opens normally; user pastes the storyboard_id.
 *
 * Message protocol (ui → plugin):
 *   { type: 'CREATE_STORYBOARD', payload: PluginPayload, apiUrl: string }
 *   { type: 'SETUP_TEMPLATE',    apiUrl: string }
 *   { type: 'CANCEL' }
 *
 * Message protocol (plugin → ui):
 *   { type: 'PREFILL',           storyboard_id, api_url }
 *   { type: 'PROGRESS',          pct, text, beatIndex? }
 *   { type: 'BEAT_DONE',         beatIndex }
 *   { type: 'BEAT_ERROR',        beatIndex, beatNumber, error }
 *   { type: 'REGISTER_MAPPING',  apiUrl, sid, body }
 *   { type: 'DONE',              storyboard_id, fileName, framesCreated }
 *   { type: 'TEMPLATE_DONE',     fileKey, panelCount, apiUrl }
 *   { type: 'TEMPLATE_ERROR',    error }
 *   { type: 'ERROR',             error }
 */

// ── Resolve launch parameters (deep link or manual) ──────────────────────────
let deepLinkData = null;
try {
  var _pluginData = figma.pluginData;
  if (_pluginData) {
    deepLinkData = typeof _pluginData === 'string' ? JSON.parse(_pluginData) : _pluginData;
  }
} catch (_) {
  deepLinkData = null;
}

figma.showUI(__html__, {
  width: 340,
  height: 560,
  title: 'PLAYWRIGHT Storyboard',
});

// Send pre-fill data to the UI immediately after it loads
if (deepLinkData && deepLinkData.storyboard_id) {
  // Small delay to ensure the UI iframe is ready
  setTimeout(function() {
    figma.ui.postMessage({
      type: 'PREFILL',
      storyboard_id: deepLinkData.storyboard_id,
      api_url: deepLinkData.api_url || 'http://localhost:8000',
    });
  }, 300);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function send(msg) {
  figma.ui.postMessage(msg);
}

function progress(pct, text, beatIndex) {
  send({ type: 'PROGRESS', pct, text, beatIndex });
}

async function loadFont(family, style) {
  try {
    await figma.loadFontAsync({ family, style });
  } catch (_) {
    await figma.loadFontAsync({ family: 'Roboto', style: 'Regular' });
  }
}

function dataUriToBytes(dataUri) {
  const comma = dataUri.indexOf(',');
  if (comma === -1) return null;
  const b64 = dataUri.slice(comma + 1);
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function applyImageFill(rectNode, imageSource, apiUrl) {
  let bytes;
  if (typeof imageSource === 'string') {
    if (imageSource.startsWith('data:')) {
      bytes = dataUriToBytes(imageSource);
    } else {
      // Relative or absolute URL — fetch it via the sandbox
      var url = imageSource.startsWith('http') ? imageSource : (apiUrl || 'http://localhost:8000') + imageSource;
      try {
        var resp = await fetch(url);
        if (!resp.ok) return false;
        var arrBuf = await resp.arrayBuffer();
        bytes = new Uint8Array(arrBuf);
      } catch (_) {
        return false;
      }
    }
  } else {
    bytes = imageSource;
  }
  if (!bytes || bytes.length === 0) return false;
  const img = figma.createImage(bytes);
  rectNode.fills = [{ type: 'IMAGE', scaleMode: 'FILL', imageHash: img.hash }];
  return true;
}

async function createBeatFrame(frameDesc, beatIndex, totalBeats, apiUrl) {
  const pctBase = 15 + Math.round((beatIndex / totalBeats) * 75);

  const W = frameDesc.width  || 343;
  const H = frameDesc.height || 458;
  // Image area: full width, leaves 28px for label bar at bottom + 28px for meta bar at top
  const IMG_TOP    = 28;
  const IMG_H      = H - 28 - 28;   // top meta bar + bottom label bar
  const LABEL_H    = 28;
  const META_H     = 28;
  const BADGE_SIZE = 28;
  const PAD        = 10;

  // ── Outer panel frame ────────────────────────────────────────────────────
  const frame = figma.createFrame();
  frame.name = frameDesc.name;
  frame.x = frameDesc.x;
  frame.y = frameDesc.y;
  frame.resize(W, H);
  frame.clipsContent = true;
  frame.fills = [{ type: 'SOLID', color: { r: 0.08, g: 0.08, b: 0.10 } }];
  frame.strokes = [{ type: 'SOLID', color: { r: 0.15, g: 0.15, b: 0.20 } }];
  frame.strokeWeight = 1;
  frame.strokeAlign = 'INSIDE';
  frame.cornerRadius = 4;

  let imageNodeId = '';
  let labelNodeId = '';
  let metaNodeId  = '';

  // ── Image fill rectangle ─────────────────────────────────────────────────
  const imgRect = figma.createRectangle();
  imgRect.name = 'image_fill';
  imgRect.x = 0;
  imgRect.y = IMG_TOP;
  imgRect.resize(W, IMG_H);

  // imageUrl is stored directly on the frameDesc for create_frames mode
  var imageUrl = frameDesc.imageUrl || '';
  // Also check inside the image_fill child (legacy path)
  if (!imageUrl) {
    var imgChild = (frameDesc.children || []).find(function(c) { return c.name === 'image_fill'; });
    var imgFill  = imgChild && (imgChild.fills || []).find(function(f) { return f.type === 'IMAGE'; });
    if (imgFill) imageUrl = imgFill.imageUrl || '';
  }

  if (imageUrl) {
    progress(pctBase, 'Beat ' + (beatIndex + 1) + ': loading image\u2026', beatIndex);
    const ok = await applyImageFill(imgRect, imageUrl, apiUrl);
    if (!ok) {
      imgRect.fills = [{ type: 'SOLID', color: { r: 0.10, g: 0.10, b: 0.14 } }];
    }
  } else {
    imgRect.fills = [{ type: 'SOLID', color: { r: 0.10, g: 0.10, b: 0.14 } }];
  }
  frame.appendChild(imgRect);
  imageNodeId = imgRect.id;

  // ── Meta bar (top) — camera · lighting ───────────────────────────────────
  const metaBg = figma.createRectangle();
  metaBg.name = 'meta_bg';
  metaBg.x = 0;
  metaBg.y = 0;
  metaBg.resize(W, META_H);
  metaBg.fills = [{ type: 'SOLID', color: { r: 0, g: 0, b: 0 }, opacity: 0.70 }];
  frame.appendChild(metaBg);

  const metaChild = (frameDesc.children || []).find(function(c) { return c.name === 'meta'; }) || frameDesc;
  await figma.loadFontAsync({ family: 'Inter', style: 'Medium' }).catch(function() {});
  const metaTxt = figma.createText();
  metaTxt.name = 'meta';
  metaTxt.x = PAD;
  metaTxt.y = 6;
  metaTxt.resize(W - PAD * 2, META_H - 6);
  try {
    await figma.loadFontAsync({ family: 'Inter', style: 'Medium' });
    metaTxt.fontName = { family: 'Inter', style: 'Medium' };
  } catch (_) {
    await figma.loadFontAsync({ family: 'Roboto', style: 'Regular' });
    metaTxt.fontName = { family: 'Roboto', style: 'Regular' };
  }
  metaTxt.fontSize = 11;
  metaTxt.fills = [{ type: 'SOLID', color: { r: 1, g: 1, b: 1 }, opacity: 0.80 }];
  metaTxt.characters = (metaChild && metaChild.characters) || '';
  frame.appendChild(metaTxt);
  metaNodeId = metaTxt.id;

  // ── Beat number badge (top-left) ─────────────────────────────────────────
  const badgeBg = figma.createRectangle();
  badgeBg.name = 'badge_bg';
  badgeBg.x = PAD;
  badgeBg.y = 4;
  badgeBg.resize(BADGE_SIZE, BADGE_SIZE - 8);
  badgeBg.fills = [{ type: 'SOLID', color: { r: 1, g: 0.84, b: 0 } }];
  badgeBg.cornerRadius = 3;
  frame.appendChild(badgeBg);

  const beatNumChild = (frameDesc.children || []).find(function(c) { return c.name === 'beat_number'; }) || {};
  const badgeTxt = figma.createText();
  badgeTxt.name = 'beat_number';
  badgeTxt.x = PAD + 2;
  badgeTxt.y = 5;
  badgeTxt.resize(BADGE_SIZE - 4, BADGE_SIZE - 10);
  try {
    await figma.loadFontAsync({ family: 'Inter', style: 'Bold' });
    badgeTxt.fontName = { family: 'Inter', style: 'Bold' };
  } catch (_) {
    await figma.loadFontAsync({ family: 'Roboto', style: 'Bold' });
    badgeTxt.fontName = { family: 'Roboto', style: 'Bold' };
  }
  badgeTxt.fontSize = 10;
  badgeTxt.fills = [{ type: 'SOLID', color: { r: 0, g: 0, b: 0 } }];
  badgeTxt.characters = (beatNumChild && beatNumChild.characters) || String(beatIndex + 1);
  frame.appendChild(badgeTxt);

  // ── Label bar (bottom) — narrator line ───────────────────────────────────
  const labelBg = figma.createRectangle();
  labelBg.name = 'label_bg';
  labelBg.x = 0;
  labelBg.y = H - LABEL_H;
  labelBg.resize(W, LABEL_H);
  labelBg.fills = [{ type: 'SOLID', color: { r: 0, g: 0, b: 0 }, opacity: 0.82 }];
  frame.appendChild(labelBg);

  const labelChild = (frameDesc.children || []).find(function(c) { return c.name === 'label'; }) || {};
  const labelTxt = figma.createText();
  labelTxt.name = 'label';
  labelTxt.x = PAD;
  labelTxt.y = H - LABEL_H + 6;
  labelTxt.resize(W - PAD * 2, LABEL_H - 8);
  try {
    await figma.loadFontAsync({ family: 'Inter', style: 'Semi Bold' });
    labelTxt.fontName = { family: 'Inter', style: 'Semi Bold' };
  } catch (_) {
    await figma.loadFontAsync({ family: 'Roboto', style: 'Regular' });
    labelTxt.fontName = { family: 'Roboto', style: 'Regular' };
  }
  labelTxt.fontSize = 11;
  labelTxt.fills = [{ type: 'SOLID', color: { r: 1, g: 1, b: 1 } }];
  labelTxt.textTruncation = 'ENDING';
  labelTxt.characters = (labelChild && labelChild.characters) || '';
  frame.appendChild(labelTxt);
  labelNodeId = labelTxt.id;

  figma.currentPage.appendChild(frame);
  return { frameNode: frame, imageNodeId, labelNodeId, metaNodeId };
}

// ── Template setup mode ───────────────────────────────────────────────────────
// Creates a blank 12-panel storyboard template in the current Figma file,
// matching the layout in the screenshot: 2-column grid, title bar at top,
// each panel has a beat-number badge, image area, meta bar, label bar.

async function createTemplate(apiUrl) {
  try {
    // ── Layout constants ──────────────────────────────────────────────────
    // Image model outputs 832×464 (16:9). Panel width is set so two columns
    // fit comfortably; image area preserves the exact 832:464 aspect ratio.
    var COLS      = 2;
    var PANELS    = 12;
    var IMG_W_SRC = 832;
    var IMG_H_SRC = 464;
    var GAP_X     = 20;
    var GAP_Y     = 24;
    var PAD_X     = 48;
    var PAD_TOP   = 108;   // space for title bar
    var TITLE_H   = 56;
    var META_H    = 28;    // top bar (camera · lighting)
    var LABEL_H   = 52;    // bottom bar — taller so narrator text fits

    // Derive panel width from available canvas space, then image height from ratio
    // Canvas = 2 * PAD_X + 2 * PW + GAP_X  →  target canvas ~920px wide
    var PW        = 416;                              // panel width
    var IMG_H     = Math.round(PW * IMG_H_SRC / IMG_W_SRC);  // 232px (exact ratio)
    var PH        = META_H + IMG_H + LABEL_H;         // 28 + 232 + 52 = 312

    var GRID_W    = COLS * PW + (COLS - 1) * GAP_X;
    var CANVAS_W  = GRID_W + PAD_X * 2;
    var ROWS      = Math.ceil(PANELS / COLS);
    var CANVAS_H  = PAD_TOP + ROWS * PH + (ROWS - 1) * GAP_Y + PAD_X;

    // ── Fonts ─────────────────────────────────────────────────────────────
    send({ type: 'PROGRESS', pct: 5, text: 'Loading fonts…' });
    var fontBold = { family: 'Inter', style: 'Bold' };
    var fontSemi = { family: 'Inter', style: 'Semi Bold' };
    var fontMed  = { family: 'Inter', style: 'Medium' };
    var fontReg  = { family: 'Inter', style: 'Regular' };

    // Load all four variants; fall back to Roboto if Inter is unavailable
    var fallback = { family: 'Roboto', style: 'Regular' };
    await figma.loadFontAsync(fallback);  // always load fallback first
    try { await figma.loadFontAsync(fontReg);  } catch (_) { fontReg  = fallback; }
    try { await figma.loadFontAsync(fontMed);  } catch (_) { fontMed  = fontReg; }
    try { await figma.loadFontAsync(fontSemi); } catch (_) { fontSemi = fontMed; }
    try { await figma.loadFontAsync(fontBold); } catch (_) { fontBold = { family: fallback.family, style: 'Bold' }; try { await figma.loadFontAsync(fontBold); } catch (_2) { fontBold = fontReg; } }

    // ── Page setup ────────────────────────────────────────────────────────
    figma.currentPage.name = 'Storyboard Template';

    // ── Outer wrapper frame — linear gradient FEF9C2 → FFE2E2 → F3E8FF ──
    send({ type: 'PROGRESS', pct: 10, text: 'Building template frame…' });
    var wrapper = figma.createFrame();
    wrapper.name = 'Storyboard Template';
    wrapper.x = 0;
    wrapper.y = 0;
    wrapper.resize(CANVAS_W, CANVAS_H);
    // Vertical linear gradient: yellow → pink → purple
    wrapper.fills = [{
      type: 'GRADIENT_LINEAR',
      gradientTransform: [[0, 1, 0], [-1, 0, 1]],  // top→bottom
      gradientStops: [
        { position: 0.0, color: { r: 0.996, g: 0.976, b: 0.761, a: 1 } },  // #FEF9C2
        { position: 0.5, color: { r: 1.000, g: 0.886, b: 0.886, a: 1 } },  // #FFE2E2
        { position: 1.0, color: { r: 0.953, g: 0.910, b: 1.000, a: 1 } },  // #F3E8FF
      ],
    }];
    wrapper.clipsContent = false;
    wrapper.strokeWeight = 2;
    wrapper.strokes = [{ type: 'SOLID', color: { r: 0.85, g: 0.82, b: 0.90 } }];
    wrapper.strokeAlign = 'OUTSIDE';
    wrapper.cornerRadius = 12;

    // ── Title bar ─────────────────────────────────────────────────────────
    var titleBg = figma.createRectangle();
    titleBg.name = 'title_bg';
    titleBg.x = PAD_X;
    titleBg.y = 28;
    titleBg.resize(GRID_W, TITLE_H);
    titleBg.fills = [{ type: 'SOLID', color: { r: 1, g: 1, b: 1 } }];
    titleBg.strokes = [{ type: 'SOLID', color: { r: 0.1, g: 0.1, b: 0.1 } }];
    titleBg.strokeWeight = 2;
    titleBg.strokeAlign = 'INSIDE';
    titleBg.cornerRadius = 4;
    wrapper.appendChild(titleBg);

    var titleTxt = figma.createText();
    titleTxt.name = 'title';
    titleTxt.fontName = fontBold;
    titleTxt.fontSize = 16;
    titleTxt.characters = 'STORYBOARD TEMPLATE';
    titleTxt.fills = [{ type: 'SOLID', color: { r: 0.05, g: 0.05, b: 0.05 } }];
    titleTxt.textAlignHorizontal = 'CENTER';
    titleTxt.resize(GRID_W - 24, TITLE_H - 16);
    titleTxt.x = PAD_X + 12;
    titleTxt.y = 28 + 16;
    wrapper.appendChild(titleTxt);

    // ── 12 beat panels ────────────────────────────────────────────────────
    // META_H, LABEL_H, IMG_H, PH are all defined above from the image ratio.
    var IMG_TOP  = META_H;
    var BADGE_W  = 26;
    var BADGE_H  = 20;
    var BPAD     = 10;

    for (var i = 0; i < PANELS; i++) {
      var col = i % COLS;
      var row = Math.floor(i / COLS);
      var px  = PAD_X + col * (PW + GAP_X);
      var py  = PAD_TOP + row * (PH + GAP_Y);
      var beatNum = i + 1;

      send({ type: 'PROGRESS', pct: 10 + Math.round((i / PANELS) * 80), text: 'Creating panel ' + beatNum + ' of ' + PANELS + '…' });

      // Outer panel frame
      var panel = figma.createFrame();
      panel.name = 'Beat ' + beatNum;
      panel.x = px;
      panel.y = py;
      panel.resize(PW, PH);
      panel.clipsContent = true;
      panel.fills = [{ type: 'SOLID', color: { r: 1, g: 1, b: 1 } }];
      panel.strokes = [{ type: 'SOLID', color: { r: 0.1, g: 0.1, b: 0.1 } }];
      panel.strokeWeight = 2;
      panel.strokeAlign = 'INSIDE';
      panel.cornerRadius = 2;

      // ── image_fill: exact 832×464 ratio ──────────────────────────────
      var imgRect = figma.createRectangle();
      imgRect.name = 'image_fill';
      imgRect.x = 0;
      imgRect.y = IMG_TOP;
      imgRect.resize(PW, IMG_H);
      imgRect.fills = [{ type: 'SOLID', color: { r: 0.93, g: 0.93, b: 0.95 } }];
      panel.appendChild(imgRect);

      // ── Upload placeholder (hidden when image applied) ────────────────
      var placeholder = figma.createFrame();
      placeholder.name = 'Label';
      placeholder.x = 0;
      placeholder.y = IMG_TOP;
      placeholder.resize(PW, IMG_H);
      placeholder.fills = [];
      placeholder.clipsContent = false;

      var iconBg = figma.createRectangle();
      iconBg.name = 'upload_icon';
      iconBg.resize(32, 32);
      iconBg.x = (PW - 32) / 2;
      iconBg.y = (IMG_H - 52) / 2;
      iconBg.fills = [];
      iconBg.strokes = [{ type: 'SOLID', color: { r: 0.6, g: 0.6, b: 0.65 } }];
      iconBg.strokeWeight = 1.5;
      iconBg.cornerRadius = 6;
      placeholder.appendChild(iconBg);

      var uploadTxt = figma.createText();
      uploadTxt.name = 'upload_text';
      uploadTxt.fontName = fontMed;
      uploadTxt.fontSize = 11;
      uploadTxt.characters = 'UPLOAD IMAGE';
      uploadTxt.fills = [{ type: 'SOLID', color: { r: 0.55, g: 0.55, b: 0.60 } }];
      uploadTxt.textAlignHorizontal = 'CENTER';
      uploadTxt.resize(PW - 20, 18);
      uploadTxt.x = 10;
      uploadTxt.y = (IMG_H - 52) / 2 + 38;
      placeholder.appendChild(uploadTxt);

      var dropTxt = figma.createText();
      dropTxt.name = 'drop_text';
      dropTxt.fontName = fontReg;
      dropTxt.fontSize = 10;
      dropTxt.characters = 'or drag & drop';
      dropTxt.fills = [{ type: 'SOLID', color: { r: 0.7, g: 0.7, b: 0.75 } }];
      dropTxt.textAlignHorizontal = 'CENTER';
      dropTxt.resize(PW - 20, 16);
      dropTxt.x = 10;
      dropTxt.y = (IMG_H - 52) / 2 + 58;
      placeholder.appendChild(dropTxt);

      panel.appendChild(placeholder);

      // ── Meta bar (top) ────────────────────────────────────────────────
      var metaBg = figma.createRectangle();
      metaBg.name = 'meta_bg';
      metaBg.x = 0;
      metaBg.y = 0;
      metaBg.resize(PW, META_H);
      metaBg.fills = [{ type: 'SOLID', color: { r: 0.97, g: 0.97, b: 0.98 } }];
      metaBg.strokes = [{ type: 'SOLID', color: { r: 0.85, g: 0.85, b: 0.88 } }];
      metaBg.strokeWeight = 1;
      metaBg.strokeAlign = 'INSIDE';
      panel.appendChild(metaBg);

      // Beat number badge (yellow, top-left)
      var badgeBg = figma.createRectangle();
      badgeBg.name = 'badge_bg';
      badgeBg.x = BPAD;
      badgeBg.y = (META_H - BADGE_H) / 2;
      badgeBg.resize(BADGE_W, BADGE_H);
      badgeBg.fills = [{ type: 'SOLID', color: { r: 1, g: 0.84, b: 0 } }];
      badgeBg.cornerRadius = 4;
      panel.appendChild(badgeBg);

      var badgeTxt = figma.createText();
      badgeTxt.name = 'beat_number';
      badgeTxt.fontName = fontBold;
      badgeTxt.fontSize = 10;
      badgeTxt.characters = String(beatNum);
      badgeTxt.fills = [{ type: 'SOLID', color: { r: 0, g: 0, b: 0 } }];
      badgeTxt.textAlignHorizontal = 'CENTER';
      badgeTxt.resize(BADGE_W, BADGE_H);
      badgeTxt.x = BPAD;
      badgeTxt.y = (META_H - BADGE_H) / 2;
      panel.appendChild(badgeTxt);

      // Meta text (top-right, camera · lighting)
      var metaTxt = figma.createText();
      metaTxt.name = 'meta';
      metaTxt.fontName = fontMed;
      metaTxt.fontSize = 10;
      metaTxt.characters = 'meta';
      metaTxt.fills = [{ type: 'SOLID', color: { r: 0.45, g: 0.45, b: 0.50 } }];
      metaTxt.textAlignHorizontal = 'RIGHT';
      metaTxt.resize(PW - BADGE_W - BPAD * 3, META_H - 8);
      metaTxt.x = BADGE_W + BPAD * 2;
      metaTxt.y = (META_H - 14) / 2;
      panel.appendChild(metaTxt);

      // ── Label bar (bottom) — taller so narrator text wraps comfortably ─
      var labelBg = figma.createRectangle();
      labelBg.name = 'label_bg';
      labelBg.x = 0;
      labelBg.y = PH - LABEL_H;
      labelBg.resize(PW, LABEL_H);
      labelBg.fills = [{ type: 'SOLID', color: { r: 0.97, g: 0.97, b: 0.98 } }];
      labelBg.strokes = [{ type: 'SOLID', color: { r: 0.85, g: 0.85, b: 0.88 } }];
      labelBg.strokeWeight = 1;
      labelBg.strokeAlign = 'INSIDE';
      panel.appendChild(labelBg);

      var labelTxt = figma.createText();
      labelTxt.name = 'label';
      labelTxt.fontName = fontMed;
      labelTxt.fontSize = 11;
      labelTxt.characters = 'label';
      labelTxt.fills = [{ type: 'SOLID', color: { r: 0.2, g: 0.2, b: 0.25 } }];
      labelTxt.textAutoResize = 'HEIGHT';
      labelTxt.resize(PW - BPAD * 2, LABEL_H - 12);
      labelTxt.x = BPAD;
      labelTxt.y = PH - LABEL_H + 8;
      panel.appendChild(labelTxt);

      wrapper.appendChild(panel);
    }

    // ── Fit viewport ──────────────────────────────────────────────────────
    send({ type: 'PROGRESS', pct: 95, text: 'Fitting canvas…' });
    figma.currentPage.appendChild(wrapper);
    figma.viewport.scrollAndZoomIntoView([wrapper]);

    var fileKey = figma.fileKey || '';
    send({ type: 'TEMPLATE_DONE', fileKey, panelCount: PANELS, apiUrl });

  } catch (err) {
    send({ type: 'TEMPLATE_ERROR', error: String(err) });
  }
}

// ── Template patch mode ───────────────────────────────────────────────────────
// Patches existing nodes in the Figma template.
//
// Resolution strategy (most-to-least reliable):
//   1. Name-based lookup  — find "Beat N" frame on the current page, then walk
//      its children for 'image_fill', 'Label', 'label', 'meta' by name.
//      Works on ANY copy of the template regardless of which file it's in.
//   2. Node-ID fast path  — if the backend-supplied node ID resolves via
//      figma.getNodeById(), use it directly (same file, no copy).
//   3. Fallback           — if no "Beat N" frame exists at all, create frames
//      from scratch (blank new file with no template).

function _findChildByName(parent, name) {
  if (!parent || typeof parent.findOne !== 'function') return null;
  return parent.findOne(function(n) { return n.name === name; }) || null;
}

function _findBeatFrame(beatNumber) {
  var beatName = 'Beat ' + beatNumber;
  // Search the whole page so it works whether panels are inside a wrapper
  // frame or placed directly on the canvas.
  return figma.currentPage.findOne(function(n) {
    return n.type === 'FRAME' && n.name === beatName;
  }) || null;
}

async function patchTemplateBeats(payload, apiUrl) {
  const patches  = payload.patches || [];
  const sid      = payload.storyboard_id;
  const fileName = payload.file_name;

  if (!patches.length) {
    send({ type: 'ERROR', error: 'Patch payload contains no beats.' });
    return;
  }

  // ── Check whether ANY Beat frame exists on this page ─────────────────────
  var firstBeatFrame = _findBeatFrame(patches[0].beat_number);
  if (!firstBeatFrame) {
    // No template at all — create frames from scratch
    progress(5, 'No template found in this file \u2014 creating frames from scratch\u2026');
    var syntheticFrames = patches.map(function(p) {
      return {
        name:     'Beat ' + p.beat_number,
        x:        0,
        y:        0,
        width:    343,
        height:   458,
        imageUrl: p.imageUrl || '',
        children: [
          { name: 'meta',        characters: p.meta  || '' },
          { name: 'beat_number', characters: '#' + String(p.beat_number).padStart(2, '0') },
          { name: 'label',       characters: p.label || '' },
        ],
      };
    });
    var COLS = 3, GAP_X = 24, GAP_Y = 24, PAD = 48;
    for (var fi = 0; fi < syntheticFrames.length; fi++) {
      var col = fi % COLS, row = Math.floor(fi / COLS);
      syntheticFrames[fi].x = PAD + col * (343 + GAP_X);
      syntheticFrames[fi].y = PAD + row * (458 + GAP_Y);
    }
    await createFramesMode(Object.assign({}, payload, { mode: 'create_frames', frames: syntheticFrames }), apiUrl);
    return;
  }

  progress(10, 'Patching ' + patches.length + ' beat(s) into your template\u2026');

  const beatNodeRecords = [];
  let patchedCount = 0;

  for (let i = 0; i < patches.length; i++) {
    const patch      = patches[i];
    const beatNumber = patch.beat_number;
    const pct        = 15 + Math.round((i / patches.length) * 75);
    progress(pct, 'Beat ' + beatNumber + ': loading image\u2026', i);

    try {
      // ── Resolve the Beat N frame ──────────────────────────────────────
      // Try name-based first (works on copies), then node-ID fast path.
      var beatFrame = _findBeatFrame(beatNumber)
        || (patch.frame_node_id ? figma.getNodeById(patch.frame_node_id) : null);

      if (!beatFrame) {
        send({ type: 'BEAT_ERROR', beatIndex: i, beatNumber, error: 'Beat ' + beatNumber + ' frame not found on this page' });
        continue;
      }

      // ── Resolve image_fill node ───────────────────────────────────────
      var imgNode = _findChildByName(beatFrame, 'image_fill')
        || (patch.image_node_id ? figma.getNodeById(patch.image_node_id) : null);

      if (imgNode && patch.imageUrl) {
        var ok = await applyImageFill(imgNode, patch.imageUrl, apiUrl);
        if (!ok) send({ type: 'BEAT_ERROR', beatIndex: i, beatNumber, error: 'Image load failed' });
      }

      // ── Hide the upload placeholder ('Label' child of image area) ─────
      var placeholderNode = _findChildByName(beatFrame, 'Label')
        || (patch.placeholder_node_id ? figma.getNodeById(patch.placeholder_node_id) : null);
      if (placeholderNode) placeholderNode.visible = false;

      // ── Label text (narrator line, bottom bar) ────────────────────────
      // Walk into wrapper frames to find the actual TEXT node.
      var labelNode = _findChildByName(beatFrame, 'label')
        || (patch.label_node_id ? figma.getNodeById(patch.label_node_id) : null);
      if (labelNode && labelNode.type !== 'TEXT') {
        labelNode = _findChildByName(labelNode, null) || labelNode;
        if (labelNode.type !== 'TEXT') labelNode = null;
      }
      if (labelNode && labelNode.type === 'TEXT' && patch.label) {
        await figma.loadFontAsync(labelNode.fontName);
        labelNode.characters = patch.label;
      }

      // ── Meta text (camera · lighting, top bar) ────────────────────────
      var metaNode = _findChildByName(beatFrame, 'meta')
        || (patch.meta_node_id ? figma.getNodeById(patch.meta_node_id) : null);
      if (metaNode && metaNode.type !== 'TEXT') {
        metaNode = _findChildByName(metaNode, null) || metaNode;
        if (metaNode.type !== 'TEXT') metaNode = null;
      }
      if (metaNode && metaNode.type === 'TEXT' && patch.meta) {
        await figma.loadFontAsync(metaNode.fontName);
        metaNode.characters = patch.meta;
      }

      beatNodeRecords.push({
        beat_number:   beatNumber,
        frame_node_id: beatFrame.id,
        image_node_id: imgNode   ? imgNode.id   : '',
        label_node_id: labelNode ? labelNode.id : '',
        meta_node_id:  metaNode  ? metaNode.id  : '',
      });

      patchedCount++;
      send({ type: 'BEAT_DONE', beatIndex: i });

    } catch (err) {
      send({ type: 'BEAT_ERROR', beatIndex: i, beatNumber, error: String(err) });
    }
  }

  // ── Fill unused template panels with pastel background colours ───────────
  // Cycles through FEF9C2 (yellow), FFE2E2 (pink), F3E8FF (purple).
  var UNUSED_COLORS = [
    { r: 0.996, g: 0.976, b: 0.761 },  // #FEF9C2 yellow
    { r: 1.000, g: 0.886, b: 0.886 },  // #FFE2E2 pink
    { r: 0.953, g: 0.910, b: 1.000 },  // #F3E8FF purple
  ];
  const unusedPanels = payload.unused_panels || [];
  if (unusedPanels.length > 0) {
    progress(88, 'Filling ' + unusedPanels.length + ' unused panel(s)\u2026');
    for (var ui = 0; ui < unusedPanels.length; ui++) {
      var up = unusedPanels[ui];
      var bgColor = UNUSED_COLORS[ui % UNUSED_COLORS.length];
      // Resolve by beat_number name first, then by stored node ID
      var upBeatNum  = up.beat_number || (unusedPanels.indexOf(up) + (patches.length || 0) + 1);
      var upFrame    = _findBeatFrame(upBeatNum)
        || (up.frame_node_id ? figma.getNodeById(up.frame_node_id) : null);
      try {
        var upImgNode = (upFrame && _findChildByName(upFrame, 'image_fill'))
          || (up.image_node_id ? figma.getNodeById(up.image_node_id) : null);
        if (upImgNode) upImgNode.fills = [{ type: 'SOLID', color: bgColor }];

        var upPlaceholder = (upFrame && _findChildByName(upFrame, 'Label'))
          || (up.placeholder_node_id ? figma.getNodeById(up.placeholder_node_id) : null);
        if (upPlaceholder) upPlaceholder.visible = false;

        var upLabel = (upFrame && _findChildByName(upFrame, 'label'))
          || (up.label_node_id ? figma.getNodeById(up.label_node_id) : null);
        if (upLabel && upLabel.type === 'TEXT') {
          await figma.loadFontAsync(upLabel.fontName);
          upLabel.characters = '';
        }

        var upMeta = (upFrame && _findChildByName(upFrame, 'meta'))
          || (up.meta_node_id ? figma.getNodeById(up.meta_node_id) : null);
        if (upMeta && upMeta.type === 'TEXT') {
          await figma.loadFontAsync(upMeta.fontName);
          upMeta.characters = '';
        }
      } catch (upErr) {
        console.warn('Could not fill unused panel: ' + String(upErr));
      }
    }
  }

  progress(92, 'Fitting canvas\u2026');
  figma.viewport.scrollAndZoomIntoView(figma.currentPage.children);
  progress(95, 'Registering node mapping with backend\u2026');

  const fileKey = figma.fileKey || '';
  send({
    type: 'REGISTER_MAPPING',
    apiUrl,
    sid,
    body: {
      file_key:   fileKey,
      file_url:   fileKey ? 'https://www.figma.com/file/' + fileKey : 'https://www.figma.com/files/recent',
      page_id:    figma.currentPage.id,
      page_name:  figma.currentPage.name,
      beat_nodes: beatNodeRecords,
    },
  });

  send({ type: 'DONE', storyboard_id: sid, fileName, framesCreated: patchedCount });
}


// ── Main message handler ──────────────────────────────────────────────────────

figma.ui.onmessage = async function(msg) {
  if (msg.type === 'CANCEL') {
    figma.closePlugin();
    return;
  }

  // ── Proxy HTTP fetch for the UI iframe (blocked by Figma's CSP) ────────────
  if (msg.type === 'FETCH_PAYLOAD') {
    var url = msg.url;
    try {
      var resp = await fetch(url);
      if (!resp.ok) {
        var errText = await resp.text();
        send({ type: 'FETCH_PAYLOAD_ERROR', error: 'HTTP ' + resp.status + ': ' + errText });
        return;
      }
      var data = await resp.json();
      send({ type: 'FETCH_PAYLOAD_RESULT', payload: data });
    } catch (e) {
      var errMsg = (e && e.message) ? e.message : (e && e.toString ? e.toString() : 'Unknown fetch error');
      send({ type: 'FETCH_PAYLOAD_ERROR', error: errMsg });
    }
    return;
  }

  if (msg.type === 'SETUP_TEMPLATE') {
    await createTemplate(msg.apiUrl || 'http://localhost:8000');
    return;
  }

  if (msg.type !== 'CREATE_STORYBOARD') return;

  const { payload, apiUrl } = msg;

  // ── Route to the correct mode ─────────────────────────────────────────────
  if (payload.mode === 'patch_template') {
    await patchTemplateBeats(payload, apiUrl);
    return;
  }

  await createFramesMode(payload, apiUrl);
};

// ── create_frames mode ────────────────────────────────────────────────────────
// Creates new beat frames from scratch. Called directly when mode='create_frames'
// and also as a fallback from patchTemplateBeats when the template nodes are not
// found in the current file (e.g. a fresh blank Figma file).
async function createFramesMode(payload, apiUrl) {
  const sid      = payload.storyboard_id;
  const fileName = payload.file_name;
  const frames   = payload.frames || [];

  if (!frames.length) {
    send({ type: 'ERROR', error: 'Payload contains no frames.' });
    return;
  }

  progress(10, 'Setting up page "' + (payload.page_name || 'Storyboard') + '"\u2026');
  figma.currentPage.name = payload.page_name || 'Storyboard';

  const beatNodeRecords = [];
  const createdFrameNodes = [];
  let framesCreated = 0;

  for (let i = 0; i < frames.length; i++) {
    const frameDesc  = frames[i];
    const beatNumber = parseInt((frameDesc.name.split(' ')[1]) || String(i + 1), 10);

    progress(
      15 + Math.round((i / frames.length) * 75),
      'Creating ' + frameDesc.name + ' (' + (i + 1) + '/' + frames.length + ')\u2026',
      i,
    );

    try {
      const { frameNode, imageNodeId, labelNodeId, metaNodeId } =
        await createBeatFrame(frameDesc, i, frames.length, apiUrl);

      beatNodeRecords.push({
        beat_number:   beatNumber,
        frame_node_id: frameNode.id,
        image_node_id: imageNodeId,
        label_node_id: labelNodeId,
        meta_node_id:  metaNodeId,
      });

      createdFrameNodes.push(frameNode);
      framesCreated++;
      send({ type: 'BEAT_DONE', beatIndex: i });

    } catch (err) {
      send({ type: 'BEAT_ERROR', beatIndex: i, beatNumber, error: String(err) });
    }
  }

  // ── Group all beat frames into a named Figma Section ─────────────────────
  progress(90, 'Grouping frames into section\u2026');
  if (createdFrameNodes.length > 0) {
    try {
      var SECTION_PAD = 80;
      var minX = createdFrameNodes[0].x;
      var minY = createdFrameNodes[0].y;
      var maxX = createdFrameNodes[0].x + createdFrameNodes[0].width;
      var maxY = createdFrameNodes[0].y + createdFrameNodes[0].height;
      for (var fi = 1; fi < createdFrameNodes.length; fi++) {
        var fn = createdFrameNodes[fi];
        if (fn.x < minX) minX = fn.x;
        if (fn.y < minY) minY = fn.y;
        if (fn.x + fn.width  > maxX) maxX = fn.x + fn.width;
        if (fn.y + fn.height > maxY) maxY = fn.y + fn.height;
      }

      var section = figma.createSection();
      section.name = fileName || 'PLAYWRIGHT Storyboard';
      section.x = minX - SECTION_PAD;
      section.y = minY - SECTION_PAD;
      section.resizeWithoutConstraints(
        (maxX - minX) + SECTION_PAD * 2,
        (maxY - minY) + SECTION_PAD * 2
      );

      for (var si = 0; si < createdFrameNodes.length; si++) {
        section.appendChild(createdFrameNodes[si]);
      }
    } catch (sectionErr) {
      console.warn('Could not create section: ' + String(sectionErr));
    }
  }

  progress(92, 'Fitting canvas to frames\u2026');
  figma.viewport.scrollAndZoomIntoView(figma.currentPage.children);

  progress(95, 'Registering node mapping with backend\u2026');

  const fileKey = figma.fileKey || '';
  const fileUrl = fileKey
    ? 'https://www.figma.com/file/' + fileKey
    : 'https://www.figma.com/files/recent';

  send({
    type: 'REGISTER_MAPPING',
    apiUrl,
    sid,
    body: {
      file_key:   fileKey,
      file_url:   fileUrl,
      page_id:    figma.currentPage.id,
      page_name:  figma.currentPage.name,
      beat_nodes: beatNodeRecords,
    },
  });

  send({ type: 'DONE', storyboard_id: sid, fileName, framesCreated });
}
