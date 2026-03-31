const pdfInput = document.getElementById("pdf-file");
const rangeInput = document.getElementById("page-range");
const qualityInput = document.getElementById("jpg-quality");
const renderButton = document.getElementById("render-button");
const downloadAllButton = document.getElementById("download-all-button");
const statusEl = document.getElementById("tool-status");
const previewCountEl = document.getElementById("preview-count");
const previewGrid = document.getElementById("preview-grid");
const uploadPanel = document.getElementById("upload-panel");
const selectedFileNameEl = document.getElementById("selected-file-name");
const qualityValueEl = document.getElementById("jpg-quality-value");

let currentPdfFile = null;
let isRendering = false;
let lastResult = null;

function setStatus(message) {
  statusEl.textContent = message;
}

function updateQualityLabel() {
  if (!qualityValueEl) {
    return;
  }

  qualityValueEl.textContent = `${Math.round(Number(qualityInput.value || "0.9") * 100)}%`;
}

function updateSelectedFileLabel(file) {
  if (!selectedFileNameEl) {
    return;
  }

  selectedFileNameEl.textContent = file ? file.name : "아직 선택되지 않음";
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

function clearResult() {
  if (lastResult && lastResult.url) {
    URL.revokeObjectURL(lastResult.url);
  }

  lastResult = null;
  previewGrid.innerHTML = "";
  previewCountEl.textContent = "아직 서버에서 생성한 ZIP 파일이 없습니다.";
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
        <p class="app-description">서버가 만든 JPG 묶음을 ZIP 파일로 내려받을 수 있습니다.</p>
      </div>
      <button id="result-download-button" class="button primary" type="button">ZIP 다운로드</button>
    </article>
  `;

  const downloadButton = document.getElementById("result-download-button");
  if (downloadButton) {
    downloadButton.addEventListener("click", () => {
      triggerDownload(lastResult.url, lastResult.filename);
    });
  }
}

function updateSelectedFile(fileList) {
  const files = Array.from(fileList || []);
  const pdfFile = files.find((file) => file.type === "application/pdf" || /\.pdf$/i.test(file.name));

  clearResult();

  if (!pdfFile) {
    pdfInput.value = "";
    currentPdfFile = null;
    updateSelectedFileLabel(null);
    setStatus("PDF 파일만 넣을 수 있습니다.");
    return;
  }

  const transfer = new DataTransfer();
  transfer.items.add(pdfFile);
  pdfInput.files = transfer.files;
  currentPdfFile = pdfFile;
  updateSelectedFileLabel(pdfFile);
  setStatus(`선택된 파일: ${pdfFile.name}`);
}

async function requestServerConversion() {
  if (isRendering) {
    setStatus("지금 변환 중입니다. 잠시만 기다려주세요.");
    return;
  }

  if (!pdfInput.files || !pdfInput.files[0]) {
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
  setStatus("서버에 PDF를 보내는 중입니다...");

  try {
    const formData = new FormData();
    formData.append("file", currentPdfFile);
    formData.append("page_range", rangeInput.value.trim());
    formData.append("jpg_quality", qualityInput.value || "0.9");

    const response = await fetch(`${apiBaseUrl}/api/pdf/convert`, {
      method: "POST",
      body: formData
    });

    if (!response.ok) {
      let errorMessage = "서버 변환에 실패했습니다.";

      try {
        const errorData = await response.json();
        if (errorData && errorData.detail) {
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
    setStatus(`변환 완료. ${filename} 파일을 다운로드했습니다.`);
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

downloadAllButton.addEventListener("click", () => {
  if (lastResult) {
    triggerDownload(lastResult.url, lastResult.filename);
  }
});

pdfInput.addEventListener("change", () => {
  if (pdfInput.files && pdfInput.files[0]) {
    updateSelectedFile(pdfInput.files);
  } else {
    clearResult();
    currentPdfFile = null;
    updateSelectedFileLabel(null);
    setStatus("PDF를 선택하면 서버 변환 준비를 시작합니다.");
  }
});

qualityInput.addEventListener("input", () => {
  updateQualityLabel();
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
setStatus(getConfiguredApiBaseUrl()
  ? "PDF를 선택하면 서버 변환을 시작할 수 있습니다."
  : "변환 서버를 준비하는 중입니다. 잠시 후 다시 시도해 주세요.");
