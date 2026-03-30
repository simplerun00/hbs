const apps = window.APP_DATA || [];
const appGrid = document.getElementById("app-grid");
const countEl = document.getElementById("tool-count");

if (countEl) {
  countEl.textContent = `${apps.length}개`;
}

if (appGrid) {
  appGrid.innerHTML = apps.map((app) => `
    <article class="app-card">
      <div class="app-top">
        <div>
          <p class="section-kicker">${app.category}</p>
          <h3 class="app-title">${app.name}</h3>
          <p class="app-description">${app.summary}</p>
        </div>
        <span class="badge">${app.status}</span>
      </div>

      <div class="meta-row">
        <span><strong class="meta-label">버전</strong>${app.version}</span>
        <span><strong class="meta-label">업데이트</strong>${app.updatedAt}</span>
      </div>

      <p class="status-note">${app.nextStep}</p>

      <div class="app-actions">
        ${app.webPath ? `<a class="button primary" href="${app.webPath}">웹에서 실행</a>` : `<a class="button primary" href="./app.html?id=${app.id}">상세 보기</a>`}
        ${app.webPath ? `<a class="button secondary" href="./app.html?id=${app.id}">도구 설명 보기</a>` : `<a class="button secondary" href="${app.packagePath}">압축 파일 열기</a>`}
      </div>
    </article>
  `).join("");
}
