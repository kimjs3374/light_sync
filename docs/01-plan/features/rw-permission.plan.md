# RW 권한 분리 + 금액 필드 가시성 제어

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | 메뉴 R/RW 권한 분리 + 부서별 금액 컬럼 숨김 |
| 시작일 | 2026-03-22 |
| 예상 범위 | config.py, auth_decorators.py, auth.py, app.py, admin_menu_perms.html + 금액 포함 템플릿 |

| 관점 | 내용 |
|------|------|
| **문제** | 메뉴 접근이 Boolean(있다/없다)이라 "보기만 허용" 불가, 금액 정보가 모든 사용자에게 노출 |
| **해결** | 메뉴별 R/RW 구분 + 부서별 hide_financial 플래그로 금액 컬럼 자체 제거 |
| **기능 UX** | R 권한 사용자는 수정 버튼이 안 보이고, 금액 비노출 사용자는 해당 컬럼 자체가 없는 화면을 봄 |
| **핵심 가치** | 부서 간 데이터 보호 + 실수 방지, 자연스러운 UX |

## 1. 배경 및 목적

### 실제 요구사항 3건

| # | 상황 | 누가 | 뭘 | 어떻게 |
|---|------|------|-----|--------|
| 1 | 금액 숨기기 | 일반직원(생산부 등) | 계약금액, 단가, 발주금액 | 해당 컬럼 자체를 안 보여줌 |
| 2 | 타 부서 읽기전용 | 생산부 → 영업 협의 확인 | 영업관리 화면 | 메뉴 접근은 되지만 수정 버튼 미노출 |
| 3 | 타 부서 읽기전용 | 영업부 → 재고 확인 | 재고관리 화면 | 메뉴 접근은 되지만 수정 버튼 미노출 |

## 2. 현재 구조 분석

### 권한 데이터 흐름
```
GroupPermission.allowed_menus = "contract,sales,inventory"  (CSV)
User.extra_menus = "production"  (CSV, 개인 추가)
  ↓ 로그인 시 병합
session['allowed_menus'] = ["contract","sales","inventory","production"]
  ↓ 라우트 접근
@menu_required("contract")  → allowed에 있으면 통과
  ↓ 사이드바
inject_sidebar_menus()  → allowed에 있으면 메뉴 표시
```

### 한계
- **접근 여부만 판단** — R/W 구분 없음
- **금액 필드 제어 없음** — 모든 사용자에게 동일한 화면
- **POST 요청 차단 불가** — 메뉴 접근 가능하면 GET/POST 모두 허용

## 3. 설계 방향

### 3-1. 메뉴 R/RW 분리

**CSV 형식 확장 (하위호환)**
```
기존:  "contract,sales,inventory"
확장:  "contract:rw,sales:rw,inventory:r"
기본값: 접미사 없으면 :rw (하위호환)
```

**세션 저장 구조 변경**
```python
# 기존
session['allowed_menus'] = ["contract", "sales", "inventory"]

# 변경
session['allowed_menus'] = ["contract", "sales", "inventory"]  # 유지 (사이드바 호환)
session['writable_menus'] = ["contract", "sales"]              # 추가 (쓰기 가능 메뉴)
```

**데코레이터 확장**
```python
# 기존
@menu_required("contract")  # 접근 여부만

# 확장
@menu_required("contract")           # 읽기 접근 (GET)
@menu_required("contract", write=True)  # 쓰기 접근 (POST/수정)
```

**템플릿에서 쓰기 버튼 제어**
```html
{% if "contract" in session.get("writable_menus", []) %}
  <button>수정</button>
{% endif %}
```

### 3-2. 금액 필드 가시성

**GroupPermission에 hide_financial 컬럼 추가**
```sql
ALTER TABLE light_sync.group_permissions ADD COLUMN hide_financial BOOLEAN DEFAULT FALSE;
```

**세션에 플래그 추가**
```python
session['hide_financial'] = group_data.hide_financial or False
```

**템플릿에서 금액 컬럼 조건부 렌더링**
```html
{% if not session.get('hide_financial') %}
  <th>계약금액</th>
{% endif %}
```

- `***` 마스킹이 아닌 **컬럼 자체 미표시** → "원래 이 화면에 금액이 없구나"

## 4. 수정 대상 파일

### 핵심 (6개)
| # | 파일 | 변경 내용 |
|---|------|-----------|
| 1 | `config.py` | DEFAULT_GROUP_MENUS 형식에 :r/:rw 예시 추가 |
| 2 | `modules/auth_decorators.py` | menu_required에 write 파라미터 추가 |
| 3 | `routes/auth.py` | 로그인 시 writable_menus 파싱, hide_financial 세션 저장 |
| 4 | `app.py` | inject_sidebar_menus에 writable 정보 전달 |
| 5 | `modules/models/auth_entities.py` | GroupPermission에 hide_financial 컬럼 |
| 6 | `templates/partials/admin_menu_perms.html` | 체크박스 UI를 R/RW 2열로 변경 |

### 금액 숨김 대상 템플릿 (금액 컬럼 포함 화면)
| # | 템플릿 | 금액 필드 |
|---|--------|-----------|
| 1 | `contract_detail.html` | 계약금액, 단가 |
| 2 | `contract_list_card.html` | 계약금액 |
| 3 | `material_management.html` | 발주금액, 단가 |
| 4 | `receiving_list.html` | 입고단가, 금액 |
| 5 | `purchase_order_*.html` | 발주 합계, 단가 |
| 6 | `financial_dashboard.html` | 매출 전체 |
| 7 | `quotation_*.html` | 견적 금액 |
| 8 | `inventory*.html` | 재고금액, 재고단가 |
| 9 | `procurement*.html` | 조달 계약금액 |

### POST 라우트 쓰기 차단 대상
| # | 라우트 파일 | 주요 POST 핸들러 |
|---|------------|-----------------|
| 1 | `routes/material.py` | sync, update, bulk_update |
| 2 | `routes/inventory_routes.py` | 재고 조정, 실사 |
| 3 | `routes/sales.py` | 영업 상태 변경 |
| 4 | `routes/production.py` | 공정 상태 변경 |

## 5. 구현 순서

1. **DB** — GroupPermission에 hide_financial 추가
2. **백엔드** — auth_decorators.py 수정, auth.py 로그인 로직 수정
3. **사이드바** — app.py context processor 수정
4. **관리 UI** — admin_menu_perms.html R/RW 체크박스
5. **금액 숨김** — 각 템플릿에 `{% if not hide_financial %}` 래핑
6. **쓰기 차단** — 주요 POST 라우트에 write=True 데코레이터 적용

## 6. 하위호환

- 기존 CSV `"contract,sales"` → `:rw` 기본값으로 해석 (변환 불필요)
- `hide_financial` 기본값 `False` → 기존 동작 유지
- 관리자/임원진 → 항상 RW + 금액 표시 (기존과 동일)
