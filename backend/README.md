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

## Render 권장값

이 저장소 루트에는 Render용 [`render.yaml`](/D:/황병수(D)/lab/hbs/render.yaml)이 포함되어 있습니다.

직접 입력해서 만들 경우 값은 다음과 같습니다.

- Service Type: `Web Service`
- Runtime: `Python`
- Root Directory: `backend`
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health Check Path: `/health`

환경 변수:

- `PYTHON_VERSION=3.12.10`
- `CORS_ORIGINS=https://simplerun00.github.io`
