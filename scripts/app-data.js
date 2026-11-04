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
    packagePath: "",
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
    status: "웹에서 실행 (서버 변환)",
    summary: "PDF 파일을 변환 서버로 보내 페이지별 JPG로 만들고 ZIP 파일로 내려받을 수 있습니다.",
    description: "PDF 파일을 변환 서버로 업로드해 미리보기와 JPG 변환을 처리하는 웹 도구입니다. 업무 자료나 민감한 자료는 올리지 마세요.",
    detail: "파일 업로드, 페이지 범위 선택, 지우개 편집, ZIP 다운로드를 한 화면에서 처리할 수 있게 구성했습니다.",
    version: "배포본 기준",
    updatedAt: "2026-03-30",
    packagePath: "",
    sourcePath: "../extracted/pdf-jpeg-converter/PDF를 JPEG로 변환.pyw",
    webPath: "./pdf-tool.html",
    highlights: [
      "PDF 파일은 변환 서버로 전송됩니다. 업무 자료나 민감한 자료는 올리지 마세요.",
      "페이지 범위를 지정해 필요한 페이지만 JPG로 저장할 수 있습니다.",
      "지우개로 페이지를 편집한 뒤 JPG 묶음을 ZIP 파일로 내려받을 수 있습니다."
    ],
    nextStep: "우선 이 웹 도구로 변환 흐름을 정착시키고, 사용 의견에 따라 기능을 보완합니다."
  }
];
