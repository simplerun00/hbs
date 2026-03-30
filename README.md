# 정비사업 실무 자동화 포털

도시계획·재개발 정비사업 실무를 위한 웹 포털 프로젝트입니다.

현재 포함된 내용:

- `portal-site/`
  - 소개 랜딩 페이지
  - PDF를 JPG로 변환하는 웹 도구
- `copy.md`
  - 사이트용 카피 초안
- `extracted/`
  - 기존 데스크톱 프로그램 원본 보관
- `공유 프로그램/`
  - 기존 배포용 압축파일 보관

## 웹사이트 파일

실제 웹사이트는 `portal-site` 폴더에 있습니다.

주요 파일:

- `portal-site/index.html`
- `portal-site/pdf-tool.html`
- `portal-site/styles.css`
- `portal-site/scripts/app-data.js`
- `portal-site/scripts/index.js`
- `portal-site/scripts/app.js`
- `portal-site/scripts/pdf-tool.js`

## GitHub 관리 권장 방식

GitHub에는 웹사이트 코드 중심으로 올리고, 대용량 배포본은 제외하는 구성을 권장합니다.

권장 포함:

- `portal-site/`
- `copy.md`
- `README.md`
- `.gitignore`

권장 제외:

- `공유 프로그램/*.zip`
- `extracted/**/*.exe`

## Git 설치 후 기본 명령

```powershell
git init
git add .
git commit -m "Initial portal site"
```

원격 저장소 연결:

```powershell
git branch -M main
git remote add origin <GITHUB_REPOSITORY_URL>
git push -u origin main
```

## GitHub Pages 배포

정적 사이트라서 GitHub Pages로 배포하기 좋습니다.

배포 기준 폴더:

- 저장소 루트에 `portal-site`를 유지하거나
- `portal-site` 내용을 저장소 루트로 올려서 배포

가장 간단한 방법은 `portal-site` 안 파일들을 저장소 루트에 두는 방식입니다.
