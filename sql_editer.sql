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
