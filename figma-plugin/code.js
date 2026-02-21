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
 *   { type: 'CANCEL' }
 *
 * Message protocol (plugin → ui):
 *   { type: 'PREFILL',      storyboard_id, api_url }   ← deep-link pre-fill
 *   { type: 'PROGRESS',     pct, text, beatIndex? }
 *   { type: 'BEAT_DONE',    beatIndex }
 *   { type: 'BEAT_ERROR',   beatIndex, beatNumber, error }
 *   { type: 'REGISTER_MAPPING', apiUrl, sid, body }     ← relay HTTP via UI iframe
 *   { type: 'DONE',         storyboard_id, fileName, framesCreated }
 *   { type: 'ERROR',        error }
 */

// ── Resolve launch parameters (deep link or manual) ──────────────────────────
const params = figma.command === 'run' ? figma.pluginData : null;
let deepLinkData = null;
if (params) {
  try {
    deepLinkData = typeof params === 'string' ? JSON.parse(params) : params;
  } catch (_) {
    deepLinkData = null;
  }
}

figma.showUI(__html__, {
  width: 340,
  height: 560,
  title: 'PLAYWRIGHT Storyboard',
});

// Send pre-fill data to the UI immediately after it loads
if (deepLinkData?.storyboard_id) {
  // Small delay to ensure the UI iframe is ready
  setTimeout(() => {
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

async function applyImageFill(rectNode, imageSource) {
  let bytes;
  if (typeof imageSource === 'string') {
    if (imageSource.startsWith('data:')) {
      bytes = dataUriToBytes(imageSource);
    }
    if (!bytes) return false;
  } else {
    bytes = imageSource;
  }
  const img = figma.createImage(bytes);
  rectNode.fills = [{ type: 'IMAGE', scaleMode: 'FILL', imageHash: img.hash }];
  return true;
}

async function createBeatFrame(frameDesc, beatIndex, totalBeats) {
  const pctBase = 15 + Math.round((beatIndex / totalBeats) * 75);

  const frame = figma.createFrame();
  frame.name = frameDesc.name;
  frame.x = frameDesc.x;
  frame.y = frameDesc.y;
  frame.resize(frameDesc.width, frameDesc.height);
  frame.clipsContent = frameDesc.clipsContent !== false;
  frame.fills = [{ type: 'SOLID', color: { r: 0.08, g: 0.08, b: 0.12 } }];

  let imageNodeId = '';
  let labelNodeId = '';
  let metaNodeId  = '';

  for (const child of (frameDesc.children || [])) {

    if (child.name === 'image_fill') {
      const rect = figma.createRectangle();
      rect.name = 'image_fill';
      rect.x = child.x || 0;
      rect.y = child.y || 0;
      rect.resize(child.width || frameDesc.width, child.height || frameDesc.height);

      const imageFill = (child.fills || []).find(f => f.type === 'IMAGE');
      if (imageFill && imageFill.imageUrl) {
        progress(pctBase, `Beat ${beatIndex + 1}: loading image…`, beatIndex);
        const ok = await applyImageFill(rect, imageFill.imageUrl);
        if (!ok) {
          rect.fills = [{ type: 'SOLID', color: { r: 0.1, g: 0.1, b: 0.15 } }];
        }
      } else {
        rect.fills = [{ type: 'SOLID', color: { r: 0.1, g: 0.1, b: 0.15 } }];
      }

      frame.appendChild(rect);
      imageNodeId = rect.id;
    }

    else if (child.type === 'TEXT') {
      const style     = child.style || {};
      const fontFamily = style.fontFamily || 'Inter';
      const fontStyle  = style.fontWeight >= 600 ? 'Semi Bold'
                       : style.fontWeight >= 500 ? 'Medium'
                       : 'Regular';

      const txt = figma.createText();
      txt.name = child.name;
      txt.x = child.x || 0;
      txt.y = child.y || 0;
      txt.resize(child.width || 200, child.height || 40);
      txt.textAutoResize = 'HEIGHT';

      try {
        await figma.loadFontAsync({ family: fontFamily, style: fontStyle });
        txt.fontName = { family: fontFamily, style: fontStyle };
      } catch (_) {
        await figma.loadFontAsync({ family: 'Roboto', style: 'Regular' });
        txt.fontName = { family: 'Roboto', style: 'Regular' };
      }

      txt.fontSize = style.fontSize || 14;
      txt.characters = child.characters || '';

      const fillColor = (style.fills || [])[0];
      if (fillColor && fillColor.type === 'SOLID') {
        const c = fillColor.color;
        txt.fills = [{
          type: 'SOLID',
          color: { r: c.r, g: c.g, b: c.b },
          opacity: c.a !== undefined ? c.a : 1,
        }];
      } else {
        txt.fills = [{ type: 'SOLID', color: { r: 1, g: 1, b: 1 }, opacity: 0.9 }];
      }

      frame.appendChild(txt);
      if (child.name === 'label') labelNodeId = txt.id;
      if (child.name === 'meta')  metaNodeId  = txt.id;
    }
  }

  figma.currentPage.appendChild(frame);
  return { frameNode: frame, imageNodeId, labelNodeId, metaNodeId };
}

// ── Main message handler ──────────────────────────────────────────────────────

figma.ui.onmessage = async (msg) => {
  if (msg.type === 'CANCEL') {
    figma.closePlugin();
    return;
  }

  if (msg.type !== 'CREATE_STORYBOARD') return;

  const { payload, apiUrl } = msg;
  const frames   = payload.frames || [];
  const sid      = payload.storyboard_id;
  const fileName = payload.file_name;

  if (!frames.length) {
    send({ type: 'ERROR', error: 'Payload contains no frames.' });
    return;
  }

  progress(10, `Setting up page "${payload.page_name || 'Storyboard'}"…`);
  figma.currentPage.name = payload.page_name || 'Storyboard';

  const beatNodeRecords = [];
  let framesCreated = 0;

  for (let i = 0; i < frames.length; i++) {
    const frameDesc  = frames[i];
    const beatNumber = parseInt((frameDesc.name.split(' ')[1]) || String(i + 1), 10);

    progress(
      15 + Math.round((i / frames.length) * 75),
      `Creating ${frameDesc.name} (${i + 1}/${frames.length})…`,
      i,
    );

    try {
      const { frameNode, imageNodeId, labelNodeId, metaNodeId } =
        await createBeatFrame(frameDesc, i, frames.length);

      beatNodeRecords.push({
        beat_number:   beatNumber,
        frame_node_id: frameNode.id,
        image_node_id: imageNodeId,
        label_node_id: labelNodeId,
        meta_node_id:  metaNodeId,
      });

      framesCreated++;
      send({ type: 'BEAT_DONE', beatIndex: i });

    } catch (err) {
      send({ type: 'BEAT_ERROR', beatIndex: i, beatNumber, error: String(err) });
    }
  }

  progress(92, 'Fitting canvas to frames…');
  figma.viewport.scrollAndZoomIntoView(figma.currentPage.children);

  progress(95, 'Registering node mapping with backend…');

  const fileKey = figma.fileKey || '';
  const fileUrl = fileKey
    ? `https://www.figma.com/file/${fileKey}`
    : 'https://www.figma.com/files/recent';

  // Relay the HTTP registration call through the UI iframe (sandbox can't fetch)
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
};
