const pdfInput = document.getElementById("pdf-file");
const rangeInput = document.getElementById("page-range");
const qualityInput = document.getElementById("jpg-quality");
const renderButton = document.getElementById("render-button");
const editorButton = document.getElementById("editor-button");
const downloadAllButton = document.getElementById("download-all-button");
const statusEl = document.getElementById("tool-status");
const previewCountEl = document.getElementById("preview-count");
const previewGrid = document.getElementById("preview-grid");
const uploadPanel = document.getElementById("upload-panel");
const selectedFileNameEl = document.getElementById("selected-file-name");
const qualityValueEl = document.getElementById("jpg-quality-value");
const backendStatusEl = document.getElementById("backend-status");

const editorModal = document.getElementById("editor-modal");
const editorCloseButton = document.getElementById("editor-close");
const editorCanvas = document.getElementById("editor-canvas");
const editorOverlay = document.getElementById("editor-overlay");
const editorCanvasShell = document.querySelector(".editor-canvas-shell");
const editorPageLabel = document.getElementById("editor-page-label");
const editorFileLabel = document.getElementById("editor-file-label");
const editorStatus = document.getElementById("editor-status");
const editorPrevButton = document.getElementById("editor-prev");
const editorNextButton = document.getElementById("editor-next");
const editorUndoButton = document.getElementById("editor-undo");
const editorResetButton = document.getElementById("editor-reset");
const editorApplyButton = document.getElementById("editor-apply");
const editorRotateLeftButton = document.getElementById("editor-rotate-left");
const editorRotateRightButton = document.getElementById("editor-rotate-right");
const editorPanModeButton = document.getElementById("editor-pan-mode");
const editorZoomInButton = document.getElementById("editor-zoom-in");
const editorZoomOutButton = document.getElementById("editor-zoom-out");
const editorZoomFitButton = document.getElementById("editor-zoom-fit");
const editorZoomValue = document.getElementById("editor-zoom-value");
const editorSizeInput = document.getElementById("editor-size");
const editorSizeValue = document.getElementById("editor-size-value");
const editorToolButtons = Array.from(document.querySelectorAll(".editor-tool-button"));

let currentPdfFile = null;
let isRendering = false;
let lastResult = null;
let resolvedApiBaseUrl = "";

let pdfDocument = null;
let editorPages = [];
let currentEditorIndex = 0;
let editorEdits = {};
let editorRotations = {};
let editorTool = "rect";
let editorDrawing = false;
let editorPoints = [];
let editorRectStart = null;
let activePointerId = null;
let editorZoom = 1;
let editorBaseScale = 1.25;
let editorPan = false;
let editorPanPointer = null;
let editorPanStart = null;
let editorPanScrollStart = null;
let editorPreviewCache = {};

function setStatus(message) {
  statusEl.textContent = message;
}

function setEditorStatus(message) {
  editorStatus.textContent = message;
}

function updateQualityLabel() {
  qualityValueEl.textContent = `${Math.round(Number(qualityInput.value || "0.9") * 100)}%`;
}

function updateSelectedFileLabel(file) {
  selectedFileNameEl.textContent = file ? file.name : "아직 선택한 파일이 없습니다.";
}

function setBackendStatus(message, isLocal = false) {
  if (!backendStatusEl) {
    return;
  }
  backendStatusEl.textContent = message;
  backendStatusEl.dataset.mode = isLocal ? "local" : "remote";
}

function normalizeApiBaseUrl(value) {
  return (value || "").trim().replace(/\/+$/, "");
}

function getCandidateApiBaseUrls() {
  const config = window.PDF_TOOL_CONFIG || {};
  const local = normalizeApiBaseUrl(config.localApiBaseUrl);
  const remote = normalizeApiBaseUrl(config.defaultApiBaseUrl);
  const preferLocal = Boolean(config.preferLocalhost) && window.location.hostname === "127.0.0.1";
  return preferLocal ? [local, remote].filter(Boolean) : [remote, local].filter(Boolean);
}

function getRequestTimeoutMs() {
  const config = window.PDF_TOOL_CONFIG || {};
  return Number(config.requestTimeoutMs || 300000);
}

