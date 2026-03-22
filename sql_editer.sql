-- ══════════════════════════════════════════════
-- 예외처리 사유 컬럼 (2026-03-21)
-- ══════════════════════════════════════════════
ALTER TABLE light_sync.contracts ADD COLUMN IF NOT EXISTS exclude_reason VARCHAR(50);
ALTER TABLE light_sync.contracts ADD COLUMN IF NOT EXISTS exclude_note VARCHAR(200);

-- ══════════════════════════════════════════════
-- A/S 관리 시스템 전면 재설계 (2026-03-21)
-- ══════════════════════════════════════════════

-- 불필요 컬럼 제거
ALTER TABLE light_sync.warranties DROP COLUMN IF EXISTS project_name;

-- 테이블 생성은 Flask init_db() → Base.metadata.create_all()이 자동 처리
-- 아래는 기존 테이블에 새 컬럼을 추가하는 마이그레이션만 담당

-- 먼저 스키마 설정
SET search_path TO light_sync, public;

-- Warranty 비정규화 필드 (기존 테이블에 컬럼 추가)
ALTER TABLE light_sync.warranties ADD COLUMN IF NOT EXISTS contract_name VARCHAR(200);
ALTER TABLE light_sync.warranties ADD COLUMN IF NOT EXISTS project_name VARCHAR(200);
ALTER TABLE light_sync.warranties ADD COLUMN IF NOT EXISTS item_group VARCHAR(50);
ALTER TABLE light_sync.warranties ADD COLUMN IF NOT EXISTS model_name VARCHAR(200);
ALTER TABLE light_sync.warranties ADD COLUMN IF NOT EXISTS quantity INTEGER;
ALTER TABLE light_sync.warranties ADD COLUMN IF NOT EXISTS site_address VARCHAR(500);
ALTER TABLE light_sync.warranties ADD COLUMN IF NOT EXISTS customer_contact VARCHAR(200);
ALTER TABLE light_sync.warranties ADD COLUMN IF NOT EXISTS customer_phone VARCHAR(50);

-- WarrantyCase 유상/무상 + 고객 + 부품 + 물류 + 비정규화
ALTER TABLE light_sync.warranty_cases ADD COLUMN IF NOT EXISTS is_chargeable BOOLEAN DEFAULT FALSE;
ALTER TABLE light_sync.warranty_cases ADD COLUMN IF NOT EXISTS charge_amount INTEGER DEFAULT 0;
ALTER TABLE light_sync.warranty_cases ADD COLUMN IF NOT EXISTS charge_status VARCHAR(20);
ALTER TABLE light_sync.warranty_cases ADD COLUMN IF NOT EXISTS request_channel VARCHAR(30);
ALTER TABLE light_sync.warranty_cases ADD COLUMN IF NOT EXISTS customer_name VARCHAR(100);
ALTER TABLE light_sync.warranty_cases ADD COLUMN IF NOT EXISTS customer_phone VARCHAR(50);
ALTER TABLE light_sync.warranty_cases ADD COLUMN IF NOT EXISTS parts_json TEXT;
ALTER TABLE light_sync.warranty_cases ADD COLUMN IF NOT EXISTS shipping_method VARCHAR(30);
ALTER TABLE light_sync.warranty_cases ADD COLUMN IF NOT EXISTS shipping_tracking VARCHAR(100);
ALTER TABLE light_sync.warranty_cases ADD COLUMN IF NOT EXISTS shipping_date DATE;
ALTER TABLE light_sync.warranty_cases ADD COLUMN IF NOT EXISTS contract_name VARCHAR(200);
ALTER TABLE light_sync.warranty_cases ADD COLUMN IF NOT EXISTS item_group VARCHAR(50);
ALTER TABLE light_sync.warranty_cases ADD COLUMN IF NOT EXISTS model_name VARCHAR(200);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_warranty_end ON light_sync.warranties(warranty_end);
CREATE INDEX IF NOT EXISTS idx_warranty_type ON light_sync.warranties(warranty_type);
CREATE INDEX IF NOT EXISTS idx_case_status ON light_sync.warranty_cases(status);
CREATE INDEX IF NOT EXISTS idx_case_reported ON light_sync.warranty_cases(reported_date DESC);

