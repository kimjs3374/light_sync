"""
illuminance_pdf_parser.py
Relux 시뮬레이션 PDF에서 조도설계 데이터를 추출합니다.

지원 형식:
- 3-4자리 정수 격자 (풋살장 400~800 lx)
- 2-3자리 정수 격자 (주차장·보행로 13~200 lx)
- 소수점 1자리 격자 (직선조도 88.8 lx)
- 붙어있는 소수열 (71.878.184.6 → 71.8, 78.1, 84.6)
- 소형 격자 (테니스장 5×3, 3×3 등)
"""
import re
import json
from collections import Counter

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


KS_STANDARDS = {
    # 스포츠시설 (KS A 3011)
    '풋살장':        {'eav': 300, 'uo': 0.50},
    '풋살장_훈련':   {'eav': 300, 'uo': 0.50},
    '풋살장_경기':   {'eav': 500, 'uo': 0.60},
    '축구장':        {'eav': 200, 'uo': 0.50},
    '축구장_훈련':   {'eav': 200, 'uo': 0.50},
    '테니스장':      {'eav': 300, 'uo': 0.60},
    '테니스장_경기': {'eav': 500, 'uo': 0.70},
    '체육관':        {'eav': 300, 'uo': 0.60},
    # 산업/물류 (KS A 3011)
    '공장':          {'eav': 300, 'uo': 0.60},
    '물류창고':      {'eav': 100, 'uo': 0.40},
    # 도로/주차 (KS A 3701)
    '주차장':        {'eav': 30,  'uo': 0.25},
    '주차장_실외':   {'eav': 30,  'uo': 0.25},
    '도로':          {'eav': 20,  'uo': 0.40},
    '보행로_일반':   {'eav': 15,  'uo': 0.40},
}


def get_ks_standard(facility_type: str) -> dict:
    return KS_STANDARDS.get(facility_type, {'eav': 0, 'uo': 0})


def judge_ks(measured_eav, measured_uo, ks_eav, ks_uo) -> str:
    if not ks_eav and not ks_uo:
        return 'N/A'
    eav_ok = (measured_eav or 0) >= (ks_eav or 0)
    uo_ok  = (measured_uo  or 0) >= (ks_uo  or 0)
    if eav_ok and uo_ok:
        return 'PASS'
    if eav_ok or uo_ok:
        return 'WARNING'
    return 'FAIL'


# 통계 및 헤더 라인 건너뛰기 패턴
_SKIP_RE = re.compile(
    r'Average illuminance|Minimum illuminance|Maximum illuminance|'
    r'Uniformity|Diversity|Height of the reference|Vertical illuminance|'
    r'from direction\s*:|Illuminance \[lx\]|'
    r'\bObject\b|\bInstallation\b|Project\s+number|'
    r'Page\s+\d+/\d+|please put your|Calculation\s+results|'
    r'\bDescription\b|3D\s+(view|luminance)|Floor\s*plan|'
    r'1\s*:\s*\d+.*\[m\]|^\s*:\s+',
    re.I
)


def _normalize(text: str) -> str:
    """non-breaking space 등 특수 공백을 일반 공백으로 치환"""
    return text.replace('\xa0', ' ').replace('\u2009', ' ').replace('\u202f', ' ')


def _layout_nums(line: str) -> list:
    """
    layout 모드 텍스트 라인에서 (char_pos, value) 쌍 추출.
    - [150] / (638) → 내부 숫자를 원래 위치에서 추출
    - [m] → 무시
    위치 보존: 괄호를 같은 길이의 공백으로 치환해 인덱스 불변.
    """
    def _expand(m):
        inner = m.group(1)
        total = len(m.group(0))
        return ' ' + inner + ' ' * (total - len(inner) - 1)

    s = re.sub(r'\[m\]', '   ', line)
    s = re.sub(r'\[(\d+(?:\.\d)?)\]', _expand, s)
    s = re.sub(r'\((\d+(?:\.\d)?)\)', _expand, s)

    result = []
    for m in re.finditer(r'(\d+(?:\.\d)?)', s):
        try:
            result.append((m.start(), float(m.group(1))))
        except ValueError:
            pass
    return result