async function probeApiBaseUrl(baseUrl) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 4000);

  try {
    const response = await fetch(`${baseUrl}/health`, {
      method: "GET",
      signal: controller.signal,
      cache: "no-store"
    });
    if (!response.ok) {
      throw new Error("health check failed");
    }
    return true;
  } catch (error) {
    return false;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function resolveApiBaseUrl(force = false) {
  if (resolvedApiBaseUrl && !force) {
    return resolvedApiBaseUrl;
  }

  setBackendStatus("연결할 변환 서버를 확인하는 중입니다.");

  for (const baseUrl of getCandidateApiBaseUrls()) {
    if (await probeApiBaseUrl(baseUrl)) {
      resolvedApiBaseUrl = baseUrl;
      const isLocal = baseUrl.includes("127.0.0.1") || baseUrl.includes("localhost");
      setBackendStatus(
        isLocal
          ? `현재 로컬 변환 서버 사용 중: ${baseUrl}`
          : `현재 원격 변환 서버 사용 중: ${baseUrl}`,
        isLocal
      );
      return resolvedApiBaseUrl;
    }
  }

  resolvedApiBaseUrl = "";
  setBackendStatus("변환 서버에 연결하지 못했습니다. 로컬 백엔드 또는 Render 서버 상태를 확인해 주세요.");
  return "";
}

function parsePageRange(rangeText, totalPages) {
  const text = (rangeText || "").trim();

  if (!text || text.toLowerCase() === "all" || text === "전체") {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }

  const pages = new Set();

  for (const part of text.replace(/\s+/g, "").split(",")) {
    if (!part) {
      continue;
    }

    if (part.includes("-")) {
      const [startText, endText] = part.split("-");
      const start = Number.parseInt(startText, 10);
      const end = Number.parseInt(endText, 10);

      if (Number.isNaN(start) || Number.isNaN(end) || start < 1 || end < start) {
        throw new Error("페이지 범위를 다시 확인해 주세요.");
      }

      for (let page = start; page <= Math.min(end, totalPages); page += 1) {
        pages.add(page);
      }
      continue;
    }

    const page = Number.parseInt(part, 10);
    if (Number.isNaN(page) || page < 1 || page > totalPages) {
      throw new Error("페이지 번호를 다시 확인해 주세요.");
    }
    pages.add(page);
  }

  if (!pages.size) {
    throw new Error("변환할 페이지가 없습니다.");
  }

  return [...pages].sort((a, b) => a - b);
}

function clearResult() {
  if (lastResult?.url) {
    URL.revokeObjectURL(lastResult.url);
  }

  lastResult = null;
  previewGrid.innerHTML = "";
  previewCountEl.textContent = "아직 생성된 ZIP 파일이 없습니다.";
  downloadAllButton.disabled = true;
}

function triggerDownload(url, filename) {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function renderResultCard() {
  if (!lastResult) {
    clearResult();
    return;
  }

  previewCountEl.textContent = `${lastResult.pageCount}개 페이지가 서버에서 변환되었습니다.`;
  downloadAllButton.disabled = false;
  previewGrid.innerHTML = `
    <article class="preview-card">
      <div class="preview-card-copy">
        <p class="section-kicker">ZIP</p>
        <h3>${lastResult.filename}</h3>
        <p class="app-description">편집이 반영된 JPG 묶음을 ZIP 파일로 다시 내려받을 수 있습니다.</p>
      </div>
      <button id="result-download-button" class="button primary" type="button">ZIP 다운로드</button>
    </article>
  `;

  document.getElementById("result-download-button")?.addEventListener("click", () => {
    triggerDownload(lastResult.url, lastResult.filename);
  });
}

function resetEditorState() {
  editorEdits = {};
  editorRotations = {};
  pdfDocument = null;
  editorPages = [];
  currentEditorIndex = 0;
  editorZoom = 1;
  editorPan = false;
  editorPreviewCache = {};
}

function updateSelectedFile(fileList) {
  const files = Array.from(fileList || []);
  const pdfFile = files.find((file) => file.type === "application/pdf" || /\.pdf$/i.test(file.name));

  clearResult();
  resetEditorState();

  if (!pdfFile) {
    pdfInput.value = "";
    currentPdfFile = null;
    updateSelectedFileLabel(null);
    setStatus("PDF 파일만 선택할 수 있습니다.");
    return;
  }

  const transfer = new DataTransfer();
  transfer.items.add(pdfFile);
  pdfInput.files = transfer.files;
  currentPdfFile = pdfFile;
  updateSelectedFileLabel(pdfFile);
  setStatus(`선택한 파일: ${pdfFile.name}`);
}

function getPageKey(pageNumber) {
  return String(pageNumber);
}

function ensurePageEdits(pageNumber) {
  const key = getPageKey(pageNumber);
  if (!Array.isArray(editorEdits[key])) {
    editorEdits[key] = [];
  }
  return editorEdits[key];
}

function getCurrentEditorPageNumber() {
  return editorPages[currentEditorIndex] || 1;
}

function getCurrentRotation() {
  const key = getPageKey(getCurrentEditorPageNumber());
  return Number(editorRotations[key] || 0);
}

function setCurrentRotation(rotation) {
  const key = getPageKey(getCurrentEditorPageNumber());
  editorRotations[key] = ((rotation % 360) + 360) % 360;
}

function updateEditorToolButtons() {
  editorToolButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.tool === editorTool);
  });
  editorPanModeButton?.classList.toggle("is-active", editorPan);
  editorOverlay.classList.toggle("is-pan-mode", editorPan);
}

