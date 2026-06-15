-- ══════════════════════════════════════════════
-- 서류 패키지 조립 순서 (2026-04-03)
-- ══════════════════════════════════════════════
-- 전체 기본 순서 저장용
CREATE TABLE IF NOT EXISTS light_sync.system_settings (
    key VARCHAR(100) PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 현장별 개별 순서 저장용
ALTER TABLE light_sync.document_packages ADD COLUMN IF NOT EXISTS assembly_order JSONB;

-- ══════════════════════════════════════════════
-- 현장대리인계용 직원 개인정보 컬럼 (2026-04-02)
-- ══════════════════════════════════════════════
ALTER TABLE light_sync.users ADD COLUMN IF NOT EXISTS address VARCHAR(300);
ALTER TABLE light_sync.users ADD COLUMN IF NOT EXISTS birth_date DATE;
ALTER TABLE light_sync.users ADD COLUMN IF NOT EXISTS hire_date DATE;

-- 기존 엑셀 하드코딩 데이터 이관
UPDATE light_sync.users SET address='광주광역시 광산구 사암로215번길 16', birth_date='1990-03-09', hire_date='2017-11-13' WHERE full_name='김정수';
UPDATE light_sync.users SET address='광주광역시 광산구 수등로 287', birth_date='1991-10-20', hire_date='2023-08-01' WHERE full_name='김선중';
UPDATE light_sync.users SET address='광주광역시 광산구 신창동 1285', birth_date='1991-10-05', hire_date='2024-05-21' WHERE full_name='최한진';

-- ══════════════════════════════════════════════
-- 변경계약 추적용 변경차수 컬럼 (2026-04-02)
-- ══════════════════════════════════════════════
ALTER TABLE light_sync.contracts
    ADD COLUMN IF NOT EXISTS g2b_change_ord VARCHAR(5) DEFAULT '00';

-- 기존 계약의 변경차수 일괄 세팅 (G2B 데이터 기준)
UPDATE light_sync.contracts c
SET g2b_change_ord = sub.max_chg
FROM (
    SELECT cntrct_dlvr_req_no, MAX(cntrct_dlvr_req_chg_ord) as max_chg
    FROM light_sync.g2b_procurements
    WHERE fnl_cntrct_dlvr_req_chg_ord_yn = 'Y' OR fnl_cntrct_dlvr_req_chg_ord_yn IS NULL
    GROUP BY cntrct_dlvr_req_no
) sub
WHERE c.g2b_contract_no = sub.cntrct_dlvr_req_no
  AND c.g2b_contract_no IS NOT NULL;

-- ══════════════════════════════════════════════
-- 외부메일 계정 정렬순서 (2026-04-02)
-- ══════════════════════════════════════════════
ALTER TABLE light_sync.mail_accounts
    ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0;

-- ══════════════════════════════════════════════
-- 외부메일 계정 지원 (2026-04-02)
-- ══════════════════════════════════════════════
ALTER TABLE light_sync.mail_accounts
    ADD COLUMN IF NOT EXISTS account_type VARCHAR(20) DEFAULT 'internal';

-- 기존 계정은 모두 internal
UPDATE light_sync.mail_accounts SET account_type = 'internal' WHERE account_type IS NULL;

-- ══════════════════════════════════════════════
-- 웹메일 테이블 (2026-04-01)
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS light_sync.mail_accounts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES light_sync.users(id),
    email VARCHAR(255) NOT NULL,
    display_name VARCHAR(100),
    imap_host VARCHAR(255) NOT NULL DEFAULT '192.168.0.101',
    imap_port INTEGER NOT NULL DEFAULT 993,
    smtp_host VARCHAR(255) NOT NULL DEFAULT '192.168.0.101',
    smtp_port INTEGER NOT NULL DEFAULT 587,
    username VARCHAR(255) NOT NULL,
    password_encrypted TEXT NOT NULL,
    use_ssl BOOLEAN DEFAULT TRUE,
    is_shared BOOLEAN DEFAULT FALSE,
    signature TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS light_sync.mail_shared_access (
    id SERIAL PRIMARY KEY,
    mail_account_id INTEGER NOT NULL REFERENCES light_sync.mail_accounts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES light_sync.users(id),
    can_send BOOLEAN DEFAULT FALSE,
    can_delete BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(mail_account_id, user_id)
);

CREATE TABLE IF NOT EXISTS light_sync.mail_contacts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES light_sync.users(id),
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL,
    company VARCHAR(200),
    memo TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mail_accounts_user_id ON light_sync.mail_accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_mail_shared_access_user_id ON light_sync.mail_shared_access(user_id);
CREATE INDEX IF NOT EXISTS idx_mail_contacts_user_id ON light_sync.mail_contacts(user_id);

-- ══════════════════════════════════════════════
-- 납품관리 모델별 분할납품 (2026-03-30)
-- delivery_splits.contract_item_id (레거시 단일 모델, 유지)
-- delivery_split_items (회차별 복수 모델 수량)
-- ══════════════════════════════════════════════
ALTER TABLE light_sync.delivery_splits
ADD COLUMN IF NOT EXISTS contract_item_id INTEGER REFERENCES light_sync.contract_items(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_delivery_splits_contract_item_id
ON light_sync.delivery_splits(contract_item_id);

CREATE TABLE IF NOT EXISTS light_sync.delivery_split_items (
    id SERIAL PRIMARY KEY,
    split_id INTEGER NOT NULL REFERENCES light_sync.delivery_splits(id) ON DELETE CASCADE,
    contract_item_id INTEGER NOT NULL REFERENCES light_sync.contract_items(id) ON DELETE CASCADE,
    quantity INTEGER DEFAULT 0,
    UNIQUE(split_id, contract_item_id)
);
CREATE INDEX IF NOT EXISTS idx_dsi_split_id ON light_sync.delivery_split_items(split_id);
CREATE INDEX IF NOT EXISTS idx_dsi_contract_item_id ON light_sync.delivery_split_items(contract_item_id);

-- ══════════════════════════════════════════════
-- G2B 자동생성 유령 프로젝트 12건 삭제 (2026-03-30)
-- 원인: auto_create_contracts()에 날짜 컷오프 없어서
--       2020~2024년 과거 G2B 건이 G-2026-0032~0043으로 생성됨
-- ══════════════════════════════════════════════
DELETE FROM light_sync.contract_items
WHERE contract_id IN (
  SELECT c.id FROM light_sync.contracts c
  JOIN light_sync.projects p ON p.id = c.project_id
  WHERE p.id IN (4200,4201,4202,4203,4204,4205,4206,4207,4208,4209,4210,4211)
);

DELETE FROM light_sync.contracts
WHERE project_id IN (4200,4201,4202,4203,4204,4205,4206,4207,4208,4209,4210,4211);

DELETE FROM light_sync.projects
WHERE id IN (4200,4201,4202,4203,4204,4205,4206,4207,4208,4209,4210,4211);
-- 삭제 대상: G-2026-0032(순천시민로) ~ G-2026-0043(태백LED투광등)

-- ══════════════════════════════════════════════
-- BOM 모델명 별칭 테이블 (2026-03-28)
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS light_sync.bom_model_aliases (
  id SERIAL PRIMARY KEY,
  bom_id INTEGER NOT NULL REFERENCES light_sync.bom_headers(id) ON DELETE CASCADE,
  alias_name VARCHAR(200) NOT NULL,
  alias_type VARCHAR(20) DEFAULT 'manual',
  note VARCHAR(300),
  created_at TIMESTAMP DEFAULT NOW(),
  created_by VARCHAR(50) DEFAULT '시스템',
  CONSTRAINT uq_bom_alias UNIQUE(alias_name)
);
CREATE INDEX IF NOT EXISTS idx_bom_model_aliases_bom_id ON light_sync.bom_model_aliases(bom_id);
CREATE INDEX IF NOT EXISTS idx_bom_model_aliases_name ON light_sync.bom_model_aliases(alias_name);

-- ══════════════════════════════════════════════
-- 재고관리 재설계: StockMovement 확장 + 소진 테이블 (2026-03-27)
-- ══════════════════════════════════════════════
ALTER TABLE light_sync.stock_movements
  ADD COLUMN IF NOT EXISTS model_name VARCHAR(200),
  ADD COLUMN IF NOT EXISTS project_id INTEGER REFERENCES light_sync.projects(id),
  ADD COLUMN IF NOT EXISTS tx_date DATE;

CREATE TABLE IF NOT EXISTS light_sync.stock_consumptions (
  id SERIAL PRIMARY KEY,
  project_id INTEGER REFERENCES light_sync.projects(id),
  contract_item_id INTEGER REFERENCES light_sync.contract_items(id),
  model_name VARCHAR(200) NOT NULL,
  quantity INTEGER NOT NULL DEFAULT 0,
  bom_id INTEGER REFERENCES light_sync.bom_headers(id),
  tx_date DATE NOT NULL,
  note TEXT,
  created_by VARCHAR(50) DEFAULT '사용자',
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS light_sync.stock_consumption_items (
  id SERIAL PRIMARY KEY,
  consumption_id INTEGER NOT NULL REFERENCES light_sync.stock_consumptions(id) ON DELETE CASCADE,
  item_id INTEGER NOT NULL REFERENCES light_sync.items(id),
  bom_item_id INTEGER REFERENCES light_sync.bom_items(id),
  required_qty FLOAT NOT NULL DEFAULT 0,
  consumed_qty FLOAT NOT NULL DEFAULT 0,
  movement_id INTEGER REFERENCES light_sync.stock_movements(id),
  note TEXT
);

CREATE INDEX IF NOT EXISTS idx_stock_consumptions_project ON light_sync.stock_consumptions(project_id);
CREATE INDEX IF NOT EXISTS idx_stock_consumptions_tx_date ON light_sync.stock_consumptions(tx_date);
CREATE INDEX IF NOT EXISTS idx_stock_consumption_items_consumption ON light_sync.stock_consumption_items(consumption_id);

-- ══════════════════════════════════════════════
-- 서류관리 테이블 생성 (2026-03-26)
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS light_sync.document_serials (
    id SERIAL PRIMARY KEY,
    year INTEGER NOT NULL UNIQUE,
    last_number INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS light_sync.document_packages (
    id SERIAL PRIMARY KEY,
    procurement_req_no VARCHAR(30) NOT NULL,
    project_id INTEGER REFERENCES light_sync.projects(id),
    contract_id INTEGER REFERENCES light_sync.contracts(id),
    business_name VARCHAR(300),
    demand_org VARCHAR(200),
    demand_org_no VARCHAR(20),
    org_type VARCHAR(10),
    contract_no VARCHAR(50),
    contract_date DATE,
    fee INTEGER,
    total_amount INTEGER,
    supply_amount INTEGER,
    warranty_period VARCHAR(20),
    inspection_org VARCHAR(200),
    acceptance_org VARCHAR(200),
    req_pdf_path VARCHAR(500),
    commencement_doc_no VARCHAR(30),
    commencement_date DATE,
    commencement_agent_id INTEGER REFERENCES light_sync.users(id),
    commencement_generated BOOLEAN DEFAULT FALSE,
    delivery_doc_no VARCHAR(30),
    delivery_date DATE,
    delivery_generated BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by VARCHAR(50)
);
CREATE INDEX IF NOT EXISTS idx_docpkg_req_no ON light_sync.document_packages(procurement_req_no);

CREATE TABLE IF NOT EXISTS light_sync.document_attachments (
    id SERIAL PRIMARY KEY,
    package_id INTEGER NOT NULL REFERENCES light_sync.document_packages(id) ON DELETE CASCADE,
    file_type VARCHAR(50) NOT NULL,
    file_name VARCHAR(300),
    storage_path VARCHAR(500),
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ══════════════════════════════════════════════
-- G2B 조달내역 PDF 파싱 보완 필드 추가 (2026-03-26)
-- ══════════════════════════════════════════════
ALTER TABLE light_sync.g2b_procurements ADD COLUMN IF NOT EXISTS pdf_contract_no VARCHAR(50);
ALTER TABLE light_sync.g2b_procurements ADD COLUMN IF NOT EXISTS pdf_contract_date DATE;
ALTER TABLE light_sync.g2b_procurements ADD COLUMN IF NOT EXISTS pdf_fee INTEGER;
ALTER TABLE light_sync.g2b_procurements ADD COLUMN IF NOT EXISTS pdf_total_amount INTEGER;
ALTER TABLE light_sync.g2b_procurements ADD COLUMN IF NOT EXISTS pdf_warranty_period VARCHAR(20);
ALTER TABLE light_sync.g2b_procurements ADD COLUMN IF NOT EXISTS pdf_inspection_org VARCHAR(200);
ALTER TABLE light_sync.g2b_procurements ADD COLUMN IF NOT EXISTS pdf_acceptance_org VARCHAR(200);

-- ══════════════════════════════════════════════
-- 기존 코멘트 scope 보정 (2026-03-25)
-- common으로 저장된 코멘트를 가장 가까운 시스템 로그의 scope로 유추하여 업데이트
-- ══════════════════════════════════════════════
UPDATE light_sync.history_logs AS c
SET log_scope = COALESCE(
    (SELECT s.log_scope
     FROM light_sync.history_logs s
     WHERE s.project_id = c.project_id
       AND s.log_kind = 'system'
       AND s.log_scope IS NOT NULL
       AND s.log_scope != 'common'
       AND s.created_at <= c.created_at
     ORDER BY s.created_at DESC
     LIMIT 1),
    c.log_scope
)
WHERE c.log_kind = 'comment'
  AND c.log_scope = 'common'
  AND EXISTS (
    SELECT 1 FROM light_sync.history_logs s
    WHERE s.project_id = c.project_id
      AND s.log_kind = 'system'
      AND s.log_scope IS NOT NULL
      AND s.log_scope != 'common'
      AND s.created_at <= c.created_at
  );

-- ══════════════════════════════════════════════
-- 입고품목에 품번 컬럼 추가 (2026-03-24)
-- ══════════════════════════════════════════════
ALTER TABLE light_sync.receiving_items ADD COLUMN IF NOT EXISTS item_cd VARCHAR(50);

-- ══════════════════════════════════════════════
-- 비밀번호 강제변경 플래그 (2026-03-23)
-- ══════════════════════════════════════════════
ALTER TABLE light_sync.users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN DEFAULT FALSE;

-- ══════════════════════════════════════════════
-- 히스토리 읽음 표시 테이블 (2026-03-22)
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS light_sync.history_read_marks (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES light_sync.users(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES light_sync.projects(id) ON DELETE CASCADE,
    last_read_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_history_read_user_project UNIQUE (user_id, project_id)
);

-- ══════════════════════════════════════════════
-- 조도검증 구역 설계기준 Ud 컬럼 추가 (2026-03-22)
-- ══════════════════════════════════════════════
ALTER TABLE light_sync.illuminance_areas ADD COLUMN IF NOT EXISTS ks_ud_min FLOAT;

-- ══════════════════════════════════════════════
-- 챗봇 질문 패턴 학습 테이블 (2026-03-22)
-- ══════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS light_sync.mcp_query_patterns (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    tool_name VARCHAR(100) NOT NULL,
    tool_args JSONB DEFAULT '{}',
    success BOOLEAN DEFAULT TRUE,
    hit_count INTEGER DEFAULT 1,
    last_used_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mcp_qp_tool ON light_sync.mcp_query_patterns(tool_name);
CREATE INDEX IF NOT EXISTS idx_mcp_qp_hit ON light_sync.mcp_query_patterns(hit_count DESC);

-- ══════════════════════════════════════════════
-- 가공발주 테이블 3개 생성 (2026-03-22)
-- ══════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS light_sync.processing_orders (
    id SERIAL PRIMARY KEY,
    fo_no VARCHAR(20) UNIQUE NOT NULL,
    fo_date DATE NOT NULL,
    vendor_id INTEGER NOT NULL REFERENCES light_sync.vendors(id),
    processing_type VARCHAR(20) DEFAULT '외주가공',
    project_id INTEGER REFERENCES light_sync.projects(id),
    contract_id INTEGER REFERENCES light_sync.contracts(id),
    assigned_to INTEGER REFERENCES light_sync.users(id),
    status VARCHAR(20) DEFAULT '작성중',
    total_amount FLOAT DEFAULT 0,
    tax_amount FLOAT DEFAULT 0,
    note TEXT,
    created_by INTEGER REFERENCES light_sync.users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    history_log TEXT
);

CREATE TABLE IF NOT EXISTS light_sync.processing_order_items (
    id SERIAL PRIMARY KEY,
    fo_id INTEGER NOT NULL REFERENCES light_sync.processing_orders(id) ON DELETE CASCADE,
    item_id INTEGER REFERENCES light_sync.items(id),
    item_name VARCHAR(300) NOT NULL,
    item_spec VARCHAR(500),
    quantity FLOAT DEFAULT 0,
    unit_price FLOAT DEFAULT 0,
    amount FLOAT DEFAULT 0,
    unit VARCHAR(50),
    delivery_date DATE,
    in_confirmed BOOLEAN DEFAULT FALSE,
    in_confirmed_at TIMESTAMP,
    bom_item_id INTEGER REFERENCES light_sync.bom_items(id),
    material_order_id INTEGER REFERENCES light_sync.material_orders(id),
    processing_note TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS light_sync.processing_order_files (
    id SERIAL PRIMARY KEY,
    fo_id INTEGER NOT NULL REFERENCES light_sync.processing_orders(id) ON DELETE CASCADE,
    file_name VARCHAR(500) NOT NULL,
    file_path VARCHAR(1000) NOT NULL,
    file_size INTEGER DEFAULT 0,
    file_type VARCHAR(20),
    uploaded_by INTEGER REFERENCES light_sync.users(id),
    uploaded_at TIMESTAMP DEFAULT NOW()
);

-- ══════════════════════════════════════════════
-- dashboard_settings.setting_value String(200) → Text 변경 (2026-03-22)
-- ══════════════════════════════════════════════
ALTER TABLE light_sync.dashboard_settings ALTER COLUMN setting_value TYPE text;

-- ══════════════════════════════════════════════
-- 조명배치도 테이블 생성 (2026-03-22)
-- ══════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS light_sync.tower_layouts (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES light_sync.projects(id),
    tower_name VARCHAR(100) NOT NULL,
    rows INTEGER NOT NULL DEFAULT 2,
    cols INTEGER NOT NULL DEFAULT 3,
    model_name VARCHAR(200),
    watt INTEGER,
    note TEXT,
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS light_sync.tower_layout_positions (
    id SERIAL PRIMARY KEY,
    tower_layout_id INTEGER NOT NULL REFERENCES light_sync.tower_layouts(id) ON DELETE CASCADE,
    position_no INTEGER NOT NULL,
    row_idx INTEGER NOT NULL,
    col_idx INTEGER NOT NULL,
    lens_angle VARCHAR(50),
    note VARCHAR(200)
);

CREATE INDEX IF NOT EXISTS idx_tower_layouts_project ON light_sync.tower_layouts(project_id);
CREATE INDEX IF NOT EXISTS idx_tower_layout_pos_layout ON light_sync.tower_layout_positions(tower_layout_id);

CREATE TABLE IF NOT EXISTS light_sync.lens_angle_configs (
    id SERIAL PRIMARY KEY,
    model_name VARCHAR(100) UNIQUE NOT NULL,
    angles VARCHAR(500) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 초기 데이터 (예시)
INSERT INTO light_sync.lens_angle_configs (model_name, angles) VALUES
    ('STA', '20|35|55'),
    ('BATOO', '15|30|45|60|120'),
    ('ARENA', '광각|중각|협각')
ON CONFLICT (model_name) DO NOTHING;

-- ══════════════════════════════════════════════
-- 완료/취소 현장 → 생산완료 일괄 처리 (2026-03-22)
-- 입금완료/변경완료/취소 = 더 이상 생산 불필요
-- ══════════════════════════════════════════════

-- 1) 대상 확인 (먼저 실행해서 건수 확인)
SELECT c.project_id, p.name AS project_name, c.payment_status,
       ci.id AS item_id, ci.model_name, ci.status_prod
FROM light_sync.contract_items ci
JOIN light_sync.contracts c ON c.id = ci.contract_id
JOIN light_sync.projects p ON p.id = c.project_id
WHERE c.payment_status IN ('입금완료', '변경완료', '취소')
  AND ci.status_prod != '생산완료';

-- 2) 일괄 업데이트 실행
UPDATE light_sync.contract_items
SET status_prod = '생산완료'
WHERE contract_id IN (
    SELECT id FROM light_sync.contracts WHERE payment_status IN ('입금완료', '변경완료', '취소')
)
AND status_prod != '생산완료';

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

-- ===================================================================
-- 워크보드 아카이브 카카오워크 스타일 리디자인 (2026-03-23)
-- content_json: ProseMirror 구조, attachments_json: 첨부파일 배열
-- ===================================================================
ALTER TABLE light_sync.archive_posts ADD COLUMN IF NOT EXISTS content_json JSONB;
ALTER TABLE light_sync.archive_posts ADD COLUMN IF NOT EXISTS attachments_json JSONB DEFAULT '[]'::jsonb;
ALTER TABLE light_sync.archive_posts ADD COLUMN IF NOT EXISTS contract_no VARCHAR(50);
ALTER TABLE light_sync.archive_comments ADD COLUMN IF NOT EXISTS content_json JSONB;
ALTER TABLE light_sync.archive_comments ADD COLUMN IF NOT EXISTS attachments_json JSONB DEFAULT '[]'::jsonb;

-- ===================================================================
-- 히스토리보드 업그레이드 — @멘션 + 파일첨부 + 읽음표시 (2026-03-23)
-- ===================================================================
ALTER TABLE light_sync.history_logs ADD COLUMN IF NOT EXISTS attachments_json JSONB DEFAULT '[]'::jsonb;
ALTER TABLE light_sync.history_logs ADD COLUMN IF NOT EXISTS mentions_json JSONB DEFAULT '[]'::jsonb;
-- history_read_marks: full_name 캐시 (아바타 표시용)
ALTER TABLE light_sync.history_read_marks ADD COLUMN IF NOT EXISTS full_name VARCHAR(50);

-- ===================================================================
-- 자재발주 첨부파일 테이블 (검수 사진 등) (2026-03-24)
-- ===================================================================
CREATE TABLE IF NOT EXISTS light_sync.purchase_order_files (
    id SERIAL PRIMARY KEY,
    po_id INTEGER NOT NULL REFERENCES light_sync.purchase_orders(id) ON DELETE CASCADE,
    file_name VARCHAR(500) NOT NULL,
    file_path VARCHAR(1000) NOT NULL,
    file_size INTEGER DEFAULT 0,
    file_type VARCHAR(20),
    uploaded_by INTEGER REFERENCES light_sync.users(id),
    uploaded_at TIMESTAMP DEFAULT NOW(),
    is_confirmed INTEGER DEFAULT 0,
    confirmed_by INTEGER REFERENCES light_sync.users(id),
    confirmed_at TIMESTAMP
);

-- ===================================================================
-- 입고사진 피드 (워크보드 스타일) (2026-03-24)
-- ===================================================================
CREATE TABLE IF NOT EXISTS light_sync.receiving_photo_posts (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    vendor_name VARCHAR(200),
    po_no VARCHAR(20),
    photos_json JSONB DEFAULT '[]'::jsonb,
    created_by INTEGER REFERENCES light_sync.users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

-- ══════════════════════════════════════════════
-- 출장관리 테이블 (2026-03-24)
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS light_sync.business_trips (
    id SERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    destination VARCHAR(300) NOT NULL,
    purpose TEXT,
    vehicle VARCHAR(100),
    status VARCHAR(20) DEFAULT '예정',
    departure_date TIMESTAMP NOT NULL,
    return_date TIMESTAMP,
    note TEXT,
    created_by INTEGER NOT NULL REFERENCES light_sync.users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS light_sync.business_trip_members (
    id SERIAL PRIMARY KEY,
    trip_id INTEGER NOT NULL REFERENCES light_sync.business_trips(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES light_sync.users(id),
    user_name VARCHAR(50) NOT NULL,
    position VARCHAR(50),
    department VARCHAR(50)
);

-- ══════════════════════════════════════════════
-- 공구관리 테이블 (2026-03-25)
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS light_sync.tools (
    id SERIAL PRIMARY KEY,
    tool_name VARCHAR(200) NOT NULL,
    category VARCHAR(50) DEFAULT '전동공구',
    team VARCHAR(50),
    total_qty INTEGER DEFAULT 1,
    available_qty INTEGER DEFAULT 1,
    current_location VARCHAR(200) DEFAULT '사무실',
    status VARCHAR(20) DEFAULT '보관중',
    note TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS light_sync.tool_checkouts (
    id SERIAL PRIMARY KEY,
    tool_id INTEGER NOT NULL REFERENCES light_sync.tools(id) ON DELETE CASCADE,
    checkout_user_id INTEGER REFERENCES light_sync.users(id),
    checkout_user_name VARCHAR(50) NOT NULL,
    purpose TEXT,
    location VARCHAR(200),
    checkout_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expected_return_at TIMESTAMP,
    return_at TIMESTAMP,
    return_note TEXT,
    status VARCHAR(20) DEFAULT '불출',
    created_at TIMESTAMP DEFAULT NOW()
);

-- 초기 데이터: 전동공구 관리대장.xlsx 기반
-- 생산1팀 (10종)
INSERT INTO light_sync.tools (tool_name, category, team, total_qty, available_qty) VALUES
('충전 그라인더', '전동공구', '생산1팀', 1, 1),
('충전 드릴', '전동공구', '생산1팀', 2, 2),
('전기 4인치 그라인더', '전동공구', '생산1팀', 8, 8),
('충전 임팩드릴', '전동공구', '생산1팀', 3, 3),
('전기 6인치 그라인더', '전동공구', '생산1팀', 1, 1),
('전기 포터블 그라인더 (광택 작업용)', '전동공구', '생산1팀', 3, 3),
('전기 샌딩기', '전동공구', '생산1팀', 2, 2),
('에어 샌딩기', '전동공구', '생산1팀', 2, 2),
('충전 임팩렌치 (기초너트 체결용)', '전동공구', '생산1팀', 1, 1),
('에어 니들 건 (CO2 용접 비딩 제거)', '전동공구', '생산1팀', 2, 2);

-- 생산2팀 (15종)
INSERT INTO light_sync.tools (tool_name, category, team, total_qty, available_qty) VALUES
('충전 실리콘 건', '전동공구', '생산2팀', 1, 1),
('충전 임팩 드릴', '전동공구', '생산2팀', 2, 2),
('충전 리벳 건', '전동공구', '생산2팀', 2, 2),
('충전 그라인더', '전동공구', '생산2팀', 1, 1),
('전기 샌딩기', '전동공구', '생산2팀', 1, 1),
('충전 드릴', '전동공구', '생산2팀', 6, 6),
('전기 히팅건', '전동공구', '생산2팀', 2, 2),
('에어 리벳건', '전동공구', '생산2팀', 1, 1),
('수동 리벳건', '수공구', '생산2팀', 1, 1),
('압착기 6SQ미만', '수공구', '생산2팀', 3, 3),
('압착기 6SQ이상', '수공구', '생산2팀', 3, 3),
('압착기 16SQ이상', '수공구', '생산2팀', 1, 1),
('밀워키 배터리 18V', '배터리', '생산2팀', 3, 3),
('밀워키 배터리 12V', '배터리', '생산2팀', 2, 2),
('보쉬 배터리 10.8V', '배터리', '생산2팀', 15, 15);

-- ══════════════════════════════════════════════
-- 재고변동 movement_type 보정 (2026-03-26)
-- 직접입고 시 '입고'(한글)로 잘못 기록된 건 → 'IN_RECEIVING'으로 통일
-- ══════════════════════════════════════════════
UPDATE light_sync.stock_movements
SET movement_type = 'IN_RECEIVING'
WHERE movement_type = '입고';
-- ============================================================
-- 인증서 일괄 임포트 (매그나텍 인증 및 유효기간 관리.xlsx)
-- ============================================================

-- 시트1: 매그나텍 인증관련 (회사 인증서)
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('KS인증', 'KS C 7658(가로등 및 보안등기구)', '2026-03-27', '2026-08-04', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('KS인증', 'KS C 7712(투광등기구)', '2026-03-27', '2028-03-29', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('KS인증', 'KS C 7658(1년심사)', NULL, '2026-08-31', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('조달우수제품', '우수제품지정증서(가로등,보안등)', '2026-03-27', '2027-03-21', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('조달우수제품', '우수제품지정증서(투광등)', '2026-03-27', '2027-03-24', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('혁신제품', '혁신제품 ARENA(M)', '2026-03-27', '2027-01-28', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('혁신제품', '혁신제품 STA(X)', '2026-03-27', '2026-12-25', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('녹색기술인증', '녹색기술인증서 (3차원 히트파이프와 적층3D 방열핀이 적용된 조명기기용 냉각기술', '2026-03-27', '2027-10-13', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('ISO', 'ISO 9001(3년)', '2026-03-27', '2027-08-09', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('ISO', 'ISO 14001(3년)', '2026-03-27', '2027-08-09', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('ISO', 'ISO 9001,14001(1년심사)', NULL, '2026-08-31', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('MAS계약', 'MAS계약(가로등부속자재)', '2026-03-27', '2028-04-17', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('MAS계약', 'MAS계약(LED투광등기구)', '2026-03-27', '2026-08-31', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('MAS계약', 'MAS계약(조명타워)', '2026-03-27', '2028-03-03', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('MAS계약', 'MAS계약(등주)', '2026-03-27', '2028-04-17', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('MAS계약', 'MAS계약(태양광가로등)', '2026-03-27', '2026-10-31', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('조달우수제품', '조달우수계약(가로등,보안등)', '2026-03-27', '2027-03-21', 30, '60일전부터 신청가능', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('조달우수제품', '조달우수계약(LED투광등)', '2026-03-27', '2027-03-24', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('중소기업확인서', '중소기업확인서', '2026-03-27', '2026-03-31', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('직접생산증명', '직접생산증명(등기구)', '2026-03-27', '2027-01-20', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('직접생산증명', '직접생산증명(등주)', '2026-03-27', '2026-07-31', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('직접생산증명', '직접생산증명(조명타워)', '2026-03-27', '2026-07-31', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('직접생산증명', '직접생산증명(도로표지병)', NULL, '2027-09-25', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('G-PASS', 'G-PASS', '2026-03-27', '2029-09-22', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('기타', '광기술원 장비사용계약서', '2026-03-27', '2027-02-02', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('단체표준', '단체표준 지정연장(탄소,스테인레스 등주)', NULL, '2029-01-28', 30, NULL, true);
INSERT INTO light_sync.certifications (cert_type, cert_name, issued_date, expiry_date, alert_days, note, is_active) VALUES ('단체표준', '단체표준 지정연장(조명타워)', NULL, '2028-10-31', 30, NULL, true);

-- 시트2: 고효율인증유효기간 (제품별 고효율 인증)
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-FL-400S', '37685', '2026-08-19', 'MT-FL-400S', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA(X)-1500', '71592', '2026-09-14', 'STA(X)-1500', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA(X)-1000', '71573', '2026-09-15', 'STA(X)-1000', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA(X)-400', '71587', '2026-09-15', 'STA(X)-400', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA(X)-500', '71558', '2026-09-15', 'STA(X)-500', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA(X)-700', '71481', '2026-09-19', 'STA(X)-700', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA(X)-800', '71480', '2026-09-19', 'STA(X)-800', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA(X)-1200', '71622', '2026-09-21', 'STA(X)-1200', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA(X)-600', '71621', '2026-09-21', 'STA(X)-600', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLC-025-35', '72471', '2026-10-26', 'MT-SLC-025-35', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLC-075-40', '72472', '2026-10-26', 'MT-SLC-075-40', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLC-100-40', '72476', '2026-10-26', 'MT-SLC-100-40', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLC-100-45', '72477', '2026-10-26', 'MT-SLC-100-45', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLC-125-40', '72470', '2026-10-26', 'MT-SLC-125-40', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLC-125-45', '72473', '2026-10-26', 'MT-SLC-125-45', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLC-150-40', '72484', '2026-10-26', 'MT-SLC-150-40', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLC-150-45', '72475', '2026-10-26', 'MT-SLC-150-45', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLC-200', '72474', '2026-10-26', 'MT-SLC-200', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLC-050-35', '72702', '2026-11-01', 'MT-SLC-050-35', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLC-075-45', '72722', '2026-11-01', 'MT-SLC-075-45', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLC-240', '72685', '2026-11-01', 'MT-SLC-240', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA-400', '72623', '2026-11-01', 'STA-400', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA-500', '72621', '2026-11-01', 'STA-500', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA-600', '72622', '2026-11-01', 'STA-600', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA-700', '72634', '2026-11-01', 'STA-700', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA-800', '72624', '2026-11-01', 'STA-800', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA-400', '41808', '2026-12-22', 'ARENA-400', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA-500', '41809', '2026-12-22', 'ARENA-500', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA-600', '41807', '2026-12-22', 'ARENA-600', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA-800', '41806', '2026-12-22', 'ARENA-800', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA-400(3000K)', '43264', '2027-02-05', 'ARENA-400(3000K)', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA-500(3000K)', '43242', '2027-02-06', 'ARENA-500(3000K)', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA-600(3000K)', '43290', '2027-02-08', 'ARENA-600(3000K)', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA-800(3000K)', '43323', '2027-02-09', 'ARENA-800(3000K)', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA(M)-400', '50668', '2027-09-10', 'ARENA(M)-400', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA(M)-500', '50667', '2027-09-10', 'ARENA(M)-500', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA(M)-600', '50677', '2027-09-10', 'ARENA(M)-600', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA(M)-800', '50680', '2027-09-10', 'ARENA(M)-800', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-ML-050', '18449', '2027-12-10', 'MT-ML-050', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-ML-125', '18450', '2027-12-10', 'MT-ML-125', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-ML-150', '18451', '2027-12-10', 'MT-ML-150', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 BATOO-400', '18610', '2027-12-17', 'BATOO-400', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 BATOO-300', '19409', '2028-01-24', 'BATOO-300', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-FL-1000A', '19407', '2028-01-24', 'MT-FL-1000A', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-FL-1200A', '19408', '2028-01-25', 'MT-FL-1200A', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-FL-300A', '19404', '2028-01-25', 'MT-FL-300A', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-FL-600A', '19405', '2028-01-25', 'MT-FL-600A', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-FL-800A', '19406', '2028-01-25', 'MT-FL-800A', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 BATOO-600', '19501', '2028-01-28', 'BATOO-600', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-TL-100', '19480', '2028-01-28', 'MT-TL-100', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-TL-200', '19481', '2028-01-28', 'MT-TL-200', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 BATOO-1000', '19517', '2028-01-29', 'BATOO-1000', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 BATOO-1200', '19516', '2028-01-29', 'BATOO-1200', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 BATOO-800', '19509', '2028-01-29', 'BATOO-800', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA-400S', '54888', '2028-02-01', 'ARENA-400S', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA-200S', '55088', '2028-02-04', 'ARENA-200S', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA-300S', '55087', '2028-02-04', 'ARENA-300S', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-ML-040', '19832', '2028-02-06', 'MT-ML-040', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-ML-060', '19819', '2028-02-06', 'MT-ML-060', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-ML-100', '19830', '2028-02-06', 'MT-ML-100', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-ML-030', '19865', '2028-02-07', 'MT-ML-030', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-TL-050', '20095', '2028-02-13', 'MT-TL-050', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-TL-075', '20070', '2028-02-13', 'MT-TL-075', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-TL-150', '20072', '2028-02-13', 'MT-TL-150', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA-1000', '55523', '2028-02-21', 'STA-1000', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA-1200', '55524', '2028-02-21', 'STA-1200', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA-1500', '55522', '2028-02-21', 'STA-1500', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLA-030', '91947', '2028-03-07', 'MT-SLA-030', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLA-040', '91948', '2028-03-07', 'MT-SLA-040', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLA-050', '91946', '2028-03-07', 'MT-SLA-050', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLA-075', '91949', '2028-03-07', 'MT-SLA-075', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLA-100', '91950', '2028-03-07', 'MT-SLA-100', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLA-150', '91954', '2028-03-07', 'MT-SLA-150', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLA-125', '92147', '2028-03-13', 'MT-SLA-125', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA(M)-200S', '56753', '2028-04-06', 'ARENA(M)-200S', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA(M)-300S', '56752', '2028-04-06', 'ARENA(M)-300S', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA(M)-400S', '56751', '2028-04-06', 'ARENA(M)-400S', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA(H)-1500', '93719', '2028-04-17', 'STA(H)-1500', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA(H)-1200', '94709', '2028-05-12', 'STA(H)-1200', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA(M)-1200', '58432', '2028-06-02', 'STA(M)-1200', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA(M)-1000', '58430', '2028-06-03', 'STA(M)-1000', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 STA(M)-1500', '58625', '2028-06-09', 'STA(M)-1500', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA(X)-600', '60051', '2028-07-12', 'ARENA(X)-600', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA(X)-400', '59787', '2028-07-13', 'ARENA(X)-400', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA(X)-500', '59751', '2028-07-13', 'ARENA(X)-500', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA(X)-800', '59749', '2028-07-13', 'ARENA(X)-800', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA(X)-200S', '60055', '2028-07-21', 'ARENA(X)-200S', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA(X)-300S', '60050', '2028-07-21', 'ARENA(X)-300S', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 ARENA(X)-400S', '60056', '2028-07-21', 'ARENA(X)-400S', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 BATOO-200', '25269', '2028-07-24', 'BATOO-200', 60, 'LED투광등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLA(D)-040', '25-1744', '2029-03-10', 'MT-SLA(D)-040', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLA(D)-050', '25-1745', '2029-03-10', 'MT-SLA(D)-050', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLA(D)-100', '25-1746', '2029-03-10', 'MT-SLA(D)-100', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLA(D)-125', '25-1747', '2029-03-10', 'MT-SLA(D)-125', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLA(D)-150', '25-1748', '2029-03-10', 'MT-SLA(D)-150', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLC-030', '31243', '2030-02-20', 'MT-SLC-030', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLC-040', '31240', '2030-02-20', 'MT-SLC-040', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLC-050', '31241', '2030-02-20', 'MT-SLC-050', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLC-060', '31239', '2030-02-20', 'MT-SLC-060', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLC-100', '31242', '2030-02-20', 'MT-SLC-100', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLC-125', '31244', '2030-02-20', 'MT-SLC-125', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLC-150', '31237', '2030-02-20', 'MT-SLC-150', 60, 'LED 가로등 및 보안 등기구', true);
INSERT INTO light_sync.certifications (cert_type, cert_name, cert_no, expiry_date, product_model, alert_days, note, is_active) VALUES ('고효율인증', '고효율인증 MT-SLC-075', '32912', '2030-04-07', 'MT-SLC-075', 60, 'LED 가로등 및 보안 등기구', true);
-- 2026-04-04: DocumentPackage procurement_req_no unique 제약 추가 (중복 방지)
ALTER TABLE light_sync.document_packages ADD CONSTRAINT uq_document_packages_req_no UNIQUE (procurement_req_no);

-- 2026-04-06: 공유 주소록 지원
ALTER TABLE light_sync.mail_contacts ALTER COLUMN user_id DROP NOT NULL;
ALTER TABLE light_sync.mail_contacts ADD COLUMN IF NOT EXISTS is_shared BOOLEAN DEFAULT FALSE;

-- 2026-04-13: 도면관리 PDF-only 업로드 허용 (dwg_path NOT NULL 제거)
ALTER TABLE light_sync.drawing_versions ALTER COLUMN dwg_path DROP NOT NULL;

-- 2026-04-28: 업무용차량 운행기록부 (vehicle_log feature)
CREATE TABLE IF NOT EXISTS light_sync.vehicle_logs (
  id SERIAL PRIMARY KEY,
  use_date DATE NOT NULL,
  vehicle VARCHAR(100) NOT NULL,
  user_id INTEGER REFERENCES light_sync.users(id),
  user_name VARCHAR(50) NOT NULL,
  user_department VARCHAR(50),
  user_position VARCHAR(50),
  odometer_start INTEGER,
  odometer_end INTEGER NOT NULL,
  distance_km INTEGER NOT NULL,
  fuel_amount INTEGER,
  origin VARCHAR(200) NOT NULL,
  destination VARCHAR(200) NOT NULL,
  purpose TEXT NOT NULL,
  receipt_url TEXT,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_vehicle_logs_vehicle_date ON light_sync.vehicle_logs(vehicle, use_date DESC);
CREATE INDEX IF NOT EXISTS ix_vehicle_logs_user ON light_sync.vehicle_logs(user_id);
CREATE INDEX IF NOT EXISTS ix_vehicle_logs_use_date ON light_sync.vehicle_logs(use_date DESC);

-- ═══════════════════════════════════════════════════════════════
-- 2026-05-13 AX 0주차 데이터 정리 (Mattermost 봇 도입 준비)
-- 백업 테이블: _bk_*_20260513_143740 (6종)
-- ═══════════════════════════════════════════════════════════════

-- 1. history_logs: 사람/시스템/채팅 origin 구분 (AX KPI 기준선)
ALTER TABLE light_sync.history_logs
  ADD COLUMN IF NOT EXISTS origin VARCHAR(20) DEFAULT 'system';
-- 기준선: 30일 사람 작성 13/195 = 6.7%. 목표: 50%+
UPDATE light_sync.history_logs
  SET origin = 'web'
  WHERE user_name IS NOT NULL
    AND user_name NOT IN ('시스템', '시스템 🤖', '봇', 'system')
    AND user_name NOT LIKE '%시스템%';

-- 2. contracts: 미청구 사유 분류 (회수불가/탕감/분쟁/단순지연/기타)
ALTER TABLE light_sync.contracts
  ADD COLUMN IF NOT EXISTS unpaid_reason VARCHAR(50),
  ADD COLUMN IF NOT EXISTS unpaid_reason_note TEXT;

-- 3. notifications: 실제 중복 방어 키 (현재는 title 비교만 — gap 분석 1번)
ALTER TABLE light_sync.notifications
  ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR(200);
CREATE INDEX IF NOT EXISTS idx_notifications_dedupe
  ON light_sync.notifications(dedupe_key, created_at DESC)
  WHERE dedupe_key IS NOT NULL;

-- 4. 동시수정 충돌 방지 — optimistic locking
ALTER TABLE light_sync.deliveries
  ADD COLUMN IF NOT EXISTS entity_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE light_sync.delivery_splits
  ADD COLUMN IF NOT EXISTS entity_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE light_sync.warranty_cases
  ADD COLUMN IF NOT EXISTS entity_version INTEGER NOT NULL DEFAULT 1;

-- 5. Mattermost 채널 × MCP tool 권한 매트릭스 (PERSONAS dict 대체)
CREATE TABLE IF NOT EXISTS light_sync.channel_tool_acl (
  channel_name VARCHAR(50) NOT NULL,
  tool_name VARCHAR(100) NOT NULL,
  allow BOOLEAN NOT NULL DEFAULT TRUE,
  note TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
  PRIMARY KEY (channel_name, tool_name)
);
CREATE INDEX IF NOT EXISTS idx_channel_tool_acl_channel
  ON light_sync.channel_tool_acl(channel_name);

-- 6. delivery_splits status 한글 통일 (waiting/done 영문 잔존 정리)
UPDATE light_sync.delivery_splits SET status='완료' WHERE status='done';
UPDATE light_sync.delivery_splits SET status='대기' WHERE status='waiting';

-- ════════════════════════════════════════════════════════
-- 2026-05-13 write_ops: pending_write_sessions 테이블
-- ════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS light_sync.pending_write_sessions (
    token         VARCHAR(36)  PRIMARY KEY,
    intent_type   VARCHAR(50)  NOT NULL,
    payload_json  TEXT         NOT NULL DEFAULT '{}',
    channel_id    VARCHAR(50),
    user_name     VARCHAR(50),
    created_at    TIMESTAMP    DEFAULT NOW(),
    expires_at    TIMESTAMP    NOT NULL,
    used          BOOLEAN      DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_pws_expires ON light_sync.pending_write_sessions(expires_at);
CREATE INDEX IF NOT EXISTS ix_pws_used ON light_sync.pending_write_sessions(used);

-- 만료 세션 자동 정리 (선택사항: pg_cron 없으면 수동)
-- DELETE FROM light_sync.pending_write_sessions WHERE expires_at < NOW() - INTERVAL '1 hour';

-- ════════════════════════════════════════════════════════
-- 2026-05-18 메일 신착 알림 (mail_notify_state)
-- IMAP UID 워터마크 기반 mail_account 단위 상태. mail_notifier 데몬에서 사용.
-- ════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS light_sync.mail_notify_state (
    account_id      INTEGER     PRIMARY KEY
                                REFERENCES light_sync.mail_accounts(id) ON DELETE CASCADE,
    last_seen_uid   BIGINT      NOT NULL DEFAULT 0,
    uid_validity    BIGINT,
    is_enabled      BOOLEAN     NOT NULL DEFAULT TRUE,
    last_polled_at  TIMESTAMP,
    last_error      TEXT,
    notify_count    INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMP   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP   NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_mns_enabled ON light_sync.mail_notify_state(is_enabled);

-- ════════════════════════════════════════════════════════
-- 전자결재 (電子決裁) — 2026-06-10
-- 순차 결재 + 직급/부서 기반 기본 결재선(수정가능) + 참조/수신.
-- 양식(approval_form_templates)은 관리자가 추가/수정 가능.
-- (init_db create_all로도 자동 생성됨 — 이 SQL은 기록/수동복구용)
-- ════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS light_sync.approval_form_templates (
    id              SERIAL      PRIMARY KEY,
    form_key        VARCHAR(50) UNIQUE NOT NULL,
    name            VARCHAR(100) NOT NULL,
    description     TEXT,
    icon            VARCHAR(20),
    field_schema    JSONB       NOT NULL DEFAULT '[]'::jsonb,
    default_line    JSONB,
    has_amount      BOOLEAN     DEFAULT FALSE,
    amount_field    VARCHAR(50),
    is_active       BOOLEAN     DEFAULT TRUE,
    sort_order      INTEGER     DEFAULT 0,
    created_at      TIMESTAMP   DEFAULT NOW(),
    updated_at      TIMESTAMP   DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS light_sync.approval_documents (
    id              SERIAL      PRIMARY KEY,
    doc_no          VARCHAR(30) UNIQUE,
    form_key        VARCHAR(50) NOT NULL,
    form_name       VARCHAR(100) NOT NULL,
    title           VARCHAR(200) NOT NULL,
    drafter_id      INTEGER     NOT NULL REFERENCES light_sync.users(id),
    drafter_name    VARCHAR(50) NOT NULL,
    drafter_dept    VARCHAR(50),
    drafter_position VARCHAR(50),
    form_data       JSONB,
    content         TEXT,
    amount          NUMERIC(15,0),
    status          VARCHAR(20) NOT NULL DEFAULT 'draft',
    current_step    INTEGER     DEFAULT 0,
    created_at      TIMESTAMP   DEFAULT NOW(),
    submitted_at    TIMESTAMP,
    completed_at    TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_ea_doc_drafter ON light_sync.approval_documents(drafter_id);
CREATE INDEX IF NOT EXISTS ix_ea_doc_status ON light_sync.approval_documents(status);

CREATE TABLE IF NOT EXISTS light_sync.approval_steps (
    id              SERIAL      PRIMARY KEY,
    document_id     INTEGER     NOT NULL REFERENCES light_sync.approval_documents(id) ON DELETE CASCADE,
    step_order      INTEGER     NOT NULL,
    approver_id     INTEGER     NOT NULL REFERENCES light_sync.users(id),
    approver_name   VARCHAR(50) NOT NULL,
    approver_position VARCHAR(50),
    approver_dept   VARCHAR(50),
    role            VARCHAR(20) DEFAULT 'approval',
    status          VARCHAR(20) DEFAULT 'waiting',
    comment         TEXT,
    acted_at        TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_ea_step_doc ON light_sync.approval_steps(document_id);
CREATE INDEX IF NOT EXISTS ix_ea_step_approver ON light_sync.approval_steps(approver_id, status);

CREATE TABLE IF NOT EXISTS light_sync.approval_references (
    id              SERIAL      PRIMARY KEY,
    document_id     INTEGER     NOT NULL REFERENCES light_sync.approval_documents(id) ON DELETE CASCADE,
    user_id         INTEGER     NOT NULL REFERENCES light_sync.users(id),
    user_name       VARCHAR(50) NOT NULL,
    ref_type        VARCHAR(20) DEFAULT 'reference',
    is_read         BOOLEAN     DEFAULT FALSE,
    read_at         TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_ea_ref_doc ON light_sync.approval_references(document_id);
CREATE INDEX IF NOT EXISTS ix_ea_ref_user ON light_sync.approval_references(user_id);

CREATE TABLE IF NOT EXISTS light_sync.approval_attachments (
    id              SERIAL      PRIMARY KEY,
    document_id     INTEGER     NOT NULL REFERENCES light_sync.approval_documents(id) ON DELETE CASCADE,
    filename        VARCHAR(255) NOT NULL,
    storage_path    VARCHAR(500) NOT NULL,
    content_type    VARCHAR(100),
    size            INTEGER,
    uploaded_at     TIMESTAMP   DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_ea_att_doc ON light_sync.approval_attachments(document_id);

CREATE TABLE IF NOT EXISTS light_sync.approval_comments (
    id              SERIAL      PRIMARY KEY,
    document_id     INTEGER     NOT NULL REFERENCES light_sync.approval_documents(id) ON DELETE CASCADE,
    user_id         INTEGER     NOT NULL REFERENCES light_sync.users(id),
    user_name       VARCHAR(50) NOT NULL,
    content         TEXT        NOT NULL,
    created_at      TIMESTAMP   DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_ea_cmt_doc ON light_sync.approval_comments(document_id);

-- ════════════════════════════════════════════════════════
-- 인사관리 — 연차 수동 가감 (2026-06-10)
-- 연차는 입사일 기준 자동 산정(hr_service) + 전자결재 휴가 자동차감(승인분 집계).
-- 이 테이블은 이월/특별부여/보정 등 수동 가감만 기록.
-- ════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS light_sync.leave_adjustments (
    id          SERIAL      PRIMARY KEY,
    user_id     INTEGER     NOT NULL REFERENCES light_sync.users(id),
    days        NUMERIC(4,1) NOT NULL,
    reason      TEXT,
    leave_year  INTEGER,
    created_by  VARCHAR(50),
    created_at  TIMESTAMP   DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_leave_adj_user ON light_sync.leave_adjustments(user_id, leave_year);

-- ════════════════════════════════════════════════════════
-- 현장사진 갤러리 — 드래그&드롭 순서변경 (2026-06-15)
-- project_photos에 sort_order 추가. 작을수록 갤러리 앞쪽.
-- 기존 데이터는 created_at DESC(최신순) 기준으로 백필.
-- ════════════════════════════════════════════════════════
ALTER TABLE light_sync.project_photos ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0;

WITH ranked AS (
    SELECT id, ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY created_at DESC, id DESC) - 1 AS rn
    FROM light_sync.project_photos
)
UPDATE light_sync.project_photos p SET sort_order = ranked.rn
FROM ranked WHERE p.id = ranked.id;
