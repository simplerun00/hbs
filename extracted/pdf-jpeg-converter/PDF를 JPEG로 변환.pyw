"""
PDF → JPEG 고화질 변환 프로그램 (지우개 편집 기능 포함)
포토샵 없이 고해상도(300 DPI) JPEG 변환

사용법: 더블클릭으로 실행, PDF를 드래그 앤 드롭
"""

import os
import sys
import time
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from datetime import datetime
from PIL import Image, ImageDraw, ImageTk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

import fitz  # PyMuPDF


# ================================================================
# 지우개 편집기 창
# ================================================================
class EraserEditor(tk.Toplevel):
    """PDF 페이지를 미리보고 지우개로 편집하는 창 (회전/확대축소 지원)"""

    @staticmethod
    def _parse_page_range_static(text, total_pages):
        text = text.strip()
        if not text or text == "전체":
            return None
        pages = set()
        for part in text.replace(" ", "").split(","):
            if not part:
                continue
            if "-" in part:
                s, e = part.split("-", 1)
                for p in range(max(1, int(s)), min(total_pages, int(e)) + 1):
                    pages.add(p - 1)
            else:
                p = int(part)
                if 1 <= p <= total_pages:
                    pages.add(p - 1)
        return pages if pages else None

    def __init__(self, master, pdf_files, on_done_callback, page_range_text="전체"):
        super().__init__(master)
        self.title("지우개 편집기")
        self.geometry("1100x800")
        self.resizable(True, True)

        self.pdf_files = pdf_files
        self.on_done = on_done_callback

        # 전체 페이지 목록: [(pdf_path, page_num), ...] — 페이지 범위 적용
        self.pages = []
        for pdf_path in pdf_files:
            doc = fitz.open(pdf_path)
            total = len(doc)
            selected = self._parse_page_range_static(page_range_text, total)
            page_nums = sorted(selected) if selected is not None else range(total)
            for i in page_nums:
                self.pages.append((pdf_path, i))
            doc.close()

        self.current_idx = 0
        self.preview_dpi = 150  # 미리보기 해상도

        # 편집 기록: {(pdf_path, page_num): [edit, ...]}
        self.edits = {}
        # 페이지별 회전 각도 (0, 90, 180, 270)
        self.rotations = {}

        # 확대/축소
        self.zoom_level = 1.0
        self.zoom_min = 0.2
        self.zoom_max = 5.0
        # 팬(스크롤) 오프셋
        self.pan_x = 0
        self.pan_y = 0
        self.panning = False
        self.pan_start = None

        # 현재 도구
        self.tool = "freehand"  # "freehand" | "rect"
        self.eraser_size = 20
        self.drawing = False
        self.freehand_points = []
        self.rect_start = None

        # 현재 페이지 이미지 (PIL, 회전 적용된 원본)
        self.page_image = None
        self.tk_image = None
        self.img_offset_x = 0
        self.img_offset_y = 0
        self.img_display_w = 0
        self.img_display_h = 0
        self._scale = 1.0

        self._build_ui()
        self._load_page()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.grab_set()

    def _build_ui(self):
        # ── 상단 도구 바 ──
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=5, pady=5)

        # 도구 선택
        self.tool_var = tk.StringVar(value="freehand")
        ttk.Label(toolbar, text="도구:").pack(side="left", padx=(0, 5))
        ttk.Radiobutton(toolbar, text="자유 지우개", variable=self.tool_var, value="freehand",
                        command=self._on_tool_change).pack(side="left", padx=2)
        ttk.Radiobutton(toolbar, text="사각형 지우개", variable=self.tool_var, value="rect",
                        command=self._on_tool_change).pack(side="left", padx=2)

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)

        # 지우개 크기
        ttk.Label(toolbar, text="크기:").pack(side="left", padx=(0, 3))
        self.size_var = tk.IntVar(value=20)
        ttk.Scale(toolbar, from_=5, to=100, variable=self.size_var,
                  orient="horizontal", length=100, command=self._on_size_change).pack(side="left")
        self.size_label = ttk.Label(toolbar, text="20px")
        self.size_label.pack(side="left", padx=3)

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)

        # 회전 버튼
        ttk.Button(toolbar, text="↶ 왼쪽 90°", command=lambda: self.rotate_page(-90)).pack(side="left", padx=2)
        ttk.Button(toolbar, text="↷ 오른쪽 90°", command=lambda: self.rotate_page(90)).pack(side="left", padx=2)

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)

        # 확대/축소
        ttk.Button(toolbar, text="−", width=3, command=lambda: self._zoom_step(-0.2)).pack(side="left", padx=1)
        self.zoom_label = ttk.Label(toolbar, text="100%", width=6, anchor="center")
        self.zoom_label.pack(side="left")
        ttk.Button(toolbar, text="+", width=3, command=lambda: self._zoom_step(0.2)).pack(side="left", padx=1)
        ttk.Button(toolbar, text="맞춤", command=self.zoom_fit).pack(side="left", padx=3)

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)

        # 되돌리기
        ttk.Button(toolbar, text="되돌리기", command=self.undo).pack(side="left", padx=2)
        ttk.Button(toolbar, text="초기화", command=self.reset_page).pack(side="left", padx=2)

        # ── 캔버스 (스크롤 지원) ──
        canvas_frame = ttk.Frame(self)
        canvas_frame.pack(fill="both", expand=True, padx=5)

        self.canvas = tk.Canvas(canvas_frame, bg="#606060", cursor="circle")
        self.canvas.pack(fill="both", expand=True)

        # 캔버스에 마우스 올리면 포커스 (휠 이벤트 받으려면 필수)
        self.canvas.bind("<Enter>", lambda e: self.canvas.focus_set())

        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        # Ctrl+휠 = 확대축소, 휠만 = 상하 스크롤, Shift+휠 = 좌우 스크롤
        self.canvas.bind("<Control-MouseWheel>", self._on_ctrl_wheel)
        self.canvas.bind("<MouseWheel>", self._on_wheel_scroll)
        self.canvas.bind("<Shift-MouseWheel>", self._on_shift_wheel)
        self.canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self.canvas.bind("<B2-Motion>", self._on_pan_move)
        self.canvas.bind("<ButtonRelease-2>", self._on_pan_end)
        # 오른쪽 클릭으로도 팬 (가운데 버튼 없는 마우스)
        self.canvas.bind("<ButtonPress-3>", self._on_pan_start)
        self.canvas.bind("<B3-Motion>", self._on_pan_move)
        self.canvas.bind("<ButtonRelease-3>", self._on_pan_end)

        # ── 하단 네비게이션 ──
        nav = ttk.Frame(self)
        nav.pack(fill="x", padx=5, pady=5)

        ttk.Button(nav, text="< 이전", command=self.prev_page).pack(side="left", padx=2)
        self.page_label = ttk.Label(nav, text="1 / 1")
        self.page_label.pack(side="left", padx=10)
        ttk.Button(nav, text="다음 >", command=self.next_page).pack(side="left", padx=2)

        self.file_label = ttk.Label(nav, text="", foreground="gray")
        self.file_label.pack(side="left", padx=15)

        self.rotate_info = ttk.Label(nav, text="", foreground="#1a73e8")
        self.rotate_info.pack(side="left", padx=10)

        ttk.Button(nav, text="편집 완료 → 변환", command=self._on_done_click).pack(side="right", padx=2)
        ttk.Button(nav, text="편집 취소", command=self._on_close).pack(side="right", padx=2)

        # 단축키
        self.bind("<Control-z>", lambda e: self.undo())
        self.bind("<Left>", lambda e: self.prev_page())
        self.bind("<Right>", lambda e: self.next_page())
        self.bind("<Control-plus>", lambda e: self._zoom_step(0.2))
        self.bind("<Control-equal>", lambda e: self._zoom_step(0.2))
        self.bind("<Control-minus>", lambda e: self._zoom_step(-0.2))
        self.bind("<Control-0>", lambda e: self.zoom_fit())

    def _on_tool_change(self):
        self.tool = self.tool_var.get()
        self.canvas.config(cursor="crosshair" if self.tool == "rect" else "circle")

    def _on_size_change(self, val):
        self.eraser_size = int(float(val))
        self.size_label.config(text=f"{self.eraser_size}px")

    # ── 회전 ──────────────────────────────────────
    def rotate_page(self, degrees):
        key = self.pages[self.current_idx]
        cur = self.rotations.get(key, 0)
        self.rotations[key] = (cur + degrees) % 360
        self.zoom_level = 1.0  # 회전 시 줌 리셋
        self.pan_x = 0
        self.pan_y = 0
        self._load_page()

    def _get_rotation(self):
        key = self.pages[self.current_idx]
        return self.rotations.get(key, 0)

    # ── 확대/축소 ─────────────────────────────────
    def _zoom_step(self, delta):
        old_zoom = self.zoom_level
        self.zoom_level = max(self.zoom_min, min(self.zoom_max, self.zoom_level + delta))
        if self.zoom_level != old_zoom:
            self._update_display()

    def _on_ctrl_wheel(self, event):
        # Ctrl + 마우스 휠 = 확대/축소 (마우스 위치 기준)
        old_zoom = self.zoom_level
        if event.delta > 0:
            self.zoom_level = min(self.zoom_max, self.zoom_level * 1.15)
        else:
            self.zoom_level = max(self.zoom_min, self.zoom_level / 1.15)

        if self.zoom_level != old_zoom and self.page_image:
            # 마우스 위치 기준으로 팬 조정
            mx, my = event.x, event.y
            ratio = self.zoom_level / old_zoom
            self.pan_x = mx - ratio * (mx - self.pan_x)
            self.pan_y = my - ratio * (my - self.pan_y)
            self._update_display()
        return "break"

    def _on_wheel_scroll(self, event):
        # 일반 휠 = 세로 스크롤
        scroll = int(event.delta / 120) * 60
        self.pan_y += scroll
        self._update_display()
        return "break"

    def _on_shift_wheel(self, event):
        # Shift+휠 = 가로 스크롤
        scroll = int(event.delta / 120) * 60
        self.pan_x += scroll
        self._update_display()
        return "break"

    def zoom_fit(self):
        self.zoom_level = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self._update_display()

    # ── 팬 (드래그 스크롤) ─────────────────────────
    def _on_pan_start(self, event):
        self.panning = True
        self.pan_start = (event.x, event.y)
        self.canvas.config(cursor="fleur")

    def _on_pan_move(self, event):
        if self.panning and self.pan_start:
            dx = event.x - self.pan_start[0]
            dy = event.y - self.pan_start[1]
            self.pan_x += dx
            self.pan_y += dy
            self.pan_start = (event.x, event.y)
            self._update_display()

    def _on_pan_end(self, event):
        self.panning = False
        self.pan_start = None
        self._on_tool_change()  # 커서 복원

    # ── 페이지 로드 / 표시 ───────────────────────────
    def _load_page(self):
        if not self.pages:
            return
        pdf_path, page_num = self.pages[self.current_idx]
        rot = self._get_rotation()

        doc = fitz.open(pdf_path)
        page = doc[page_num]
        zoom = self.preview_dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        if rot:
            mat = mat.prerotate(rot)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        doc.close()

        self.page_image = img.copy()

        # 기존 편집 적용
        key = (pdf_path, page_num)
        if key in self.edits:
            self._apply_edits_to_image(self.page_image, self.edits[key])

        self._update_display()
        self._update_nav_labels()

    def _apply_edits_to_image(self, img, edits):
        draw = ImageDraw.Draw(img)
        w, h = img.size
        for ed in edits:
            if ed["type"] == "rect":
                x1 = int(ed["x1"] * w)
                y1 = int(ed["y1"] * h)
                x2 = int(ed["x2"] * w)
                y2 = int(ed["y2"] * h)
                draw.rectangle([x1, y1, x2, y2], fill="white")
            elif ed["type"] == "freehand":
                pts = [(int(px * w), int(py * h)) for px, py in ed["points"]]
                line_w = max(1, int(ed["width"] * w))
                if len(pts) >= 2:
                    draw.line(pts, fill="white", width=line_w, joint="curve")
                r = line_w // 2
                for px, py in pts:
                    draw.ellipse([px - r, py - r, px + r, py + r], fill="white")

    def _update_display(self):
        if self.page_image is None:
            return

        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 10 or ch < 10:
            return

        iw, ih = self.page_image.size

        # 기본 스케일: 캔버스에 맞추기
        base_scale = min(cw / iw, ch / ih)
        scale = base_scale * self.zoom_level
        new_w = max(1, int(iw * scale))
        new_h = max(1, int(ih * scale))

        # 기본 중앙 위치 + 팬 오프셋
        base_x = (cw - new_w) // 2
        base_y = (ch - new_h) // 2
        self.img_offset_x = base_x + int(self.pan_x)
        self.img_offset_y = base_y + int(self.pan_y)
        self.img_display_w = new_w
        self.img_display_h = new_h
        self._scale = scale

        display = self.page_image.resize((new_w, new_h), Image.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(display)

        self.canvas.delete("all")
        self.canvas.create_image(self.img_offset_x, self.img_offset_y,
                                 anchor="nw", image=self.tk_image, tags="img")

        # 줌 레벨 표시
        self.zoom_label.config(text=f"{int(self.zoom_level * 100)}%")

    def _on_canvas_resize(self, event):
        self._update_display()

    def _update_nav_labels(self):
        total = len(self.pages)
        self.page_label.config(text=f"{self.current_idx + 1} / {total}")
        pdf_path, page_num = self.pages[self.current_idx]
        self.file_label.config(text=f"{os.path.basename(pdf_path)} - {page_num + 1}페이지")
        rot = self._get_rotation()
        self.rotate_info.config(text=f"회전: {rot}°" if rot else "")

    # ── 좌표 변환 ──────────────────────────────────
    def _canvas_to_norm(self, cx, cy):
        nx = (cx - self.img_offset_x) / self.img_display_w if self.img_display_w else 0
        ny = (cy - self.img_offset_y) / self.img_display_h if self.img_display_h else 0
        return max(0, min(1, nx)), max(0, min(1, ny))

    # ── 마우스 이벤트 (지우개) ──────────────────────
    def _on_mouse_down(self, event):
        if self.panning:
            return
        self.drawing = True
        if self.tool == "freehand":
            self.freehand_points = [(event.x, event.y)]
        elif self.tool == "rect":
            self.rect_start = (event.x, event.y)

    def _on_mouse_move(self, event):
        if not self.drawing or self.panning:
            return

        if self.tool == "freehand":
            self.freehand_points.append((event.x, event.y))
            if len(self.freehand_points) >= 2:
                x1, y1 = self.freehand_points[-2]
                x2, y2 = self.freehand_points[-1]
                size = max(1, int(self.eraser_size * self._scale))
                self.canvas.create_line(x1, y1, x2, y2, fill="white", width=size,
                                        capstyle="round", tags="preview")
        elif self.tool == "rect":
            self.canvas.delete("rect_preview")
            if self.rect_start:
                self.canvas.create_rectangle(
                    self.rect_start[0], self.rect_start[1], event.x, event.y,
                    outline="#ff0000", width=2, dash=(4, 4), tags="rect_preview"
                )

    def _on_mouse_up(self, event):
        if not self.drawing or self.panning:
            return
        self.drawing = False

        key = self.pages[self.current_idx]
        if key not in self.edits:
            self.edits[key] = []

        if self.tool == "freehand" and len(self.freehand_points) >= 2:
            norm_pts = [self._canvas_to_norm(x, y) for x, y in self.freehand_points]
            norm_width = self.eraser_size / self.page_image.size[0] if self.page_image else 0.02
            self.edits[key].append({
                "type": "freehand",
                "points": norm_pts,
                "width": norm_width,
            })
            self._apply_last_edit()
            self.freehand_points = []

        elif self.tool == "rect" and self.rect_start:
            nx1, ny1 = self._canvas_to_norm(self.rect_start[0], self.rect_start[1])
            nx2, ny2 = self._canvas_to_norm(event.x, event.y)
            x1, x2 = min(nx1, nx2), max(nx1, nx2)
            y1, y2 = min(ny1, ny2), max(ny1, ny2)
            self.edits[key].append({
                "type": "rect",
                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            })
            self._apply_last_edit()
            self.rect_start = None
            self.canvas.delete("rect_preview")

    def _apply_last_edit(self):
        key = self.pages[self.current_idx]
        edits = self.edits.get(key, [])
        if edits:
            self._apply_edits_to_image(self.page_image, [edits[-1]])
        self._update_display()

    # ── 되돌리기 / 초기화 ──────────────────────────
    def undo(self):
        key = self.pages[self.current_idx]
        edits = self.edits.get(key, [])
        if edits:
            edits.pop()
            self._reload_and_apply()

    def reset_page(self):
        key = self.pages[self.current_idx]
        self.edits.pop(key, None)
        self.rotations.pop(key, None)
        self._reload_and_apply()

    def _reload_and_apply(self):
        pdf_path, page_num = self.pages[self.current_idx]
        rot = self._get_rotation()
        doc = fitz.open(pdf_path)
        page = doc[page_num]
        zoom = self.preview_dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        if rot:
            mat = mat.prerotate(rot)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        doc.close()

        self.page_image = img
        key = (pdf_path, page_num)
        if key in self.edits and self.edits[key]:
            self._apply_edits_to_image(self.page_image, self.edits[key])

        self._update_display()

    # ── 페이지 이동 ──────────────────────────────
    def prev_page(self):
        if self.current_idx > 0:
            self.current_idx -= 1
            self.zoom_level = 1.0
            self.pan_x = 0
            self.pan_y = 0
            self._load_page()

    def next_page(self):
        if self.current_idx < len(self.pages) - 1:
            self.current_idx += 1
            self.zoom_level = 1.0
            self.pan_x = 0
            self.pan_y = 0
            self._load_page()

    # ── 완료 / 취소 ─────────────────────────────
    def _on_done_click(self):
        self.grab_release()
        self.destroy()
        self.on_done(self.edits, self.rotations)

    def _on_close(self):
        self.grab_release()
        self.destroy()


# ================================================================
# 메인 앱
# ================================================================
class PDFtoJPEGApp:
    def __init__(self, root):
        self.root = root
        self.root.title("PDF → JPEG 변환")
        self.root.geometry("650x750")
        self.root.resizable(False, False)

        self.pdf_files = []
        self.is_running = False
        self.pending_edits = {}  # 편집 데이터
        self.pending_rotations = {}  # 페이지별 회전

        self._build_ui()
        self.log("프로그램 시작")
        self.log(f"PyMuPDF {fitz.version[0]} / Python {sys.version.split()[0]}")
        if HAS_DND:
            self.log("드래그 앤 드롭 지원됨")
        else:
            self.log("[경고] tkinterdnd2 없음 - 드래그 앤 드롭 비활성")

    def _build_ui(self):
        # 드래그 앤 드롭 영역
        self.drop_frame = tk.Frame(
            self.root, bg="#e8f0fe", relief="groove", bd=2, cursor="hand2"
        )
        self.drop_frame.pack(fill="x", padx=10, pady=(10, 5), ipady=20)

        self.drop_label = tk.Label(
            self.drop_frame,
            text="PDF 파일을 여기에 드래그 & 드롭\n또는 클릭하여 파일 선택",
            bg="#e8f0fe", fg="#1a73e8",
            font=("맑은 고딕", 12, "bold"),
        )
        self.drop_label.pack(expand=True)

        self.drop_frame.bind("<Button-1>", lambda e: self.add_files())
        self.drop_label.bind("<Button-1>", lambda e: self.add_files())

        if HAS_DND:
            self.drop_frame.drop_target_register(DND_FILES)
            self.drop_frame.dnd_bind("<<Drop>>", self._on_drop)
            self.drop_frame.dnd_bind("<<DragEnter>>", self._on_drag_enter)
            self.drop_frame.dnd_bind("<<DragLeave>>", self._on_drag_leave)
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)

        # 파일 목록
        frame_list = ttk.LabelFrame(self.root, text="변환할 파일 목록", padding=5)
        frame_list.pack(fill="x", padx=10, pady=(0, 5))

        list_inner = ttk.Frame(frame_list)
        list_inner.pack(fill="x")

        self.file_listbox = tk.Listbox(list_inner, height=5, selectmode=tk.EXTENDED)
        scrollbar = ttk.Scrollbar(list_inner, orient="vertical", command=self.file_listbox.yview)
        self.file_listbox.config(yscrollcommand=scrollbar.set)
        self.file_listbox.pack(side="left", fill="x", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.file_count_var = tk.StringVar(value="0개 파일")
        btn_frame = ttk.Frame(frame_list)
        btn_frame.pack(fill="x", pady=(5, 0))
        ttk.Label(btn_frame, textvariable=self.file_count_var, foreground="gray").pack(side="left")
        ttk.Button(btn_frame, text="선택 삭제", command=self.remove_selected).pack(side="right", padx=(5, 0))
        ttk.Button(btn_frame, text="전체 비우기", command=self.clear_files).pack(side="right", padx=(5, 0))
        ttk.Button(btn_frame, text="폴더 추가", command=self.add_folder).pack(side="right")

        # 설정 영역
        frame_settings = ttk.LabelFrame(self.root, text="설정", padding=10)
        frame_settings.pack(fill="x", padx=10, pady=5)

        row1 = ttk.Frame(frame_settings)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="해상도 (DPI):").pack(side="left")
        self.dpi_var = tk.StringVar(value="300")
        ttk.Combobox(row1, textvariable=self.dpi_var, values=["150", "200", "300", "400", "600"], width=8).pack(side="left", padx=(5, 20))
        ttk.Label(row1, text="JPEG 품질 (1~100):").pack(side="left")
        self.quality_var = tk.StringVar(value="95")
        ttk.Combobox(row1, textvariable=self.quality_var, values=["80", "85", "90", "95", "100"], width=8).pack(side="left", padx=5)

        row_pages = ttk.Frame(frame_settings)
        row_pages.pack(fill="x", pady=2)
        ttk.Label(row_pages, text="페이지:").pack(side="left")
        self.pages_var = tk.StringVar(value="전체")
        pages_entry = ttk.Entry(row_pages, textvariable=self.pages_var, width=25)
        pages_entry.pack(side="left", padx=5)
        ttk.Label(row_pages, text="예: 전체, 1-5, 3, 8-10", foreground="gray").pack(side="left")

        row_orient = ttk.Frame(frame_settings)
        row_orient.pack(fill="x", pady=2)
        ttk.Label(row_orient, text="방향:").pack(side="left")
        self.orient_var = tk.StringVar(value="auto")
        ttk.Radiobutton(row_orient, text="원본 유지", variable=self.orient_var, value="auto").pack(side="left", padx=5)
        ttk.Radiobutton(row_orient, text="세로 (Portrait)", variable=self.orient_var, value="portrait").pack(side="left", padx=5)
        ttk.Radiobutton(row_orient, text="가로 (Landscape)", variable=self.orient_var, value="landscape").pack(side="left", padx=5)

        row2 = ttk.Frame(frame_settings)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="저장 위치:").pack(side="left")
        self.save_mode_var = tk.StringVar(value="same")
        ttk.Radiobutton(row2, text="PDF와 같은 폴더", variable=self.save_mode_var, value="same").pack(side="left", padx=5)
        ttk.Radiobutton(row2, text="직접 지정", variable=self.save_mode_var, value="custom").pack(side="left", padx=5)

        row3 = ttk.Frame(frame_settings)
        row3.pack(fill="x", pady=2)
        self.custom_path_var = tk.StringVar()
        self.custom_path_entry = ttk.Entry(row3, textvariable=self.custom_path_var, state="disabled")
        self.custom_path_entry.pack(side="left", fill="x", expand=True)
        self.custom_path_btn = ttk.Button(row3, text="찾아보기", command=self.select_output_folder, state="disabled")
        self.custom_path_btn.pack(side="left", padx=(5, 0))
        self.save_mode_var.trace_add("write", self._on_save_mode_change)

        # 진행 상황
        frame_progress = ttk.LabelFrame(self.root, text="진행 상황", padding=10)
        frame_progress.pack(fill="x", padx=10, pady=5)

        self.progress_var = tk.DoubleVar()
        self.progressbar = ttk.Progressbar(frame_progress, variable=self.progress_var, maximum=100)
        self.progressbar.pack(fill="x")

        self.status_var = tk.StringVar(value="대기 중 - PDF 파일을 드래그하세요")
        ttk.Label(frame_progress, textvariable=self.status_var).pack(anchor="w", pady=(5, 0))

        # 실행 버튼
        btn_row = ttk.Frame(self.root)
        btn_row.pack(pady=8)
        self.run_btn = ttk.Button(btn_row, text="바로 변환", command=self.start_conversion)
        self.run_btn.pack(side="left", padx=5)
        self.edit_btn = ttk.Button(btn_row, text="지우개 편집 후 변환", command=self.open_editor)
        self.edit_btn.pack(side="left", padx=5)

        # 로그 영역
        frame_log = ttk.LabelFrame(self.root, text="로그", padding=5)
        frame_log.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        log_inner = ttk.Frame(frame_log)
        log_inner.pack(fill="both", expand=True)

        self.log_text = tk.Text(
            log_inner, height=7, wrap="word",
            font=("Consolas", 9), bg="#1e1e1e", fg="#cccccc",
            insertbackground="#cccccc", selectbackground="#264f78",
            state="disabled",
        )
        log_scroll = ttk.Scrollbar(log_inner, orient="vertical", command=self.log_text.yview)
        self.log_text.config(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        self.log_text.tag_configure("time", foreground="#6a9955")
        self.log_text.tag_configure("error", foreground="#f44747")
        self.log_text.tag_configure("success", foreground="#4ec9b0")
        self.log_text.tag_configure("info", foreground="#cccccc")

    # ── 로그 ──────────────────────────────────────────
    def log(self, msg, level="info"):
        def _do():
            self.log_text.config(state="normal")
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log_text.insert(tk.END, f"[{timestamp}] ", "time")
            self.log_text.insert(tk.END, f"{msg}\n", level)
            self.log_text.see(tk.END)
            self.log_text.config(state="disabled")
        if threading.current_thread() is threading.main_thread():
            _do()
        else:
            self.root.after(0, _do)

    # ── 드래그 앤 드롭 ──────────────────────────────────
    def _parse_drop_data(self, data):
        files = []
        i = 0
        while i < len(data):
            if data[i] == '{':
                end = data.index('}', i)
                files.append(data[i + 1:end])
                i = end + 2
            elif data[i] == ' ':
                i += 1
            else:
                end = data.find(' ', i)
                if end == -1:
                    end = len(data)
                files.append(data[i:end])
                i = end + 1
        return files

    def _on_drop(self, event):
        paths = self._parse_drop_data(event.data)
        self.log(f"드롭 감지: {len(paths)}개 항목")
        added = 0
        for path in paths:
            path = path.strip()
            if os.path.isdir(path):
                self.log(f"  폴더: {os.path.basename(path)}")
                for name in sorted(os.listdir(path)):
                    if name.lower().endswith(".pdf"):
                        full = os.path.join(path, name)
                        if full not in self.pdf_files:
                            self.pdf_files.append(full)
                            self.file_listbox.insert(tk.END, os.path.basename(full))
                            added += 1
            elif path.lower().endswith(".pdf") and path not in self.pdf_files:
                self.pdf_files.append(path)
                self.file_listbox.insert(tk.END, os.path.basename(path))
                self.log(f"  추가: {os.path.basename(path)}")
                added += 1
            elif not path.lower().endswith(".pdf"):
                self.log(f"  건너뜀 (PDF 아님): {os.path.basename(path)}", "error")

        self._update_file_count()
        self.drop_frame.config(bg="#e8f0fe")
        self.drop_label.config(bg="#e8f0fe")

        if added > 0:
            self.log(f"{added}개 PDF 추가됨", "success")
        elif paths:
            self.status_var.set("PDF 파일만 추가할 수 있습니다")

    def _on_drag_enter(self, event):
        self.drop_frame.config(bg="#c6dafb")
        self.drop_label.config(bg="#c6dafb")

    def _on_drag_leave(self, event):
        self.drop_frame.config(bg="#e8f0fe")
        self.drop_label.config(bg="#e8f0fe")

    # ── 파일 관리 ──────────────────────────────────────
    def add_files(self):
        files = filedialog.askopenfilenames(title="PDF 파일 선택", filetypes=[("PDF 파일", "*.pdf")])
        for f in files:
            if f not in self.pdf_files:
                self.pdf_files.append(f)
                self.file_listbox.insert(tk.END, os.path.basename(f))
                self.log(f"추가: {os.path.basename(f)}")
        self._update_file_count()

    def add_folder(self):
        folder = filedialog.askdirectory(title="PDF 파일이 있는 폴더 선택")
        if not folder:
            return
        count = 0
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith(".pdf"):
                full = os.path.join(folder, name)
                if full not in self.pdf_files:
                    self.pdf_files.append(full)
                    self.file_listbox.insert(tk.END, name)
                    count += 1
        self.log(f"폴더에서 {count}개 PDF 추가: {os.path.basename(folder)}")
        self._update_file_count()

    def remove_selected(self):
        selected = list(self.file_listbox.curselection())
        for idx in reversed(selected):
            name = self.file_listbox.get(idx)
            self.file_listbox.delete(idx)
            del self.pdf_files[idx]
            self.log(f"제거: {name}")
        self._update_file_count()

    def clear_files(self):
        count = len(self.pdf_files)
        self.pdf_files.clear()
        self.file_listbox.delete(0, tk.END)
        self._update_file_count()
        self.pending_edits = {}
        self.pending_rotations = {}
        if count:
            self.log(f"목록 비움 ({count}개)")

    def _update_file_count(self):
        self.file_count_var.set(f"{len(self.pdf_files)}개 파일")

    def _parse_page_range(self, text, total_pages):
        """페이지 범위 문자열 파싱. '전체' 또는 '1-5, 8, 10-12' 형태.
        Returns: 0-based 페이지 인덱스 set, None이면 전체"""
        text = text.strip()
        if not text or text == "전체":
            return None  # 전체

        pages = set()
        for part in text.replace(" ", "").split(","):
            if not part:
                continue
            if "-" in part:
                start, end = part.split("-", 1)
                s = max(1, int(start))
                e = min(total_pages, int(end))
                for p in range(s, e + 1):
                    pages.add(p - 1)  # 0-based
            else:
                p = int(part)
                if 1 <= p <= total_pages:
                    pages.add(p - 1)
        return pages if pages else None

    def _on_save_mode_change(self, *_):
        if self.save_mode_var.get() == "custom":
            self.custom_path_entry.config(state="normal")
            self.custom_path_btn.config(state="normal")
        else:
            self.custom_path_entry.config(state="disabled")
            self.custom_path_btn.config(state="disabled")

    def select_output_folder(self):
        folder = filedialog.askdirectory(title="저장할 폴더 선택")
        if folder:
            self.custom_path_var.set(folder)
            self.log(f"저장 폴더: {folder}")

    # ── 편집기 열기 ───────────────────────────────────
    def open_editor(self):
        if not self.pdf_files:
            messagebox.showwarning("알림", "PDF 파일을 먼저 추가해주세요.")
            return
        if self.is_running:
            return

        self.log("지우개 편집기 열기")
        EraserEditor(self.root, list(self.pdf_files), self._on_editor_done, self.pages_var.get())

    def _on_editor_done(self, edits, rotations):
        self.pending_edits = edits
        self.pending_rotations = rotations
        edit_count = sum(len(v) for v in edits.values())
        rot_count = sum(1 for v in rotations.values() if v != 0)
        self.log(f"편집 완료: {edit_count}개 지우개, {rot_count}개 회전", "success")
        self.start_conversion()

    # ── 변환 ──────────────────────────────────────────
    def start_conversion(self):
        if self.is_running:
            return
        if not self.pdf_files:
            messagebox.showwarning("알림", "PDF 파일을 추가해주세요.")
            return

        dpi = int(self.dpi_var.get())
        quality = int(self.quality_var.get())
        save_mode = self.save_mode_var.get()
        custom_path = self.custom_path_var.get()
        orient = self.orient_var.get()
        page_range_text = self.pages_var.get()

        if save_mode == "custom" and not custom_path:
            messagebox.showwarning("알림", "저장 폴더를 지정해주세요.")
            return

        self.is_running = True
        self.run_btn.config(state="disabled")
        self.edit_btn.config(state="disabled")
        orient_label = {"auto": "원본", "portrait": "세로", "landscape": "가로"}[orient]
        pages_label = page_range_text if page_range_text.strip() and page_range_text.strip() != "전체" else "전체"
        self.log(f"변환 시작 (DPI={dpi}, 품질={quality}, 방향={orient_label}, 페이지={pages_label})")

        edits = dict(self.pending_edits)
        rotations = dict(self.pending_rotations)

        thread = threading.Thread(
            target=self._convert_all,
            args=(list(self.pdf_files), dpi, quality, save_mode, custom_path, orient, edits, rotations, page_range_text),
            daemon=True,
        )
        thread.start()

    def _convert_all(self, pdf_files, dpi, quality, save_mode, custom_path, orient, edits, rotations, page_range_text):
        start_time = time.time()

        total_pages = 0
        file_pages = []
        for pdf_path in pdf_files:
            try:
                doc = fitz.open(pdf_path)
                n = len(doc)
                selected = self._parse_page_range(page_range_text, n)
                count = len(selected) if selected is not None else n
                file_pages.append((n, selected))
                total_pages += count
                doc.close()
            except Exception:
                file_pages.append((0, None))

        self.log(f"총 {len(pdf_files)}개 파일, {total_pages}페이지")

        done_pages = 0
        success_files = 0
        fail_list = []

        for idx, pdf_path in enumerate(pdf_files):
            basename = os.path.splitext(os.path.basename(pdf_path))[0]
            self._update_status(f"변환 중: {os.path.basename(pdf_path)} ({idx + 1}/{len(pdf_files)})")

            if save_mode == "same":
                out_dir = os.path.dirname(pdf_path)
            else:
                out_dir = custom_path

            os.makedirs(out_dir, exist_ok=True)

            try:
                doc = fitz.open(pdf_path)
                num_pages = len(doc)
                _, selected_pages = file_pages[idx]
                pad = len(str(num_pages))

                zoom = dpi / 72.0

                target_pages = sorted(selected_pages) if selected_pages is not None else range(num_pages)
                self.log(f"[{idx+1}/{len(pdf_files)}] {os.path.basename(pdf_path)} ({len(target_pages)}/{num_pages}p)")

                for page_num in target_pages:
                    page = doc[page_num]
                    rect = page.rect
                    w, h = rect.width, rect.height

                    # 편집기 회전 우선, 없으면 설정 패널 방향 적용
                    editor_rot = rotations.get((pdf_path, page_num), 0)
                    if editor_rot:
                        rotation = editor_rot
                    elif orient == "landscape" and h > w:
                        rotation = 90
                    elif orient == "portrait" and w > h:
                        rotation = 90
                    else:
                        rotation = 0

                    matrix = fitz.Matrix(zoom, zoom)
                    if rotation:
                        matrix = matrix.prerotate(rotation)

                    pix = page.get_pixmap(matrix=matrix, alpha=False)

                    page_str = str(page_num + 1).zfill(pad)
                    out_file = os.path.join(out_dir, f"{basename}_{page_str}.jpg")

                    # 편집 적용 여부 확인
                    page_edits = edits.get((pdf_path, page_num), [])
                    if page_edits:
                        # PIL로 편집 적용 후 저장
                        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                        draw = ImageDraw.Draw(img)
                        iw, ih = img.size
                        for ed in page_edits:
                            if ed["type"] == "rect":
                                x1 = int(ed["x1"] * iw)
                                y1 = int(ed["y1"] * ih)
                                x2 = int(ed["x2"] * iw)
                                y2 = int(ed["y2"] * ih)
                                draw.rectangle([x1, y1, x2, y2], fill="white")
                            elif ed["type"] == "freehand":
                                pts = [(int(px * iw), int(py * ih)) for px, py in ed["points"]]
                                line_w = max(1, int(ed["width"] * iw))
                                if len(pts) >= 2:
                                    draw.line(pts, fill="white", width=line_w, joint="curve")
                                r = line_w // 2
                                for px, py in pts:
                                    draw.ellipse([px - r, py - r, px + r, py + r], fill="white")
                        img.save(out_file, "JPEG", quality=quality, subsampling=0)
                        self.log(f"  p{page_num+1} -> {basename}_{page_str}.jpg (편집 적용)")
                    else:
                        pix.save(out_file, jpg_quality=quality)
                        size_kb = os.path.getsize(out_file) / 1024
                        self.log(f"  p{page_num+1} -> {basename}_{page_str}.jpg ({size_kb:.0f}KB)")

                    done_pages += 1
                    pct = (done_pages / total_pages) * 100 if total_pages else 0
                    self._update_progress(pct)

                doc.close()
                success_files += 1
                self.log(f"  완료 -> {out_dir}", "success")

            except Exception as e:
                err_msg = f"{os.path.basename(pdf_path)}: {e}"
                fail_list.append(err_msg)
                self.log(f"  실패: {e}", "error")
                self.log(traceback.format_exc(), "error")
                n, sel = file_pages[idx]
                done_pages += len(sel) if sel is not None else n

        elapsed = time.time() - start_time
        self.is_running = False
        self.pending_edits = {}
        self.pending_rotations = {}

        self.log(f"전체 완료: {success_files}개 성공, {len(fail_list)}개 실패 ({elapsed:.1f}초)", "success")

        msg = f"변환 완료! 성공: {success_files}개 ({elapsed:.1f}초)"
        if fail_list:
            msg += f", 실패: {len(fail_list)}개\n\n실패 목록:\n" + "\n".join(fail_list)
        self._finish(msg)

    def _update_status(self, text):
        self.root.after(0, lambda: self.status_var.set(text))

    def _update_progress(self, pct):
        self.root.after(0, lambda: self.progress_var.set(pct))

    def _finish(self, msg):
        def _do():
            self.status_var.set("완료")
            self.progress_var.set(100)
            self.run_btn.config(state="normal")
            self.edit_btn.config(state="normal")
            messagebox.showinfo("결과", msg)
        self.root.after(0, _do)


if __name__ == "__main__":
    try:
        if HAS_DND:
            root = TkinterDnD.Tk()
        else:
            root = tk.Tk()
        app = PDFtoJPEGApp(root)
        root.mainloop()
    except Exception:
        err_path = os.path.join(os.path.dirname(__file__), "에러로그.txt")
        with open(err_path, "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        messagebox.showerror("오류", f"프로그램 오류 발생\n에러 로그: {err_path}")