function updateEditorSizeLabel() {
  editorSizeValue.textContent = `${editorSizeInput.value}px`;
}

function updateEditorZoomLabel() {
  editorZoomValue.textContent = `${Math.round(editorZoom * 100)}%`;
}

function getEditorNaturalCanvasSize() {
  if (!editorCanvas.width || !editorCanvas.height) {
    return null;
  }

  return {
    width: editorCanvas.width / Math.max(editorZoom, 0.01),
    height: editorCanvas.height / Math.max(editorZoom, 0.01)
  };
}

function getFitZoomValue() {
  const naturalSize = getEditorNaturalCanvasSize();
  if (!naturalSize) {
    return 1;
  }

  const shellStyles = window.getComputedStyle(editorCanvasShell);
  const horizontalPadding = Number.parseFloat(shellStyles.paddingLeft || "0") + Number.parseFloat(shellStyles.paddingRight || "0");
  const verticalPadding = Number.parseFloat(shellStyles.paddingTop || "0") + Number.parseFloat(shellStyles.paddingBottom || "0");
  const availableWidth = Math.max(120, editorCanvasShell.clientWidth - horizontalPadding);
  const availableHeight = Math.max(120, editorCanvasShell.clientHeight - verticalPadding);

  return Math.min(
    4,
    Math.max(
      0.2,
      Math.min(availableWidth / naturalSize.width, availableHeight / naturalSize.height)
    )
  );
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function getViewportCenter() {
  const shellRect = editorCanvasShell.getBoundingClientRect();
  return {
    clientX: shellRect.left + shellRect.width / 2,
    clientY: shellRect.top + shellRect.height / 2
  };
}

function getZoomAnchor(clientX, clientY) {
  const shellRect = editorCanvasShell.getBoundingClientRect();
  const canvasRect = editorCanvas.getBoundingClientRect();
  const canvasWidth = Math.max(1, editorCanvas.clientWidth || editorCanvas.width);
  const canvasHeight = Math.max(1, editorCanvas.clientHeight || editorCanvas.height);

  return {
    normalizedX: clamp((clientX - canvasRect.left) / canvasWidth, 0, 1),
    normalizedY: clamp((clientY - canvasRect.top) / canvasHeight, 0, 1),
    viewportX: clamp(clientX - shellRect.left, 0, shellRect.width),
    viewportY: clamp(clientY - shellRect.top, 0, shellRect.height)
  };
}

function applyZoomAnchor(anchor) {
  if (!anchor) {
    return;
  }

  const displayWidth = Math.max(1, editorCanvas.clientWidth || editorCanvas.width);
  const displayHeight = Math.max(1, editorCanvas.clientHeight || editorCanvas.height);
  const maxLeft = Math.max(0, editorCanvasShell.scrollWidth - editorCanvasShell.clientWidth);
  const maxTop = Math.max(0, editorCanvasShell.scrollHeight - editorCanvasShell.clientHeight);
  const targetLeft = editorCanvas.offsetLeft + anchor.normalizedX * displayWidth - anchor.viewportX;
  const targetTop = editorCanvas.offsetTop + anchor.normalizedY * displayHeight - anchor.viewportY;

  editorCanvasShell.scrollLeft = clamp(targetLeft, 0, maxLeft);
  editorCanvasShell.scrollTop = clamp(targetTop, 0, maxTop);
}

async function setEditorZoom(nextZoom, anchor = null) {
  const resolvedAnchor = anchor || getZoomAnchor(getViewportCenter().clientX, getViewportCenter().clientY);
  editorZoom = Math.min(4, Math.max(0.5, nextZoom));
  updateEditorZoomLabel();
  if (editorPages.length && currentPdfFile) {
    await renderEditorPage();
    window.requestAnimationFrame(() => {
      applyZoomAnchor(resolvedAnchor);
    });
  }
}

function clearEditorOverlay() {
  const overlayContext = editorOverlay.getContext("2d");
  overlayContext.clearRect(0, 0, editorOverlay.width, editorOverlay.height);
}

function canvasPointToNormalized(x, y) {
  return {
    x: Math.max(0, Math.min(1, x / editorCanvas.width)),
    y: Math.max(0, Math.min(1, y / editorCanvas.height))
  };
}

function normalizedToCanvas(point) {
  return {
    x: point.x * editorCanvas.width,
    y: point.y * editorCanvas.height
  };
}

function drawEditPreview(edit, context) {
  context.save();
  context.strokeStyle = "rgba(255, 255, 255, 0.95)";
  context.fillStyle = "rgba(255, 255, 255, 0.95)";
  context.lineCap = "round";
  context.lineJoin = "round";

  if (edit.type === "rect") {
    const start = normalizedToCanvas({ x: edit.x1, y: edit.y1 });
    const end = normalizedToCanvas({ x: edit.x2, y: edit.y2 });
    context.fillRect(start.x, start.y, end.x - start.x, end.y - start.y);
  }

  if (edit.type === "freehand") {
    const width = Math.max(1, edit.width * editorCanvas.width);
    context.lineWidth = width;
    context.beginPath();
    edit.points.forEach((point, index) => {
      const canvasPoint = normalizedToCanvas({ x: point[0], y: point[1] });
      if (index === 0) {
        context.moveTo(canvasPoint.x, canvasPoint.y);
      } else {
        context.lineTo(canvasPoint.x, canvasPoint.y);
      }
    });
    context.stroke();
  }

  context.restore();
}

function drawLatestEditOnCanvas() {
  const pageEdits = ensurePageEdits(getCurrentEditorPageNumber());
  const latestEdit = pageEdits[pageEdits.length - 1];
  if (!latestEdit) {
    return;
  }

  const context = editorCanvas.getContext("2d", { alpha: false });
  drawEditPreview(latestEdit, context);
}

function syncCanvasDisplaySize(width, height) {
  const widthPx = `${width}px`;
  const heightPx = `${height}px`;
  editorCanvas.style.width = widthPx;
  editorCanvas.style.height = heightPx;
  editorOverlay.style.width = widthPx;
  editorOverlay.style.height = heightPx;
}

async function fitEditorToViewport() {
  editorZoom = getFitZoomValue();
  updateEditorZoomLabel();
  if (editorPages.length && currentPdfFile) {
    await renderEditorPage();
    editorCanvasShell.scrollLeft = 0;
    editorCanvasShell.scrollTop = 0;
  }
}

async function renderEditorPage() {
  if (!editorPages.length || !currentPdfFile) {
    return;
  }

  const pageNumber = getCurrentEditorPageNumber();
  const rotation = getCurrentRotation();
  const context = editorCanvas.getContext("2d", { alpha: false });
  const cacheKey = `${pageNumber}:${rotation}`;
  let preview = editorPreviewCache[cacheKey];

  if (!preview) {
    setEditorStatus(`${pageNumber}페이지 미리보기를 불러오는 중입니다...`);

    const apiBaseUrl = await resolveApiBaseUrl();
    if (!apiBaseUrl) {
      throw new Error("미리보기 서버에 연결하지 못했습니다.");
    }

    const formData = new FormData();
    formData.append("file", currentPdfFile);
    formData.append("page_number", String(pageNumber));
    formData.append("jpg_quality", qualityInput.value || "0.9");
    formData.append("rotation", String(rotation));

    const response = await fetch(`${apiBaseUrl}/api/pdf/preview-page`, {
      method: "POST",
      body: formData
    });

    if (!response.ok) {
      throw new Error("편집용 미리보기를 불러오지 못했습니다.");
    }

    const blob = await response.blob();
    const imageUrl = URL.createObjectURL(blob);
    const image = new Image();
    image.src = imageUrl;
    await image.decode();
    preview = { image, imageUrl };
    editorPreviewCache[cacheKey] = preview;
  }

  const width = Math.max(1, Math.round(preview.image.naturalWidth * editorZoom));
  const height = Math.max(1, Math.round(preview.image.naturalHeight * editorZoom));
  editorCanvas.width = width;
  editorCanvas.height = height;
  editorOverlay.width = width;
  editorOverlay.height = height;
  syncCanvasDisplaySize(width, height);

  context.clearRect(0, 0, width, height);
  context.drawImage(preview.image, 0, 0, width, height);
  ensurePageEdits(pageNumber).forEach((edit) => drawEditPreview(edit, context));

  clearEditorOverlay();
  editorPageLabel.textContent = `${currentEditorIndex + 1} / ${editorPages.length}`;
  editorFileLabel.textContent = `${currentPdfFile ? currentPdfFile.name : "PDF"} - ${pageNumber}페이지`;
  setEditorStatus(`현재 ${pageNumber}페이지를 편집 중입니다.`);
  editorPrevButton.disabled = currentEditorIndex === 0;
  editorNextButton.disabled = currentEditorIndex === editorPages.length - 1;
}

async function openEditor() {
  if (!currentPdfFile) {
    setStatus("먼저 PDF 파일을 선택해 주세요.");
    return;
  }

  try {
    const apiBaseUrl = await resolveApiBaseUrl();
    if (!apiBaseUrl) {
      setStatus("편집기를 열기 전에 변환 서버에 연결해야 합니다.");
      return;
    }

    const formData = new FormData();
    formData.append("file", currentPdfFile);

    const inspectResponse = await fetch(`${apiBaseUrl}/api/pdf/inspect`, {
      method: "POST",
      body: formData
    });

    if (!inspectResponse.ok) {
      throw new Error("PDF 페이지 정보를 불러오지 못했습니다.");
    }

    const inspectData = await inspectResponse.json();
    editorPages = parsePageRange(rangeInput.value, inspectData.page_count);
    currentEditorIndex = 0;
    editorZoom = 1;
    editorPan = false;

    editorModal.hidden = false;
    document.body.classList.add("modal-open");
    updateEditorZoomLabel();
    updateEditorToolButtons();
    setEditorStatus("휠로 확대/축소, 드래그 이동으로 화면 탐색, Esc로 닫을 수 있습니다.");
    await renderEditorPage();
    await fitEditorToViewport();
  } catch (error) {
    setStatus(error.message || "편집기를 열지 못했습니다.");
  }
}

function closeEditor() {
  editorDrawing = false;
  activePointerId = null;
  editorPoints = [];
  editorRectStart = null;
  editorModal.hidden = true;
  document.body.classList.remove("modal-open");
  clearEditorOverlay();
}

function handleEditorUndo() {
  const pageEdits = ensurePageEdits(getCurrentEditorPageNumber());
  if (pageEdits.length) {
    pageEdits.pop();
    renderEditorPage();
  }
}

function handleEditorReset() {
  const key = getPageKey(getCurrentEditorPageNumber());
  editorEdits[key] = [];
  editorRotations[key] = 0;
  renderEditorPage();
}

function getEditorPointerPosition(event) {
  const rect = editorOverlay.getBoundingClientRect();
  return {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top
  };
}

function drawOverlayFreehand(points) {
  const overlayContext = editorOverlay.getContext("2d");
  clearEditorOverlay();
  overlayContext.save();
  overlayContext.strokeStyle = "rgba(255, 255, 255, 0.95)";
  overlayContext.lineCap = "round";
  overlayContext.lineJoin = "round";
  overlayContext.lineWidth = Number(editorSizeInput.value || "22");
  overlayContext.beginPath();
  points.forEach((point, index) => {
    if (index === 0) {
      overlayContext.moveTo(point.x, point.y);
    } else {
      overlayContext.lineTo(point.x, point.y);
    }
  });
  overlayContext.stroke();
  overlayContext.restore();
}

function drawOverlayRect(start, end) {
  const overlayContext = editorOverlay.getContext("2d");
  clearEditorOverlay();
  overlayContext.save();
  overlayContext.setLineDash([6, 4]);
  overlayContext.strokeStyle = "rgba(255, 255, 255, 0.95)";
  overlayContext.lineWidth = 2;
  overlayContext.strokeRect(start.x, start.y, end.x - start.x, end.y - start.y);
  overlayContext.restore();
}

function commitFreehandEdit() {
  if (editorPoints.length < 2) {
    return;
  }

  const normalizedPoints = editorPoints.map((point) => {
    const normalized = canvasPointToNormalized(point.x, point.y);
    return [normalized.x, normalized.y];
  });

  ensurePageEdits(getCurrentEditorPageNumber()).push({
    type: "freehand",
    points: normalizedPoints,
    width: Number(editorSizeInput.value || "22") / editorCanvas.width
  });
}

function commitRectEdit(currentPoint) {
  if (!editorRectStart) {
    return;
  }

  const start = canvasPointToNormalized(editorRectStart.x, editorRectStart.y);
  const end = canvasPointToNormalized(currentPoint.x, currentPoint.y);

  ensurePageEdits(getCurrentEditorPageNumber()).push({
    type: "rect",
    x1: Math.min(start.x, end.x),
    y1: Math.min(start.y, end.y),
    x2: Math.max(start.x, end.x),
    y2: Math.max(start.y, end.y)
  });
}

editorOverlay.addEventListener("pointerdown", (event) => {
  if (editorModal.hidden) {
    return;
  }

  event.preventDefault();
  editorOverlay.setPointerCapture?.(event.pointerId);

  if (editorPan) {
    editorPanPointer = event.pointerId;
    editorPanStart = { x: event.clientX, y: event.clientY };
    editorPanScrollStart = {
      left: editorCanvasShell.scrollLeft,
      top: editorCanvasShell.scrollTop
    };
    return;
  }

  activePointerId = event.pointerId;
  editorDrawing = true;
  const point = getEditorPointerPosition(event);

  if (editorTool === "freehand") {
    editorPoints = [point];
    drawOverlayFreehand(editorPoints);
  } else {
    editorRectStart = point;
    drawOverlayRect(editorRectStart, point);
  }
});

editorOverlay.addEventListener("pointermove", (event) => {
  if (editorPan && editorPanPointer === event.pointerId && editorPanStart && editorPanScrollStart) {
    event.preventDefault();
    const dx = event.clientX - editorPanStart.x;
    const dy = event.clientY - editorPanStart.y;
    editorCanvasShell.scrollLeft = editorPanScrollStart.left - dx;
    editorCanvasShell.scrollTop = editorPanScrollStart.top - dy;
    return;
  }

  if (!editorDrawing || activePointerId !== event.pointerId) {
    return;
  }

  const point = getEditorPointerPosition(event);
  if (editorTool === "freehand") {
    editorPoints.push(point);
    drawOverlayFreehand(editorPoints);
  } else {
    drawOverlayRect(editorRectStart, point);
  }
});

editorOverlay.addEventListener("pointerup", (event) => {
  editorOverlay.releasePointerCapture?.(event.pointerId);

  if (editorPan && editorPanPointer === event.pointerId) {
    editorPanPointer = null;
    editorPanStart = null;
    editorPanScrollStart = null;
    return;
  }

  if (!editorDrawing || activePointerId !== event.pointerId) {
    return;
  }

  const point = getEditorPointerPosition(event);
  if (editorTool === "freehand") {
    editorPoints.push(point);
    commitFreehandEdit();
    editorPoints = [];
  } else {
    commitRectEdit(point);
    editorRectStart = null;
  }

  editorDrawing = false;
  activePointerId = null;
  clearEditorOverlay();
  drawLatestEditOnCanvas();
  setEditorStatus(`현재 ${getCurrentEditorPageNumber()}페이지를 편집 중입니다.`);
});

editorOverlay.addEventListener("pointercancel", () => {
  editorDrawing = false;
  activePointerId = null;
  editorPoints = [];
  editorRectStart = null;
  editorPanPointer = null;
  editorPanStart = null;
  editorPanScrollStart = null;
  clearEditorOverlay();
});

editorOverlay.addEventListener("wheel", (event) => {
  if (editorModal.hidden) {
    return;
  }

  event.preventDefault();
  const anchor = getZoomAnchor(event.clientX, event.clientY);
  const delta = event.deltaY < 0 ? 0.1 : -0.1;
  setEditorZoom(editorZoom + delta, anchor);
}, { passive: false });

async function requestServerConversion() {
  if (isRendering) {
    setStatus("지금 변환 중입니다. 잠시만 기다려 주세요.");
    return;
  }

  if (!pdfInput.files?.[0]) {
    setStatus("먼저 PDF 파일을 선택해 주세요.");
    return;
  }

  const apiBaseUrl = await resolveApiBaseUrl();
  if (!apiBaseUrl) {
    setStatus("변환 서버에 연결하지 못했습니다. 로컬 백엔드 또는 Render 서버 상태를 확인해 주세요.");
    return;
  }

  clearResult();
  currentPdfFile = pdfInput.files[0];
  isRendering = true;
  renderButton.disabled = true;
  setStatus("서버로 PDF를 보내는 중입니다...");

  try {
    const formData = new FormData();
    formData.append("file", currentPdfFile);
    formData.append("page_range", rangeInput.value.trim());
    formData.append("jpg_quality", qualityInput.value || "0.9");
    formData.append("edits_json", JSON.stringify(editorEdits));
    formData.append("rotations_json", JSON.stringify(editorRotations));

    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), getRequestTimeoutMs());
    const response = await fetch(`${apiBaseUrl}/api/pdf/convert`, {
      method: "POST",
      body: formData,
      signal: controller.signal
    });
    window.clearTimeout(timeout);

    if (!response.ok) {
      let errorMessage = "서버 변환에 실패했습니다.";

      try {
        const errorData = await response.json();
        if (errorData?.detail) {
          errorMessage = errorData.detail;
        }
      } catch (error) {
        // Keep default message when the server does not return JSON.
      }

      throw new Error(errorMessage);
    }

    const blob = await response.blob();
    const pageCount = Number.parseInt(response.headers.get("X-Converted-Pages") || "0", 10) || 0;
    const filenameHeader = response.headers.get("X-Output-Filename");
    const filename = filenameHeader || `${currentPdfFile.name.replace(/\.pdf$/i, "")}-jpg.zip`;
    const url = URL.createObjectURL(blob);

    lastResult = { url, filename, pageCount: Math.max(pageCount, 1) };
    renderResultCard();
    triggerDownload(url, filename);
    setStatus(`변환이 완료되었습니다. ${filename} 파일을 내려받았습니다.`);
  } catch (error) {
    clearResult();
    if (error.name === "AbortError") {
      setStatus("변환 시간이 길어지고 있습니다. 대용량 PDF이거나 서버 응답이 지연된 상태입니다. 로컬 백엔드를 우선 사용하거나 페이지 범위를 줄여 다시 시도해 주세요.");
    } else {
      setStatus(error.message || "서버 변환 중 오류가 발생했습니다.");
    }
  } finally {
    isRendering = false;
    renderButton.disabled = false;
  }
}

