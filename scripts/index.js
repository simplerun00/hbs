const apps = window.APP_DATA || [];
const appGrid = document.getElementById("app-grid");
const countEl = document.getElementById("tool-count");
const featuredToolsEl = document.getElementById("hero-featured-tools");

function getPrimaryLink(app) {
  return app.webPath ? app.webPath : `./app.html?id=${app.id}`;
}

function getPrimaryLabel(app) {
  return app.webPath ? "바로 실행" : "도구 보기";
}

function getSecondaryLink(app) {
  if (app.webPath) {
    return `./app.html?id=${app.id}`;
  }

  if (app.packagePath) {
    return app.packagePath;
  }

  return `./app.html?id=${app.id}`;
}

function getSecondaryLabel(app) {
  if (app.webPath) {
    return "도구 설명";
  }

  return app.packagePath ? "패키지 열기" : "도구 설명";
}

if (countEl) {
  countEl.textContent = `${apps.length}개`;
}

if (featuredToolsEl) {
  featuredToolsEl.innerHTML = apps.slice(0, 2).map((app) => `
    <article class="hero-tool-card">
      <div class="hero-tool-top">
        <div>
          <p class="section-kicker">${app.category}</p>
          <h3 class="hero-tool-title">${app.name}</h3>
        </div>
        <span class="badge">${app.status}</span>
      </div>
      <p class="hero-tool-summary">${app.summary}</p>
      <div class="hero-tool-actions">
        <a class="button primary" href="${getPrimaryLink(app)}">${getPrimaryLabel(app)}</a>
        <a class="button secondary" href="${getSecondaryLink(app)}">${getSecondaryLabel(app)}</a>
      </div>
    </article>
  `).join("");
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
        <a class="button primary" href="${getPrimaryLink(app)}">${getPrimaryLabel(app)}</a>
        <a class="button secondary" href="${getSecondaryLink(app)}">${getSecondaryLabel(app)}</a>
      </div>
    </article>
  `).join("");
}
