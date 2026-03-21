from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import sessionmaker

from .base import Base
from .constants import DETAIL_ITEM_OPTIONS
from .entities import Contract, ContractItem, GroupPermission, Material, User, IlluminanceProject, IlluminanceArea, IlluminanceMeasured
from .helpers import _read_env_value, normalize_detail_item, quote_ident

# 최고관리자 계정 username — 변경 시 여기만 수정
SUPERADMIN_USERNAME = "magnatech"

# -------------------------------------------------------------------
# DB 연결 및 초기화
# -------------------------------------------------------------------
DATABASE_URL = _read_env_value('DATABASE_URL') or _read_env_value('SUPABASE_DB_DSN')
DB_SCHEMA = _read_env_value('DB_SCHEMA', 'light_sync')
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL(또는 SUPABASE_DB_DSN)이 설정되지 않았습니다. "
        "SQLite fallback은 비활성화되어 Supabase(Postgres) 설정이 필수입니다."
    )

try:
    engine = create_engine(DATABASE_URL)
except ModuleNotFoundError as e:
    if e.name in {'psycopg2', 'psycopg'}:
        raise RuntimeError(
            "PostgreSQL 드라이버가 없습니다. `pip install psycopg2-binary` 후 다시 실행하세요."
        ) from e
    raise


def _is_postgres_engine():
    return engine.dialect.name == 'postgresql'


if _is_postgres_engine():
    def _do_set_search_path(dbapi_connection):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"SET search_path TO {quote_ident(DB_SCHEMA)}, public")
        finally:
            cursor.close()

    @event.listens_for(engine, 'connect')
    def _set_postgres_search_path(dbapi_connection, connection_record):
        _do_set_search_path(dbapi_connection)

    @event.listens_for(engine, 'checkout')
    def _checkout_set_search_path(dbapi_connection, connection_record, connection_proxy):
        _do_set_search_path(dbapi_connection)


SessionLocal = sessionmaker(bind=engine)


def _is_sqlite_engine():
    # Supabase(Postgres) 강제 운영: SQLite 마이그레이션 경로 비활성화
    return False


def _ensure_postgres_schema():
    if not _is_postgres_engine():
        return
    schema_ident = quote_ident(DB_SCHEMA)
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_ident}"))
        conn.execute(text(f"SET search_path TO {schema_ident}, public"))

