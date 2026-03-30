const params = new URLSearchParams(window.location.search);
const appId = params.get("id");
const app = (window.APP_DATA || []).find((item) => item.id === appId);
const detailRoot = document.getElementById("app-detail");

if (!app) {
  detailRoot.innerHTML = `
    <section class="empty-state">
      <p class="section-kicker">Not Found</p>
      <h1 class="detail-title">프로그램 정보를 찾을 수 없습니다.</h1>
      <p class="detail-summary">주소의 id 값을 확인하거나 목록 페이지에서 다시 선택해 주세요.</p>
    </section>
  `;
} else {
  document.title = `${app.name} | 정비사업 실무 자동화 포털`;

  detailRoot.innerHTML = `
    <section class="detail-header">
      <div>
        <p class="section-kicker">${app.category}</p>
        <h1 class="detail-title">${app.name}</h1>
        <p class="detail-summary">${app.description}</p>
      </div>
      <span class="badge">${app.status}</span>
    </section>

    <section class="detail-grid">
      <div class="detail-section">
        <p class="section-kicker">Overview</p>
        <p class="detail-body">${app.detail}</p>

        <p class="section-kicker">핵심 포인트</p>
        <ul class="detail-list">
          ${app.highlights.map((item) => `<li>${item}</li>`).join("")}
        </ul>

        <p class="section-kicker">다음 단계</p>
        <p class="detail-body">${app.nextStep}</p>
      </div>

      <aside class="detail-side">
        <p class="section-kicker">Package</p>
        <p class="detail-body">현재 포털 기준으로 웹 실행형과 상세 안내를 함께 제공합니다. 배포본이 없는 도구는 설명 페이지를 통해 전환 방향을 안내합니다.</p>
        <div class="detail-actions">
          ${app.webPath ? `<a class="button primary" href="${app.webPath}">웹에서 실행</a>` : `<a class="button primary" href="./index.html#tools">도구 목록 보기</a>`}
          ${app.packagePath ? `<a class="button secondary" href="${app.packagePath}">배포본도 보기</a>` : `<a class="button secondary" href="./index.html#tools">목록으로 돌아가기</a>`}
        </div>

        <p class="section-kicker">원본 코드 위치</p>
        <div class="path-box">${app.sourcePath}</div>

        <p class="section-kicker">배포 정보</p>
        <ul class="detail-list">
          <li>버전: ${app.version}</li>
          <li>업데이트: ${app.updatedAt}</li>
          <li>공유 방식: 다운로드형 포털</li>
        </ul>
      </aside>
    </section>
  `;
}
