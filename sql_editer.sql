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