renderButton.addEventListener("click", () => {
  requestServerConversion();
});

editorButton.addEventListener("click", () => {
  openEditor();
});

editorCloseButton.addEventListener("click", () => {
  closeEditor();
});

editorModal.addEventListener("click", (event) => {
  if (event.target === editorModal) {
    closeEditor();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !editorModal.hidden) {
    closeEditor();
    return;
  }

  if (editorModal.hidden) {
    return;
  }

  if (event.key === "+" || event.key === "=") {
    event.preventDefault();
    setEditorZoom(editorZoom + 0.25);
  } else if (event.key === "-") {
    event.preventDefault();
    setEditorZoom(editorZoom - 0.25);
  } else if (event.key === "0") {
    event.preventDefault();
    setEditorZoom(1);
  } else if (event.key.toLowerCase() === "m") {
    event.preventDefault();
    editorPan = !editorPan;
    updateEditorToolButtons();
    setEditorStatus(editorPan ? "드래그 이동 모드입니다. 화면을 끌어서 위치를 옮길 수 있습니다." : `현재 ${getCurrentEditorPageNumber()}페이지를 편집 중입니다.`);
  } else if (event.key.toLowerCase() === "r") {
    event.preventDefault();
    editorPan = false;
    editorTool = "rect";
    updateEditorToolButtons();
    setEditorStatus("사각 지우개 모드입니다.");
  } else if (event.key.toLowerCase() === "h") {
    event.preventDefault();
    editorPan = false;
    editorTool = "freehand";
    updateEditorToolButtons();
    setEditorStatus("자유 지우개 모드입니다.");
  }
});