-- ══════════════════════════════════════════════
-- 아카이브 (워크보드+A/S 과거 데이터) (2026-03-21)
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS light_sync.archive_posts (
    id INTEGER PRIMARY KEY,
    board_type VARCHAR(20) NOT NULL,
    author VARCHAR(100),
    content_text TEXT,
    is_notice BOOLEAN DEFAULT FALSE,
    children_count INTEGER DEFAULT 0,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS light_sync.archive_comments (
    id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES light_sync.archive_posts(id) ON DELETE CASCADE,
    author VARCHAR(100),
    content_text TEXT,
    created_at TIMESTAMP
);

-- ══════════════════════════════════════════════
-- 조도검증-설계관리 통합 연동 (2026-03-21)
-- ══════════════════════════════════════════════
ALTER TABLE light_sync.projects ADD COLUMN IF NOT EXISTS illuminance_facility_type VARCHAR(100);
ALTER TABLE light_sync.projects ADD COLUMN IF NOT EXISTS illuminance_design_lux FLOAT;
ALTER TABLE light_sync.projects ADD COLUMN IF NOT EXISTS illuminance_design_uo FLOAT;
ALTER TABLE light_sync.projects ADD COLUMN IF NOT EXISTS illuminance_fixtures TEXT;
ALTER TABLE light_sync.illuminance_areas ADD COLUMN IF NOT EXISTS fixtures TEXT;
ALTER TABLE light_sync.illuminance_projects ALTER COLUMN facility_type TYPE VARCHAR(100);

-- ══════════════════════════════════════════════
-- 매그나텍 업무플로우 보강 (2026-03-21)
-- ══════════════════════════════════════════════

-- 스키마 설정
SET search_path TO light_sync, public;

-- 0) G2B→계약 동기화: project_id nullable 변경
ALTER TABLE light_sync.contracts ALTER COLUMN project_id DROP NOT NULL;
ALTER TABLE light_sync.warranties ALTER COLUMN contract_id DROP NOT NULL;
ALTER TABLE light_sync.warranties ALTER COLUMN project_id DROP NOT NULL;
ALTER TABLE light_sync.warranties DROP CONSTRAINT IF EXISTS warranties_contract_id_key;  -- unique 제약 제거 (G2B 건은 contract 없을 수 있음)

-- 1) 검수 관리: 검수자 컬럼
ALTER TABLE light_sync.deliveries ADD COLUMN IF NOT EXISTS inspector VARCHAR(100);

-- 2) 인증서 만료 관리
CREATE TABLE IF NOT EXISTS light_sync.certifications (
    id SERIAL PRIMARY KEY,
    cert_type VARCHAR(50) NOT NULL,               -- KS인증/성능인증/녹색기술인증/환경표지/조달우수제품/G-PASS/기타
    cert_name VARCHAR(200) NOT NULL,               -- 인증서명
    cert_no VARCHAR(100),                          -- 인증번호
    issued_by VARCHAR(200),                        -- 발급기관
    issued_date DATE,                              -- 발급일
    expiry_date DATE,                              -- 만료일
    product_model VARCHAR(200),                    -- 대상 제품/모델
    alert_days INTEGER DEFAULT 30,                 -- 만료 전 알림 일수
    file_path VARCHAR(500),                        -- 첨부파일 경로
    note TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 3) 하자보증: 보증유형 + 자동산출
ALTER TABLE light_sync.warranties ADD COLUMN IF NOT EXISTS warranty_type VARCHAR(20) DEFAULT '일반';
ALTER TABLE light_sync.warranties ADD COLUMN IF NOT EXISTS auto_generated BOOLEAN DEFAULT FALSE;

-- 4) 시방서/규격서 추적
CREATE TABLE IF NOT EXISTS light_sync.spec_documents (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES light_sync.projects(id) ON DELETE CASCADE,
    doc_type VARCHAR(30) NOT NULL DEFAULT '시방서',
    doc_status VARCHAR(20) NOT NULL DEFAULT '미제출',
    title VARCHAR(300),
    file_path VARCHAR(500),
    submitted_date DATE,
    confirmed_date DATE,
    note TEXT,
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 5) 조도 시뮬레이션 설계 보고서
CREATE TABLE IF NOT EXISTS light_sync.design_simulation_docs (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES light_sync.projects(id) ON DELETE CASCADE,
    doc_type VARCHAR(30) NOT NULL DEFAULT 'DIALux',
    title VARCHAR(300),
    file_path VARCHAR(500),
    simulation_date DATE,
    target_lux FLOAT,
    achieved_lux FLOAT,
    uniformity FLOAT,
    note TEXT,
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);

