# 모바일 반응형 작업 내역 (2026-03-23)

## 작업 목적
전체 ERP 페이지의 모바일(375px) 반응형 최적화. 가로 스크롤 제거, 테이블 카드형 변환, 버튼/배지 줄바꿈 방지, 폰트 사이즈 일관성.

---

## 수정 파일 목록

### CSS
- **`static/css/magnatech.css`** — 글로벌 모바일 CSS 대폭 추가/수정
  - 모바일 카드형 테이블 CSS 전면 재작성 (display: block 기반)
  - 빈 상태 메시지(colspan) 세로 텍스트 수정
  - 버튼 white-space: nowrap 전역 적용
  - 배지/상태칩 줄바꿈 금지
  - KPI 숫자 줄바꿈 방지 + 자동 축소
  - 페이지 히어로 버튼 wrap + 사이즈
  - pagination 모바일 최적화
  - 탭/pill 가로 스크롤 (nowrap)
  - 통계카드 3열 그리드
  - 필터 접기/펼치기 모바일 처리
  - 챗봇 하단 입력바 터치 최적화
  - 모달 내 테이블 폰트 축소
  - contract-item-table 모바일 가로 스크롤 + 폰트 축소
  - mat-order-table 모바일 카드형 (불필요 컬럼 숨김)
  - 글로벌 자동 테이블 카드 변환 (no-stack-table 미적용 테이블)

### JavaScript
- **`static/js/mobile-table.js`**
  - `markStackTables()`: no-stack-table 클래스 자동 제거, 모든 테이블 카드형 변환
  - `hydrateMobileTableLabels()`: colspan 셀 감지 시 부모 tr까지 인라인 스타일로 빈 상태 처리
  - contract-item-table, tree-card-table, 모달 내 테이블은 카드 변환 제외

### HTML 템플릿
- **`templates/material_detail.html`** — min-width 인라인 스타일 제거
- **`templates/sales_detail.html`** — no-stack-table 추가 (JS가 자동 제거)
- **`templates/production_detail.html`** — no-stack-table 추가
- **`templates/fo_detail.html`** — no-stack-table 추가
- **`templates/po_detail.html`** — no-stack-table 추가
- **`templates/receiving_detail.html`** — no-stack-table 추가

---

## 처리 방식 요약

### 테이블 자동 변환 흐름
1. `mobile-table.js`가 DOMContentLoaded 시 실행
2. `.main-content` 내 모든 `table.table` 요소 탐색
3. `tree-card-table` / 모달 내부 테이블 제외
4. `no-stack-table` 클래스 자동 제거 + `mobile-stack-table` 추가
5. `<thead>` 숨김, `<tbody>` + `<tr>` + `<td>` → block 레이아웃
6. colspan 셀 감지 → 부모 tr 카드 스타일 해제 + 텍스트 중앙 정렬

### 모바일 카드 레이아웃
- tr: `display: block`, 왼쪽 파란 보더 4px, 라운드 10px, 그림자
- td: `display: inline`, 인라인 흐름 (자재명 + 수량 + 상태 뱃지가 한 줄에)
- 버튼: `white-space: nowrap` 절대 줄바꿈 금지
- 빈 td: `display: none`
- colspan td: `display: block`, 중앙 정렬, 카드 스타일 해제

### 특수 테이블 처리
- **contract-item-table**: 편집 폼 테이블 → 가로 스크롤 유지 (폰트 축소)
- **tree-card-table**: 트리형 변환은 기존 CSS 유지
- **mat-order-table**: 13개 컬럼 중 5개만 표시 (자재명, 수량, 상태, 체크박스, 버튼)

---

## 확인된 페이지 목록

### 리스트 페이지 (카드형 자동 변환)
- 조달내역, 계약관리, 납품관리, 자재관리, 생산관리, 협의관리
- 견적관리, 발주관리, AS관리, 가공발주, 품목관리
- BOM관리, 재고관리, 인증서관리, 거래처관리, 입고관리

### 상세 페이지 (개별 처리)
- 계약상세, 납품상세, 자재상세, 협의상세
- 생산상세, 가공발주상세, 발주상세, 입고상세

### 대시보드/차트 페이지
- 메인 대시보드, 매출 대시보드, 재고 대시보드
- 종합현황, 납품집계

---

## 2차 수정 내역 (에이전트 검수 후)

### 수정된 문제
1. **빈 상태 메시지 세로 텍스트** — tbody `display: flex` → `display: block` 변경으로 width 100% 보장
2. **세금계산서 가로 스크롤** — JS 셀렉터에 `inv-tbl` 추가로 카드 변환 적용
3. **입고관리 가로 스크롤** — JS에서 `no-stack-table` 자동 제거로 카드 변환 적용
4. **카드 오른쪽 공백** — padding `10px 12px` → `8px 8px 8px 10px` 축소
5. **뱃지 오버플로우** — max-width: 100% + overflow: hidden + text-overflow: ellipsis
6. **터치 음영** — `-webkit-tap-highlight-color: transparent` 전역 적용
7. **필터 버튼 사이즈 불일관** — filter 영역 `.btn` 사이즈 통일 (0.8rem, 36px)
8. **조도검증 격자 깨짐** — ilv-grid, ilv-cell 테이블 카드 변환 제외
9. **BOM/견적 편집 테이블 깨짐** — bomTable, itemsTable, editItemsTable ID로 제외
10. **피벗 테이블 깨짐** — pivot-tbl 클래스 카드 변환 제외

### 카드 변환 제외 대상 (가로 스크롤 유지)
- 조도검증 격자 (ilv-grid)
- BOM 편집 (bomTable, itemsTable)
- 피벗 테이블 (pivot-tbl)
- 모달 내 테이블
- tree-card-table (기존 트리형 유지)

---

## 3차 수정 내역

1. **서브 테이블 라벨 인라인화** — tree-card-table collapse 내 서브 테이블의 td를 `display: inline`으로 변경. 라벨 제거하고 값만 인라인 흐름으로 표시. 카드 높이 대폭 축소.
2. **hover/active 음영 전면 제거** — 모바일에서 table-hover, clickable-row 등의 hover 배경색/box-shadow 전부 `transparent !important`로 비활성화.
3. **-webkit-tap-highlight-color: transparent** — 터치 시 파란 하이라이트 제거. a, button, btn, tr[onclick], clickable-row 전부 적용.
4. **스크린샷 파일 전부 삭제** — 작업 중 생성된 mobile_*, fo_create_*, check_* 등 PNG 전부 정리.