editorApplyButton.addEventListener("click", () => {
  closeEditor();
  setStatus("편집 내용을 저장했습니다. ZIP 생성 시작을 누르면 반영됩니다.");
});

editorPrevButton.addEventListener("click", async () => {
  if (currentEditorIndex > 0) {
    currentEditorIndex -= 1;
    await renderEditorPage();
  }
});

editorNextButton.addEventListener("click", async () => {
  if (currentEditorIndex < editorPages.length - 1) {
    currentEditorIndex += 1;
    await renderEditorPage();
  }
});

editorUndoButton.addEventListener("click", () => {
  handleEditorUndo();
});

editorResetButton.addEventListener("click", () => {
  handleEditorReset();
});

editorRotateLeftButton.addEventListener("click", async () => {
  setCurrentRotation(getCurrentRotation() - 90);
  await renderEditorPage();
});

editorRotateRightButton.addEventListener("click", async () => {
  setCurrentRotation(getCurrentRotation() + 90);
  await renderEditorPage();
});

editorPanModeButton.addEventListener("click", () => {
  editorPan = !editorPan;
  updateEditorToolButtons();
  setEditorStatus(editorPan ? "드래그 이동 모드입니다. 화면을 끌어서 위치를 옮길 수 있습니다." : `현재 ${getCurrentEditorPageNumber()}페이지를 편집 중입니다.`);
});

