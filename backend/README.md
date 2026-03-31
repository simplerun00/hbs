# PDF Converter Backend

GitHub Pages에서 동작하는 프론트엔드가 호출할 PDF 변환 API입니다.

## 실행

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

기본 주소:

- `http://127.0.0.1:8000`
- 상태 확인: `GET /health`
- 변환 API: `POST /api/pdf/convert`

## CORS

허용할 사이트 주소를 환경 변수로 지정할 수 있습니다.

```bash
set CORS_ORIGINS=https://simplerun00.github.io,http://127.0.0.1:5500
```

설정하지 않으면 모든 출처를 허용합니다.

## 배포 메모

- GitHub Pages에는 백엔드를 올릴 수 없습니다.
- Render, Railway, Fly.io 같은 별도 서비스에 `backend/`를 배포하면 됩니다.
- 배포 후 프론트엔드의 백엔드 주소 입력란에 API 주소를 넣으면 됩니다.
