## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | 조도검증-설계관리 통합 연동 |
| 작성일 | 2026-03-21 |
| 예상 기간 | 2일 |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 조도검증과 설계관리가 분리되어 있어 설계현장 연결 시 현장명 미반영, 다중 기구/사이트 미대응, KS 기준 하드코딩, 시설종류 직접입력 불가 |
| **Solution** | Project 모델에 설계조도 필드 통합, 조도검증↔설계관리 양방향 연동, 다중 기구/구역 구조 확장 |
| **Function UX Effect** | 설계관리에서 입력한 조도 기준이 조도검증에 자동 반영, 검증 결과가 설계관리에 실시간 표시 |
| **Core Value** | 중복 입력 제거, 설계-검증 데이터 일관성, 1현장 N사이트 유연 대응 |

---

# Plan: 조도검증-설계관리 통합 연동

## 1. 현황 분석 및 문제점

### 1.1 현재 구조

```
Project (설계관리)          IlluminanceProject (조도검증)
├─ design_basis (Text)     ├─ erp_project_id (FK → Project)
├─ spec_confirmed          ├─ project_name (독립)
└─ work_path               ├─ facility_type (선택형 5가지)
                           └─ areas[] → measurements[]
```

### 1.2 문제점 7가지

| # | 문제 | 영향 |
|---|------|------|
| 1 | 설계현장 연결 시 현장명 미반영 | `onErpProjectChange()`가 빈 필드만 채움, 변경 시 미반영 |
| 2 | KS 기준이 `facility_type`(풋살장 등) 고정 | 실제는 설계기준조도(설계자 지정)를 써야 함 |
| 3 | 기구 1종만 대응 | 1구역에 LED투광등 + LED보안등 혼합 설치 시 표현 불가 |
| 4 | 1현장 1프로젝트 전제 | 같은 현장에 풋살장+주차장 등 다중 사이트 시 별도 프로젝트 필요 |
| 5 | 시설종류 선택형 5가지 | 직접입력 불가, 운동장/공원/도로 등 미지원 |
| 6 | 설계관리↔조도검증 단절 | 설계관리에서 조도 정보 확인 불가, 조도검증에서 설계기준 수동 입력 |
| 7 | 설계기준조도가 Area별 하드코딩 | Project 레벨 설계기준이 없어 전체 현장 기준 파악 어려움 |

---

## 2. 해결 전략

### 2.1 핵심 원칙

> **설계관리(Project)가 마스터, 조도검증(IlluminanceProject)이 소비자**
> - 설계기준조도, 시설종류, 기구정보는 설계관리에서 입력
> - 조도검증은 설계관리 데이터를 참조하되, 독립적으로도 동작 가능
> - 검증 결과는 설계관리에 역방향 표시

### 2.2 변경 범위

| 영역 | 변경 내용 |
|------|-----------|
| **DB 모델** | Project에 조도 설계 필드 추가, IlluminanceArea 기구 다중화, facility_type 자유입력 |
| **설계관리 UI** | 조도 설계정보 섹션 추가 (기준조도, 시설종류, 기구목록) |
| **조도검증 신규등록** | 설계현장 연결 시 자동 채움 강화, 시설종류 자유입력 |
| **양방향 연동** | 설계관리에서 조도검증 현황 표시, 조도검증에서 설계정보 참조 |

---

## 3. 상세 설계

### 3.1 DB 스키마 변경

#### Project 모델에 조도 설계 필드 추가

```python
# project_entities.py — 추가 필드
class Project(Base):
    # 기존 필드 유지...

    # 조도 설계 정보 (신규)
    illuminance_facility_type = Column(String(100))   # 시설종류 (자유입력: "풋살장", "주차장 B구역" 등)
    illuminance_design_lux = Column(Float)            # 설계기준조도 (lx) — KS 기준 대체
    illuminance_design_uo = Column(Float)             # 설계기준 균일도 (Uo)
    illuminance_fixtures = Column(Text)               # 기구 목록 JSON: [{"type":"LED투광등","watt":400,"qty":8},...]
    illuminance_notes = Column(Text)                  # 조도 설계 비고
```

