# Drawing Management — Completion Report

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | drawing-management (도면관리 고도화) |
| Date | 2026-03-21 |
| Duration | 1 session |
| Match Rate | ~93% (기능 요건 기준) |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 기존 도면관리는 단순 업로드/목록 표시 수준. PDF 미리보기·버전관리·선택삭제 등 실무 기능 부재 |
| **Solution** | 사진관리와 동일한 SPA 구조로 전면 재작성. 좌측 현장 패널 + 우측 갤러리 + PDF 라이트박스 + DWG 지원 |
| **Function UX Effect** | 모달 없이 인라인 업로드, XHR 프로그레스바, 버전 탭 전환, 전체선택/선택삭제로 업무 속도 대폭 향상 |
| **Core Value** | 현장별 도면 이력 완전 관리 (PDF 미리보기·DWG 원본 다운로드·버전별 추적·이력 로그) |

---

## 1. 구현 기능 목록

### 1.1 SPA 레이아웃 (drawings_gallery.html)

- **좌측 현장 패널**: 전체 현장 목록 + 실시간 검색 + 도면 수 뱃지
- **우측 갤러리 패널**: 현장 헤더 → 업로드 카드 → 필터 탭 → 도면 카드 그리드
- 현장 선택 시 URL pushState (`/drawings/project/<id>`)로 딥링크 지원
- 모바일: 좌측 패널 숨김 + select 드롭다운 전환

### 1.2 인라인 업로드 카드

- 도면 유형 pill 버튼 (`제작도면` / `발주도면`)
- 도면명 텍스트 입력 + 기존 도면 선택 드롭다운 (버전 추가용)
- 드래그앤드롭 존 + 파일 선택 버튼
- **XHR 업로드** — `onprogress` 진행바, 성공 시 그리드 즉시 갱신 (페이지 리로드 없음)
- CSRF 중복 헤더 버그 수정 (`base.html` send() 오버라이드와 충돌 제거)

### 1.3 PDF / DWG 파일 지원

| 파일 | 업로드 | 미리보기 | 다운로드 |
|------|:------:|:--------:|:--------:|
| PDF  | ✅ | ✅ iframe | ✅ |
| DWG  | ✅ | ❌ "미리볼 수 없습니다" + 다운로드 버튼 | ✅ |

- `pdf_path` / `dwg_path` 필드 분리 저장
- `content_type`: PDF → `application/pdf`, DWG → `application/octet-stream`
- 버전 탭에 `PDF` / `DWG` 레이블 표시

### 1.4 PDF 라이트박스

- 전체화면 iframe 오버레이 (`z-index: 9000`)
- **버전 탭**: v1, v2 … 최신 버전에 ★ 마크, 탭 클릭으로 즉시 전환
- 다운로드 버튼, 삭제 버튼 (권한자만)
- 이전/다음 도면 내비게이션 (← →) + 키보드 `ArrowLeft` / `ArrowRight` / `Escape`

### 1.5 선택 삭제 (Bulk Delete)

- 필터 바 우측 `☑ 선택` 버튼으로 선택 모드 진입
- 카드에 체크 오버레이 표시, 클릭으로 개별 선택/해제
- **전체선택** (현재 필터 기준) / **선택취소**
- **선택삭제 (N)** — 확인 후 순차 DELETE, 성공·실패 건수 토스트
- 현장 변경 시 선택 모드 자동 해제

### 1.6 AJAX API (routes/drawing.py)

| Endpoint | Method | 설명 |
|----------|--------|------|
| `/drawings/api/project/<id>` | GET | 현장별 도면 목록 (버전 포함) |
| `/drawings/api/upload/<id>` | POST | PDF/DWG 업로드 (Supabase Storage) |
| `/drawings/api/version/<id>` | DELETE | 버전 단건 삭제 |
| `/drawings/api/drawing/<id>` | DELETE | 도면 전체 (모든 버전) 삭제 |
| `/drawings/version/<id>/view` | GET | PDF 서빙 (iframe용) |
| `/drawings/version/<id>/download` | GET | PDF/DWG 다운로드 |

### 1.7 사이드바 메뉴 등록

- `config.py` MENU_REGISTRY "공유" 그룹에 `drawing` 키 추가
- `db.py` 기존 `GroupPermission` 레코드에 `drawing` 자동 마이그레이션

---

## 2. 수정 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| `routes/drawing.py` | 전면 재작성 — SPA 라우트 + 6개 AJAX API |
| `templates/drawings_gallery.html` | 신규 — SPA 갤러리 템플릿 (~850줄) |
| `templates/drawings_index.html` | Dead code (기존 인덱스 페이지, 미사용) |
| `templates/drawings_project.html` | Dead code (기존 현장별 페이지, 미사용) |
| `config.py` | MENU_REGISTRY `drawing` 키 추가 |
| `modules/models/db.py` | drawing 권한 자동 마이그레이션 추가 |

---

## 3. 주요 기술 결정

- **SPA 패턴**: `photo_gallery.html`과 동일한 구조 적용 — 현장 전환 시 fetch + 그리드 재렌더, URL pushState
- **PDF 미리보기**: 브라우저 내장 PDF 렌더러 활용 (`<iframe src="/drawings/version/<id>/view">`)
- **DWG 처리**: 서버에서 변환하지 않고 원본 그대로 저장/다운로드, 라이트박스에서 "미리보기 불가" 안내
- **CSRF 수정**: `base.html`이 XHR `send()` 오버라이드로 토큰 자동 주입 — 수동 `setRequestHeader` 제거
- **버전 관리**: `DrawingVersion` 테이블의 `is_latest` 플래그로 최신 버전 추적, 업로드 시 기존 latest 해제

---

## 4. 이력 로그

모든 업로드·버전삭제·도면삭제 시 `append_history_log(scope='design', kind='system')` 기록.

---

## 5. Key Result

- 신규 파일: `templates/drawings_gallery.html` (1개)
- 전면 재작성: `routes/drawing.py` (482줄 → 520줄)
- 지원 형식: PDF 미리보기 + DWG 다운로드
- 삭제 방식: 버전 단건 삭제 + 도면 전체 삭제 + 선택 다중 삭제 3종
