from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from .base import Base
from .constants import DETAIL_ITEM_OPTIONS
from .entities import Contract, ContractItem, GroupPermission, Material, User
from .helpers import _read_env_value, normalize_detail_item, quote_ident

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
    @event.listens_for(engine, 'connect')
    def _set_postgres_search_path(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"SET search_path TO {quote_ident(DB_SCHEMA)}, public")
        finally:
            cursor.close()


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
    except OperationalError as e:
        # 간헐적으로 SQLite has_table 체크 타이밍 이슈로 "already exists"가 발생하는 경우 무시
        if 'already exists' not in str(e).lower():
            raise
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
        if perms:
            db.commit()

        if not db.query(GroupPermission).first():
            all_menus = "🏠 메인 현황판,설계관리 리스트,📋 게약관리 리스트,💼 영업관리,🏟️ 스포츠 조도 계산기,📐 도면관리"
            db.add(GroupPermission(group_name="최고관리자", allowed_menus=all_menus + ",👑 시스템 및 권한 관리"))
            db.add(GroupPermission(group_name="영업부", allowed_menus=all_menus))
            db.add(GroupPermission(group_name="관리부", allowed_menus=all_menus))
            db.add(GroupPermission(group_name="생산부", allowed_menus=all_menus))
            db.commit()

        admin_exists = db.query(User).filter_by(username="admin").first()
        if not admin_exists:
            import bcrypt
            hashed_pw = bcrypt.hashpw("admin1234".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            db.add(User(username="admin", password_hash=hashed_pw, full_name="최고관리자",
                        phone_number="010-0000-0000", user_group="최고관리자", role="admin", is_approved=True))
            db.commit()
    except:
        db.rollback()
    finally:
        db.close()