#### IlluminanceProject 변경

```python
class IlluminanceProject(Base):
    # facility_type: String(100) — 기존 선택형 → 자유입력으로 변경 (DB 변경 없음, UI만 변경)
    # 추가 필드 없음 — Project에서 참조
```

#### IlluminanceArea 기구 다중화

```python
class IlluminanceArea(Base):
    # 기존: lamp_type, lamp_watt, lamp_qty (1종만)
    # 변경: fixtures JSON 필드 추가
    fixtures = Column(Text)  # JSON: [{"type":"LED투광등 400W","watt":400,"qty":4},{"type":"LED보안등 100W","watt":100,"qty":2}]
    # 기존 lamp_type, lamp_watt, lamp_qty는 호환성 유지 (1종일 때 사용)
```

### 3.2 설계현장 연결 시 자동 채움 강화

현재 `onErpProjectChange()`는 빈 필드만 채움 → **항상 채우도록 변경** (사용자 확인 후)

```javascript
function onErpProjectChange(sel) {
    const opt = sel.options[sel.selectedIndex];
    if (!opt.value) return;

    // 현장명: 항상 반영 (기존: 빈 경우만)
    document.getElementById('fieldName').value = opt.dataset.name || '';
    document.getElementById('fieldLocation').value = opt.dataset.addr || '';

    // 설계기준조도: Project에서 가져오기 (AJAX)
    fetch(`/api/project/${opt.value}/illuminance-info`)
        .then(r => r.json())
        .then(data => {
            if (data.facility_type) document.getElementById('fieldFacility').value = data.facility_type;
            if (data.design_lux) document.getElementById('fieldDesignLux').value = data.design_lux;
            if (data.design_uo) document.getElementById('fieldDesignUo').value = data.design_uo;
            // 기구 목록도 채움
        });
}
```

### 3.3 시설종류 자유입력

```html
<!-- 기존: select 5가지 -->
<!-- 변경: input + datalist (자유입력 + 추천) -->
<input type="text" name="facility_type" id="fieldFacility"
       list="facilityList" class="form-control"
       placeholder="예: 풋살장, 주차장, 테니스장, 보행로">
<datalist id="facilityList">
    <option value="풋살장">
    <option value="축구장">
    <option value="테니스장">
    <option value="주차장">
    <option value="보행로">
    <option value="운동장">
    <option value="공원">
    <option value="도로">
</datalist>
```

### 3.4 KS 기준 → 설계기준조도 전환

현재: `get_ks_standard(facility_type)` → 시설종류별 고정값
변경: **설계기준조도(lx)를 직접 입력** + 기존 KS 기준은 참고값으로 유지

```python
# 저장 시 우선순위:
# 1. 사용자가 입력한 설계기준조도 (design_lux)
# 2. ERP 설계관리에서 가져온 값 (Project.illuminance_design_lux)
# 3. 시설종류 기반 KS 기준 (get_ks_standard) — fallback

ks_eav = float(form.get('design_lux') or 0)
if not ks_eav and erp_project:
    ks_eav = erp_project.illuminance_design_lux or 0
if not ks_eav:
    ks = get_ks_standard(facility_type)
    ks_eav = ks.get('eav', 0)
```

### 3.5 1현장 다중 사이트 대응

**현재**: 1 IlluminanceProject = N Areas (구역)
**이미 가능**: 같은 ERP 현장(Project)에 여러 IlluminanceProject를 연결 가능

```
Project "○○공원"
├─ IlluminanceProject "○○공원 풋살장" (erp_project_id=1)
│   ├─ Area "풋살장 A코트"
│   └─ Area "풋살장 B코트"
└─ IlluminanceProject "○○공원 주차장" (erp_project_id=1)
    └─ Area "주차장 전체"
```

→ **별도 구조 변경 없이**, 설계관리 상세에서 연결된 조도검증 목록을 표시하면 해결

