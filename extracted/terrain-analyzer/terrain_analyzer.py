# -*- coding: utf-8 -*-
"""
표고·경사 분석 자동화 도구 v4
- 입력1: 지적도 SHP (토지특성정보 → 지적선 배경)
- 입력2: 수치지형도 SHP (등고선 → 표고 데이터)
- 입력3: 구역계 (SHP/이미지 → 분석 범위 제한)
"""

import os, sys, json, shutil, subprocess, traceback, datetime, tempfile

LOG_FILE = os.path.join(os.path.expanduser("~"), "Desktop", "분석기_오류로그.txt")

def write_crash_log(msg):
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n[{datetime.datetime.now()}]\n{msg}\n")
    except Exception:
        pass

# ============================================================
# 계산 모드
# ============================================================
def run_compute_mode(params_file):
    import numpy as np
    import shapefile
    from scipy.interpolate import griddata
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    from matplotlib.patches import Patch
    from matplotlib.collections import LineCollection
    import matplotlib.font_manager as fm

    for fn in ['Malgun Gothic', '맑은 고딕', 'NanumGothic']:
        if fn in [f.name for f in fm.fontManager.ttflist]:
            plt.rcParams['font.family'] = fn
            break
    plt.rcParams['axes.unicode_minus'] = False

    with open(params_file, 'r', encoding='utf-8') as f:
        params = json.load(f)

    contour_path = params.get('contour_path', '')
    dxf_files = params.get('dxf_files', [])
    cadastral_path = params.get('cadastral_path')
    boundary_path = params.get('boundary_path')
    boundary_type = params.get('boundary_type')
    elev_field = params['elev_field']
    # 색상 설정
    user_elev_colors = params.get('elev_colors', ['#228B22', '#6BBD45', '#FFFF96', '#DEB887', '#A5714E', '#F0F0F0'])
    user_slope_colors = params.get('slope_colors', ['#38A800', '#CDFF00', '#FFFF00', '#FFAA00', '#FF0000', '#A80000'])
    user_slope_bounds = params.get('slope_bounds', [0, 5, 10, 15, 20, 25, 90])
    user_slope_labels = params.get('slope_labels', ['평지', '완경사', '약간경사', '경사', '급경사', '험준'])
    user_elev_classes = params.get('elev_classes', 5)
    user_cadastral_color = params.get('cadastral_color', '#000000')
    user_cadastral_width = params.get('cadastral_width', 0.5)
    user_cadastral_alpha = params.get('cadastral_alpha', 0.7)
    user_boundary_color = params.get('boundary_color', '#FF0000')
    user_boundary_width = params.get('boundary_width', 2.5)
    user_viewport_x = params.get('viewport_x', 2000)
    user_viewport_y = params.get('viewport_y', 1000)
    resolution = params['resolution']
    output_dir = params['output_dir']
    progress_file = params['progress_file']
    BUFFER_RADIUS = 1000.0

    def update_progress(step, pct, msg):
        with open(progress_file, 'w', encoding='utf-8') as f:
            json.dump({'step': step, 'pct': pct, 'msg': msg, 'done': False, 'error': None}, f)
        write_crash_log(f"[{step}] {msg}")

    def finish_progress(error=None):
        with open(progress_file, 'w', encoding='utf-8') as f:
            json.dump({'step': 99, 'pct': 100, 'msg': '완료' if not error else '오류',
                       'done': True, 'error': error}, f)

    def read_shp(path):
        for enc in ['euc-kr', 'cp949', 'utf-8', 'utf-8-sig', 'latin-1']:
            try:
                sf = shapefile.Reader(path, encoding=enc)
                _ = sf.fields
                return sf
            except Exception:
                continue
        return None

    try:
        # ── 0) 구역계 → 분석 범위 결정 ──
        boundary_polygons = []
        analysis_bbox = None
        boundary_center = None

        if boundary_path and boundary_type in ('shp', 'dxf'):
            update_progress(0, 3, f"구역계 {boundary_type.upper()} 읽는 중...")
            all_bx, all_by = [], []

            if boundary_type == 'shp':
                bsf = read_shp(boundary_path)
                if bsf:
                    for shape in bsf.shapes():
                        parts = list(shape.parts) if hasattr(shape, 'parts') and shape.parts else [0]
                        parts.append(len(shape.points))
                        for pi in range(len(parts) - 1):
                            seg = shape.points[parts[pi]:parts[pi + 1]]
                            if len(seg) >= 3:
                                boundary_polygons.append(([p[0] for p in seg], [p[1] for p in seg]))
                                all_bx.extend([p[0] for p in seg])
                                all_by.extend([p[1] for p in seg])

            elif boundary_type == 'dxf':
                import ezdxf
                try:
                    bdxf = ezdxf.readfile(boundary_path)
                    bmsp = bdxf.modelspace()
                    type_counts = {}
                    for ent in bmsp:
                        etype = ent.dxftype()
                        type_counts[etype] = type_counts.get(etype, 0) + 1
                        pts = []
                        if etype == 'LWPOLYLINE':
                            pts = [(p[0], p[1]) for p in ent.get_points()]
                            # 닫힌 폴리라인이면 마지막에 첫점 추가
                            if hasattr(ent.dxf, 'flags') and ent.dxf.flags & 1:
                                pts.append(pts[0])
                        elif etype == 'POLYLINE':
                            pts = [(v.dxf.location.x, v.dxf.location.y) for v in ent.vertices]
                            if ent.is_closed:
                                pts.append(pts[0])
                        elif etype == 'LINE':
                            pts = [(ent.dxf.start.x, ent.dxf.start.y), (ent.dxf.end.x, ent.dxf.end.y)]
                        elif etype == 'SPLINE':
                            # flattening으로 곡선을 직선 세그먼트로 변환
                            try:
                                pts = [(p.x, p.y) for p in ent.flattening(0.5)]
                            except Exception:
                                pts = [(p[0], p[1]) for p in ent.control_points]
                        elif etype == 'ARC':
                            try:
                                pts = [(p.x, p.y) for p in ent.flattening(0.5)]
                            except Exception:
                                pass
                        elif etype == 'CIRCLE':
                            try:
                                pts = [(p.x, p.y) for p in ent.flattening(0.5)]
                            except Exception:
                                pass
                        if len(pts) >= 2:
                            boundary_polygons.append(([p[0] for p in pts], [p[1] for p in pts]))
                            all_bx.extend([p[0] for p in pts])
                            all_by.extend([p[1] for p in pts])
                    write_crash_log(f"구역계 DXF 엔티티: {type_counts}, 폴리곤: {len(boundary_polygons)}개")
                except Exception as e:
                    write_crash_log(f"구역계 DXF 오류: {traceback.format_exc()}")

            if boundary_polygons and all_bx:
                bx_min, bx_max = min(all_bx), max(all_bx)
                by_min, by_max = min(all_by), max(all_by)
                write_crash_log(f"구역계 원본좌표: X({bx_min:.1f}~{bx_max:.1f}), Y({by_min:.1f}~{by_max:.1f})")

                # 좌표계 자동 감지 및 변환 (등고선 좌표와 비교)
                # 등고선 DXF를 먼저 스캔해서 좌표 범위 확인
                contour_x_range = None
                if dxf_files:
                    import ezdxf as _ezdxf
                    sample_xs, sample_ys = [], []
                    try:
                        sdxf = _ezdxf.readfile(dxf_files[0])
                        smsp = sdxf.modelspace()
                        for ent in smsp:
                            if len(sample_xs) > 1000:
                                break
                            try:
                                if ent.dxftype() == 'LWPOLYLINE':
                                    for p in ent.get_points():
                                        sample_xs.append(p[0])
                                        sample_ys.append(p[1])
                                elif ent.dxftype() == 'POLYLINE':
                                    for v in ent.vertices:
                                        sample_xs.append(v.dxf.location.x)
                                        sample_ys.append(v.dxf.location.y)
                                elif ent.dxftype() == 'LINE':
                                    sample_xs.extend([ent.dxf.start.x, ent.dxf.end.x])
                                    sample_ys.extend([ent.dxf.start.y, ent.dxf.end.y])
                                elif ent.dxftype() == 'POINT':
                                    sample_xs.append(ent.dxf.location.x)
                                    sample_ys.append(ent.dxf.location.y)
                            except Exception:
                                pass
                        if sample_xs:
                            contour_x_range = (min(sample_xs), max(sample_xs), min(sample_ys), max(sample_ys))
                            write_crash_log(f"등고선 좌표범위: X({contour_x_range[0]:.1f}~{contour_x_range[1]:.1f}), Y({contour_x_range[2]:.1f}~{contour_x_range[3]:.1f})")
                        else:
                            write_crash_log("등고선 좌표 스캔: 엔티티 없음")
                    except Exception as e:
                        write_crash_log(f"등고선 좌표 스캔 오류: {e}")

                # 좌표계가 안 맞으면 자동 변환 시도
                if contour_x_range:
                    cx_min, cx_max, cy_min, cy_max = contour_x_range
                    # 겹치는지 확인
                    overlaps = not (bx_max < cx_min - 2000 or bx_min > cx_max + 2000 or
                                    by_max < cy_min - 2000 or by_min > cy_max + 2000)

                    if not overlaps:
                        write_crash_log("좌표 불일치 → 자동 변환 시도")
                        transformed = False

                        # 1) pyproj로 정밀 변환: 한국 좌표계 자동 감지
                        if not transformed:
                            try:
                                import pyproj
                                # Y값으로 좌표계 추정
                                # 5174/2097: FN=500000 → Y≈440000~560000
                                # 5186: FN=600000 → Y≈540000~660000
                                # 5179: FN=2000000 → Y≈1900000~2100000
                                src_epsg = None
                                dst_epsg = None
                                contour_y_mid = (cy_min + cy_max) / 2
                                boundary_y_mid = (by_min + by_max) / 2

                                if 400000 < boundary_y_mid < 560000 and 540000 < contour_y_mid < 660000:
                                    src_epsg = 5174; dst_epsg = 5186
                                elif 540000 < boundary_y_mid < 660000 and 400000 < contour_y_mid < 560000:
                                    src_epsg = 5186; dst_epsg = 5174
                                elif 1800000 < boundary_y_mid < 2200000 and 540000 < contour_y_mid < 660000:
                                    src_epsg = 5179; dst_epsg = 5186
                                elif 540000 < boundary_y_mid < 660000 and 1800000 < contour_y_mid < 2200000:
                                    src_epsg = 5186; dst_epsg = 5179

                                if src_epsg and dst_epsg:
                                    write_crash_log(f"pyproj 변환: EPSG:{src_epsg} → EPSG:{dst_epsg}")
                                    transformer = pyproj.Transformer.from_crs(
                                        f"EPSG:{src_epsg}", f"EPSG:{dst_epsg}", always_xy=True)
                                    new_polys = []
                                    all_bx, all_by = [], []
                                    for bpx, bpy in boundary_polygons:
                                        tx, ty = transformer.transform(bpx, bpy)
                                        tx, ty = list(tx), list(ty)
                                        new_polys.append((tx, ty))
                                        all_bx.extend(tx)
                                        all_by.extend(ty)
                                    boundary_polygons = new_polys
                                    bx_min, bx_max = min(all_bx), max(all_bx)
                                    by_min, by_max = min(all_by), max(all_by)
                                    transformed = True
                                    write_crash_log(f"pyproj 변환 완료: X({bx_min:.1f}~{bx_max:.1f}), Y({by_min:.1f}~{by_max:.1f})")
                            except Exception as e:
                                write_crash_log(f"pyproj 변환 실패: {e}")

                        # 2) 단순 Y축 오프셋 (pyproj 없을 때 폴백)
                        if not transformed:
                            for y_offset in [100000, -100000]:
                                test_ymin = by_min + y_offset
                                test_ymax = by_max + y_offset
                                if not (test_ymax < cy_min - 2000 or test_ymin > cy_max + 2000 or
                                        bx_max < cx_min - 2000 or bx_min > cx_max + 2000):
                                    write_crash_log(f"Y축 오프셋 {y_offset:+d} 적용 (폴백)")
                                    new_polys = []
                                    all_bx, all_by = [], []
                                    for bpx, bpy in boundary_polygons:
                                        new_y = [y + y_offset for y in bpy]
                                        new_polys.append((bpx, new_y))
                                        all_bx.extend(bpx)
                                        all_by.extend(new_y)
                                    boundary_polygons = new_polys
                                    bx_min, bx_max = min(all_bx), max(all_bx)
                                    by_min, by_max = min(all_by), max(all_by)
                                    transformed = True
                                    break

                        # 3) pyproj 변환 (WGS84 → TM 등)
                        if not transformed and bx_max < 200 and by_max < 90:
                            try:
                                import pyproj
                                # WGS84 → EPSG:5186
                                transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5186", always_xy=True)
                                new_polys = []
                                all_bx, all_by = [], []
                                for bpx, bpy in boundary_polygons:
                                    tx, ty = transformer.transform(bpx, bpy)
                                    tx, ty = list(tx), list(ty)
                                    new_polys.append((tx, ty))
                                    all_bx.extend(tx)
                                    all_by.extend(ty)
                                boundary_polygons = new_polys
                                bx_min, bx_max = min(all_bx), max(all_bx)
                                by_min, by_max = min(all_by), max(all_by)
                                write_crash_log(f"WGS84→EPSG:5186 변환 완료")
                                transformed = True
                            except Exception as e:
                                write_crash_log(f"pyproj 변환 실패: {e}")

                        # 3) XY 스왑
                        if not transformed:
                            test_xmin, test_xmax = by_min, by_max
                            test_ymin, test_ymax = bx_min, bx_max
                            if not (test_xmax < cx_min - 2000 or test_xmin > cx_max + 2000 or
                                    test_ymax < cy_min - 2000 or test_ymin > cy_max + 2000):
                                write_crash_log("XY 스왑 적용")
                                new_polys = []
                                all_bx, all_by = [], []
                                for bpx, bpy in boundary_polygons:
                                    new_polys.append((bpy, bpx))
                                    all_bx.extend(bpy)
                                    all_by.extend(bpx)
                                boundary_polygons = new_polys
                                bx_min, bx_max = min(all_bx), max(all_bx)
                                by_min, by_max = min(all_by), max(all_by)
                                transformed = True

                        write_crash_log(f"변환 후 좌표: X({bx_min:.1f}~{bx_max:.1f}), Y({by_min:.1f}~{by_max:.1f})")

                boundary_center = ((bx_min + bx_max) / 2, (by_min + by_max) / 2)
                analysis_bbox = (bx_min - BUFFER_RADIUS, bx_max + BUFFER_RADIUS,
                                 by_min - BUFFER_RADIUS, by_max + BUFFER_RADIUS)
                update_progress(0, 5, f"구역계: {bx_max-bx_min:.0f}x{by_max-by_min:.0f}m + 1km 버퍼")
                write_crash_log(f"분석범위: X({analysis_bbox[0]:.0f}~{analysis_bbox[1]:.0f}), Y({analysis_bbox[2]:.0f}~{analysis_bbox[3]:.0f})")

        # ── 1) 수치지형도에서 등고선 추출 (SHP 또는 DXF) ──
        # DXF 파일 리스트 결정
        if dxf_files:
            contour_ext = '.dxf'
        elif contour_path:
            contour_ext = os.path.splitext(contour_path)[1].lower()
        else:
            finish_progress("수치지형도 파일이 없습니다.")
            return

        xs, ys, zs = [], [], []
        contour_lines = []
        skipped = 0

        if contour_ext == '.dxf':
            # ── DXF 등고선 추출 (여러 파일 합산) ──
            import ezdxf
            all_dxf = dxf_files if dxf_files else [contour_path]
            update_progress(1, 8, f"DXF {len(all_dxf)}개 파일 읽는 중...")

            all_layer_counts = {}
            all_msp_entries = []

            for fi, dxf_path in enumerate(all_dxf):
                update_progress(1, 8 + int(3 * fi / len(all_dxf)), f"DXF {fi+1}/{len(all_dxf)} 읽기: {os.path.basename(dxf_path)}")
                try:
                    doc, _ = ezdxf.recover.readfile(dxf_path)
                except Exception:
                    try:
                        doc = ezdxf.readfile(dxf_path)
                    except Exception as e:
                        write_crash_log(f"DXF 읽기 실패: {dxf_path}: {e}")
                        continue
                msp = doc.modelspace()
                for ent in msp:
                    ln = ent.dxf.layer
                    all_layer_counts[ln] = all_layer_counts.get(ln, 0) + 1
                    all_msp_entries.append(ent)

            layer_counts = all_layer_counts
            write_crash_log(f"DXF 총 레이어: {len(layer_counts)}, 엔티티: {len(all_msp_entries):,}")
            update_progress(1, 11, f"DXF {len(all_dxf)}개: {len(layer_counts)}레이어, {len(all_msp_entries):,}엔티티")

            # 등고선 레이어 자동 감지
            # v1.0: 7111~7124, v2.0: F001xxxx
            CONTOUR_CODES = {'7111', '7121', '7112', '7122', '7113', '7123', '7114', '7124'}
            CONTOUR_PREFIXES = ('F001', 'F002')  # F001=등고선, F002=표고점
            contour_layers = set()
            for ln in layer_counts:
                # 정확 일치
                if ln in CONTOUR_CODES:
                    contour_layers.add(ln)
                # v2.0 접두사 (F0017111, F0017114, F0027217 등)
                elif any(ln.startswith(p) for p in CONTOUR_PREFIXES):
                    contour_layers.add(ln)
                # 끝부분 일치
                elif any(ln.endswith(c) for c in CONTOUR_CODES):
                    contour_layers.add(ln)
                # 키워드 일치
                elif any(k in ln.lower() for k in ['contour', '등고', 'cont']):
                    contour_layers.add(ln)

            if not contour_layers:
                # 못 찾으면 Z값이 있는 POLYLINE 레이어 탐색
                update_progress(1, 12, "등고선 레이어 자동 탐색 중...")
                checked_layers = {}
                for ent in all_msp_entries:
                    ln = ent.dxf.layer
                    if ln in contour_layers or checked_layers.get(ln, 0) > 5:
                        continue
                    checked_layers[ln] = checked_layers.get(ln, 0) + 1
                    et = ent.dxftype()
                    if et == 'LWPOLYLINE':
                        z = ent.dxf.get('elevation', 0.0)
                        if z != 0.0:
                            contour_layers.add(ln)
                    elif et in ('POLYLINE', '3DPOLYLINE'):
                        pts = list(ent.points())
                        if pts and pts[0].z != 0.0:
                            contour_layers.add(ln)

            write_crash_log(f"등고선 레이어: {contour_layers}")
            update_progress(1, 11, f"등고선 레이어: {contour_layers or '없음'}")

            if not contour_layers:
                finish_progress("DXF에서 등고선 레이어를 찾을 수 없습니다.\n"
                                f"발견된 레이어: {list(layer_counts.keys())[:20]}")
                return

            # 등고선 데이터 추출
            total_ent = sum(layer_counts.get(ln, 0) for ln in contour_layers)
            processed = 0
            for ent in all_msp_entries:
                if ent.dxf.layer not in contour_layers:
                    continue
                processed += 1
                et = ent.dxftype()

                pts_3d = []
                if et == 'LWPOLYLINE':
                    z = ent.dxf.get('elevation', 0.0)
                    pts_3d = [(p.x, p.y, z) for p in ent.vertices_in_wcs()]
                elif et in ('POLYLINE', '3DPOLYLINE'):
                    pts_3d = [(p.x, p.y, p.z) for p in ent.points()]
                elif et == 'LINE':
                    s, e = ent.dxf.start, ent.dxf.end
                    pts_3d = [(s.x, s.y, s.z), (e.x, e.y, e.z)]
                elif et == 'POINT':
                    loc = ent.dxf.location
                    pts_3d = [(loc.x, loc.y, loc.z)]
                elif et == 'INSERT':
                    loc = ent.dxf.insert
                    if hasattr(loc, 'z') and loc.z != 0:
                        pts_3d = [(loc.x, loc.y, loc.z)]

                if len(pts_3d) < 1:
                    continue

                z_val = pts_3d[0][2]
                if z_val == 0.0:
                    continue

                # 구역계 범위 필터
                seg_x = [p[0] for p in pts_3d]
                seg_y = [p[1] for p in pts_3d]
                if analysis_bbox:
                    ab = analysis_bbox
                    if max(seg_x) < ab[0] or min(seg_x) > ab[1] or \
                       max(seg_y) < ab[2] or min(seg_y) > ab[3]:
                        skipped += 1
                        continue

                if len(pts_3d) >= 2:
                    contour_lines.append((seg_x, seg_y))
                for p in pts_3d:
                    xs.append(p[0])
                    ys.append(p[1])
                    zs.append(p[2])

                if processed % 3000 == 0:
                    update_progress(1, 11 + int(5 * processed / max(1, total_ent)),
                        f"DXF 등고선: {processed:,}/{total_ent:,} ({len(xs):,}pt, {skipped:,}스킵)")

        else:
            # ── SHP 등고선 추출 ──
            update_progress(1, 8, "SHP 등고선 읽는 중...")
            sf = read_shp(contour_path)
            if sf is None:
                finish_progress("수치지형도 SHP를 읽을 수 없습니다.")
                return

            fields_info = sf.fields[1:]
            field_names = [fi[0] for fi in fields_info]
            field_idx = field_names.index(elev_field)
            total_features = len(sf)

            for i, sr in enumerate(sf.iterShapeRecords()):
                shape = sr.shape
                z_val = sr.record[field_idx]
                if z_val is None:
                    continue
                try:
                    z_val = float(z_val)
                except (ValueError, TypeError):
                    continue

                if analysis_bbox:
                    ab = analysis_bbox
                    shape_xs = [p[0] for p in shape.points]
                    shape_ys = [p[1] for p in shape.points]
                    if max(shape_xs) < ab[0] or min(shape_xs) > ab[1] or \
                       max(shape_ys) < ab[2] or min(shape_ys) > ab[3]:
                        skipped += 1
                        continue

                parts = list(shape.parts) if hasattr(shape, 'parts') and shape.parts else [0]
                parts.append(len(shape.points))
                for pi in range(len(parts) - 1):
                    seg = shape.points[parts[pi]:parts[pi + 1]]
                    if len(seg) >= 2:
                        contour_lines.append(([p[0] for p in seg], [p[1] for p in seg]))
                        for p in seg:
                            xs.append(p[0]); ys.append(p[1]); zs.append(z_val)

                if (i + 1) % 5000 == 0:
                    update_progress(1, 8 + int(7 * i / total_features),
                        f"등고선: {i+1:,}/{total_features:,} ({len(xs):,}pt, {skipped:,}스킵)")

        xs, ys, zs = np.array(xs), np.array(ys), np.array(zs)
        if len(xs) == 0:
            finish_progress("등고선 데이터가 없습니다.\n구역계 범위와 좌표계가 맞는지 확인하세요.")
            return
        update_progress(1, 16, f"등고선: {len(xs):,}pt, 표고 {zs.min():.1f}~{zs.max():.1f}m ({skipped:,}스킵)")

        # ── 2) 지적도 읽기 + 좌표 변환 (5174↔5186 자동 맞춤) ──
        cadastral_shapes = []
        # cadastral_path는 리스트 또는 단일 경로
        cadastral_list = cadastral_path if isinstance(cadastral_path, list) else ([cadastral_path] if cadastral_path else [])
        for cad_idx, cad_file in enumerate(cadastral_list):
            update_progress(2, 18, f"지적도 {cad_idx+1}/{len(cadastral_list)} 읽는 중...")
            csf = read_shp(cad_file)
            if csf:
                # 좌표 변환 필요 여부 확인 (등고선 범위 vs SHP 범위 비교)
                cad_bbox = csf.bbox  # [xmin, ymin, xmax, ymax]
                dem_cx = (xs.min() + xs.max()) / 2
                dem_cy = (ys.min() + ys.max()) / 2
                cad_cx = (cad_bbox[0] + cad_bbox[2]) / 2
                cad_cy = (cad_bbox[1] + cad_bbox[3]) / 2

                # Y축 차이가 5만 이상이면 5174↔5186 변환 필요
                coord_transform = None
                dy_diff = abs(dem_cy - cad_cy)
                dx_diff = abs(dem_cx - cad_cx)
                write_crash_log(f"좌표 비교: DXF중심({dem_cx:.0f},{dem_cy:.0f}), SHP중심({cad_cx:.0f},{cad_cy:.0f}), 차이({dx_diff:.0f},{dy_diff:.0f})")

                if dy_diff > 50000:
                    update_progress(2, 19, f"좌표계 차이 감지 (Y차이 {dy_diff:.0f}m) → 자동 변환...")
                    try:
                        from pyproj import Transformer
                        # DXF가 5174(Y~45만), SHP가 5186(Y~55만) 또는 반대
                        if dem_cy < cad_cy:
                            # DXF=5174, SHP=5186 → SHP를 5174로 변환
                            coord_transform = Transformer.from_crs('EPSG:5186', 'EPSG:5174', always_xy=True).transform
                            write_crash_log("변환: SHP(5186) → DXF(5174)")
                        else:
                            # DXF=5186, SHP=5174 → SHP를 5186로 변환
                            coord_transform = Transformer.from_crs('EPSG:5174', 'EPSG:5186', always_xy=True).transform
                            write_crash_log("변환: SHP(5174) → DXF(5186)")
                        update_progress(2, 20, "좌표 변환 적용 중...")
                    except Exception as e:
                        write_crash_log(f"pyproj 변환 실패: {e}, 단순 오프셋 적용")
                        # pyproj 없으면 단순 Y오프셋 (약 10만m)
                        y_offset = dem_cy - cad_cy
                        x_offset = dem_cx - cad_cx
                        coord_transform = lambda x, y: (x + x_offset, y + y_offset)

                for i, shape in enumerate(csf.shapes()):
                    parts = list(shape.parts) if hasattr(shape, 'parts') and shape.parts else [0]
                    parts.append(len(shape.points))
                    for pi in range(len(parts) - 1):
                        seg = shape.points[parts[pi]:parts[pi + 1]]
                        if len(seg) >= 2:
                            if coord_transform:
                                seg_x, seg_y = [], []
                                for p in seg:
                                    tx, ty = coord_transform(p[0], p[1])
                                    seg_x.append(tx)
                                    seg_y.append(ty)
                            else:
                                seg_x = [p[0] for p in seg]
                                seg_y = [p[1] for p in seg]
                            # 등고선 분석 범위 내 필터
                            if max(seg_x) < xs.min() or min(seg_x) > xs.max() or \
                               max(seg_y) < ys.min() or min(seg_y) > ys.max():
                                continue
                            cadastral_shapes.append((seg_x, seg_y))

                update_progress(2, 22, f"지적도 {cad_idx+1}: {len(cadastral_shapes):,}개 선분 (변환: {'적용' if coord_transform else '불필요'})")

        if cadastral_list:
            write_crash_log(f"지적도 총 {len(cadastral_list)}개 파일, {len(cadastral_shapes):,}개 선분")

        # ── 3) DEM 보간 ──
        update_progress(3, 25, "DEM 보간 준비...")
        x_min, x_max = xs.min(), xs.max()
        y_min, y_max = ys.min(), ys.max()
        width, height = x_max - x_min, y_max - y_min

        grid_x = np.arange(x_min, x_max, resolution)
        grid_y = np.arange(y_min, y_max, resolution)
        total_cols, total_rows = len(grid_x), len(grid_y)

        # 격자 제한
        MAX_DIM = 800
        if total_cols > MAX_DIM or total_rows > MAX_DIM:
            resolution = max(width, height) / MAX_DIM
            grid_x = np.arange(x_min, x_max, resolution)
            grid_y = np.arange(y_min, y_max, resolution)
            total_cols, total_rows = len(grid_x), len(grid_y)
            write_crash_log(f"해상도 자동 조정: {resolution:.1f}m")

        dem = np.full((total_rows, total_cols), np.nan)
        TILE_SIZE, TILE_BUFFER = 500.0, 100.0
        n_tiles_x = max(1, int(np.ceil(width / TILE_SIZE)))
        n_tiles_y = max(1, int(np.ceil(height / TILE_SIZE)))
        total_tiles = n_tiles_x * n_tiles_y

        update_progress(3, 27, f"DEM: {total_cols}x{total_rows}, {total_tiles}타일, {len(xs):,}pt")
        points_all = np.column_stack((xs, ys))

        tile_count = 0
        for ti in range(n_tiles_x):
            for tj in range(n_tiles_y):
                tile_count += 1
                tx_min = x_min + ti * TILE_SIZE - TILE_BUFFER
                tx_max = x_min + (ti + 1) * TILE_SIZE + TILE_BUFFER
                ty_min = y_min + tj * TILE_SIZE - TILE_BUFFER
                ty_max = y_min + (tj + 1) * TILE_SIZE + TILE_BUFFER
                mask = (xs >= tx_min) & (xs <= tx_max) & (ys >= ty_min) & (ys <= ty_max)
                tile_pts, tile_zs = points_all[mask], zs[mask]
                if len(tile_pts) < 3:
                    continue
                c0 = max(0, int((tx_min + TILE_BUFFER - x_min) / resolution))
                c1 = min(total_cols, int((tx_max - TILE_BUFFER - x_min) / resolution))
                r0 = max(0, int((ty_min + TILE_BUFFER - y_min) / resolution))
                r1 = min(total_rows, int((ty_max - TILE_BUFFER - y_min) / resolution))
                if c1 <= c0 or r1 <= r0:
                    continue
                tgx, tgy = np.meshgrid(grid_x[c0:c1], grid_y[r0:r1])
                try:
                    dem[r0:r1, c0:c1] = griddata(tile_pts, tile_zs, (tgx, tgy), method='linear')
                except Exception:
                    pass
                if tile_count % max(1, total_tiles // 10) == 0 or tile_count == total_tiles:
                    update_progress(3, 27 + int(20 * tile_count / total_tiles),
                        f"DEM: {tile_count}/{total_tiles} 타일")

        # NaN 채우기
        nan_mask = np.isnan(dem)
        if nan_mask.any():
            update_progress(3, 48, "빈 영역 채우기...")
            max_pts = 80000
            if len(xs) > max_pts:
                idx = np.random.choice(len(xs), max_pts, replace=False)
                pts_s, zs_s = points_all[idx], zs[idx]
            else:
                pts_s, zs_s = points_all, zs
            gxx, gyy = np.meshgrid(grid_x, grid_y)
            dem[nan_mask] = griddata(pts_s, zs_s, (gxx, gyy), method='nearest')[nan_mask]

        grid_xx, grid_yy = np.meshgrid(grid_x, grid_y)
        update_progress(3, 50, f"DEM 완료 ({total_cols}x{total_rows})")

        # ── 4) 경사도 ──
        update_progress(4, 52, "경사도 계산...")
        dy, dx = np.gradient(dem, resolution)
        slope = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))

        # ── 구역계 내부 마스크 (SHP/DXF인 경우) ──
        boundary_from_image = []
        boundary_mask_grid = None
        if boundary_polygons:
            from matplotlib.path import Path
            # 모든 구역계 폴리곤의 합집합 마스크
            flat_pts = np.column_stack((grid_xx.ravel(), grid_yy.ravel()))
            combined_mask = np.zeros(grid_xx.shape, dtype=bool)
            for bpx, bpy in boundary_polygons:
                if len(bpx) >= 3:
                    poly_pts = list(zip(bpx, bpy))
                    bpath = Path(poly_pts)
                    m = bpath.contains_points(flat_pts).reshape(grid_xx.shape)
                    combined_mask |= m
            if combined_mask.any():
                boundary_mask_grid = combined_mask
                write_crash_log(f"구역계 내부: {combined_mask.sum():,}셀 ({combined_mask.sum()/combined_mask.size*100:.1f}%)")

        # ── 오버레이 헬퍼 ──
        def draw_overlays(ax):
            # 지적선
            if cadastral_shapes:
                lc = LineCollection([list(zip(sx, sy)) for sx, sy in cadastral_shapes],
                                    colors=user_cadastral_color, linewidths=user_cadastral_width,
                                    alpha=user_cadastral_alpha, zorder=6)
                ax.add_collection(lc)
            # 구역계 (이미지에서 추출된 빨간 선)
            if boundary_from_image:
                blc = LineCollection([list(zip(bx, by)) for bx, by in boundary_from_image],
                                     colors='#780000', linewidths=2.5, alpha=0.95, zorder=10)
                ax.add_collection(blc)
            # 구역계 (SHP/DXF)
            if boundary_polygons:
                blc = LineCollection([list(zip(bx, by)) for bx, by in boundary_polygons],
                                     colors=user_boundary_color, linewidths=user_boundary_width,
                                     alpha=0.95, zorder=10)
                ax.add_collection(blc)

        # ── 5) 표고분석도 ──
        update_progress(5, 55, "표고분석도 생성...")
        import math
        vmin, vmax = np.nanmin(dem), np.nanmax(dem)

        # 표고 범례: 최대 8~10개, 대상지 근처 세분화
        user_elev_step = params.get('elev_step', 10)  # 기본 10m 단위
        MAX_LEGEND = 10

        if boundary_mask_grid is not None and boundary_mask_grid.any():
            dem_inside = dem[boundary_mask_grid]
            target_min = float(np.nanmin(dem_inside))
            target_max = float(np.nanmax(dem_inside))
            target_range = target_max - target_min

            # 대상지 범위에 맞춰 세분화 스텝 결정 (범례 3~5개 정도)
            if target_range <= 10:
                fine_step = 2
            elif target_range <= 30:
                fine_step = 5
            else:
                fine_step = 10

            # 대상지 구간
            t_start = math.floor(target_min / fine_step) * fine_step
            t_end = math.ceil(target_max / fine_step) * fine_step
            target_bounds = list(range(int(t_start), int(t_end) + 1, int(fine_step)))

            # 대상지 아래/위 구간 (큰 단위로 1~2개씩)
            coarse_step = max(user_elev_step, 20)
            below = math.floor(vmin / coarse_step) * coarse_step
            above = math.ceil(vmax / coarse_step) * coarse_step

            elev_bounds = []
            # 아래 구간
            v = int(below)
            while v < t_start:
                elev_bounds.append(v)
                v += coarse_step
            # 대상지 세밀 구간
            elev_bounds.extend(target_bounds)
            # 위 구간
            v = int(t_end) + coarse_step
            while v <= above:
                elev_bounds.append(v)
                v += coarse_step

            elev_bounds = sorted(set(elev_bounds))
            # 범례 너무 많으면 축소
            while len(elev_bounds) > MAX_LEGEND + 1 and fine_step < coarse_step:
                fine_step += 1
                target_bounds = list(range(int(t_start), int(t_end) + 1, int(fine_step)))
                elev_bounds = []
                v = int(below)
                while v < t_start:
                    elev_bounds.append(v)
                    v += coarse_step
                elev_bounds.extend(target_bounds)
                v = int(t_end) + coarse_step
                while v <= above:
                    elev_bounds.append(v)
                    v += coarse_step
                elev_bounds = sorted(set(elev_bounds))

            write_crash_log(f"표고 범례: 대상지 {target_min:.0f}~{target_max:.0f}m, 세밀={fine_step}m, 총{len(elev_bounds)-1}개")
        else:
            e_start = math.floor(vmin / user_elev_step) * user_elev_step
            e_end = math.ceil(vmax / user_elev_step) * user_elev_step
            elev_bounds = list(range(int(e_start), int(e_end) + 1, int(user_elev_step)))

        if len(elev_bounds) < 2:
            elev_bounds = [int(math.floor(vmin)), int(math.ceil(vmax))]

        # ── 대상지 중심 뷰포트 계산 ──
        view_xmin, view_xmax = x_min, x_max
        view_ymin, view_ymax = y_min, y_max
        if boundary_polygons:
            all_bx, all_by = [], []
            for bpx, bpy in boundary_polygons:
                all_bx.extend(bpx)
                all_by.extend(bpy)
            if all_bx and all_by:
                b_xmin, b_xmax = min(all_bx), max(all_bx)
                b_ymin, b_ymax = min(all_by), max(all_by)
                b_cx = (b_xmin + b_xmax) / 2
                b_cy = (b_ymin + b_ymax) / 2
                x_range = float(user_viewport_x)
                y_range = float(user_viewport_y)
                view_xmin = max(x_min, b_cx - x_range / 2)
                view_xmax = min(x_max, b_cx + x_range / 2)
                view_ymin = max(y_min, b_cy - y_range / 2)
                view_ymax = min(y_max, b_cy + y_range / 2)
                write_crash_log(f"대상지 뷰포트: X({view_xmin:.0f}~{view_xmax:.0f}), Y({view_ymin:.0f}~{view_ymax:.0f})")

        # figsize 비율을 뷰포트에 맞춤
        vp_w = view_xmax - view_xmin
        vp_h = view_ymax - view_ymin
        if vp_h > 0:
            aspect = vp_w / vp_h
            fig_h = 10
            fig_w = max(10, fig_h * aspect)
        else:
            fig_w, fig_h = 14, 10
        fig, ax = plt.subplots(1, 1, figsize=(fig_w, fig_h), dpi=100)
        cmap_e = mcolors.LinearSegmentedColormap.from_list('elev', user_elev_colors, N=256)
        ax.pcolormesh(grid_xx, grid_yy, dem, cmap=cmap_e, vmin=vmin, vmax=vmax, shading='auto')
        ax.set_aspect('equal')
        ax.set_xlim(view_xmin, view_xmax)
        ax.set_ylim(view_ymin, view_ymax)
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_frame_on(False)
        draw_overlays(ax)
        # 범례
        elev_labels = []
        elev_leg_colors = []
        for i in range(len(elev_bounds) - 1):
            lo = elev_bounds[i]
            hi = elev_bounds[i + 1]
            elev_labels.append(f'{lo}~{hi}m')
            t = (lo + hi) / 2
            t_norm = (t - vmin) / (vmax - vmin) if vmax > vmin else 0.5
            elev_leg_colors.append(cmap_e(max(0, min(1, t_norm))))
        elev_patches = [Patch(facecolor=c, edgecolor='gray', label=l) for c, l in zip(elev_leg_colors, elev_labels)]
        leg = ax.legend(handles=elev_patches, loc='lower right', fontsize=9, title='표고분석도',
                  title_fontsize=10, framealpha=0.9, edgecolor='gray', fancybox=True)
        leg.set_zorder(20)
        plt.tight_layout(pad=0.5)
        update_progress(5, 65, "표고분석도 저장...")
        fig.savefig(os.path.join(output_dir, '표고분석도.png'), dpi=150, bbox_inches='tight',
                    facecolor='white', pad_inches=0.1)
        plt.close(fig)

        # ── 6) 경사분석도 ──
        update_progress(6, 70, "경사분석도 생성...")
        fig, ax = plt.subplots(1, 1, figsize=(fig_w, fig_h), dpi=100)
        cmap_s = mcolors.ListedColormap(user_slope_colors)
        norm = mcolors.BoundaryNorm(user_slope_bounds, cmap_s.N)
        ax.pcolormesh(grid_xx, grid_yy, slope, cmap=cmap_s, norm=norm, shading='auto')
        ax.set_aspect('equal')
        ax.set_xlim(view_xmin, view_xmax)
        ax.set_ylim(view_ymin, view_ymax)
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_frame_on(False)
        # 지적선 오버레이
        draw_overlays(ax)
        # 범례 (오른쪽 아래, zorder 최상위)
        slope_leg_labels = []
        for i in range(len(user_slope_colors)):
            lo = user_slope_bounds[i]
            hi = user_slope_bounds[i + 1] if i + 1 < len(user_slope_bounds) else 90
            name = user_slope_labels[i] if i < len(user_slope_labels) else ''
            slope_leg_labels.append(f'{name} ({lo}~{hi}°)')
        patches = [Patch(facecolor=c, edgecolor='gray', label=l) for c, l in zip(user_slope_colors, slope_leg_labels)]
        leg2 = ax.legend(handles=patches, loc='lower right', fontsize=9, title='경사분석도',
                  title_fontsize=10, framealpha=0.9, edgecolor='gray', fancybox=True)
        leg2.set_zorder(20)
        plt.tight_layout(pad=0.5)
        update_progress(6, 82, "경사분석도 저장...")
        fig.savefig(os.path.join(output_dir, '경사분석도.png'), dpi=150, bbox_inches='tight',
                    facecolor='white', pad_inches=0.1)
        plt.close(fig)

        # ── 8) 통계 ──
        update_progress(8, 95, "통계 저장...")
        with open(os.path.join(output_dir, '분석통계.txt'), 'w', encoding='utf-8') as f:
            f.write("=" * 50 + "\n  표고·경사 분석 결과\n" + "=" * 50 + "\n\n")
            f.write(f"수치지형도: {os.path.basename(params.get('original_contour',''))}\n")
            if cadastral_path:
                f.write(f"지적도: {os.path.basename(params.get('original_cadastral',''))}\n")
            f.write(f"등고선 포인트: {len(xs):,}개\nDEM 해상도: {resolution:.1f}m\n")
            f.write(f"격자: {total_cols} x {total_rows}\n\n")

            # === 전체 영역 통계 ===
            f.write("-" * 40 + "\n  [전체 영역]\n" + "-" * 40 + "\n")
            f.write(f"표고: 최저 {vmin:.1f}m / 최고 {vmax:.1f}m / 평균 {np.nanmean(dem):.1f}m\n")
            f.write(f"경사: 최소 {np.nanmin(slope):.1f}° / 최대 {np.nanmax(slope):.1f}° / 평균 {np.nanmean(slope):.1f}°\n\n")
            total = slope.size
            for i in range(len(user_slope_colors)):
                lo = user_slope_bounds[i]
                hi = user_slope_bounds[i + 1] if i + 1 < len(user_slope_bounds) else 90
                name = user_slope_labels[i] if i < len(user_slope_labels) else f'구간{i+1}'
                f.write(f"  {name}({lo}~{hi}°): {np.sum((slope >= lo) & (slope < hi)) / total * 100:.1f}%\n")

            # === 대상지(구역계) 내부 통계 ===
            if boundary_mask_grid is not None and boundary_mask_grid.any():
                f.write(f"\n{'=' * 50}\n  [대상지 내부]\n{'=' * 50}\n")
                dem_inside = dem[boundary_mask_grid]
                slope_inside = slope[boundary_mask_grid]
                calc_area = boundary_mask_grid.sum() * (resolution ** 2)
                custom_area = params.get('custom_area', 0)
                use_area = custom_area if custom_area > 0 else calc_area

                f.write(f"자동 계산 면적: {calc_area:,.2f}m² ({calc_area/10000:.2f}ha)\n")
                if custom_area > 0:
                    f.write(f"수동 입력 면적: {custom_area:,.2f}m² ({custom_area/10000:.2f}ha) ← 적용\n")
                f.write(f"적용 면적: {use_area:,.2f}m² ({use_area/10000:.2f}ha)\n\n")

                e_min_i = float(np.nanmin(dem_inside))
                e_max_i = float(np.nanmax(dem_inside))
                total_inside = len(slope_inside)

                # ── 순서: 표고 → 표고 면적 → 경사 → 경사 면적 ──
                # 1) 표고
                f.write(f"[표고]\n")
                f.write(f"  최저: {e_min_i:.2f}m / 최고: {e_max_i:.2f}m\n")
                f.write(f"  평균: {np.nanmean(dem_inside):.2f}m / 표고차: {e_max_i - e_min_i:.2f}m\n\n")

                # 2) 표고 면적 비율
                e_stp = params.get('elev_step', 10)
                e_start_i = math.floor(e_min_i / e_stp) * e_stp
                e_end_i = math.ceil(e_max_i / e_stp) * e_stp
                e_bounds = list(range(int(e_start_i), int(e_end_i) + 1, int(e_stp)))
                if len(e_bounds) < 2:
                    e_bounds = [int(e_start_i), int(e_end_i)]
                elev_classes_data = []
                f.write(f"[표고 면적 비율]\n")
                for ei in range(len(e_bounds) - 1):
                    elo = e_bounds[ei]
                    ehi = e_bounds[ei + 1]
                    ecnt = np.sum((dem_inside >= elo) & (dem_inside < ehi))
                    epct = ecnt / total_inside * 100
                    earea = epct / 100 * use_area
                    f.write(f"  {elo}~{ehi}m: {epct:.2f}% ({earea:,.2f}m²)\n")
                    elev_classes_data.append({'range': f'{elo}~{ehi}m', 'pct': round(epct, 2), 'area': round(earea, 2)})

                # 3) 경사
                f.write(f"\n[경사]\n")
                f.write(f"  최소: {np.nanmin(slope_inside):.2f}° / 최대: {np.nanmax(slope_inside):.2f}°\n")
                f.write(f"  평균: {np.nanmean(slope_inside):.2f}°\n\n")

                # 4) 경사 면적 비율
                f.write(f"[경사 면적 비율]\n")
                slope_classes_data = []
                for i in range(len(user_slope_colors)):
                    lo = user_slope_bounds[i]
                    hi = user_slope_bounds[i + 1] if i + 1 < len(user_slope_bounds) else 90
                    name = user_slope_labels[i] if i < len(user_slope_labels) else f'구간{i+1}'
                    cnt = np.sum((slope_inside >= lo) & (slope_inside < hi))
                    pct = cnt / total_inside * 100
                    area_val = pct / 100 * use_area
                    f.write(f"  {name}({lo}~{hi}°): {pct:.2f}% ({area_val:,.2f}m²)\n")
                    slope_classes_data.append({'name': name, 'range': f'{lo}~{hi}°', 'pct': round(pct, 2), 'area': round(area_val, 2)})

                # 대상지 통계 JSON (GUI 결과 패널용)
                target_stats = {
                    'calc_area': round(calc_area, 2), 'custom_area': custom_area, 'use_area': round(use_area, 2),
                    'elev_min': round(e_min_i, 2), 'elev_max': round(e_max_i, 2),
                    'elev_avg': round(float(np.nanmean(dem_inside)), 2),
                    'elev_diff': round(e_max_i - e_min_i, 2),
                    'slope_min': round(float(np.nanmin(slope_inside)), 2),
                    'slope_max': round(float(np.nanmax(slope_inside)), 2),
                    'slope_avg': round(float(np.nanmean(slope_inside)), 2),
                    'elev_classes': elev_classes_data,
                    'slope_classes': slope_classes_data,
                }
                with open(os.path.join(output_dir, '_target_stats.json'), 'w', encoding='utf-8') as jf:
                    json.dump(target_stats, jf, ensure_ascii=False)

        finish_progress()
    except Exception as e:
        finish_progress(str(e) + "\n\n" + traceback.format_exc())


