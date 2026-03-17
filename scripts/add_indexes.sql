-- Phase 6: DB Index Optimization
-- 주요 FK 및 필터 컬럼에 인덱스 추가
-- 실행: psql -f scripts/add_indexes.sql 또는 SQLite에서 직접 실행

-- Project 테이블: 거의 모든 목록 쿼리에서 사용
CREATE INDEX IF NOT EXISTS ix_projects_is_contracted ON projects (is_contracted);

-- Contract 테이블: FK + 납기일 범위 쿼리
CREATE INDEX IF NOT EXISTS ix_contracts_project_id ON contracts (project_id);
CREATE INDEX IF NOT EXISTS ix_contracts_delivery_due_date ON contracts (delivery_due_date);

-- ContractItem 테이블: FK
CREATE INDEX IF NOT EXISTS ix_contract_items_contract_id ON contract_items (contract_id);

-- Delivery 테이블: FK
CREATE INDEX IF NOT EXISTS ix_deliveries_project_id ON deliveries (project_id);

-- HistoryLog 테이블: FK + 타임라인 쿼리
CREATE INDEX IF NOT EXISTS ix_history_logs_project_id ON history_logs (project_id);

-- DeliveryPhoto 테이블: FK
CREATE INDEX IF NOT EXISTS ix_delivery_photos_delivery_id ON delivery_photos (delivery_id);

-- MaterialOrder 테이블: FK
CREATE INDEX IF NOT EXISTS ix_material_orders_contract_item_id ON material_orders (contract_item_id);
