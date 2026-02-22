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

      const imageFill = (child.fills || []).find(function(f) { return f.type === 'IMAGE'; });
      if (imageFill && imageFill.imageUrl) {
        progress(pctBase, 'Beat ' + (beatIndex + 1) + ': loading image\u2026', beatIndex);
        const ok = await applyImageFill(rect, imageFill.imageUrl, apiUrl);
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
      const style      = child.style || {};
      const fontFamily = style.fontFamily || 'Inter';
      const fontStyle  = style.fontWeight >= 600 ? 'Semi Bold'
                       : style.fontWeight >= 500 ? 'Medium'
                       : 'Regular';

      const txt = figma.createText();
      txt.name = child.name;
      txt.x = child.x || 0;
      txt.y = child.y || 0;

      // Font MUST be loaded before setting textAutoResize or characters
      try {
        await figma.loadFontAsync({ family: fontFamily, style: fontStyle });
        txt.fontName = { family: fontFamily, style: fontStyle };
      } catch (_) {
        await figma.loadFontAsync({ family: 'Roboto', style: 'Regular' });
        txt.fontName = { family: 'Roboto', style: 'Regular' };
      }

      txt.fontSize = style.fontSize || 14;
      txt.resize(child.width || 200, child.height || 40);
      txt.textAutoResize = 'HEIGHT';
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

// ── Template patch mode ───────────────────────────────────────────────────────
// Patches existing nodes in the Figma template using node IDs supplied by the
// backend. Uses figma.getNodeById() so the template layout is fully preserved.

async function patchTemplateBeats(payload, apiUrl) {
  const patches  = payload.patches || [];
  const sid      = payload.storyboard_id;
  const fileName = payload.file_name;

  if (!patches.length) {
    send({ type: 'ERROR', error: 'Patch payload contains no beats.' });
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
      // ── Image node: replace fill with the generated image ──────────────
      if (patch.image_node_id && patch.imageUrl) {
        var imgNode = figma.getNodeById(patch.image_node_id);
        if (imgNode) {
          var ok = await applyImageFill(imgNode, patch.imageUrl, apiUrl);
          if (!ok) {
            send({ type: 'BEAT_ERROR', beatIndex: i, beatNumber, error: 'Image load failed' });
          }
        }
      }

      // ── Label node: update narrator text ───────────────────────────────
      if (patch.label_node_id && patch.label) {
        var labelNode = figma.getNodeById(patch.label_node_id);
        if (labelNode && labelNode.type === 'TEXT') {
          await figma.loadFontAsync(labelNode.fontName);
          labelNode.characters = patch.label;
        }
      }

      // ── Meta node: update camera · lighting text ────────────────────────
      if (patch.meta_node_id && patch.meta) {
        var metaNode = figma.getNodeById(patch.meta_node_id);
        if (metaNode && metaNode.type === 'TEXT') {
          await figma.loadFontAsync(metaNode.fontName);
          metaNode.characters = patch.meta;
        }
      }

      beatNodeRecords.push({
        beat_number:   beatNumber,
        frame_node_id: patch.frame_node_id,
        image_node_id: patch.image_node_id,
        label_node_id: patch.label_node_id,
        meta_node_id:  patch.meta_node_id,
      });

      patchedCount++;
      send({ type: 'BEAT_DONE', beatIndex: i });

    } catch (err) {
      send({ type: 'BEAT_ERROR', beatIndex: i, beatNumber, error: String(err) });
    }
  }

  progress(92, 'Fitting canvas\u2026');
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

  if (msg.type !== 'CREATE_STORYBOARD') return;

  const { payload, apiUrl } = msg;
  const sid      = payload.storyboard_id;
  const fileName = payload.file_name;

  // ── Route to the correct mode ─────────────────────────────────────────────
  // patch_template: update existing nodes in the user's Figma template
  // create_frames (default): create new frames from scratch
  if (payload.mode === 'patch_template') {
    await patchTemplateBeats(payload, apiUrl);
    return;
  }

  // ── create_frames mode (no template) ─────────────────────────────────────
  const frames = payload.frames || [];

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
};