# ============================================================
if len(sys.argv) > 1 and sys.argv[1] == '--compute':
    run_compute_mode(sys.argv[2])
    sys.exit(0)

# ============================================================
# GUI
# ============================================================
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext
try:
    import windnd
    HAS_WINDND = True
except ImportError:
    HAS_WINDND = False
import shapefile

ELEV_CANDIDATES = ['CONT', '등고수치', 'EL_VAL', 'ELEVATION', 'ELEV', '고도', 'Z', 'HEIGHT',
                    'ALT', '표고', 'DEM', 'H', 'Z_COORD', 'VALUE', 'cont', 'elev', 'z', 'h']
IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff')

def normalize_path(p):
    return os.path.normpath(p.strip().strip('"').strip("'"))

def decode_drop(raw):
    if isinstance(raw, bytes):
        for enc in ['cp949', 'euc-kr', 'utf-8']:
            try:
                d = raw.decode(enc)
                if os.path.exists(d):
                    return d
            except Exception:
                continue
        return raw.decode('cp949', errors='replace')
    return raw

def copy_shp_local(path, prefix="shp_", log_func=None):
    td = tempfile.mkdtemp(prefix=prefix)
    base = os.path.splitext(path)[0]
    exts = ['.shp', '.shx', '.dbf', '.prj', '.cpg']
    copied = None
    for ext in exts:
        for te in [ext, ext.upper()]:
            src = base + te
            if os.path.isfile(src):
                dst = os.path.join(td, "data" + ext)
                shutil.copy2(src, dst)
                if ext == '.shp':
                    copied = dst
                break
    if copied is None:
        try:
            sdir = os.path.dirname(path)
            bname = os.path.splitext(os.path.basename(path))[0]
            for fn in os.listdir(sdir):
                fb, fe = os.path.splitext(fn)
                if fb == bname and fe.lower() in exts:
                    shutil.copy2(os.path.join(sdir, fn), os.path.join(td, "data" + fe.lower()))
                    if fe.lower() == '.shp':
                        copied = os.path.join(td, "data.shp")
        except Exception:
            pass
    return copied, td