editorZoomInButton.addEventListener("click", async () => {
  const center = getViewportCenter();
  await setEditorZoom(editorZoom + 0.25, getZoomAnchor(center.clientX, center.clientY));
});

editorZoomOutButton.addEventListener("click", async () => {
  const center = getViewportCenter();
  await setEditorZoom(editorZoom - 0.25, getZoomAnchor(center.clientX, center.clientY));
});

editorZoomFitButton.addEventListener("click", async () => {
  await fitEditorToViewport();
});

editorToolButtons.forEach((button) => {
  button.addEventListener("click", () => {
    editorTool = button.dataset.tool;
    updateEditorToolButtons();
  });
});

downloadAllButton.addEventListener("click", () => {
  if (lastResult) {
    triggerDownload(lastResult.url, lastResult.filename);
  }
});

pdfInput.addEventListener("click", () => {
  setStatus("파일 선택 창을 여는 중입니다...");
});

uploadPanel?.addEventListener("pointerdown", () => {
  setStatus("파일 선택 창을 여는 중입니다...");
});

pdfInput.addEventListener("change", () => {
  if (pdfInput.files?.[0]) {
    updateSelectedFile(pdfInput.files);
  } else {
    clearResult();
    currentPdfFile = null;
    updateSelectedFileLabel(null);
    setStatus("PDF를 선택하면 서버 변환을 시작할 수 있습니다.");
  }
});

qualityInput.addEventListener("input", () => {
  updateQualityLabel();
});

editorSizeInput.addEventListener("input", () => {
  updateEditorSizeLabel();
});

if (uploadPanel) {
  ["dragenter", "dragover"].forEach((eventName) => {
    uploadPanel.addEventListener(eventName, (event) => {
      event.preventDefault();
      uploadPanel.classList.add("drag-active");
    });
  });

  ["dragleave", "dragend", "drop"].forEach((eventName) => {
    uploadPanel.addEventListener(eventName, (event) => {
      event.preventDefault();
      uploadPanel.classList.remove("drag-active");
    });
  });

  uploadPanel.addEventListener("drop", (event) => {
    updateSelectedFile(event.dataTransfer ? event.dataTransfer.files : null);
  });
}

updateSelectedFileLabel(null);
updateQualityLabel();
updateEditorSizeLabel();
updateEditorZoomLabel();
updateEditorToolButtons();
closeEditor();
resolveApiBaseUrl();
setStatus(
  getCandidateApiBaseUrls().length
    ? "PDF를 선택하면 서버 변환을 시작할 수 있습니다."
    : "변환 서버를 준비하는 중입니다. 잠시 후 다시 시도해 주세요."
);