def _extract_nums_from_line(line: str) -> list:
    """
    한 줄에서 조도값(정수/소수) 목록 추출.
    - [150]113 → 150, 113 (괄호 값 분리)
    - 71.878.184.6 → 71.8, 78.1, 84.6 (붙어있는 소수열 분리)
    """
    # 괄호 안 값 꺼내기: [150]→ 150, (638)→ 638
    clean = re.sub(r'[\[\(](\d+\.?\d*)[\]\)]', r' \1 ', line)
    # 숫자 추출: 정수 또는 소수점 1자리 float
    # \d+(?:\.\d)? 는 붙어있는 소수열도 순서대로 분리함
    # 예: '71.878.1' → ['71.8', '78.1']
    tokens = re.findall(r'\d+(?:\.\d)?', clean)
    result = []
    for t in tokens:
        try:
            result.append(float(t))
        except ValueError:
            pass
    return result


class ReluxPdfParser:
    """Relux 시뮬레이션 PDF 파서"""

    def __init__(self, pdf_path: str):
        if PdfReader is None:
            raise ImportError("pypdf 패키지가 필요합니다: pip install pypdf")
        self.reader = PdfReader(pdf_path)

    def analyze_pages(self) -> list:
        """모든 페이지 분석 — 타입 분류 및 미리보기 반환 (Step 2 용)"""
        results = []
        for i, page in enumerate(self.reader.pages):
            text = _normalize(page.extract_text() or '')
            try:
                text_layout = _normalize(page.extract_text(extraction_mode='layout') or '')
            except Exception:
                text_layout = ''
            page_type = self._classify_page(text, text_layout)
            preview = self._make_preview(text, page_type)
            suggested_name = self._suggest_area_name(text)
            results.append({
                'index': i,
                'page_num': i + 1,
                'type': page_type,
                'preview': preview,
                'auto_select': page_type == 'grid_table',
                'suggested_name': suggested_name,
            })
        return results

    def parse_page(self, page_index: int) -> dict:
        """단일 페이지에서 격자 + 요약값 + 설치조건 추출 (Step 3 용)"""
        page = self.reader.pages[page_index]
        text = _normalize(page.extract_text() or '')
        try:
            text_layout = _normalize(page.extract_text(extraction_mode='layout') or '')
        except Exception:
            text_layout = ''
        summary = self._extract_summary(text)
        grid_info = self._extract_grid(text, text_layout)
        conditions = self._extract_conditions(text)
        return {
            'page_index': page_index,
            'page_num': page_index + 1,
            **summary,
            **grid_info,
            **conditions,
        }

    # ── 내부 메서드 ─────────────────────────────────────────

    def _classify_page(self, text: str, text_layout: str = '') -> str:
        """페이지 타입 분류"""
        has_summary = bool(re.search(r'Average illuminance Eav\s*:', text))

        # grid_table: 요약값 + 격자 데이터 행이 존재
        if has_summary:
            grid_info = self._extract_grid(text, text_layout)
            if grid_info['grid_rows'] >= 2 and grid_info['grid_cols'] >= 2:
                return 'grid_table'

        if has_summary:
            return 'summary'
        if re.search(r'Floor\s*plan|1\s*:\s*\d+', text) and '[m]' in text:
            return 'floor_plan'
        if re.search(r'3D\s*(view|luminance)|Luminance in the scene', text, re.I):
            return '3d_view'
        if re.search(r'조명높이|조명기구|조명수량|Installation\s*:', text):
            return 'cover'
        return 'other'

    def _make_preview(self, text: str, page_type: str) -> str:
        """UI에 표시할 짧은 발췌"""
        if page_type == 'grid_table':
            m = re.search(r'Average illuminance Eav\s*:\s*([\d.]+)\s*lx', text)
            eav = m.group(1) if m else '?'
            m2 = re.search(r'Minimum illuminance Emin\s*:\s*([\d.]+)', text)
            emin = m2.group(1) if m2 else '?'
            name = self._suggest_area_name(text)
            return f"{name} — Eav: {eav} lx, Emin: {emin} lx"
        if page_type == 'summary':
            m = re.search(r'Average illuminance Eav\s*:\s*([\d.]+)\s*lx', text)
            eav = m.group(1) if m else '?'
            return f"요약: Eav={eav} lx"
        if page_type == 'cover':
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            for line in lines:
                if len(line) > 5 and not line.startswith('-') and not line.startswith('Page'):
                    return line[:50]
        clean = ' '.join(text.split())
        return clean[:60]

    def _suggest_area_name(self, text: str) -> str:
        """페이지에서 구역명 추정.
        Relux 형식: '1.3.2  구역 중앙부Table, 1  (E)' → '구역 중앙부 1'
        """
        # "1.3.x  <이름>Table, N" 또는 "1.3.x  <이름>Table,  (E)" 패턴 (숫자 선택)
        m = re.search(r'\d+\.\d+\.\d+\s+([\w가-힣][^\n]*?)Table,\s*(\d*)', text)
        if m:
            name = m.group(1).strip()
            num = m.group(2).strip()
            return f"{name} {num}" if num else name
        # "Evaluation area N" 패턴
        m = re.search(r'Evaluation\s+area\s+(\d+)', text, re.I)
        if m:
            return f"구역 {m.group(1)}"
        # "Table, N" 단독 패턴
        m = re.search(r'Table,\s*(\d+)', text, re.I)
        if m:
            return f"구역 {m.group(1)}"
        # "Exterior N" 패턴
        m = re.search(r'Exterior\s+(\d+)', text, re.I)
        if m:
            return f"외부 {m.group(1)}"
        return "구역"

    def _extract_summary(self, text: str) -> dict:
        """Eav/Emin/Emax/Uo/Ud 추출"""
        def _find(pattern):
            m = re.search(pattern, text)
            return float(m.group(1)) if m else None

        eav  = _find(r'Average illuminance Eav\s*:\s*([\d.]+)\s*lx')
        emin = _find(r'Minimum illuminance Emin\s*:\s*([\d.]+)\s*lx')
        emax = _find(r'Maximum illuminance Emax\s*:\s*([\d.]+)\s*lx')
        uo   = _find(r'Uniformity Uo.*?\(([\d.]+)\)')
        ud   = _find(r'Diversity Ud.*?\(([\d.]+)\)')
        mf   = _find(r'Maintenance factor\s+([\d.]+)')
        flux = _find(r'Total luminous flux of all lamps\s+([\d.]+)\s*lm')
        pwr  = _find(r'Total power\s+([\d.]+)\s*W')
        ppa  = _find(r'Total power per area.*?\)\s*([\d.]+)\s*W')

        return {
            'design_eav': eav, 'design_emin': emin, 'design_emax': emax,
            'design_uo': uo, 'design_ud': ud,
            'maintenance_factor': mf, 'total_flux': flux,
            'total_power': pwr, 'power_per_area': ppa,
        }

    def _extract_grid(self, text: str, text_layout: str = '') -> dict:
        """
        격자 숫자 배열 + X/Y축 레이블 추출.
        layout 텍스트가 있으면 문자위치 기반으로 추출(빈 셀 보존),
        없으면 기존 방식(최빈 열 수)으로 폴백.
        """
        empty = {'grid_rows': 0, 'grid_cols': 0,
                 'x_labels': [], 'y_labels': [], 'design_grid': []}

        if text_layout:
            result = self._extract_grid_by_layout(text_layout)
            if result and result['grid_rows'] >= 2 and result['grid_cols'] >= 2:
                return result

        return self._extract_grid_fallback(text)

    def _extract_grid_by_layout(self, text_layout: str) -> dict | None:
        """
        layout 모드 텍스트에서 문자 위치 기반으로 격자 추출.

        컬럼 기준 결정 규칙:
        - 데이터 행의 최대 값 수 > X축 레이블 수
          → 가장 많은 값을 가진 데이터 행의 문자위치를 컬럼 기준으로 사용
            (Relux X축이 좌표 표시용이고 실제 측정격자가 더 세밀한 경우)
        - 데이터 행의 최대 값 수 <= X축 레이블 수
          → X축 레이블 문자위치를 컬럼 기준으로 사용
            (비직사각형 격자에서 희소 행의 빈 셀을 None으로 보존)
        """
        lines = text_layout.split('\n')

        # ── 1. X축 라인 찾기 (라인 끝에 [m]) ──────────────────
        x_line_idx = None
        x_cols = []  # [(char_pos, value), ...]
        for i, line in enumerate(lines):
            if not re.search(r'\[m\]\s*\|?\s*$', line):
                continue
            nums = _layout_nums(line)
            if len(nums) >= 2:
                x_line_idx = i
                x_cols = nums
                break

        if x_line_idx is None or len(x_cols) < 2:
            return None

        x_labels_from_axis = [f"{int(v)}m" if v == int(v) else f"{v}m"
                               for _, v in x_cols]

        # ── 2. 섹션 상단 경계 찾기 ────────────────────────────
        section_start = max(0, x_line_idx - 40)
        for i in range(x_line_idx - 1, max(-1, x_line_idx - 40), -1):
            if re.search(r'Table,|\d+\.\d+\.\d+', lines[i]):
                section_start = i
                break

        # ── 3. 데이터 행 1차 파싱 (y-레이블 분리 + 데이터 nums 추출) ──
        # 먼저 X축 기준 y_max_pos 를 초안으로 사용
        init_y_max = max(0, x_cols[0][0] - 5)

        raw_rows = []  # [(y_label_or_None, [(pos, val), ...])]
        for i in range(section_start + 1, x_line_idx):
            line = lines[i]
            if not line.strip() or _SKIP_RE.search(line):
                continue

            has_m_label = bool(re.search(r'\[m\]', line)) and \
                          not re.search(r'\[m\]\s*\|?\s*$', line)
            nums = _layout_nums(line)

            if not nums and not has_m_label:
                continue

            y_label = None
            data_nums = nums

            if has_m_label:
                y_label = '[m]'
            elif nums:
                fp, fv = nums[0]
                if fp <= init_y_max and fv <= 200:
                    y_label = f"{int(fv)}m" if fv == int(fv) else f"{fv}m"
                    data_nums = nums[1:]

            if not data_nums and y_label is None:
                continue  # 완전 빈 라인

            raw_rows.append((y_label, data_nums))

        if not raw_rows:
            return None

        # ── 4. 컬럼 기준 결정 ─────────────────────────────────
        from collections import Counter
        data_counts = [len(d) for _, d in raw_rows if d]
        max_data_count = max(data_counts, default=0)
        n_x = len(x_cols)

        # 3개 이상 값을 가진 행들의 값 개수 분포 분석
        meaningful_counts = [c for c in data_counts if c >= 3]
        count_freq = Counter(meaningful_counts)
        dominant_count = max(count_freq, key=count_freq.get) if count_freq else max_data_count

        # 비정형 판별: 값 개수가 다양하면 (최대-최빈 >= 2) 비정형 격자
        is_irregular = (max_data_count - dominant_count) >= 2 and max_data_count >= 4

        if max_data_count > n_x:
            # 데이터가 X축보다 세밀 → 가장 넓은 행 위치로 컬럼 정의
            densest = next((d for _, d in raw_rows if len(d) == max_data_count), None)
            col_positions = [p for p, _ in densest]
            x_labels = self._interpolate_labels(x_labels_from_axis, max_data_count)
        elif is_irregular:
            # 비정형 격자: 가장 넓은 행 기준 (빈 셀 보존)
            densest = next((d for _, d in raw_rows if len(d) == max_data_count), None)
            if densest:
                col_positions = [p for p, _ in densest]
                x_labels = self._interpolate_labels(x_labels_from_axis, max_data_count)
            else:
                col_positions = [p for p, _ in x_cols]
                x_labels = x_labels_from_axis
        elif dominant_count >= n_x:
            # 정형: 대다수 행 값 수 >= X축 수 → X축 위치 사용
            col_positions = [p for p, _ in x_cols]
            x_labels = x_labels_from_axis
        else:
            # 정형: 대다수 행 값 수 < X축 수 → 데이터 기준
            densest = next((d for _, d in raw_rows if len(d) == dominant_count), None)
            if densest:
                col_positions = [p for p, _ in densest]
                x_labels = self._interpolate_labels(x_labels_from_axis, dominant_count)
            else:
                col_positions = [p for p, _ in x_cols]
                x_labels = x_labels_from_axis

        n_cols = len(col_positions)

        # ── 5. 각 행 → 컬럼 배정 ──────────────────────────────
        rows_with_labels = []
        for y_label, data_nums in raw_rows:
            if not data_nums:
                rows_with_labels.append((y_label, [None] * n_cols))
                continue

            if len(data_nums) == n_cols:
                # 값 수 == 컬럼 수: 위치 순서대로 1:1 배정
                row = [val for _, val in sorted(data_nums, key=lambda x: x[0])]
            elif len(data_nums) > n_cols:
                # 값 수 > 컬럼 수: 위치 순서대로 앞에서 n_cols개만 사용
                sorted_nums = sorted(data_nums, key=lambda x: x[0])
                row = [val for _, val in sorted_nums[:n_cols]]
            else:
                # 값 수 < 컬럼 수: nearest 매핑 (비정형 격자 빈 셀 보존)
                row = [None] * n_cols
                for char_pos, val in data_nums:
                    nearest = min(range(n_cols),
                                  key=lambda c: abs(col_positions[c] - char_pos))
                    if row[nearest] is None:
                        row[nearest] = val
                    else:
                        # 충돌 시 인접 빈 컬럼 탐색
                        for c in sorted(range(n_cols),
                                        key=lambda c2: abs(col_positions[c2] - char_pos)):
                            if row[c] is None:
                                row[c] = val
                                break
            rows_with_labels.append((y_label, row))

        # ── 5b. sparse row 병합 ─────────────────────────────
        # 1~2개 값만 가진 행: 인접 행의 같은 열이 None이면 병합, 아니면 행 유지
        merged = []
        for i, (y_label, row) in enumerate(rows_with_labels):
            non_none = sum(1 for v in row if v is not None)
            if non_none <= 2 and non_none > 0 and n_cols >= 4:
                all_merged = True
                for ci, val in enumerate(row):
                    if val is None:
                        continue
                    placed = False
                    for di in [1, -1, 2, -2]:
                        ni = i + di
                        if 0 <= ni < len(rows_with_labels):
                            _, neighbor = rows_with_labels[ni]
                            if neighbor[ci] is None:
                                neighbor[ci] = val
                                placed = True
                                break
                    if not placed:
                        all_merged = False
                if not all_merged:
                    # 병합 실패한 값이 있으면 행 유지
                    merged.append((y_label, row))
            else:
                merged.append((y_label, row))
        rows_with_labels = merged

        # ── 6. 앞뒤 all-None 행 제거 ──────────────────────────
        first_real = next(
            (i for i, (_, r) in enumerate(rows_with_labels)
             if any(v is not None for v in r)), None)
        if first_real is None:
            return None
        last_real = next(
            (i for i, (_, r) in enumerate(reversed(rows_with_labels))
             if any(v is not None for v in r)), 0)
        end_idx = (len(rows_with_labels) - last_real
                   if last_real > 0 else len(rows_with_labels))
        rows_with_labels = rows_with_labels[first_real:end_idx]

        data_rows = [r for _, r in rows_with_labels]
        y_raw = [lbl if (lbl and lbl != '[m]') else None
                 for lbl, _ in rows_with_labels]

        # ── 7. all-None 컬럼 제거 ──────────────────────────────
        used_cols = [c for c in range(n_cols)
                     if any(r[c] is not None for r in data_rows)]
        if used_cols and len(used_cols) < n_cols:
            data_rows = [[r[c] for c in used_cols] for r in data_rows]
            x_labels = [x_labels[c] for c in used_cols]
            n_cols = len(used_cols)

        # ── 8. 중간 all-None 행 제거 ──────────────────────────
        non_empty = [(y, r) for y, r in zip(y_raw, data_rows)
                     if any(v is not None for v in r)]
        if non_empty:
            y_raw, data_rows = zip(*non_empty)
            y_raw, data_rows = list(y_raw), list(data_rows)
        else:
            return None

        # ── 9. Y축 뒤집기 (PDF는 위→아래 순이지만 격자는 아래→위) ──
        data_rows = list(reversed(data_rows))
        y_raw = list(reversed(y_raw))

        y_labels = self._fill_y_labels(y_raw)

        return {
            'grid_rows': len(data_rows),
            'grid_cols': n_cols,
            'x_labels': x_labels,
            'y_labels': y_labels,
            'design_grid': data_rows,
        }

    def _fill_y_labels(self, labels: list) -> list:
        """None 레이블을 인접 값에서 선형 보간"""
        result = list(labels)
        n = len(result)
        known = [(i, lbl) for i, lbl in enumerate(result) if lbl is not None]
        if not known:
            return [f"{i * 2}m" for i in range(n)]
        for ki in range(len(known) - 1):
            i0, l0 = known[ki]
            i1, l1 = known[ki + 1]
            try:
                v0 = float(l0.replace('m', ''))
                v1 = float(l1.replace('m', ''))
                for j in range(i0 + 1, i1):
                    frac = (j - i0) / (i1 - i0)
                    s = f"{v0 + frac * (v1 - v0):.1f}".rstrip('0').rstrip('.')
                    result[j] = f"{s}m"
            except (ValueError, AttributeError):
                for j in range(i0 + 1, i1):
                    result[j] = result[i0]
        # 앞·뒤 채우기
        if known[0][0] > 0:
            for j in range(known[0][0]):
                result[j] = result[known[0][0]]
        if known[-1][0] < n - 1:
            for j in range(known[-1][0] + 1, n):
                result[j] = result[known[-1][0]]
        return result

    def _extract_grid_fallback(self, text: str) -> dict:
        """기존 방식: 최빈 열 수 기반 격자 추출 (layout 모드 실패 시 폴백)"""
        lines = text.split('\n')
        candidate_rows = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if _SKIP_RE.search(line):
                continue
            if re.search(r'\d\s*\[m\]', line):
                continue
            if re.fullmatch(r'\[m\]', line.strip()):
                continue

            vals = _extract_nums_from_line(line)
            if len(vals) >= 2:
                candidate_rows.append(vals)

        if not candidate_rows:
            return {'grid_rows': 0, 'grid_cols': 0,
                    'x_labels': [], 'y_labels': [], 'design_grid': []}

        all_vals = [v for row in candidate_rows for v in row]
        if all_vals:
            sorted_v = sorted(all_vals)
            median_v = sorted_v[len(sorted_v) // 2]
            axis_threshold = max(median_v * 0.2, 5.0)
            candidate_rows = [
                row for row in candidate_rows
                if sum(1 for v in row if v >= axis_threshold) > len(row) * 0.5
            ]

        if not candidate_rows:
            return {'grid_rows': 0, 'grid_cols': 0,
                    'x_labels': [], 'y_labels': [], 'design_grid': []}

        col_counts = Counter(len(r) for r in candidate_rows)
        expected_cols = col_counts.most_common(1)[0][0]
        grid_rows = [r for r in candidate_rows if len(r) == expected_cols]

        if not grid_rows:
            return {'grid_rows': 0, 'grid_cols': 0,
                    'x_labels': [], 'y_labels': [], 'design_grid': []}

        x_labels, y_labels = self._extract_axis_labels(text, len(grid_rows), expected_cols)

        return {
            'grid_rows': len(grid_rows),
            'grid_cols': expected_cols,
            'x_labels': x_labels,
            'y_labels': y_labels,
            'design_grid': grid_rows,
        }

    def _extract_axis_labels(self, text: str, n_rows: int, n_cols: int) -> tuple:
        """X/Y축 레이블 추출 (m 단위 숫자 시퀀스)"""
        x_labels = None
        for line in text.split('\n'):
            m = re.search(r'^((?:\d+\s+){2,}\d+)\s*\[m\]', line.strip())
            if m:
                nums = m.group(1).split()
                if all(int(n) <= 200 for n in nums):
                    x_labels = [f"{n}m" for n in nums]
                    break

        if x_labels is None:
            x_labels = [f"{i}m" for i in range(n_cols)]
        elif len(x_labels) < n_cols and len(x_labels) >= 2:
            x_labels = self._interpolate_labels(x_labels, n_cols)

        y_labels = None
        y_match = re.search(r'\[m\]\s*\n((?:[ \t]*\d+\.?\d*[ \t]*\n){2,}[ \t]*\d+\.?\d*)', text)
        if y_match:
            nums = [n.strip() for n in y_match.group(1).split('\n') if n.strip()]
            nums = [n for n in nums if re.fullmatch(r'\d+\.?\d*', n)]
            if nums and all(float(n) <= 200 for n in nums):
                y_labels = [f"{n}m" for n in nums]

        if y_labels is None:
            y_labels = [f"{i * 2}m" for i in range(n_rows)]
        elif len(y_labels) < n_rows and len(y_labels) >= 2:
            y_labels = self._interpolate_labels(y_labels, n_rows)

        while len(x_labels) < n_cols:
            x_labels.append(x_labels[-1] if x_labels else f"{len(x_labels)}m")
        while len(y_labels) < n_rows:
            y_labels.append(y_labels[-1] if y_labels else f"{len(y_labels) * 2}m")

        return x_labels[:n_cols], y_labels[:n_rows]

    def _interpolate_labels(self, labels: list, target: int) -> list:
        """레이블 선형 보간 (예: 8개 → 16개)"""
        if not labels:
            return [f"{i}m" for i in range(target)]
        try:
            floats = [float(l.replace('m', '')) for l in labels]
            step = (floats[-1] - floats[0]) / (target - 1) if target > 1 else 0
            result = []
            for i in range(target):
                v = floats[0] + i * step
                s = f"{v:.1f}".rstrip('0').rstrip('.')
                result.append(f"{s}m")
            return result
        except Exception:
            return [f"{i}m" for i in range(target)]

    def _extract_conditions(self, text: str) -> dict:
        """설치조건 추출"""
        def _find(pattern):
            m = re.search(pattern, text)
            return m.group(1).strip() if m else None

        height = _find(r'조명높이\d*\.\s*:\s*([\d.]+)\s*m')
        watt   = _find(r'조명기구\d*\.\s*:.*?(\d+)\s*W')
        qty    = _find(r'조명수량\d*\.\s*:\s*(\d+)')
        tower  = _find(r'타워수량\d*\.\s*:\s*(\d+)')

        date_m = re.search(r'Date\s*:\s*(\d{2}\.\d{2}\.\d{4})', text)
        sim_date = None
        if date_m:
            parts = date_m.group(1).split('.')
            try:
                import datetime
                sim_date = datetime.date(int(parts[2]), int(parts[1]), int(parts[0]))
            except Exception:
                pass

        return {
            'installation_height': float(height) if height else None,
            'lamp_type': f"LED {watt}W" if watt else None,
            'lamp_watt': int(watt) if watt else None,
            'lamp_qty': int(qty) if qty else None,
            'tower_qty': int(tower) if tower else None,
            'simulation_date': sim_date,
        }
