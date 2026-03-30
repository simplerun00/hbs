const pdfInput = document.getElementById("pdf-file");
const rangeInput = document.getElementById("page-range");
const qualityInput = document.getElementById("jpg-quality");
const renderButton = document.getElementById("render-button");
const downloadAllButton = document.getElementById("download-all-button");
const statusEl = document.getElementById("tool-status");
const previewCountEl = document.getElementById("preview-count");
const previewGrid = document.getElementById("preview-grid");

let renderedImages = [];
let currentPdfFile = null;

if (window.pdfjsLib) {
  window.pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.3.136/pdf.worker.min.js";
}

function setStatus(message) {
  statusEl.textContent = message;
}

function parsePageRange(rangeText, totalPages) {
  const text = (rangeText || "").trim();

  if (!text || text === "전체") {
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
    } else {
      const page = Number.parseInt(part, 10);

      if (Number.isNaN(page) || page < 1 || page > totalPages) {
        throw new Error("페이지 번호를 다시 확인해 주세요.");
      }

      pages.add(page);
    }
  }

  return [...pages].sort((a, b) => a - b);
}

function clearPreviews() {
  renderedImages = [];
  previewGrid.innerHTML = "";
  previewCountEl.textContent = "아직 생성된 이미지가 없습니다.";
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

function renderPreviewCards() {
  if (!renderedImages.length) {
    clearPreviews();
    return;
  }

  previewCountEl.textContent = `${renderedImages.length}개의 이미지가 준비되었습니다.`;
  downloadAllButton.disabled = false;

  previewGrid.innerHTML = renderedImages.map((item) => `
    <article class="preview-card">
      <div class="preview-card-image">
        <img src="${item.url}" alt="${item.filename}">
      </div>
      <div class="preview-card-copy">
        <p class="section-kicker">Page ${item.pageNumber}</p>
        <h3>${item.filename}</h3>
      </div>
      <button class="button secondary preview-download" type="button" data-url="${item.url}" data-filename="${item.filename}">
        JPG 다운로드
      </button>
    </article>
  `).join("");

  document.querySelectorAll(".preview-download").forEach((button) => {
    button.addEventListener("click", () => {
      triggerDownload(button.dataset.url, button.dataset.filename);
    });
  });
}

async function createJpgFromPage(page, quality, filenamePrefix) {
  const viewport = page.getViewport({ scale: 2 });
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d", { alpha: false });
  canvas.width = viewport.width;
  canvas.height = viewport.height;

  await page.render({ canvasContext: context, viewport }).promise;

  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (!blob) {
        reject(new Error("이미지 생성에 실패했습니다."));
        return;
      }

      const pageNumber = page.pageNumber;
      const filename = `${filenamePrefix}-page-${String(pageNumber).padStart(2, "0")}.jpg`;
      const url = URL.createObjectURL(blob);
      resolve({ blob, url, filename, pageNumber });
    }, "image/jpeg", quality);
  });
}

async function renderPdfToImages() {
  if (!pdfInput.files || !pdfInput.files[0]) {
    setStatus("먼저 PDF 파일을 선택해 주세요.");
    return;
  }

  if (!window.pdfjsLib) {
    setStatus("PDF 처리 라이브러리를 불러오지 못했습니다. 인터넷 연결을 확인해 주세요.");
    return;
  }

  clearPreviews();
  currentPdfFile = pdfInput.files[0];
  setStatus("PDF를 읽는 중입니다...");
  renderButton.disabled = true;

  try {
    const pdfData = await currentPdfFile.arrayBuffer();
    const loadingTask = window.pdfjsLib.getDocument({ data: pdfData });
    const pdf = await loadingTask.promise;
    const pagesToRender = parsePageRange(rangeInput.value, pdf.numPages);
    const quality = Number.parseFloat(qualityInput.value || "0.9");
    const baseName = currentPdfFile.name.replace(/\.pdf$/i, "");

    setStatus(`${pagesToRender.length}개 페이지를 이미지로 만드는 중입니다...`);

    for (const pageNumber of pagesToRender) {
      const page = await pdf.getPage(pageNumber);
      const image = await createJpgFromPage(page, quality, baseName);
      renderedImages.push(image);
      renderPreviewCards();
      setStatus(`${pageNumber}페이지까지 변환했습니다.`);
    }

    setStatus(`완료되었습니다. ${renderedImages.length}개 JPG 파일을 다운로드할 수 있습니다.`);
  } catch (error) {
    clearPreviews();
    setStatus(error.message || "변환 중 오류가 발생했습니다.");
  } finally {
    renderButton.disabled = false;
  }
}

async function downloadAllImages() {
  for (const item of renderedImages) {
    triggerDownload(item.url, item.filename);
    await new Promise((resolve) => window.setTimeout(resolve, 180));
  }
}

renderButton.addEventListener("click", () => {
  renderPdfToImages();
});

downloadAllButton.addEventListener("click", () => {
  downloadAllImages();
});

pdfInput.addEventListener("change", () => {
  clearPreviews();
  if (pdfInput.files && pdfInput.files[0]) {
    setStatus(`선택된 파일: ${pdfInput.files[0].name}`);
  } else {
    setStatus("PDF를 선택하면 변환 준비를 시작합니다.");
  }
});