-- ══════════════════════════════════════════════
-- 채널 권한 + 프리셋 테이블 (2026-03-21)
-- ══════════════════════════════════════════════
ALTER TABLE chatbot_permissions
    ADD COLUMN IF NOT EXISTS channel_enabled BOOLEAN DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS chatbot_presets (
    name TEXT PRIMARY KEY,
    tools_json TEXT NOT NULL,
    channel_enabled BOOLEAN DEFAULT FALSE
);

-- ══════════════════════════════════════════════
-- 조도검증 ↔ 설계현장 연동 컬럼 추가 (2026-03-20)
-- ══════════════════════════════════════════════
ALTER TABLE illuminance_projects
    ADD COLUMN IF NOT EXISTS erp_project_id INTEGER REFERENCES light_sync.projects(id) ON DELETE SET NULL;

-- ══════════════════════════════════════════════
-- 조도설계 검증 시스템 (2026-03-20)
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS illuminance_projects (
    id SERIAL PRIMARY KEY, project_name VARCHAR(200) NOT NULL,
    customer VARCHAR(200), location VARCHAR(500), install_date DATE,
    pdf_filename VARCHAR(300), facility_type VARCHAR(50),
    status VARCHAR(20) DEFAULT 'design', notes TEXT,
    created_by VARCHAR(50), created_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS illuminance_areas (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES illuminance_projects(id) ON DELETE CASCADE,
    area_name VARCHAR(200) NOT NULL, area_index INTEGER DEFAULT 1,
    installation_height FLOAT, lamp_type VARCHAR(100), lamp_watt INTEGER,
    lamp_qty INTEGER, tower_qty INTEGER, simulation_date DATE,
    design_eav FLOAT, design_emin FLOAT, design_emax FLOAT,
    design_uo FLOAT, design_ud FLOAT,
    maintenance_factor FLOAT, total_flux FLOAT, total_power FLOAT, power_per_area FLOAT,
    grid_rows INTEGER, grid_cols INTEGER,
    grid_x_labels TEXT, grid_y_labels TEXT, design_grid TEXT,
    ks_eav_min FLOAT, ks_uo_min FLOAT, created_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS illuminance_measured (
    id SERIAL PRIMARY KEY,
    area_id INTEGER NOT NULL REFERENCES illuminance_areas(id) ON DELETE CASCADE,
    measure_date DATE NOT NULL, measured_by VARCHAR(100),
    weather VARCHAR(50), instrument VARCHAR(200),
    measured_eav FLOAT, measured_emin FLOAT, measured_emax FLOAT,
    measured_uo FLOAT, measured_ud FLOAT, measured_grid TEXT,
    ks_pass VARCHAR(10), eav_achievement FLOAT, uo_achievement FLOAT,
    notes TEXT, created_at TIMESTAMP DEFAULT NOW()
);


-- ERP 챗봇 웹 조회 권한 (2026-03-20)
CREATE TABLE IF NOT EXISTS chatbot_permissions (
    erp_username TEXT PRIMARY KEY,
    allowed_tools TEXT NOT NULL
);

-- 견적서 테이블 생성 (2026-03-19)
CREATE TABLE IF NOT EXISTS quotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_no VARCHAR(20) UNIQUE NOT NULL,
    quote_date DATE NOT NULL,
    validity_period VARCHAR(100) DEFAULT '견적일로부터 1개월',
    delivery_date VARCHAR(100) DEFAULT '협의',
    payment_method VARCHAR(100) DEFAULT '현금',
    bank_account VARCHAR(200),
    project_name VARCHAR(500),
    customer_name VARCHAR(200),
    customer_contact VARCHAR(100),
    customer_address VARCHAR(500),
    customer_tel VARCHAR(50),
    customer_fax VARCHAR(50),
    customer_email VARCHAR(200),
    total_amount REAL DEFAULT 0,
    tax_included BOOLEAN DEFAULT 0,
    note TEXT,
    status VARCHAR(20) DEFAULT '작성중',
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS quotation_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quotation_id INTEGER NOT NULL REFERENCES quotations(id) ON DELETE CASCADE,
    seq INTEGER DEFAULT 0,
    item_id INTEGER,
    item_name VARCHAR(300) NOT NULL,
    item_spec VARCHAR(500),
    unit VARCHAR(50) DEFAULT '개',
    quantity REAL DEFAULT 0,
    unit_price REAL DEFAULT 0,
    amount REAL DEFAULT 0,
    note VARCHAR(500)
);

-- 견적서 부과금/템플릿 확장 (2026-03-19)
ALTER TABLE quotations ADD COLUMN surcharges_json TEXT;
ALTER TABLE quotations ADD COLUMN grand_total REAL DEFAULT 0;

CREATE TABLE IF NOT EXISTS quote_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_name VARCHAR(200) NOT NULL,
    note TEXT,
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS quote_template_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id INTEGER NOT NULL REFERENCES quote_templates(id) ON DELETE CASCADE,
    seq INTEGER DEFAULT 0,
    item_name VARCHAR(300) NOT NULL,
    item_spec VARCHAR(500),
    unit VARCHAR(50) DEFAULT '개',
    quantity REAL DEFAULT 0,
    unit_price REAL DEFAULT 0,
    amount REAL DEFAULT 0,
    note VARCHAR(500)
);

