# Plan: photo-management

## Executive Summary

| 관점 | 내용 |
|------|------|
| **Problem** | 사진이 납품관리 하위에 종속돼 있어 현장별 사진 전체를 갤러리로 보거나 모바일에서 바로 올리기가 불편함 |
| **Solution** | 독립된 사진관리 페이지 신설. 현장별 갤러리 UI + 파일 업로드 & 모바일 카메라 이중 지원 |
| **Function UX Effect** | 현장 선택 → 갤러리 즉시 확인. 모바일에서 카메라로 바로 촬영 업로드. 물품/수량 정보 카드에 노출 |
| **Core Value** | 납품 현장 사진을 한 곳에서 관리, 모바일 현장 작업자도 즉시 업로드 가능 |

---

## 1. 배경 및 목표

### 1.1 현재 문제
- 사진이 `납품관리 > 현장 상세 > 납품` 3단계 하위에 종속
- 전체 현장 사진을 한번에 갤러리로 볼 방법 없음
- 모바일 카메라 업로드 미지원 (PC 파일선택만 가능)

### 1.2 목표
- **독립 사진관리 페이지** (`/photos`)
- 현장별 갤러리 특화 UI
- 파일 업로드 + 모바일 카메라 촬영 이중 지원
- 현장/계약/물품/수량 정보 조회 (편집 불필요)
- 기존 납품관리 사진탭 제거

---

## 2. 기능 요구사항 (FR)

| ID | 기능 | 우선순위 |
|----|------|---------|
| FR-01 | 현장 목록 사이드바 (프로젝트 검색+선택) | P1 |
| FR-02 | 현장별 사진 갤러리 (그리드, 라이트박스) | P1 |
| FR-03 | 사진 업로드 (파일 선택 + 드래그앤드롭) | P1 |
| FR-04 | 모바일 카메라 촬영 업로드 (`capture="environment"`) | P1 |
| FR-05 | 현장/계약 기본 정보 헤더 표시 (조회만) | P1 |
| FR-06 | 물품명·수량 정보 카드 (ContractItem 기반, 조회만) | P2 |
| FR-07 | 사진 삭제 | P1 |
| FR-08 | 사진 photo_type 태그 (예: 상차, 하차, 설치, 기타) | P2 |
| FR-09 | 기존 납품관리 사진탭 제거 | P1 |

---

## 3. 기술 스택

| 항목 | 내용 |
|------|------|
| Backend | Flask Blueprint (`routes/photos.py`) |
| Storage | Supabase Storage (`modules/storage_adapter.py`) 재사용 |
| Storage 경로 | `storage/photos/project_{id}/{YYYYMMDD_HHMMSSfff}{ext}` |
| DB 모델 | 신규 `ProjectPhoto` 모델 (기존 `DeliveryPhoto`는 유지) |
| Frontend | Jinja2 템플릿 + frontend-designer 에이전트 활용 |
| 모바일 지원 | `<input type="file" accept="image/*" capture="environment">` |

---

## 4. DB 설계

### 신규 모델: `ProjectPhoto`

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | Integer PK | |
| project_id | Integer FK(projects) | 현장 |
| contract_id | Integer FK(contracts) nullable | 연관 계약 |
| photo_type | String(30) | 상차/하차/설치/기타 |
| file_name | String(255) | 원본 파일명 |
| storage_path | String(500) | Supabase 경로 |
| uploaded_by | String(50) | 업로더 |
| created_at | DateTime | 생성일시 |

---

## 5. URL 구조

| Method | URL | 설명 |
|--------|-----|------|
| GET | `/photos` | 현장 목록 (기본 페이지) |
| GET | `/photos/project/<id>` | 현장별 갤러리 |
| POST | `/photos/project/<id>/upload` | 사진 업로드 |
| DELETE | `/photos/<photo_id>` | 사진 삭제 |
| GET | `/photos/<photo_id>/view` | 사진 바이너리 조회 |

---

## 6. 화면 구성

```
┌─────────────────────────────────────────────┐
│  [현장검색 사이드바]  │  [갤러리 영역]         │
│                      │                        │
│  📁 현장 목록         │  현장명 + 계약 정보    │
│  - 나주 광장 조명...  │  물품: LED조명 10개    │
│  - 보성 벌교 스포츠   │                        │
│  - 매그나텍 광주...   │  [사진 업로드 버튼]    │
│                      │  📷 카메라  📁 파일    │
│                      │                        │
│                      │  ┌──┐ ┌──┐ ┌──┐       │
│                      │  │  │ │  │ │  │       │
│                      │  └──┘ └──┘ └──┘       │
│                      │  (그리드 갤러리)        │
└─────────────────────────────────────────────┘
```

---

## 7. 구현 순서

1. `ProjectPhoto` 모델 추가 + DB 마이그레이션
2. `routes/photos.py` Blueprint 신설
3. 갤러리 템플릿 (`photo_gallery.html`) — frontend-designer 활용
4. 사진 업로드 API (파일 + 카메라)
5. 납품관리 사진탭 제거
6. 사이드바/config 메뉴 등록

---

## 8. 비기능 요구사항

- 모바일 반응형 필수 (갤러리 2열)
- 업로드 파일 크기 제한: 10MB
- 지원 포맷: jpg, jpeg, png, webp, heic
- 이미지 라이트박스: 클릭 시 원본 크기 확인
