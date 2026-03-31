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

const editorModal = document.getElementById("editor-modal");
const editorCloseButton = document.getElementById("editor-close");
const editorCanvas = document.getElementById("editor-canvas");
const editorOverlay = document.getElementById("editor-overlay");
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
const editorSizeInput = document.getElementById("editor-size");
const editorSizeValue = document.getElementById("editor-size-value");
const editorToolButtons = Array.from(document.querySelectorAll(".editor-tool-button"));

let currentPdfFile = null;
let isRendering = false;
let lastResult = null;

let pdfDocument = null;
let editorPages = [];
let currentEditorIndex = 0;
let editorEdits = {};
let editorRotations = {};
let editorTool = "freehand";
let editorDrawing = false;
let editorPoints = [];
let editorRectStart = null;
let activePointerId = null;

if (window.pdfjsLib) {
  window.pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.3.136/pdf.worker.min.js";
}

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

function normalizeApiBaseUrl(value) {
  return (value || "").trim().replace(/\/+$/, "");
}

function getConfiguredApiBaseUrl() {
  const configured = window.PDF_TOOL_CONFIG && typeof window.PDF_TOOL_CONFIG.apiBaseUrl === "string"
    ? window.PDF_TOOL_CONFIG.apiBaseUrl
    : "";
  return normalizeApiBaseUrl(configured);
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
}

function updateEditorSizeLabel() {
  editorSizeValue.textContent = `${editorSizeInput.value}px`;
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

async function renderEditorPage() {
  if (!pdfDocument || !editorPages.length) {
    return;
  }

  const pageNumber = getCurrentEditorPageNumber();
  const page = await pdfDocument.getPage(pageNumber);
  const rotation = getCurrentRotation();
  const viewport = page.getViewport({ scale: 1.25, rotation });
  const context = editorCanvas.getContext("2d", { alpha: false });

  editorCanvas.width = viewport.width;
  editorCanvas.height = viewport.height;
  editorOverlay.width = viewport.width;
  editorOverlay.height = viewport.height;

  await page.render({ canvasContext: context, viewport }).promise;
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

  if (!window.pdfjsLib) {
    setStatus("편집기에 필요한 라이브러리를 불러오지 못했습니다.");
    return;
  }

  try {
    const pdfBytes = await currentPdfFile.arrayBuffer();
    const loadingTask = window.pdfjsLib.getDocument({ data: pdfBytes });
    pdfDocument = await loadingTask.promise;
    editorPages = parsePageRange(rangeInput.value, pdfDocument.numPages);
    currentEditorIndex = 0;

    editorModal.hidden = false;
    document.body.classList.add("modal-open");
    await renderEditorPage();
  } catch (error) {
    setStatus(error.message || "편집기를 열지 못했습니다.");
  }
}

function closeEditor() {
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

editorOverlay.addEventListener("pointerup", async (event) => {
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
  await renderEditorPage();
});

editorOverlay.addEventListener("pointercancel", () => {
  editorDrawing = false;
  activePointerId = null;
  editorPoints = [];
  editorRectStart = null;
  clearEditorOverlay();
});

async function requestServerConversion() {
  if (isRendering) {
    setStatus("지금 변환 중입니다. 잠시만 기다려 주세요.");
    return;
  }

  if (!pdfInput.files?.[0]) {
    setStatus("먼저 PDF 파일을 선택해 주세요.");
    return;
  }

  const apiBaseUrl = getConfiguredApiBaseUrl();
  if (!apiBaseUrl) {
    setStatus("변환 서버를 준비하는 중입니다. 잠시 후 다시 시도해 주세요.");
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

    const response = await fetch(`${apiBaseUrl}/api/pdf/convert`, {
      method: "POST",
      body: formData
    });

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
    setStatus(error.message || "서버 변환 중 오류가 발생했습니다.");
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
updateEditorToolButtons();
setStatus(
  getConfiguredApiBaseUrl()
    ? "PDF를 선택하면 서버 변환을 시작할 수 있습니다."
    : "변환 서버를 준비하는 중입니다. 잠시 후 다시 시도해 주세요."
);