-- history-board-ux v1.1 마이그레이션 (2026-03-19)
-- 매그나텍 업무 프로세스 연동: 검수(PHASE 7) / 대금(PHASE 8) / 설계확인(PHASE 2-3)

-- projects: 시방서 반영 확인
ALTER TABLE light_sync.projects ADD COLUMN spec_confirmed BOOLEAN DEFAULT FALSE;
ALTER TABLE light_sync.projects ADD COLUMN spec_confirmed_date DATE;

-- contracts: 대금 관리
ALTER TABLE light_sync.contracts ADD COLUMN payment_status VARCHAR(20) DEFAULT '미청구';
ALTER TABLE light_sync.contracts ADD COLUMN invoice_date DATE;
ALTER TABLE light_sync.contracts ADD COLUMN payment_date DATE;

-- deliveries: 검수 관리
ALTER TABLE light_sync.deliveries ADD COLUMN inspection_status VARCHAR(20) DEFAULT '미검수';
ALTER TABLE light_sync.deliveries ADD COLUMN inspection_date DATE;
ALTER TABLE light_sync.deliveries ADD COLUMN inspection_note TEXT;

-- ===================================================================
-- 세금계산서 + 수금관리 테이블 (2026-03-19)
-- ===================================================================

-- tax_invoices: 국세청 매출전자세금계산서
CREATE TABLE IF NOT EXISTS light_sync.tax_invoices (
    id SERIAL PRIMARY KEY,
    approval_no VARCHAR(50) UNIQUE NOT NULL,
    issue_date DATE,
    send_date DATE,
    invoice_type VARCHAR(20) DEFAULT '세금계산서',
    supplier_business_no VARCHAR(20),
    supplier_name VARCHAR(200),
    buyer_business_no VARCHAR(20),
    buyer_name VARCHAR(200),
    buyer_ceo VARCHAR(100),
    total_amount INTEGER DEFAULT 0,
    supply_amount INTEGER DEFAULT 0,
    tax_amount INTEGER DEFAULT 0,
    item_date DATE,
    item_name VARCHAR(200),
    item_spec VARCHAR(200),
    item_qty INTEGER DEFAULT 0,
    item_unit_price INTEGER DEFAULT 0,
    remark TEXT,
    g2b_contract_no VARCHAR(30),
    g2b_delivery_req_no VARCHAR(30),
    g2b_delivery_no VARCHAR(30),
    contract_id INTEGER REFERENCES light_sync.contracts(id),
    project_id INTEGER REFERENCES light_sync.projects(id),
    match_status VARCHAR(20) DEFAULT '미매칭',
    payment_status VARCHAR(20) DEFAULT '미수금',
    paid_amount INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- payment_records: 수금 기록
-- 기존 임포트 데이터 초기화 (매칭 로직 수정 후 재임포트 필요)
DELETE FROM light_sync.tax_invoices;

-- tax_invoices: 비고에서 파싱한 계약명 컬럼 추가
ALTER TABLE light_sync.tax_invoices ADD COLUMN g2b_contract_name VARCHAR(300);

CREATE TABLE IF NOT EXISTS light_sync.payment_records (
    id SERIAL PRIMARY KEY,
    tax_invoice_id INTEGER NOT NULL REFERENCES light_sync.tax_invoices(id) ON DELETE CASCADE,
    payment_date DATE NOT NULL,
    amount INTEGER DEFAULT 0,
    payment_method VARCHAR(30) DEFAULT '계좌이체',
    note TEXT,
    created_by VARCHAR(50) DEFAULT '사용자',
    created_at TIMESTAMP DEFAULT NOW()
);

-- ===================================================================
-- 재고관리 (inventory-management) 마이그레이션 (2026-03-19)
-- ===================================================================

-- items: 안전재고 + 최근단가
ALTER TABLE light_sync.items ADD COLUMN safety_stock FLOAT DEFAULT 0;
ALTER TABLE light_sync.items ADD COLUMN last_unit_price FLOAT DEFAULT 0;

-- stock_audits: 재고실사 회차
CREATE TABLE IF NOT EXISTS light_sync.stock_audits (
    id SERIAL PRIMARY KEY,
    audit_no VARCHAR(30) NOT NULL,
    audit_date DATE NOT NULL,
    status VARCHAR(20) DEFAULT '진행중',
    category_filter VARCHAR(50),
    note TEXT,
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    confirmed_at TIMESTAMP
);

-- stock_audit_items: 재고실사 품목별
CREATE TABLE IF NOT EXISTS light_sync.stock_audit_items (
    id SERIAL PRIMARY KEY,
    audit_id INTEGER NOT NULL REFERENCES light_sync.stock_audits(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES light_sync.items(id),
    system_qty FLOAT DEFAULT 0,
    actual_qty FLOAT,
    diff_qty FLOAT DEFAULT 0,
    note TEXT
);

-- stock_movements: 재고 변동 이력
CREATE TABLE IF NOT EXISTS light_sync.stock_movements (
    id SERIAL PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES light_sync.items(id),
    movement_type VARCHAR(30) NOT NULL,
    quantity FLOAT DEFAULT 0,
    before_qty FLOAT DEFAULT 0,
    after_qty FLOAT DEFAULT 0,
    reference_type VARCHAR(30),
    reference_id INTEGER,
    note TEXT,
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);

-- stock_audits: 누락 컬럼 보정 (테이블이 이미 생성된 경우)
ALTER TABLE light_sync.stock_audits ADD COLUMN confirmed_at TIMESTAMP;
ALTER TABLE light_sync.stock_audits ADD COLUMN auditor_id INTEGER;
ALTER TABLE light_sync.stock_audits ADD COLUMN auditor_name VARCHAR(50);
ALTER TABLE light_sync.stock_audits ADD COLUMN total_items INTEGER DEFAULT 0;
ALTER TABLE light_sync.stock_audits ADD COLUMN diff_items INTEGER DEFAULT 0;
ALTER TABLE light_sync.stock_audits ADD COLUMN updated_at TIMESTAMP DEFAULT NOW();

-- daily_reports: 자동수집 항목 수정 가능
ALTER TABLE light_sync.daily_reports ADD COLUMN auto_items_json TEXT;

-- ===================================================================
-- 슈퍼BOM: 옵션별 BOM 필터링 (2026-03-19)
-- ===================================================================
ALTER TABLE light_sync.bom_headers ADD COLUMN option_schema TEXT;
ALTER TABLE light_sync.bom_items ADD COLUMN option_filter TEXT;

-- ===================================================================
-- 사진관리: project_photos 테이블 (2026-03-20)
-- ===================================================================
CREATE TABLE light_sync.project_photos (
    id           SERIAL PRIMARY KEY,
    project_id   INTEGER NOT NULL REFERENCES light_sync.projects(id) ON DELETE CASCADE,
    contract_id  INTEGER REFERENCES light_sync.contracts(id) ON DELETE SET NULL,
    photo_type   VARCHAR(30) DEFAULT '기타',
    file_name    VARCHAR(255) NOT NULL,
    storage_path VARCHAR(500) NOT NULL,
    uploaded_by  VARCHAR(50)  DEFAULT '사용자',
    created_at   TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_project_photos_project_id ON light_sync.project_photos(project_id);

-- ===================================================================
-- 최고관리자 비밀번호 리셋 (2026-03-20)
-- ===================================================================
UPDATE light_sync.users SET password_hash = '$2b$12$VKRbB8LtZeXoTV7mZCW7MebFTvU9U/YhI4TKsUW5fA47CaI01ntdS' WHERE username = 'magnatech';

-- ===================================================================
-- 사용자 정리: admin/test/magna_test 삭제 + magnatech id=1 (2026-03-20)
-- ===================================================================

-- 1. FK 참조 정리
DELETE FROM light_sync.user_priority_permissions WHERE user_id IN (1, 3, 4) OR granted_by_user_id IN (1, 3, 4);

-- 2. 삭제 대상 사용자 제거
DELETE FROM light_sync.users WHERE username IN ('admin', 'test', 'magna_test');

-- 3. magnatech(id=7) → id=1로 변경
UPDATE light_sync.user_priority_permissions SET user_id = 1 WHERE user_id = 7;
UPDATE light_sync.user_priority_permissions SET granted_by_user_id = 1 WHERE granted_by_user_id = 7;
UPDATE light_sync.users SET id = 1 WHERE id = 7;

-- 4. 시퀀스 리셋 (다음 가입자 id 충돌 방지)
SELECT setval('light_sync.users_id_seq', (SELECT MAX(id) FROM light_sync.users));

-- ===================================================================
-- 입고예정: PurchaseOrderItem에 예정일/확인 컬럼 추가 (2026-03-20)
-- ===================================================================
ALTER TABLE light_sync.purchase_order_items ADD COLUMN expected_in_date DATE;
ALTER TABLE light_sync.purchase_order_items ADD COLUMN in_confirmed BOOLEAN DEFAULT FALSE;
ALTER TABLE light_sync.purchase_order_items ADD COLUMN in_confirmed_at TIMESTAMP;

-- ===================================================================
-- 챗봇 대화 히스토리 영구저장 (2026-03-21)
-- ===================================================================
CREATE TABLE IF NOT EXISTS light_sync.chatbot_history (
    session_id TEXT PRIMARY KEY,
    messages_json TEXT NOT NULL DEFAULT '[]',
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ===================================================================
-- RW 권한 분리 + 금액 가시성 제어 (2026-03-22)
-- ===================================================================
ALTER TABLE light_sync.group_permissions ADD COLUMN IF NOT EXISTS hide_financial BOOLEAN DEFAULT FALSE;
ALTER TABLE light_sync.users ADD COLUMN IF NOT EXISTS hide_financial_override BOOLEAN;

-- 부서별 R/RW 권한 + 금액 숨김 설정 (2026-03-22)
UPDATE light_sync.group_permissions SET
  allowed_menus = 'project:rw,contract:rw,sales:rw,quotation:rw,delivery:rw,illuminance:rw,item:r,material:r,bom:r,inventory:r,procurement:rw,procurement_summary:r,warranty:rw,photos:rw,drawing:rw,production:r',
  hide_financial = TRUE
WHERE group_name = '영업부';

UPDATE light_sync.group_permissions SET
  allowed_menus = 'project:r,contract:r,delivery:r,item:rw,material:rw,vendor:rw,purchase_order:rw,receiving:rw,bom:rw,inventory:rw,certification:rw,procurement:r,procurement_summary:r,warranty:rw,photos:rw,drawing:r,production:r',
  hide_financial = TRUE
WHERE group_name = '관리부';

UPDATE light_sync.group_permissions SET
  allowed_menus = 'contract:r,sales:r,delivery:r,material:r,inventory:r,warranty:rw,photos:rw,drawing:r,production:rw',
  hide_financial = TRUE
WHERE group_name = '생산부';

UPDATE light_sync.group_permissions SET
  allowed_menus = 'project:rw,contract:rw,sales:rw,quotation:rw,delivery:rw,illuminance:rw,item:rw,material:rw,vendor:rw,purchase_order:rw,receiving:rw,bom:rw,inventory:rw,procurement:rw,procurement_summary:rw,warranty:rw,photos:rw,drawing:rw,production:rw,certification:rw',
  hide_financial = FALSE
WHERE group_name = '임원진';

-- ===================================================================
-- warranty_cases: warranty_id, project_id NULL 허용 (수기입력 지원) (2026-03-22)
-- ===================================================================
ALTER TABLE light_sync.warranty_cases ALTER COLUMN warranty_id DROP NOT NULL;
ALTER TABLE light_sync.warranty_cases ALTER COLUMN project_id DROP NOT NULL;