def init_db():
    _ensure_postgres_schema()

    try:
        Base.metadata.create_all(bind=engine)
    except (OperationalError, ProgrammingError) as e:
        # "already exists" 또는 새 모델의 FK 참조 시 기존 테이블 컬럼 불일치 → 무시 후 ALTER TABLE에서 처리
        if 'already exists' not in str(e).lower() and 'does not exist' not in str(e).lower():
            raise
    # PostgreSQL 컬럼 추가 마이그레이션 (안전: IF NOT EXISTS 패턴)
    if _is_postgres_engine():
        with engine.begin() as conn:
            # items 테이블 신규 컬럼 추가 (v2026-03-18)
            for col, col_type in [
                ('category', 'VARCHAR(50)'),
                ('manufacturer', 'VARCHAR(100)'),
                ('note', 'TEXT'),
                ('stock_qty', 'FLOAT DEFAULT 0'),
                ('reserved_qty', 'FLOAT DEFAULT 0'),
            ]:
                try:
                    conn.execute(text(
                        f"ALTER TABLE {quote_ident(DB_SCHEMA)}.items "
                        f"ADD COLUMN {col} {col_type}"
                    ))
                except Exception:
                    pass  # 이미 존재하면 무시

            # users 테이블: extra_menus 컬럼 추가 (v2026-03-18, 개인별 추가 메뉴 권한)
            try:
                conn.execute(text(
                    f"ALTER TABLE {quote_ident(DB_SCHEMA)}.users "
                    f"ADD COLUMN extra_menus TEXT"
                ))
            except Exception:
                pass  # 이미 존재하면 무시

            # contracts: g2b_contract_no 추가 (v2026-03-18, G2B 계약 매칭)
            try:
                conn.execute(text(
                    f"ALTER TABLE {quote_ident(DB_SCHEMA)}.contracts "
                    f"ADD COLUMN g2b_contract_no VARCHAR(30)"
                ))
            except Exception:
                pass

            # bom_items: prev_unit_price 추가 (v2026-03-18, 직전 단가)
            try:
                conn.execute(text(
                    f"ALTER TABLE {quote_ident(DB_SCHEMA)}.bom_items "
                    f"ADD COLUMN prev_unit_price FLOAT"
                ))
            except Exception:
                pass

            # purchase_order_items: bom_item_id FK 추가 (v2026-03-18, BOM-발주 연동)
            try:
                conn.execute(text(
                    f"ALTER TABLE {quote_ident(DB_SCHEMA)}.purchase_order_items "
                    f"ADD COLUMN bom_item_id INTEGER REFERENCES {quote_ident(DB_SCHEMA)}.bom_items(id)"
                ))
            except Exception:
                pass  # 이미 존재하면 무시

            # material_orders: bom_item_id FK 추가 (v2026-03-18, BOM-자재관리 연동)
            try:
                conn.execute(text(
                    f"ALTER TABLE {quote_ident(DB_SCHEMA)}.material_orders "
                    f"ADD COLUMN bom_item_id INTEGER REFERENCES {quote_ident(DB_SCHEMA)}.bom_items(id)"
                ))
            except Exception:
                pass  # 이미 존재하면 무시

            # items: stock_qty, reserved_qty 추가 (v2026-03-18, 재고관리)
            for col in ['stock_qty', 'reserved_qty']:
                try:
                    conn.execute(text(
                        f"ALTER TABLE {quote_ident(DB_SCHEMA)}.items "
                        f"ADD COLUMN {col} FLOAT DEFAULT 0"
                    ))
                except Exception:
                    pass  # 이미 존재하면 무시

            # deliveries: 검수 관련 컬럼 추가 (v2026-03-19, 매그나텍 PHASE 7)
            for col, col_type in [
                ('inspection_status', "VARCHAR(20) DEFAULT '미검수'"),
                ('inspection_date', 'DATE'),
                ('inspection_note', 'TEXT'),
            ]:
                try:
                    conn.execute(text(
                        f"ALTER TABLE {quote_ident(DB_SCHEMA)}.deliveries "
                        f"ADD COLUMN {col} {col_type}"
                    ))
                except Exception:
                    pass  # 이미 존재하면 무시

            # contracts: 대금 관련 컬럼 추가 (v2026-03-19, 매그나텍 PHASE 8)
            for col, col_type in [
                ('payment_status', "VARCHAR(20) DEFAULT '미청구'"),
                ('invoice_date', 'DATE'),
                ('payment_date', 'DATE'),
            ]:
                try:
                    conn.execute(text(
                        f"ALTER TABLE {quote_ident(DB_SCHEMA)}.contracts "
                        f"ADD COLUMN {col} {col_type}"
                    ))
                except Exception:
                    pass  # 이미 존재하면 무시

            # bom_headers: option_schema 추가 (v2026-03-19, 슈퍼BOM)
            try:
                conn.execute(text(
                    f"ALTER TABLE {quote_ident(DB_SCHEMA)}.bom_headers "
                    f"ADD COLUMN option_schema TEXT"
                ))
            except Exception:
                pass

            # bom_items: option_filter 추가 (v2026-03-19, 슈퍼BOM)
            try:
                conn.execute(text(
                    f"ALTER TABLE {quote_ident(DB_SCHEMA)}.bom_items "
                    f"ADD COLUMN option_filter TEXT"
                ))
            except Exception:
                pass

            # items: safety_stock, last_unit_price 추가 (v2026-03-19, 재고관리)
            for col, col_type in [
                ('safety_stock', 'FLOAT DEFAULT 0'),
                ('last_unit_price', 'FLOAT DEFAULT 0'),
            ]:
                try:
                    conn.execute(text(
                        f"ALTER TABLE {quote_ident(DB_SCHEMA)}.items "
                        f"ADD COLUMN {col} {col_type}"
                    ))
                except Exception:
                    pass  # 이미 존재하면 무시

            # quotations: 부과금/합계 컬럼 추가 (v2026-03-19, 견적서)
            for col, col_type in [
                ('surcharges_json', 'TEXT'),
                ('grand_total', 'FLOAT DEFAULT 0'),
            ]:
                try:
                    conn.execute(text(
                        f"ALTER TABLE {quote_ident(DB_SCHEMA)}.quotations "
                        f"ADD COLUMN {col} {col_type}"
                    ))
                except Exception:
                    pass  # 이미 존재하면 무시

            # projects: 시방서 반영 확인 컬럼 추가 (v2026-03-19, 매그나텍 PHASE 2-3)
            for col, col_type in [
                ('spec_confirmed', 'BOOLEAN DEFAULT FALSE'),
                ('spec_confirmed_date', 'DATE'),
            ]:
                try:
                    conn.execute(text(
                        f"ALTER TABLE {quote_ident(DB_SCHEMA)}.projects "
                        f"ADD COLUMN {col} {col_type}"
                    ))
                except Exception:
                    pass  # 이미 존재하면 무시

            # illuminance 테이블 3개 (v2026-03-20, 조도설계 검증 시스템)
            for tbl_sql in [
                f"""CREATE TABLE IF NOT EXISTS {quote_ident(DB_SCHEMA)}.illuminance_projects (
                    id SERIAL PRIMARY KEY, project_name VARCHAR(200) NOT NULL,
                    erp_project_id INTEGER REFERENCES {quote_ident(DB_SCHEMA)}.projects(id) ON DELETE SET NULL,
                    customer VARCHAR(200), location VARCHAR(500), install_date DATE,
                    pdf_filename VARCHAR(300), facility_type VARCHAR(50),
                    status VARCHAR(20) DEFAULT 'design', notes TEXT,
                    created_by VARCHAR(50), created_at TIMESTAMP DEFAULT NOW())""",
                f"""CREATE TABLE IF NOT EXISTS {quote_ident(DB_SCHEMA)}.illuminance_areas (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES {quote_ident(DB_SCHEMA)}.illuminance_projects(id) ON DELETE CASCADE,
                    area_name VARCHAR(200) NOT NULL, area_index INTEGER DEFAULT 1,
                    installation_height FLOAT, lamp_type VARCHAR(100), lamp_watt INTEGER,
                    lamp_qty INTEGER, tower_qty INTEGER, simulation_date DATE,
                    design_eav FLOAT, design_emin FLOAT, design_emax FLOAT,
                    design_uo FLOAT, design_ud FLOAT,
                    maintenance_factor FLOAT, total_flux FLOAT, total_power FLOAT, power_per_area FLOAT,
                    grid_rows INTEGER, grid_cols INTEGER,
                    grid_x_labels TEXT, grid_y_labels TEXT, design_grid TEXT,
                    ks_eav_min FLOAT, ks_uo_min FLOAT, created_at TIMESTAMP DEFAULT NOW())""",
                f"""CREATE TABLE IF NOT EXISTS {quote_ident(DB_SCHEMA)}.illuminance_measured (
                    id SERIAL PRIMARY KEY,
                    area_id INTEGER NOT NULL REFERENCES {quote_ident(DB_SCHEMA)}.illuminance_areas(id) ON DELETE CASCADE,
                    measure_date DATE NOT NULL, measured_by VARCHAR(100),
                    weather VARCHAR(50), instrument VARCHAR(200),
                    measured_eav FLOAT, measured_emin FLOAT, measured_emax FLOAT,
                    measured_uo FLOAT, measured_ud FLOAT, measured_grid TEXT,
                    ks_pass VARCHAR(10), eav_achievement FLOAT, uo_achievement FLOAT,
                    notes TEXT, created_at TIMESTAMP DEFAULT NOW())""",
            ]:
                try:
                    conn.execute(text(tbl_sql))
                except Exception:
                    pass  # 이미 존재하면 무시

            # illuminance_projects: erp_project_id 컬럼 추가 (기존 테이블 대응)
            try:
                conn.execute(text(
                    f"ALTER TABLE {quote_ident(DB_SCHEMA)}.illuminance_projects "
                    f"ADD COLUMN IF NOT EXISTS erp_project_id INTEGER "
                    f"REFERENCES {quote_ident(DB_SCHEMA)}.projects(id) ON DELETE SET NULL"
                ))
            except Exception:
                pass

            # 챗봇 대화 히스토리 (v2026-03-21)
            try:
                conn.execute(text(
                    f"CREATE TABLE IF NOT EXISTS {quote_ident(DB_SCHEMA)}.chatbot_history ("
                    f"  session_id TEXT PRIMARY KEY,"
                    f"  messages_json TEXT NOT NULL DEFAULT '[]',"
                    f"  updated_at TIMESTAMP DEFAULT NOW()"
                    f")"
                ))
            except Exception:
                pass

    # SQLite: illuminance_projects.erp_project_id 컬럼 추가 (create_all 이후 실행)
    if not _is_postgres_engine():
        with engine.begin() as conn:
            try:
                conn.execute(text(
                    "ALTER TABLE illuminance_projects ADD COLUMN erp_project_id INTEGER"
                ))
            except Exception:
                pass  # 이미 존재하면 무시

    # GroupPermission 기본 메뉴 자동 세팅 (빈 값이면 DEFAULT_GROUP_MENUS 적용)
    if _is_postgres_engine():
        from config import DEFAULT_GROUP_MENUS
        with engine.begin() as conn:
            for group_name, default_menus in DEFAULT_GROUP_MENUS.items():
                # 해당 그룹이 없으면 생성
                row = conn.execute(text(
                    f"SELECT allowed_menus FROM {quote_ident(DB_SCHEMA)}.group_permissions "
                    f"WHERE group_name = :gn"
                ), {"gn": group_name}).fetchone()
                if row is None:
                    conn.execute(text(
                        f"INSERT INTO {quote_ident(DB_SCHEMA)}.group_permissions (group_name, allowed_menus) "
                        f"VALUES (:gn, :menus)"
                    ), {"gn": group_name, "menus": default_menus})
                elif not row[0] or row[0] == group_name:
                    # allowed_menus가 비어있거나 그룹명 자체가 들어있으면 기본값으로 업데이트
                    conn.execute(text(
                        f"UPDATE {quote_ident(DB_SCHEMA)}.group_permissions "
                        f"SET allowed_menus = :menus WHERE group_name = :gn"
                    ), {"gn": group_name, "menus": default_menus})

    # 기존 DB 스키마 호환: SQLite만 런타임 ALTER 적용
    if _is_sqlite_engine():
        with engine.begin() as conn:
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(projects)"))]
            if 'expected_contract_date' not in cols:
                conn.execute(text("ALTER TABLE projects ADD COLUMN expected_contract_date DATE"))
            if 'created_at' not in cols:
                conn.execute(text("ALTER TABLE projects ADD COLUMN created_at DATETIME"))
                conn.execute(text("UPDATE projects SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))

            contract_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(contracts)"))]
            if 'item_group' not in contract_cols:
                conn.execute(text("ALTER TABLE contracts ADD COLUMN item_group VARCHAR(50)"))
                conn.execute(text("UPDATE contracts SET item_group = '투광등기구' WHERE item_group IS NULL OR item_group = ''"))
            if 'desired_delivery_date' not in contract_cols:
                conn.execute(text("ALTER TABLE contracts ADD COLUMN desired_delivery_date DATE"))

            item_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(contract_items)"))]
            if 'item_spec_json' not in item_cols:
                conn.execute(text("ALTER TABLE contract_items ADD COLUMN item_spec_json TEXT"))
            if 'status_prod' in item_cols:
                conn.execute(text("UPDATE contract_items SET status_prod = '자재대기중' WHERE status_prod IS NULL OR status_prod = '' OR status_prod = '자재입고대기'"))

            bc_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(contract_barcodes)"))]
            if 'site_name' not in bc_cols:
                conn.execute(text("ALTER TABLE contract_barcodes ADD COLUMN site_name VARCHAR(200)"))
            if 'model_name' not in bc_cols:
                conn.execute(text("ALTER TABLE contract_barcodes ADD COLUMN model_name VARCHAR(200)"))
            if 'producer' not in bc_cols:
                conn.execute(text("ALTER TABLE contract_barcodes ADD COLUMN producer VARCHAR(100)"))
            if 'lens_angle' not in bc_cols:
                conn.execute(text("ALTER TABLE contract_barcodes ADD COLUMN lens_angle VARCHAR(100)"))
            if 'pcb_spec' not in bc_cols:
                conn.execute(text("ALTER TABLE contract_barcodes ADD COLUMN pcb_spec VARCHAR(200)"))
            if 'pcb_cct' not in bc_cols:
                conn.execute(text("ALTER TABLE contract_barcodes ADD COLUMN pcb_cct VARCHAR(100)"))
            if 'pcb_chip_spec' not in bc_cols:
                conn.execute(text("ALTER TABLE contract_barcodes ADD COLUMN pcb_chip_spec VARCHAR(200)"))
            if 'pcb_mfg_date' not in bc_cols:
                conn.execute(text("ALTER TABLE contract_barcodes ADD COLUMN pcb_mfg_date VARCHAR(100)"))
            if 'smps_model' not in bc_cols:
                conn.execute(text("ALTER TABLE contract_barcodes ADD COLUMN smps_model VARCHAR(200)"))
            if 'smps_qty' not in bc_cols:
                conn.execute(text("ALTER TABLE contract_barcodes ADD COLUMN smps_qty INTEGER"))
            if 'smps_setting' not in bc_cols:
                conn.execute(text("ALTER TABLE contract_barcodes ADD COLUMN smps_setting VARCHAR(200)"))
            if 'smps_vdc' not in bc_cols:
                conn.execute(text("ALTER TABLE contract_barcodes ADD COLUMN smps_vdc VARCHAR(100)"))
            if 'smps_adc' not in bc_cols:
                conn.execute(text("ALTER TABLE contract_barcodes ADD COLUMN smps_adc VARCHAR(100)"))
            if 'spacing_distance' not in bc_cols:
                conn.execute(text("ALTER TABLE contract_barcodes ADD COLUMN spacing_distance VARCHAR(100)"))
            if 'replaced_from_barcode' not in bc_cols:
                conn.execute(text("ALTER TABLE contract_barcodes ADD COLUMN replaced_from_barcode VARCHAR(100)"))
            if 'replaced_reason' not in bc_cols:
                conn.execute(text("ALTER TABLE contract_barcodes ADD COLUMN replaced_reason VARCHAR(200)"))

            drawing_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(drawings)"))]
            if drawing_cols and 'contract_item_id' not in drawing_cols:
                conn.execute(text("ALTER TABLE drawings ADD COLUMN contract_item_id INTEGER"))

            history_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(history_logs)"))]
            if 'log_scope' not in history_cols:
                conn.execute(text("ALTER TABLE history_logs ADD COLUMN log_scope VARCHAR(20)"))
                conn.execute(text("UPDATE history_logs SET log_scope = 'common' WHERE log_scope IS NULL OR log_scope = ''"))
            if 'log_kind' not in history_cols:
                conn.execute(text("ALTER TABLE history_logs ADD COLUMN log_kind VARCHAR(20)"))
                conn.execute(text("UPDATE history_logs SET log_kind = CASE WHEN user_name LIKE '%시스템%' THEN 'system' ELSE 'comment' END WHERE log_kind IS NULL OR log_kind = ''"))
            if 'parent_log_id' not in history_cols:
                conn.execute(text("ALTER TABLE history_logs ADD COLUMN parent_log_id INTEGER"))
            if 'root_log_id' not in history_cols:
                conn.execute(text("ALTER TABLE history_logs ADD COLUMN root_log_id INTEGER"))
            if 'origin_snapshot' not in history_cols:
                conn.execute(text("ALTER TABLE history_logs ADD COLUMN origin_snapshot TEXT"))

            mat_order_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(material_orders)"))]
            if mat_order_cols:
                if 'item_category' not in mat_order_cols:
                    conn.execute(text("ALTER TABLE material_orders ADD COLUMN item_category VARCHAR(50)"))
                if 'item_model_name' not in mat_order_cols:
                    conn.execute(text("ALTER TABLE material_orders ADD COLUMN item_model_name VARCHAR(200)"))
                if 'order_status' not in mat_order_cols:
                    conn.execute(text("ALTER TABLE material_orders ADD COLUMN order_status VARCHAR(30)"))
                    conn.execute(text("UPDATE material_orders SET order_status = '발주대기' WHERE order_status IS NULL OR order_status = ''"))
                if 'order_date' not in mat_order_cols:
                    conn.execute(text("ALTER TABLE material_orders ADD COLUMN order_date DATE"))
                if 'expected_in_date' not in mat_order_cols:
                    conn.execute(text("ALTER TABLE material_orders ADD COLUMN expected_in_date DATE"))
                if 'in_confirmed' not in mat_order_cols:
                    conn.execute(text("ALTER TABLE material_orders ADD COLUMN in_confirmed BOOLEAN"))
                    conn.execute(text("UPDATE material_orders SET in_confirmed = 0 WHERE in_confirmed IS NULL"))
                if 'in_confirmed_at' not in mat_order_cols:
                    conn.execute(text("ALTER TABLE material_orders ADD COLUMN in_confirmed_at DATETIME"))
                if 'is_outsourcing' not in mat_order_cols:
                    conn.execute(text("ALTER TABLE material_orders ADD COLUMN is_outsourcing BOOLEAN"))
                    conn.execute(text("UPDATE material_orders SET is_outsourcing = 0 WHERE is_outsourcing IS NULL"))
                if 'outsourcing_status' not in mat_order_cols:
                    conn.execute(text("ALTER TABLE material_orders ADD COLUMN outsourcing_status VARCHAR(30)"))
                if 'note' not in mat_order_cols:
                    conn.execute(text("ALTER TABLE material_orders ADD COLUMN note TEXT"))
                if 'created_at' not in mat_order_cols:
                    conn.execute(text("ALTER TABLE material_orders ADD COLUMN created_at DATETIME"))
                    conn.execute(text("UPDATE material_orders SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
                if 'updated_at' not in mat_order_cols:
                    conn.execute(text("ALTER TABLE material_orders ADD COLUMN updated_at DATETIME"))
                    conn.execute(text("UPDATE material_orders SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"))

            poi_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(purchase_order_items)"))]
            if poi_cols:
                if 'expected_in_date' not in poi_cols:
                    conn.execute(text("ALTER TABLE purchase_order_items ADD COLUMN expected_in_date DATE"))
                if 'in_confirmed' not in poi_cols:
                    conn.execute(text("ALTER TABLE purchase_order_items ADD COLUMN in_confirmed BOOLEAN"))
                    conn.execute(text("UPDATE purchase_order_items SET in_confirmed = 0 WHERE in_confirmed IS NULL"))
                if 'in_confirmed_at' not in poi_cols:
                    conn.execute(text("ALTER TABLE purchase_order_items ADD COLUMN in_confirmed_at DATETIME"))

            prod_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(production_processes)"))]
            if prod_cols:
                if 'project_id' not in prod_cols:
                    conn.execute(text("ALTER TABLE production_processes ADD COLUMN project_id INTEGER"))
                if 'contract_id' not in prod_cols:
                    conn.execute(text("ALTER TABLE production_processes ADD COLUMN contract_id INTEGER"))
                if 'contract_item_id' not in prod_cols:
                    conn.execute(text("ALTER TABLE production_processes ADD COLUMN contract_item_id INTEGER"))
                if 'process_code' not in prod_cols:
                    conn.execute(text("ALTER TABLE production_processes ADD COLUMN process_code VARCHAR(40)"))
                if 'process_name' not in prod_cols:
                    conn.execute(text("ALTER TABLE production_processes ADD COLUMN process_name VARCHAR(200)"))
                if 'step_order' not in prod_cols:
                    conn.execute(text("ALTER TABLE production_processes ADD COLUMN step_order INTEGER"))
                if 'parent_process_id' not in prod_cols:
                    conn.execute(text("ALTER TABLE production_processes ADD COLUMN parent_process_id INTEGER"))
                if 'status' not in prod_cols:
                    conn.execute(text("ALTER TABLE production_processes ADD COLUMN status VARCHAR(30)"))
                    conn.execute(text("UPDATE production_processes SET status = '대기' WHERE status IS NULL OR status = ''"))
                if 'progress_qty' not in prod_cols:
                    conn.execute(text("ALTER TABLE production_processes ADD COLUMN progress_qty INTEGER"))
                    conn.execute(text("UPDATE production_processes SET progress_qty = 0 WHERE progress_qty IS NULL"))
                if 'progress_percent' not in prod_cols:
                    conn.execute(text("ALTER TABLE production_processes ADD COLUMN progress_percent FLOAT"))
                    conn.execute(text("UPDATE production_processes SET progress_percent = 0 WHERE progress_percent IS NULL"))
                if 'is_optional' not in prod_cols:
                    conn.execute(text("ALTER TABLE production_processes ADD COLUMN is_optional BOOLEAN"))
                    conn.execute(text("UPDATE production_processes SET is_optional = 0 WHERE is_optional IS NULL"))
                if 'is_forced' not in prod_cols:
                    conn.execute(text("ALTER TABLE production_processes ADD COLUMN is_forced BOOLEAN"))
                    conn.execute(text("UPDATE production_processes SET is_forced = 0 WHERE is_forced IS NULL"))
                if 'started_at' not in prod_cols:
                    conn.execute(text("ALTER TABLE production_processes ADD COLUMN started_at DATETIME"))
                if 'completed_at' not in prod_cols:
                    conn.execute(text("ALTER TABLE production_processes ADD COLUMN completed_at DATETIME"))
                if 'created_at' not in prod_cols:
                    conn.execute(text("ALTER TABLE production_processes ADD COLUMN created_at DATETIME"))
                    conn.execute(text("UPDATE production_processes SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
                if 'updated_at' not in prod_cols:
                    conn.execute(text("ALTER TABLE production_processes ADD COLUMN updated_at DATETIME"))
                    conn.execute(text("UPDATE production_processes SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"))

            prod_log_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(production_daily_logs)"))]
            if prod_log_cols:
                if 'production_process_id' not in prod_log_cols:
                    conn.execute(text("ALTER TABLE production_daily_logs ADD COLUMN production_process_id INTEGER"))
                if 'work_date' not in prod_log_cols:
                    conn.execute(text("ALTER TABLE production_daily_logs ADD COLUMN work_date DATE"))
                if 'daily_qty' not in prod_log_cols:
                    conn.execute(text("ALTER TABLE production_daily_logs ADD COLUMN daily_qty INTEGER"))
                    conn.execute(text("UPDATE production_daily_logs SET daily_qty = 0 WHERE daily_qty IS NULL"))
                if 'memo' not in prod_log_cols:
                    conn.execute(text("ALTER TABLE production_daily_logs ADD COLUMN memo TEXT"))
                if 'created_by' not in prod_log_cols:
                    conn.execute(text("ALTER TABLE production_daily_logs ADD COLUMN created_by VARCHAR(50)"))
                if 'created_at' not in prod_log_cols:
                    conn.execute(text("ALTER TABLE production_daily_logs ADD COLUMN created_at DATETIME"))
                    conn.execute(text("UPDATE production_daily_logs SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))

            user_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(users)"))]
            if 'can_approve_delete' not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN can_approve_delete BOOLEAN"))
                conn.execute(text("UPDATE users SET can_approve_delete = 0 WHERE can_approve_delete IS NULL"))
            if 'is_active' not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN"))
                conn.execute(text("UPDATE users SET is_active = 1 WHERE is_active IS NULL"))
            if 'deactivated_at' not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN deactivated_at DATETIME"))
            if 'deactivated_reason' not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN deactivated_reason TEXT"))

    db = SessionLocal()
    try:
        # 기존 계약/품목/영업자재 분류값을 상세품목 기준으로 정규화
        contracts = db.query(Contract).all()
        for c in contracts:
            normalized_group = normalize_detail_item(c.item_group)
            if not normalized_group:
                first_item = db.query(ContractItem).filter_by(contract_id=c.id).first()
                normalized_group = normalize_detail_item(
                    first_item.category if first_item and first_item.category else None,
                    default=DETAIL_ITEM_OPTIONS[0]
                )
            c.item_group = normalized_group or DETAIL_ITEM_OPTIONS[0]

        items = db.query(ContractItem).all()
        for item in items:
            item.category = normalize_detail_item(item.category, default=DETAIL_ITEM_OPTIONS[0])

        materials = db.query(Material).all()
        for mat in materials:
            mat.category = normalize_detail_item(mat.category, default=DETAIL_ITEM_OPTIONS[0])

        # 기존 DB 메뉴명 마이그레이션 (회의 반영)
        perms = db.query(GroupPermission).all()
        for perm in perms:
            if perm.allowed_menus and "영업관리 리스트" in perm.allowed_menus:
                perm.allowed_menus = perm.allowed_menus.replace("영업관리 리스트", "설계관리 리스트")
            if perm.allowed_menus and "계약관리 리스트" in perm.allowed_menus:
                perm.allowed_menus = perm.allowed_menus.replace("계약관리 리스트", "게약관리 리스트")
            if perm.allowed_menus and "영업관리" not in perm.allowed_menus:
                perm.allowed_menus = perm.allowed_menus + ",💼 영업관리"
            if perm.allowed_menus and "도면관리" not in perm.allowed_menus:
                perm.allowed_menus = perm.allowed_menus + ",📐 도면관리"
            # drawing 키 마이그레이션 (MENU_REGISTRY 키 기반으로 통일)
            keys = [m.strip() for m in perm.allowed_menus.split(",") if m.strip()] if perm.allowed_menus else []
            if "drawing" not in keys:
                perm.allowed_menus = (perm.allowed_menus or "") + ",drawing"
        if perms:
            db.commit()

        if not db.query(GroupPermission).first():
            all_menus = "🏠 메인 현황판,설계관리 리스트,📋 게약관리 리스트,💼 영업관리,🏟️ 스포츠 조도 계산기,📐 도면관리"
            db.add(GroupPermission(group_name="최고관리자", allowed_menus=all_menus + ",👑 시스템 및 권한 관리"))
            db.add(GroupPermission(group_name="영업부", allowed_menus=all_menus))
            db.add(GroupPermission(group_name="관리부", allowed_menus=all_menus))
            db.add(GroupPermission(group_name="생산부", allowed_menus=all_menus))
            db.commit()

        admin_exists = db.query(User).filter_by(username=SUPERADMIN_USERNAME).first()
        if not admin_exists:
            import bcrypt
            import os
            admin_pw = os.environ.get('ADMIN_DEFAULT_PASSWORD', 'blues55088--')
            hashed_pw = bcrypt.hashpw(admin_pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            db.add(User(username=SUPERADMIN_USERNAME, password_hash=hashed_pw, full_name="매그나텍",
                        phone_number="010-0000-0000", user_group="최고관리자", role="admin", is_approved=True))
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