### 3.6 설계관리 ↔ 조도검증 양방향 연동

#### 설계관리 → 조도검증 (순방향)

설계관리 상세(contract_detail.html)에 **조도 설계정보 카드** 추가:

```
┌─ 조도 설계정보 ──────────────────────────┐
│ 시설종류: 풋살장           [수정]         │
│ 설계기준조도: 300 lx                      │
│ 설계균일도: 0.6                           │
│ 기구: LED투광등 400W × 8, 보안등 100W × 4 │
│                                          │
│ ─── 조도검증 현황 ────────────────────── │
│ ✅ ○○공원 풋살장 (측정완료, 달성률 105%)  │
│ ⏳ ○○공원 주차장 (설계단계)              │
│ [+ 조도검증 등록]                        │
└──────────────────────────────────────────┘
```

#### 조도검증 → 설계관리 (역방향)

조도검증 상세/리포트에서 설계관리 링크 표시:

```
설계현장: ○○공원 [설계관리 바로가기 →]
설계기준조도: 300 lx (설계관리 연동)
```

---

## 4. 구현 순서

```
Step 1: DB 스키마 변경
  ├─ Project 모델에 illuminance_* 필드 4개 추가
  ├─ IlluminanceArea에 fixtures JSON 필드 추가
  └─ sql_editer.sql에 ALTER TABLE 추가

Step 2: API 엔드포인트
  └─ GET /api/project/<id>/illuminance-info (설계조도 정보 반환)

Step 3: 설계관리 UI
  ├─ contract_detail.html에 조도 설계정보 카드 추가
  ├─ 조도 정보 편집 모달 (시설종류, 기준조도, 균일도, 기구)
  └─ 연결된 조도검증 프로젝트 목록 표시

Step 4: 조도검증 신규등록 개선
  ├─ 시설종류 → input+datalist 자유입력
  ├─ 설계기준조도(lx) 직접입력 필드 추가
  ├─ 설계현장 연결 시 자동 채움 강화 (AJAX)
  └─ KS 기준 → 설계기준조도 우선 로직

Step 5: 기구 다중화
  ├─ 신규등록에서 기구 N건 입력 UI
  ├─ Area 상세에서 기구 목록 표시
  └─ PDF 파서에서 기구 정보 자동 추출 (이미 lamp_type/watt 파싱 가능)

Step 6: 양방향 연동 완성
  ├─ 조도검증 상세에서 설계관리 링크
  ├─ 설계관리에서 조도검증 현황 (달성률, 상태)
  └─ 대시보드/현황판에 조도검증 요약 (선택)

Step 7: 검증
  └─ 신규등록 → 설계연결 → 정보반영 → 검증결과 → 설계관리 확인
```

## 5. 예상 결과

| 지표 | Before | After |
|------|--------|-------|
| 설계현장 연결 시 반영 필드 | 2개 (현장명, 주소) | 6개+ (현장명, 주소, 시설종류, 기준조도, 균일도, 기구) |
| 시설종류 선택지 | 5개 고정 | 무제한 (자유입력+추천) |
| 기구 종류 | 1종/구역 | N종/구역 |
| KS 기준 설정 | 시설종류 자동 (하드코딩) | 설계기준조도 직접입력 (설계관리 연동) |
| 다중 사이트 | 별도 프로젝트 필요 | 같은 현장에 N개 조도검증 연결, 설계관리에서 일괄 확인 |
| 설계-검증 연동 | 단방향 (조도검증→설계현장 ID만) | 양방향 (설계정보 공유 + 검증결과 표시) |

## 6. 리스크

| 리스크 | 확률 | 대응 |
|--------|------|------|
| 기존 데이터 호환 | 낮 | 기존 lamp_type/watt/qty 유지, fixtures는 추가 필드 |
| facility_type 자유입력 시 KS 매칭 불가 | 중 | 설계기준조도 직접입력을 우선, KS는 참고값 |
| contract_detail.html이 이미 965줄 | 중 | 조도 카드는 include 분리 또는 탭 추가 |