def detect_elev_field(field_names, field_types):
    numeric = ('N', 'F', 'L')
    for c in ELEV_CANDIDATES:
        for i, n in enumerate(field_names):
            if c.lower() == n.lower() and field_types[i] in numeric:
                return n
    for i, n in enumerate(field_names):
        if field_types[i] in numeric:
            return n
    return None

def needs_local_copy(path):
    return path.startswith('\\\\') or path.startswith('//') or not all(ord(c) < 128 for c in path)


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("표고·경사 분석 v4")
        self.root.geometry("1050x780")
        self.root.resizable(True, False)
        self.root.configure(bg='#F5F6FA')

        # 상태
        self.contour_path = tk.StringVar()    # 수치지형도 (표시용)
        self.cadastral_path = tk.StringVar()  # 지적도 (표시용)
        self.cadastral_files = []  # 지적도 SHP 여러 개
        self.boundary_path = tk.StringVar()   # 구역계
        self.elev_field = tk.StringVar()
        self.resolution = tk.DoubleVar(value=10.0)
        self.boundary_type = None
        self.temp_dirs = []
        self.original_paths = {}
        self.actual_paths = {}
        self.dxf_files = []  # DXF 여러 개 지원
        self.process = None
        self.progress_file = None
        self._last_msg = ''

        # 색상 설정 (기본값)
        self.elev_colors = ['#228B22', '#6BBD45', '#FFFF96', '#DEB887', '#A5714E', '#F0F0F0']
        self.slope_colors = ['#38A800', '#CDFF00', '#FFFF00', '#FFAA00', '#FF0000', '#A80000']
        self.slope_bounds = [0, 5, 10, 15, 20, 25, 90]
        self.slope_labels = ['평지', '완경사', '약간경사', '경사', '급경사', '험준']
        self.elev_classes = 5
        self.cadastral_color = '#000000'
        self.cadastral_width = 0.5
        self.cadastral_alpha = 0.7
        self.boundary_color = '#FF0000'
        self.boundary_width = 2.5
        self.elev_step = 10  # 표고 범례 단위 (m)
        self.output_dir_override = ""  # 사용자가 선택한 출력 폴더
        self.viewport_x = 2000  # 가로 범위 (m)
        self.viewport_y = 1000  # 세로 범위 (m)

        self.build_ui()
        if HAS_WINDND:
            windnd.hook_dropfiles(self.root, func=self.on_drop)

    def build_ui(self):
        # 타이틀
        tf = tk.Frame(self.root, bg='#2C3E50', height=45)
        tf.pack(fill='x'); tf.pack_propagate(False)
        tk.Label(tf, text="표고 · 경사 분석 자동화 도구 v4",
                 font=('맑은 고딕', 13, 'bold'), fg='white', bg='#2C3E50').pack(expand=True)

        # 메인 2컬럼 레이아웃
        body = tk.Frame(self.root, bg='#F5F6FA')
        body.pack(fill='both', expand=True)
        left_panel = tk.Frame(body, bg='#F5F6FA', width=680)
        left_panel.pack(side='left', fill='both', expand=False)
        left_panel.pack_propagate(False)

        # 오른쪽 결과 패널
        right_panel = tk.Frame(body, bg='#FAFAFA', width=350, relief='groove', bd=1)
        right_panel.pack(side='right', fill='both', expand=True, padx=(0, 5), pady=5)
        tk.Label(right_panel, text="대상지 분석 결과", font=('맑은 고딕', 11, 'bold'),
                 bg='#34495E', fg='white', pady=5).pack(fill='x')
        self.result_text = scrolledtext.ScrolledText(right_panel, font=('맑은 고딕', 9),
            bg='#FAFAFA', fg='#2C3E50', wrap='word', state='disabled', height=40)
        self.result_text.pack(fill='both', expand=True, padx=5, pady=5)
        # 결과 복사 버튼
        tk.Button(right_panel, text="결과 복사", command=self.copy_result,
                  font=('맑은 고딕', 9), bg='#3498DB', fg='white', relief='flat', padx=10, cursor='hand2').pack(pady=(0, 5))

        # 드롭존 3개 (왼쪽 패널)
        drow = tk.Frame(left_panel, bg='#F5F6FA')
        drow.pack(fill='x', padx=10, pady=(8, 0))

        for i, (color, text, var_name) in enumerate([
            ('#E8F4FD', '▼ 수치지형도 ▼\n(DXF/SHP)', 'contour'),
            ('#F0FFF0', '▼ 지적도 SHP ▼\n(선택사항)', 'cadastral'),
            ('#FFF3E0', '▼ 구역계 ▼\n(SHP/DXF)', 'boundary'),
        ]):
            f = tk.Frame(drow, bg=color, relief='groove', bd=2, height=60)
            f.pack(side='left', fill='both', expand=True, padx=2)
            f.pack_propagate(False)
            lbl = tk.Label(f, text=text, font=('맑은 고딕', 9), fg='#666', bg=color, justify='center')
            lbl.pack(expand=True)
            setattr(self, f'drop_{var_name}', lbl)

        main = tk.Frame(left_panel, padx=12, pady=4, bg='#F5F6FA')
        main.pack(fill='both', expand=True)

        # 1) 수치지형도 (리스트)
        r1_hdr = tk.Frame(main, bg='#F5F6FA')
        r1_hdr.pack(fill='x')
        tk.Label(r1_hdr, text="1. 수치지형도 (DXF - 여러 개 가능)", font=('맑은 고딕', 10, 'bold'), bg='#F5F6FA').pack(side='left')
        tk.Button(r1_hdr, text="추가", command=lambda: self.browse('contour'),
                  font=('맑은 고딕', 8), bg='#3498DB', fg='white', relief='flat', padx=8, cursor='hand2').pack(side='right', padx=(3,0))
        tk.Button(r1_hdr, text="선택 삭제", command=self.remove_selected_dxf,
                  font=('맑은 고딕', 8), bg='#780000', fg='white', relief='flat', padx=8, cursor='hand2').pack(side='right', padx=(3,0))
        tk.Button(r1_hdr, text="전체 삭제", command=self.clear_all_dxf,
                  font=('맑은 고딕', 8), bg='#95A5A6', fg='white', relief='flat', padx=5, cursor='hand2').pack(side='right', padx=(3,0))
        self.dxf_listbox = tk.Listbox(main, height=3, font=('맑은 고딕', 8), selectmode='extended',
                                       bg='#FAFAFA', relief='groove', bd=1)
        self.dxf_listbox.pack(fill='x', pady=(1, 3))

        # 2) 표고 필드
        tk.Label(main, text="2. 표고 필드", font=('맑은 고딕', 10, 'bold'), bg='#F5F6FA').pack(anchor='w')
        self.field_combo = ttk.Combobox(main, textvariable=self.elev_field, state='readonly', font=('맑은 고딕', 9))
        self.field_combo.pack(fill='x', pady=(1, 3))

        # 3) 지적도 (여러 개 지원)
        r3_hdr = tk.Frame(main, bg='#F5F6FA')
        r3_hdr.pack(fill='x')
        tk.Label(r3_hdr, text="3. 지적도 SHP (선택 - 여러 개 가능)", font=('맑은 고딕', 10, 'bold'), bg='#F5F6FA').pack(side='left')
        tk.Button(r3_hdr, text="추가", command=lambda: self.browse('cadastral'),
                  font=('맑은 고딕', 8), bg='#27AE60', fg='white', relief='flat', padx=8, cursor='hand2').pack(side='right', padx=(3,0))
        tk.Button(r3_hdr, text="선택 삭제", command=self.remove_selected_cadastral,
                  font=('맑은 고딕', 8), bg='#780000', fg='white', relief='flat', padx=8, cursor='hand2').pack(side='right', padx=(3,0))
        tk.Button(r3_hdr, text="전체 삭제", command=self.clear_all_cadastral,
                  font=('맑은 고딕', 8), bg='#95A5A6', fg='white', relief='flat', padx=5, cursor='hand2').pack(side='right', padx=(3,0))
        self.cadastral_listbox = tk.Listbox(main, height=3, font=('맑은 고딕', 8), selectmode='extended',
                                             bg='#FAFAFA', relief='groove', bd=1)
        self.cadastral_listbox.pack(fill='x', pady=(1, 3))

        # 4) 구역계
        tk.Label(main, text="4. 구역계 (선택 - 분석 범위 제한)", font=('맑은 고딕', 10, 'bold'), bg='#F5F6FA').pack(anchor='w')
        r4 = tk.Frame(main, bg='#F5F6FA')
        r4.pack(fill='x', pady=(1, 3))
        tk.Entry(r4, textvariable=self.boundary_path, state='readonly', font=('맑은 고딕', 8)).pack(side='left', fill='x', expand=True)
        tk.Button(r4, text="찾기", command=lambda: self.browse('boundary'),
                  font=('맑은 고딕', 8), bg='#E67E22', fg='white', relief='flat', padx=8, cursor='hand2').pack(side='right', padx=(3,0))
        tk.Button(r4, text="X", command=lambda: self.clear_input('boundary'),
                  font=('맑은 고딕', 8), bg='#95A5A6', fg='white', relief='flat', padx=5, cursor='hand2').pack(side='right', padx=(3,0))
        self.boundary_info = tk.Label(main, text="", font=('맑은 고딕', 8), fg='#7F8C8D', bg='#F5F6FA')
        self.boundary_info.pack(anchor='w')

        # 5) 해상도
        tk.Label(main, text="5. DEM 해상도 (미터)", font=('맑은 고딕', 10, 'bold'), bg='#F5F6FA').pack(anchor='w')
        rf = tk.Frame(main, bg='#F5F6FA')
        rf.pack(fill='x', pady=(1, 3))
        tk.Scale(rf, from_=1, to=100, orient='horizontal', variable=self.resolution,
                 font=('맑은 고딕', 8), bg='#F5F6FA', highlightthickness=0, length=400).pack(side='left', fill='x', expand=True)
        tk.Label(rf, text="작을수록 정밀", font=('맑은 고딕', 8), fg='gray', bg='#F5F6FA').pack(side='right')

        # 6) 대상지 면적 수동 입력
        af = tk.Frame(main, bg='#F5F6FA')
        af.pack(fill='x', pady=(1, 3))
        tk.Label(af, text="대상지 면적(m²):", font=('맑은 고딕', 9, 'bold'), bg='#F5F6FA').pack(side='left')
        self.custom_area = tk.StringVar(value="")
        tk.Entry(af, textvariable=self.custom_area, font=('맑은 고딕', 9), width=12).pack(side='left', padx=5)
        tk.Label(af, text="비워두면 자동 계산  |  입력 시 해당 면적 기준 비율 산출", font=('맑은 고딕', 8), fg='gray', bg='#F5F6FA').pack(side='left')

        # 뷰포트 / 범례 설정
        vf = tk.Frame(main, bg='#F5F6FA')
        vf.pack(fill='x', pady=(2, 3))
        tk.Label(vf, text="이미지 범위:", font=('맑은 고딕', 9, 'bold'), bg='#F5F6FA').pack(side='left')
        tk.Label(vf, text="가로", font=('맑은 고딕', 8), bg='#F5F6FA').pack(side='left', padx=(5,0))
        self.viewport_x_var = tk.IntVar(value=self.viewport_x)
        tk.Entry(vf, textvariable=self.viewport_x_var, font=('맑은 고딕', 9), width=6).pack(side='left', padx=2)
        tk.Label(vf, text="m  세로", font=('맑은 고딕', 8), bg='#F5F6FA').pack(side='left')
        self.viewport_y_var = tk.IntVar(value=self.viewport_y)
        tk.Entry(vf, textvariable=self.viewport_y_var, font=('맑은 고딕', 9), width=6).pack(side='left', padx=2)
        tk.Label(vf, text="m", font=('맑은 고딕', 8), bg='#F5F6FA').pack(side='left')
        tk.Label(vf, text="  │  범례 단위:", font=('맑은 고딕', 9, 'bold'), bg='#F5F6FA').pack(side='left', padx=(10,0))
        self.elev_step_var = tk.IntVar(value=self.elev_step)
        step_combo = ttk.Combobox(vf, textvariable=self.elev_step_var, values=[5, 10, 15, 20, 25, 50], width=4, state='readonly')
        step_combo.pack(side='left', padx=2)
        tk.Label(vf, text="m", font=('맑은 고딕', 8), bg='#F5F6FA').pack(side='left')

        # 색상 설정 버튼
        tk.Button(main, text="색상 설정", command=self.open_color_editor,
            font=('맑은 고딕', 9), bg='#8E44AD', fg='white', relief='flat', padx=15, pady=2, cursor='hand2').pack(pady=(2, 4))

        # 출력 폴더 선택
        of = tk.Frame(main, bg='#F5F6FA')
        of.pack(fill='x', pady=(2, 3))
        tk.Label(of, text="출력 폴더:", font=('맑은 고딕', 9, 'bold'), bg='#F5F6FA').pack(side='left')
        self.output_dir_display = tk.StringVar(value="(기본값: 입력파일 폴더/분석결과)")
        tk.Label(of, textvariable=self.output_dir_display, font=('맑은 고딕', 8), fg='#666', bg='#F5F6FA').pack(side='left', padx=5, fill='x', expand=True)
        tk.Button(of, text="찾기", command=self.browse_output_dir,
                  font=('맑은 고딕', 8), bg='#16A085', fg='white', relief='flat', padx=8, cursor='hand2').pack(side='right', padx=(3,0))
        tk.Button(of, text="X", command=self.clear_output_dir,
                  font=('맑은 고딕', 8), bg='#95A5A6', fg='white', relief='flat', padx=5, cursor='hand2').pack(side='right', padx=(3,0))

        # 실행
        self.run_btn = tk.Button(main, text="분석 시작", command=self.start,
            font=('맑은 고딕', 11, 'bold'), bg='#27AE60', fg='white', relief='flat', padx=25, pady=4, cursor='hand2')
        self.run_btn.pack(pady=5)

        self.progress = ttk.Progressbar(main, mode='determinate', length=640)
        self.progress.pack(fill='x', pady=(0, 2))
        self.status_var = tk.StringVar(value="수치지형도 SHP를 드래그앤드롭 하세요.")
        tk.Label(main, textvariable=self.status_var, font=('맑은 고딕', 9), fg='#7F8C8D', bg='#F5F6FA').pack(anchor='w')

        lf = tk.Frame(main, bg='#F5F6FA')
        lf.pack(fill='x', pady=(3, 0))
        tk.Label(lf, text="로그", font=('맑은 고딕', 9, 'bold'), bg='#F5F6FA').pack(side='left')
        tk.Button(lf, text="복사", command=self.copy_log,
                  font=('맑은 고딕', 8), bg='#95A5A6', fg='white', relief='flat', padx=6, cursor='hand2').pack(side='right')
        self.log_text = scrolledtext.ScrolledText(main, height=7, font=('Consolas', 9),
            bg='#1E1E1E', fg='#D4D4D4', wrap='word')
        self.log_text.pack(fill='x', pady=(2, 0))

    def log(self, msg):
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log_text.get("1.0", tk.END))

    def copy_result(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.result_text.get("1.0", tk.END))
        self.status_var.set("결과가 클립보드에 복사되었습니다.")

    def show_target_stats(self, output_dir):
        """대상지 통계 JSON 읽어서 결과 패널에 표시"""
        stats_json = os.path.join(output_dir, '_target_stats.json')
        self.result_text.config(state='normal')
        self.result_text.delete('1.0', tk.END)

        if os.path.isfile(stats_json):
            with open(stats_json, 'r', encoding='utf-8') as f:
                s = json.load(f)

            use_area = s['use_area']
            lines = []
            lines.append("━" * 32)
            lines.append("   대 상 지  분 석  결 과")
            lines.append("━" * 32)
            lines.append("")
            if s['custom_area'] > 0:
                lines.append(f"  자동 계산: {s['calc_area']:,.2f} m²")
                lines.append(f"  수동 입력: {s['custom_area']:,.2f} m² ← 적용")
            else:
                lines.append(f"  면적: {use_area:,.2f} m²")
            lines.append(f"        ({use_area/10000:.2f} ha)")
            lines.append("")
            lines.append("─" * 32)
            lines.append("  [ 표 고 ]")
            lines.append("─" * 32)
            lines.append(f"  최저:  {s['elev_min']:.2f} m")
            lines.append(f"  최고:  {s['elev_max']:.2f} m")
            lines.append(f"  평균:  {s['elev_avg']:.2f} m")
            lines.append(f"  표고차: {s['elev_diff']:.2f} m")
            lines.append("")
            lines.append("─" * 32)
            lines.append("  [ 표고 면적 비율 ]")
            lines.append("─" * 32)
            for c in s.get('elev_classes', []):
                lines.append(f"  {c['range']}")
                lines.append(f"    {c['pct']:.2f}%  |  {c['area']:,.2f} m²")
            lines.append("")
            lines.append("─" * 32)
            lines.append("  [ 경 사 ]")
            lines.append("─" * 32)
            lines.append(f"  최소:  {s['slope_min']:.2f}°")
            lines.append(f"  최대:  {s['slope_max']:.2f}°")
            lines.append(f"  평균:  {s['slope_avg']:.2f}°")
            lines.append("")
            lines.append("─" * 32)
            lines.append("  [ 경사도 면적 비율 ]")
            lines.append("─" * 32)
            for c in s.get('slope_classes', s.get('classes', [])):
                lines.append(f"  {c.get('name','')} ({c['range']})")
                lines.append(f"    {c['pct']:.2f}%  |  {c['area']:,.2f} m²")
            lines.append("")
            lines.append("━" * 32)

            self.result_text.insert(tk.END, "\n".join(lines))
        else:
            self.result_text.insert(tk.END, "구역계가 없거나\n대상지 내부 데이터가 없습니다.\n\n구역계 SHP/DXF를 넣으면\n대상지 분석 결과가 여기에 표시됩니다.")

        self.result_text.config(state='disabled')

    # ── 파일 입력 ──
    def _guess_shp_type(self, path):
        """SHP 파일명/내용으로 종류 자동 판별"""
        name = os.path.basename(path).lower()
        # 등고선/수치지형도 키워드
        if any(k in name for k in ['f001', 'contour', '등고', '지형도', 'cont', 'dem', 'elev']):
            return 'contour'
        # 지적/토지 키워드
        if any(k in name for k in ['al_d', '토지', '지적', 'land', 'parcel', 'cadastr']):
            return 'cadastral'
        # 구역계 키워드
        if any(k in name for k in ['구역', 'boundary', 'border', 'area', '경계']):
            return 'boundary'
        # 빈 슬롯 순서로 자동 배정
        if not self.contour_path.get():
            return 'contour'
        if not self.cadastral_path.get():
            return 'cadastral'
        if not self.boundary_path.get():
            return 'boundary'
        return 'contour'

    def on_drop(self, files):
        for raw in files:
            path = normalize_path(decode_drop(raw))
            ext = os.path.splitext(path)[1].lower()
            self.log(f"[드롭] {os.path.basename(path)}")

            if ext == '.dxf':
                bn_lower = os.path.basename(path).lower()
                if any(k in bn_lower for k in ['구역', 'boundary', 'border', '경계', 'area']):
                    self.load_file(path, 'boundary')
                else:
                    self.load_file(path, 'contour')
            elif ext == '.shp':
                kind = self._guess_shp_type(path)
                self.log(f"  → 자동 판별: {kind}")
                if kind == 'cadastral':
                    actual = path
                    if needs_local_copy(path):
                        self.log(f"[복사] 로컬로 복사 중...")
                        actual, td = copy_shp_local(path)
                        if actual:
                            self.temp_dirs.append(td)
                        else:
                            self.log("[오류] SHP 복사 실패")
                            continue
                    self.add_cadastral_file(path, actual)
                else:
                    self.load_file(path, kind)
            elif ext in IMAGE_EXTS:
                self.load_file(path, 'boundary')

    def browse(self, kind):
        if kind == 'contour':
            ft = [("수치지형도", "*.dxf *.shp"), ("DXF", "*.dxf"), ("Shapefiles", "*.shp")]
        elif kind == 'boundary':
            ft = [("구역계", "*.shp *.dxf *.png *.jpg"), ("Shapefiles", "*.shp"), ("DXF", "*.dxf"), ("이미지", "*.png *.jpg")]
        elif kind == 'cadastral':
            ft = [("지적도", "*.shp"), ("모든 파일", "*.*")]
            paths = filedialog.askopenfilenames(filetypes=ft)
            for p in paths:
                actual = p
                if needs_local_copy(p):
                    actual, td = copy_shp_local(p)
                    if actual:
                        self.temp_dirs.append(td)
                    else:
                        continue
                self.add_cadastral_file(p, actual)
            return
        else:
            ft = [("Shapefiles", "*.shp")]
        path = filedialog.askopenfilename(filetypes=ft + [("모든 파일", "*.*")])
        if path:
            self.load_file(path, kind)

    def remove_selected_dxf(self):
        selected = list(self.dxf_listbox.curselection())
        if not selected:
            return
        for idx in reversed(selected):
            name = os.path.basename(self.dxf_files[idx])
            del self.dxf_files[idx]
            self.dxf_listbox.delete(idx)
            self.log(f"[수치지형도] 삭제: {name}")
        if self.dxf_files:
            self.contour_path.set(f"{len(self.dxf_files)}개 DXF")
        else:
            self.contour_path.set("")

    def clear_all_dxf(self):
        self.dxf_files.clear()
        self.dxf_listbox.delete(0, tk.END)
        self.contour_path.set("")
        self.elev_field.set("")
        self.log("[수치지형도] 전체 삭제")

    def add_cadastral_file(self, path, actual_path=None):
        """지적도 SHP를 리스트에 추가"""
        display = os.path.basename(path)
        # 중복 체크
        for cf in self.cadastral_files:
            if cf['display'] == display:
                self.log(f"[지적도] 이미 추가됨: {display}")
                return
        entry = {'original': path, 'actual': actual_path or path, 'display': display}
        self.cadastral_files.append(entry)
        self.cadastral_listbox.insert(tk.END, display)
        self.cadastral_path.set(f"{len(self.cadastral_files)}개 지적도")
        self.log(f"[지적도] 추가: {display} (총 {len(self.cadastral_files)}개)")

    def remove_selected_cadastral(self):
        """선택된 지적도 삭제"""
        selected = list(self.cadastral_listbox.curselection())
        if not selected:
            return
        for idx in reversed(selected):
            name = self.cadastral_files[idx]['display']
            del self.cadastral_files[idx]
            self.cadastral_listbox.delete(idx)
            self.log(f"[지적도] 삭제: {name}")
        if self.cadastral_files:
            self.cadastral_path.set(f"{len(self.cadastral_files)}개 지적도")
        else:
            self.cadastral_path.set("")

    def clear_all_cadastral(self):
        """전체 지적도 삭제"""
        self.cadastral_files.clear()
        self.cadastral_listbox.delete(0, tk.END)
        self.cadastral_path.set("")
        self.log("[지적도] 전체 삭제")

    def clear_input(self, kind):
        getattr(self, f'{kind}_path').set("")
        getattr(self, f'drop_{kind}').config(
            text={'cadastral': '▼ 지적도 SHP ▼\n(선택사항)',
                  'boundary': '▼ 구역계 ▼\n(SHP/이미지)'}[kind],
            fg='#666')
        if kind == 'boundary':
            self.boundary_type = None
            self.boundary_info.config(text="")
        self.actual_paths.pop(kind, None)
        self.original_paths.pop(kind, None)

    def load_file(self, path, kind):
        path = normalize_path(path)
        self.original_paths[kind] = path
        ext = os.path.splitext(path)[1].lower()

        # 이미지 구역계
        if ext in IMAGE_EXTS and kind == 'boundary':
            self.boundary_path.set(path)
            self.boundary_type = 'image'
            self.actual_paths['boundary'] = path
            self.drop_boundary.config(text=os.path.basename(path), fg='#2C3E50', font=('맑은 고딕', 9, 'bold'))
            self.boundary_info.config(text="  이미지 → 오버레이만 (클리핑은 SHP 구역계 필요)", fg='#E67E22')
            self.log(f"[구역계] 이미지: {os.path.basename(path)}")
            return

        # DXF 구역계
        if ext == '.dxf' and kind == 'boundary':
            actual = path
            if needs_local_copy(path):
                td = tempfile.mkdtemp(prefix="bdxf_")
                dst = os.path.join(td, os.path.basename(path))
                shutil.copy2(path, dst)
                actual = dst
                self.temp_dirs.append(td)
            self.actual_paths['boundary'] = actual
            self.boundary_path.set(path)
            self.boundary_type = 'dxf'
            self.drop_boundary.config(text=os.path.basename(path), fg='#2C3E50', font=('맑은 고딕', 9, 'bold'))
            self.boundary_info.config(text="  DXF 구역계 로드 완료", fg='#27AE60')
            # 수치지형도 목록에 이미 들어갔으면 제거
            bn = os.path.basename(path)
            self.dxf_files = [f for f in self.dxf_files if os.path.basename(f) != bn]
            if self.dxf_files:
                self.contour_path.set(f"{len(self.dxf_files)}개 DXF 파일")
                self.drop_contour.config(text=f"DXF {len(self.dxf_files)}개")
            self.log(f"[구역계] DXF: {bn} (수치지형도 목록에서 제거됨)")
            return

        # DXF 처리 (여러 개 누적 가능 - 수치지형도용)
        if ext == '.dxf':
            actual = path
            if needs_local_copy(path):
                self.log("[복사] DXF 로컬 복사 중...")
                td = tempfile.mkdtemp(prefix="dxf_")
                dst = os.path.join(td, os.path.basename(path))
                shutil.copy2(path, dst)
                actual = dst
                self.temp_dirs.append(td)
            self.dxf_files.append(actual)
            self.dxf_listbox.insert(tk.END, os.path.basename(path))
            self.contour_path.set(f"{len(self.dxf_files)}개 DXF")
            self.drop_contour.config(text=f"DXF {len(self.dxf_files)}개", fg='#2C3E50', font=('맑은 고딕', 9, 'bold'))
            self.field_combo['values'] = ['(DXF: Z좌표 자동)']
            self.field_combo.set('(DXF: Z좌표 자동)')
            self.elev_field.set('__DXF_Z__')
            self.status_var.set(f"DXF {len(self.dxf_files)}개 로드됨")
            self.log(f"[수치지형도] DXF #{len(self.dxf_files)}: {os.path.basename(path)}")
            return

        # SHP 처리
        actual = path
        if needs_local_copy(path):
            self.log(f"[복사] 로컬로 복사 중...")
            actual, td = copy_shp_local(path)
            if actual:
                self.temp_dirs.append(td)
            else:
                messagebox.showerror("오류", "파일을 읽을 수 없습니다.")
                return

        self.actual_paths[kind] = actual
        getattr(self, f'{kind}_path').set(path)
        getattr(self, f'drop_{kind}').config(text=os.path.basename(path), fg='#2C3E50', font=('맑은 고딕', 9, 'bold'))

        # SHP 정보 읽기
        try:
            sf = None
            for enc in ['euc-kr', 'cp949', 'utf-8', 'utf-8-sig', 'latin-1']:
                try:
                    sf = shapefile.Reader(actual, encoding=enc)
                    break
                except Exception:
                    continue
            if sf is None:
                return

            fi = sf.fields[1:]
            fnames = [f[0] for f in fi]
            ftypes = [f[1] for f in fi]
            self.log(f"[{kind}] {len(sf):,}피처, {sf.shapeTypeName}, 필드: {fnames[:8]}")

            if kind == 'contour':
                numeric = [n for n, t in zip(fnames, ftypes) if t in ('N', 'F', 'L')]
                self.field_combo['values'] = numeric
                det = detect_elev_field(fnames, ftypes)
                if det and det in numeric:
                    self.field_combo.set(det)
                elif numeric:
                    self.field_combo.set(numeric[0])
                self.status_var.set(f"수치지형도: {len(sf):,}피처 | {sf.shapeTypeName}")

            elif kind == 'boundary':
                self.boundary_type = 'shp'
                self.boundary_info.config(text=f"  SHP 구역계: {len(sf.shapes())}폴리곤", fg='#27AE60')

        except Exception as e:
            self.log(f"[오류] {e}")

    # ── 분석 ──
    def start(self):
        if not self.contour_path.get() and not self.dxf_files:
            messagebox.showwarning("필수", "수치지형도 DXF/SHP를 먼저 넣어주세요.")
            return
        if not self.elev_field.get():
            messagebox.showwarning("필수", "표고 필드를 선택하세요.")
            return

        # 출력 폴더
        if self.output_dir_override:
            od = self.output_dir_override
            try:
                os.makedirs(od, exist_ok=True)
                with open(os.path.join(od, ".t"), 'w') as f: f.write("t")
                os.remove(os.path.join(od, ".t"))
            except Exception:
                messagebox.showerror("출력 폴더 오류", f"폴더에 쓰기 권한이 없습니다:\n{od}\n\n기본값을 사용합니다.")
                od = os.path.join(os.path.dirname(self.original_paths.get('contour', os.getcwd())), "분석결과")
                os.makedirs(od, exist_ok=True)
        else:
            try:
                od = os.path.join(os.path.dirname(self.original_paths.get('contour', os.getcwd())), "분석결과")
                os.makedirs(od, exist_ok=True)
                with open(os.path.join(od, ".t"), 'w') as f: f.write("t")
                os.remove(os.path.join(od, ".t"))
            except Exception:
                od = os.path.join(os.path.expanduser("~"), "Desktop", "분석결과")
                os.makedirs(od, exist_ok=True)

        self.progress_file = os.path.join(tempfile.gettempdir(), "terrain_progress.json")
        params = {
            'contour_path': self.actual_paths.get('contour', ''),
            'dxf_files': self.dxf_files,  # DXF 여러 개
            'cadastral_path': [cf['actual'] for cf in self.cadastral_files] if self.cadastral_files else None,
            'boundary_path': self.actual_paths.get('boundary'),
            'boundary_type': self.boundary_type,
            'elev_field': self.elev_field.get(),
            'resolution': self.resolution.get(),
            'output_dir': od,
            'progress_file': self.progress_file,
            'original_contour': self.original_paths.get('contour', ''),
            'original_cadastral': self.original_paths.get('cadastral', ''),
            'elev_colors': self.elev_colors,
            'slope_colors': self.slope_colors,
            'slope_bounds': self.slope_bounds,
            'slope_labels': self.slope_labels,
            'elev_classes': self.elev_classes,
            'cadastral_color': self.cadastral_color,
            'cadastral_width': self.cadastral_width,
            'cadastral_alpha': self.cadastral_alpha,
            'boundary_color': self.boundary_color,
            'boundary_width': self.boundary_width,
            'elev_step': self.elev_step_var.get(),
            'viewport_x': self.viewport_x_var.get(),
            'viewport_y': self.viewport_y_var.get(),
            'custom_area': float(self.custom_area.get()) if self.custom_area.get().strip() else 0,
        }
        pf = os.path.join(tempfile.gettempdir(), "terrain_params.json")
        with open(pf, 'w', encoding='utf-8') as f:
            json.dump(params, f, ensure_ascii=False)

        self.log(f"\n{'='*50}")
        contour_name = os.path.basename(params['contour_path']) if params['contour_path'] else f"DXF {len(params.get('dxf_files',[]))}개"
        self.log(f"[분석] 등고선={contour_name}")
        cad_paths = params.get('cadastral_path')
        if cad_paths:
            if isinstance(cad_paths, list):
                self.log(f"[분석] 지적도={len(cad_paths)}개 SHP")
            else:
                self.log(f"[분석] 지적도={os.path.basename(cad_paths)}")
        if params['boundary_path']:
            self.log(f"[분석] 구역계={self.boundary_type}")
        self.log(f"[분석] 해상도={params['resolution']}m, 출력={od}")

        self.run_btn.config(state='disabled', text='분석 중...')
        self.output_dir = od
        self._last_msg = ''

        with open(self.progress_file, 'w', encoding='utf-8') as f:
            json.dump({'step': 0, 'pct': 0, 'msg': '시작...', 'done': False, 'error': None}, f)

        self.process = subprocess.Popen(
            [sys.executable, '--compute', pf],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)

        self.root.after(500, self.poll)

    def poll(self):
        try:
            if os.path.isfile(self.progress_file):
                with open(self.progress_file, 'r', encoding='utf-8') as f:
                    p = json.load(f)
                self.progress['value'] = p.get('pct', 0)
                msg = p.get('msg', '')
                self.status_var.set(msg)
                if msg != self._last_msg:
                    self.log(f"  [{p.get('step','?')}] {msg}")
                    self._last_msg = msg
                if p.get('done'):
                    err = p.get('error')
                    if err:
                        self.log(f"[오류] {err}")
                        messagebox.showerror("오류", f"분석 실패:\n{err[:300]}")
                    else:
                        self.log("[완료!]")
                        self.progress['value'] = 100
                        self.show_target_stats(self.output_dir)
                        messagebox.showinfo("완료", f"분석 완료!\n\n{self.output_dir}")
                        try: os.startfile(self.output_dir)
                        except: pass
                    self.run_btn.config(state='normal', text='분석 시작')
                    try: os.remove(self.progress_file)
                    except: pass
                    return
        except Exception:
            pass
        if self.process and self.process.poll() is not None and self.process.returncode != 0:
            stderr = ""
            try: stderr = self.process.stderr.read().decode('utf-8', errors='replace')[-400:]
            except: pass
            self.log(f"[오류] 프로세스 종료 ({self.process.returncode})\n{stderr}")
            self.run_btn.config(state='normal', text='분석 시작')
            return
        self.root.after(800, self.poll)

    # ── 컬러 에디터 ──
    def open_color_editor(self):
        from tkinter import colorchooser
        win = tk.Toplevel(self.root)
        win.title("색상 설정")
        win.geometry("520x760")
        win.resizable(False, False)
        win.configure(bg='#F5F6FA')
        win.grab_set()

        # --- 표고분석도 ---
        tk.Label(win, text="표고분석도 색상", font=('맑은 고딕', 11, 'bold'), bg='#F5F6FA').pack(anchor='w', padx=10, pady=(8, 2))

        elev_frame = tk.Frame(win, bg='#F5F6FA')
        elev_frame.pack(fill='x', padx=10)
        elev_btns = []
        for i, c in enumerate(self.elev_colors):
            def make_cb(idx):
                def cb():
                    result = colorchooser.askcolor(color=self.elev_colors[idx], title=f"표고 색상 {idx+1}")
                    if result[1]:
                        self.elev_colors[idx] = result[1]
                        elev_btns[idx].config(bg=result[1])
                        self._update_preview(elev_canvas, slope_canvas)
                return cb
            btn = tk.Button(elev_frame, text=f" {i+1} ", bg=c, width=5, relief='raised',
                           command=make_cb(i), cursor='hand2')
            btn.pack(side='left', padx=2, pady=2)
            elev_btns.append(btn)

        # 범례 구간
        ecf = tk.Frame(win, bg='#F5F6FA')
        ecf.pack(fill='x', padx=10, pady=(2, 0))
        tk.Label(ecf, text="표고 단위:", font=('맑은 고딕', 9), bg='#F5F6FA').pack(side='left')
        elev_step_var = tk.IntVar(value=self.elev_step_var.get())
        esb = ttk.Combobox(ecf, textvariable=elev_step_var, values=[5, 10, 15, 20, 25, 50], width=4, state='readonly')
        esb.pack(side='left', padx=3)
        tk.Label(ecf, text="m", font=('맑은 고딕', 9), bg='#F5F6FA').pack(side='left')
        tk.Label(ecf, text="    구간 수:", font=('맑은 고딕', 9), bg='#F5F6FA').pack(side='left')
        elev_class_var = tk.IntVar(value=self.elev_classes)
        ecb = ttk.Combobox(ecf, textvariable=elev_class_var, values=[3,4,5,6,7,8,10], width=4, state='readonly')
        ecb.pack(side='left', padx=3)
        ecb.bind('<<ComboboxSelected>>', lambda e: self._on_elev_class_change(elev_class_var, elev_canvas, slope_canvas))

        # 표고 프리뷰 캔버스
        tk.Label(win, text="프리뷰", font=('맑은 고딕', 9), bg='#F5F6FA', fg='gray').pack(anchor='w', padx=10)
        elev_canvas = tk.Canvas(win, width=480, height=80, bg='white', highlightthickness=1, highlightbackground='#ccc')
        elev_canvas.pack(padx=10, pady=(0, 5))

        # --- 경사분석도 ---
        tk.Label(win, text="경사분석도 색상", font=('맑은 고딕', 11, 'bold'), bg='#F5F6FA').pack(anchor='w', padx=10, pady=(8, 2))

        slope_frame = tk.Frame(win, bg='#F5F6FA')
        slope_frame.pack(fill='x', padx=10)
        slope_btns = []
        for i, (c, lbl) in enumerate(zip(self.slope_colors, self.slope_labels)):
            def make_scb(idx):
                def cb():
                    result = colorchooser.askcolor(color=self.slope_colors[idx], title=f"{self.slope_labels[idx]} 색상")
                    if result[1]:
                        self.slope_colors[idx] = result[1]
                        slope_btns[idx].config(bg=result[1])
                        self._update_preview(elev_canvas, slope_canvas)
                return cb
            bf = tk.Frame(slope_frame, bg='#F5F6FA')
            bf.pack(side='left', padx=3)
            btn = tk.Button(bf, text="  ", bg=c, width=4, relief='raised',
                           command=make_scb(i), cursor='hand2')
            btn.pack()
            tk.Label(bf, text=lbl, font=('맑은 고딕', 8), bg='#F5F6FA').pack()
            slope_btns.append(btn)

        # 경사 각도 구분 (bounds[1] ~ bounds[-2])
        saf = tk.Frame(win, bg='#F5F6FA')
        saf.pack(fill='x', padx=10, pady=(5, 0))
        tk.Label(saf, text="경사 구분(°):", font=('맑은 고딕', 9), bg='#F5F6FA').pack(side='left')
        slope_entries = []
        for i in range(1, len(self.slope_bounds) - 1):
            sv = tk.StringVar(value=str(self.slope_bounds[i]))
            e = tk.Entry(saf, textvariable=sv, width=4, font=('맑은 고딕', 9), justify='center')
            e.pack(side='left', padx=2)
            slope_entries.append(sv)

        # 경사 프리뷰 캔버스
        tk.Label(win, text="프리뷰", font=('맑은 고딕', 9), bg='#F5F6FA', fg='gray').pack(anchor='w', padx=10)
        slope_canvas = tk.Canvas(win, width=480, height=80, bg='white', highlightthickness=1, highlightbackground='#ccc')
        slope_canvas.pack(padx=10, pady=(0, 5))

        # --- 지적선 설정 ---
        tk.Label(win, text="지적선 설정", font=('맑은 고딕', 11, 'bold'), bg='#F5F6FA').pack(anchor='w', padx=10, pady=(8, 2))
        cad_frame = tk.Frame(win, bg='#F5F6FA')
        cad_frame.pack(fill='x', padx=10)

        tk.Label(cad_frame, text="색상:", font=('맑은 고딕', 9), bg='#F5F6FA').pack(side='left')
        cad_color_btn = tk.Button(cad_frame, text="  ", bg=self.cadastral_color, width=4, relief='raised', cursor='hand2')
        cad_color_btn.pack(side='left', padx=3)
        def pick_cad_color():
            result = colorchooser.askcolor(color=self.cadastral_color, title="지적선 색상")
            if result[1]:
                self.cadastral_color = result[1]
                cad_color_btn.config(bg=result[1])
        cad_color_btn.config(command=pick_cad_color)

        tk.Label(cad_frame, text="  두께:", font=('맑은 고딕', 9), bg='#F5F6FA').pack(side='left')
        cad_width_var = tk.DoubleVar(value=self.cadastral_width)
        tk.Scale(cad_frame, from_=0.1, to=3.0, orient='horizontal', variable=cad_width_var,
                 resolution=0.1, font=('맑은 고딕', 7), bg='#F5F6FA', highlightthickness=0, length=100).pack(side='left')

        tk.Label(cad_frame, text="  투명도:", font=('맑은 고딕', 9), bg='#F5F6FA').pack(side='left')
        cad_alpha_var = tk.DoubleVar(value=self.cadastral_alpha)
        tk.Scale(cad_frame, from_=0.1, to=1.0, orient='horizontal', variable=cad_alpha_var,
                 resolution=0.1, font=('맑은 고딕', 7), bg='#F5F6FA', highlightthickness=0, length=100).pack(side='left')

        # --- 구역계 설정 ---
        tk.Label(win, text="구역계 설정", font=('맑은 고딕', 11, 'bold'), bg='#F5F6FA').pack(anchor='w', padx=10, pady=(8, 2))
        bnd_frame = tk.Frame(win, bg='#F5F6FA')
        bnd_frame.pack(fill='x', padx=10)

        tk.Label(bnd_frame, text="색상:", font=('맑은 고딕', 9), bg='#F5F6FA').pack(side='left')
        bnd_color_btn = tk.Button(bnd_frame, text="  ", bg=self.boundary_color, width=4, relief='raised', cursor='hand2')
        bnd_color_btn.pack(side='left', padx=3)
        def pick_bnd_color():
            result = colorchooser.askcolor(color=self.boundary_color, title="구역계 색상")
            if result[1]:
                self.boundary_color = result[1]
                bnd_color_btn.config(bg=result[1])
        bnd_color_btn.config(command=pick_bnd_color)

        tk.Label(bnd_frame, text="  두께:", font=('맑은 고딕', 9), bg='#F5F6FA').pack(side='left')
        bnd_width_var = tk.DoubleVar(value=self.boundary_width)
        tk.Scale(bnd_frame, from_=0.5, to=5.0, orient='horizontal', variable=bnd_width_var,
                 resolution=0.5, font=('맑은 고딕', 7), bg='#F5F6FA', highlightthickness=0, length=100).pack(side='left')

        # 초기 프리뷰
        self._update_preview(elev_canvas, slope_canvas)

        # 버튼
        btn_frame = tk.Frame(win, bg='#F5F6FA')
        btn_frame.pack(pady=10)

        def apply_and_close():
            # 경사 각도 적용
            try:
                new_bounds = [0]
                for sv in slope_entries:
                    new_bounds.append(int(sv.get()))
                new_bounds.append(90)
                self.slope_bounds = new_bounds
            except ValueError:
                pass
            self.elev_classes = elev_class_var.get()
            self.elev_step = elev_step_var.get()
            self.elev_step_var.set(elev_step_var.get())  # 메인 UI 동기화
            self.cadastral_width = cad_width_var.get()
            self.cadastral_alpha = cad_alpha_var.get()
            self.boundary_width = bnd_width_var.get()
            win.destroy()

        def reset_defaults():
            self.elev_colors = ['#228B22', '#6BBD45', '#FFFF96', '#DEB887', '#A5714E', '#F0F0F0']
            self.slope_colors = ['#38A800', '#CDFF00', '#FFFF00', '#FFAA00', '#FF0000', '#A80000']
            self.slope_bounds = [0, 5, 10, 15, 20, 25, 90]
            self.slope_labels = ['평지', '완경사', '약간경사', '경사', '급경사', '험준']
            self.elev_classes = 5
            self.elev_step = 10
            elev_step_var.set(10)
            self.elev_step_var.set(10)
            self.cadastral_color = '#000000'
            self.cadastral_width = 0.5
            self.cadastral_alpha = 0.7
            for i, btn in enumerate(elev_btns):
                btn.config(bg=self.elev_colors[i])
            for i, btn in enumerate(slope_btns):
                btn.config(bg=self.slope_colors[i])
            for i, sv in enumerate(slope_entries):
                sv.set(str(self.slope_bounds[i+1]))
            elev_class_var.set(5)
            cad_color_btn.config(bg='#000000')
            cad_width_var.set(0.5)
            cad_alpha_var.set(0.7)
            self.boundary_color = '#FF0000'
            self.boundary_width = 2.5
            bnd_color_btn.config(bg='#FF0000')
            bnd_width_var.set(2.5)
            self._update_preview(elev_canvas, slope_canvas)

        tk.Button(btn_frame, text="적용", command=apply_and_close,
                  font=('맑은 고딕', 10, 'bold'), bg='#27AE60', fg='white', relief='flat', padx=20, cursor='hand2').pack(side='left', padx=5)
        tk.Button(btn_frame, text="초기화", command=reset_defaults,
                  font=('맑은 고딕', 10), bg='#95A5A6', fg='white', relief='flat', padx=15, cursor='hand2').pack(side='left', padx=5)

    def _on_elev_class_change(self, var, ec, sc):
        self.elev_classes = var.get()
        self._update_preview(ec, sc)

    def _update_preview(self, elev_canvas, slope_canvas):
        # 표고 프리뷰: 그라데이션 + 범례
        elev_canvas.delete('all')
        w, h = 480, 80
        n = len(self.elev_colors)
        bar_h = 30
        for i in range(w - 20):
            t = i / (w - 21)
            idx = t * (n - 1)
            lo = int(idx)
            hi = min(lo + 1, n - 1)
            frac = idx - lo
            c1 = self._hex_to_rgb(self.elev_colors[lo])
            c2 = self._hex_to_rgb(self.elev_colors[hi])
            r = int(c1[0] + (c2[0] - c1[0]) * frac)
            g = int(c1[1] + (c2[1] - c1[1]) * frac)
            b = int(c1[2] + (c2[2] - c1[2]) * frac)
            color = f'#{r:02x}{g:02x}{b:02x}'
            elev_canvas.create_line(10 + i, 5, 10 + i, 5 + bar_h, fill=color)
        elev_canvas.create_text(10, 5 + bar_h + 5, text="낮음", anchor='nw', font=('맑은 고딕', 8))
        elev_canvas.create_text(w - 10, 5 + bar_h + 5, text="높음", anchor='ne', font=('맑은 고딕', 8))
        # 범례 샘플
        nc = self.elev_classes
        bw = (w - 40) // nc
        for i in range(nc):
            t = (i + 0.5) / nc
            idx = t * (n - 1)
            lo = int(idx)
            hi = min(lo + 1, n - 1)
            frac = idx - lo
            c1 = self._hex_to_rgb(self.elev_colors[lo])
            c2 = self._hex_to_rgb(self.elev_colors[hi])
            r = int(c1[0] + (c2[0] - c1[0]) * frac)
            g = int(c1[1] + (c2[1] - c1[1]) * frac)
            b = int(c1[2] + (c2[2] - c1[2]) * frac)
            color = f'#{r:02x}{g:02x}{b:02x}'
            x0 = 20 + i * bw
            elev_canvas.create_rectangle(x0, 50, x0 + bw - 2, 70, fill=color, outline='gray')
            elev_canvas.create_text(x0 + bw // 2, 73, text=f"구간{i+1}", font=('맑은 고딕', 7), anchor='n')

        # 경사 프리뷰: 5단계 블록
        slope_canvas.delete('all')
        nc = len(self.slope_colors)
        bw = (w - 40) // nc
        for i in range(nc):
            x0 = 20 + i * bw
            slope_canvas.create_rectangle(x0, 5, x0 + bw - 2, 35, fill=self.slope_colors[i], outline='gray')
            lo = self.slope_bounds[i] if i < len(self.slope_bounds) else 0
            hi = self.slope_bounds[i + 1] if i + 1 < len(self.slope_bounds) else 90
            lbl = self.slope_labels[i] if i < len(self.slope_labels) else ''
            slope_canvas.create_text(x0 + bw // 2, 40, text=f"{lbl}", font=('맑은 고딕', 8), anchor='n')
            slope_canvas.create_text(x0 + bw // 2, 55, text=f"{lo}~{hi}°", font=('맑은 고딕', 7), anchor='n', fill='gray')

    # ── 출력 폴더 선택 ──
    def browse_output_dir(self):
        from tkinter import filedialog
        folder = filedialog.askdirectory(title="출력 폴더 선택")
        if folder:
            self.output_dir_override = folder
            self.output_dir_display.set(f"({folder})")
            self.log(f"[출력] 폴더 지정: {folder}")

    def clear_output_dir(self):
        self.output_dir_override = ""
        self.output_dir_display.set("(기본값: 입력파일 폴더/분석결과)")
        self.log("[출력] 폴더 선택 취소 (기본값 사용)")

    @staticmethod
    def _hex_to_rgb(h):
        h = h.lstrip('#')
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

    def run(self):
        try:
            self.root.mainloop()
        finally:
            for td in self.temp_dirs:
                try: shutil.rmtree(td)
                except: pass

if __name__ == '__main__':
    App().run()
