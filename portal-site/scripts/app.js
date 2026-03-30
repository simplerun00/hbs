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
        <p class="detail-body">현재 포털 기준 배포 방식은 압축 파일 다운로드입니다. 이후 검증된 기능부터 웹 실행형으로 확장할 수 있습니다.</p>
        <div class="detail-actions">
          ${app.webPath ? `<a class="button primary" href="${app.webPath}">웹에서 실행</a>` : `<a class="button primary" href="${app.packagePath}">압축 파일 열기</a>`}
          ${app.webPath ? `<a class="button secondary" href="${app.packagePath}">배포본도 보기</a>` : `<a class="button secondary" href="./index.html#tools">목록으로 돌아가기</a>`}
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
