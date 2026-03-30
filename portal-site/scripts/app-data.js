window.APP_DATA = [
  {
    id: "terrain-analyzer",
    name: "표고경사 분석기",
    category: "분석",
    status: "배포본 준비 완료",
    summary: "등고선, 경계, 필지 데이터를 이용해 표고와 경사를 분석하는 도구입니다.",
    description: "현재는 데스크톱 실행 파일 기반으로 공유하고 있으며, Python 원본이 확보되어 있어 기능 단위로 웹 전환을 검토할 수 있습니다.",
    detail: "대용량 공간 데이터와 좌표계 변환, 시각화 로직이 함께 들어 있어 브라우저형으로 옮길 때는 입력 검증, 계산 엔진 분리, 결과 미리보기 단계를 나눠서 진행하는 것이 안전합니다.",
    version: "v4 계열",
    updatedAt: "2026-03-30",
    packagePath: "../공유 프로그램/표고경사분석기.zip",
    sourcePath: "../extracted/terrain-analyzer/terrain_analyzer.py",
    webPath: "",
    highlights: [
      "Python 원본과 실행 파일이 함께 준비되어 있습니다.",
      "좌표계 변환, SHP/DXF 처리, 경사 계산 로직이 포함되어 있습니다.",
      "웹 전환 시 가장 먼저 입력 파일 검증과 결과 시각화 분리가 필요합니다."
    ],
    nextStep: "포털에서는 우선 다운로드와 사용 가이드를 제공하고, 이후 핵심 계산 기능을 단계별로 브라우저로 이전합니다."
  },
  {
    id: "pdf-jpeg-converter",
    name: "PDF 이미지 변환기",
    category: "웹 변환",
    status: "브라우저에서 바로 실행",
    summary: "PDF 파일을 브라우저에서 바로 불러와 페이지별 JPEG 이미지로 변환하고 다운로드할 수 있습니다.",
    description: "서버 업로드 없이 사용자의 브라우저 안에서 PDF를 렌더링하고 JPG로 저장하는 웹 도구입니다.",
    detail: "파일 업로드, 페이지 범위 선택, 미리보기, 개별 다운로드, 전체 다운로드를 한 화면에서 처리할 수 있게 구성했습니다.",
    version: "배포본 기준",
    updatedAt: "2026-03-30",
    packagePath: "../공유 프로그램/PDF_JPEG변환기.zip",
    sourcePath: "../extracted/pdf-jpeg-converter/PDF를 JPEG로 변환.pyw",
    webPath: "./pdf-tool.html",
    highlights: [
      "PDF 파일은 브라우저에서만 처리되고 별도 업로드 서버가 필요하지 않습니다.",
      "페이지 범위를 지정해 필요한 페이지만 JPG로 저장할 수 있습니다.",
      "미리보기 후 개별 다운로드 또는 전체 일괄 다운로드가 가능합니다."
    ],
    nextStep: "우선 이 웹 도구로 변환 흐름을 정착시키고, 이후 편집 기능이나 ZIP 다운로드를 추가할 수 있습니다."
  }
];
