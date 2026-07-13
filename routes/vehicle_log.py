"""업무용차량 운행기록부 라우트 (PC)

- GET  /vehicle-logs                    : 목록 + 필터
- POST /vehicle-logs/<id>/edit          : 수정
- POST /vehicle-logs/<id>/delete        : 삭제
- GET  /vehicle-logs/<id>/receipt       : 영수증 사진 프록시
- GET  /vehicle-logs/export.xlsx        : 별지서식 엑셀 다운로드
"""
import datetime
import os

from flask import (Blueprint, render_template, request, redirect, url_for, flash,
                   session, jsonify, send_file, abort, Response)
from werkzeug.utils import secure_filename

from modules.auth_decorators import menu_required, admin_required
from modules.db_context import get_db
from modules.utils import safe_int, parse_date
from modules.activity import log_activity
from modules.storage_adapter import upload_bytes, download_bytes, delete_object
from modules.models import VehicleLog, User
from modules.services.vehicle_log_excel import export_vehicle_log_excel, make_filename

vehicle_log_bp = Blueprint("vehicle_log", __name__)

# 회사 보유 업무용 승용차만 운행일지에 사용 (출장 프리셋의 개인차량/대중교통/기타 제외)
EXCLUDED_VEHICLES = {'개인차량', '대중교통', '기타', '도보', ''}


def _get_company_vehicles(db):
    """출장관리 차량 프리셋 → 회사차량 화이트리스트만 반환"""
    from routes.business_trip import _get_vehicle_choices
    presets = _get_vehicle_choices(db)
    return [v for v in presets if v not in EXCLUDED_VEHICLES]


def _get_last_odometer(db, vehicle, before_date=None, exclude_id=None):
    """직전 동일 차량 기록의 주행 후 km 반환"""
    q = db.query(VehicleLog).filter(VehicleLog.vehicle == vehicle)
    if before_date:
        q = q.filter(VehicleLog.use_date <= before_date)
    if exclude_id:
        q = q.filter(VehicleLog.id != exclude_id)
    last = q.order_by(VehicleLog.use_date.desc(), VehicleLog.id.desc()).first()
    return last.odometer_end if last else None


def _save_receipt(file_obj, log_id):
    """영수증 사진 → Supabase Storage 업로드"""
    if not file_obj or not file_obj.filename:
        return None
    data = file_obj.read()
    if not data:
        return None
    if len(data) > 5 * 1024 * 1024:  # 5MB
        raise ValueError('영수증 사진은 5MB 이하여야 합니다')
    ext = os.path.splitext(secure_filename(file_obj.filename))[1].lower() or '.jpg'
    if ext.lstrip('.') not in {'jpg', 'jpeg', 'png', 'webp'}:
        raise ValueError('이미지 파일만 첨부 가능합니다 (jpg/png/webp)')
    storage_path = f"documents/vehicle_logs/{log_id}{ext}"
    ok, err = upload_bytes(storage_path, data, file_obj.mimetype or f'image/{ext.lstrip(".")}')
    if not ok:
        raise RuntimeError(f'영수증 업로드 실패: {err}')
    return storage_path


def _can_edit(log):
    """본인 또는 admin/회계 권한자만 수정/삭제 가능"""
    if session.get('role') == 'admin':
        return True
    return log.user_id == session.get('user_id')


def _serialize_log(log):
    return {
        'id': log.id,
        'use_date': log.use_date.strftime('%Y-%m-%d') if log.use_date else None,
        'vehicle': log.vehicle,
        'user_id': log.user_id,
        'user_name': log.user_name,
        'user_department': log.user_department,
        'user_position': log.user_position,
        'odometer_start': log.odometer_start,
        'odometer_end': log.odometer_end,
        'distance_km': log.distance_km,
        'fuel_amount': log.fuel_amount,
        'origin': log.origin,
        'destination': log.destination,
        'purpose': log.purpose,
        'has_receipt': bool(log.receipt_url),
        'created_at': log.created_at.strftime('%Y-%m-%d %H:%M') if log.created_at else None,
        'can_edit': _can_edit(log),
    }


# ===================================================================
# 1. 목록
# ===================================================================
@vehicle_log_bp.route('/vehicle-logs')
@menu_required('vehicle_log')
def log_list():
    vehicle = (request.args.get('vehicle') or '').strip()
    user_id = safe_int(request.args.get('user_id'), 0)
    from_date = parse_date(request.args.get('from'))
    to_date = parse_date(request.args.get('to'))

    today = datetime.date.today()
    if not from_date and not to_date:
        # 기본: 이번 달
        from_date = today.replace(day=1)

    with get_db() as db:
        q = db.query(VehicleLog)
        if vehicle:
            q = q.filter(VehicleLog.vehicle == vehicle)
        if user_id:
            q = q.filter(VehicleLog.user_id == user_id)
        if from_date:
            q = q.filter(VehicleLog.use_date >= from_date)
        if to_date:
            q = q.filter(VehicleLog.use_date <= to_date)
        logs = q.order_by(VehicleLog.use_date.desc(), VehicleLog.id.desc()).all()

        vehicles = _get_company_vehicles(db)
        users = db.query(User).filter(User.is_active != False).order_by(User.full_name).all()  # noqa: E712

        # 출장 연동: 로그인 사용자(=운전자 본인)가 출장자로 등록된 회사차량 출장만 후보 제공
        from modules.services.vehicle_log_trip_link import recent_trips_for_vehicle_log
        trip_options = recent_trips_for_vehicle_log(
            db, user_id=session.get('user_id'),
            user_name=session.get('full_name'), limit=15)

        # 합계
        total_distance = sum((l.distance_km or 0) for l in logs)
        total_fuel = sum((l.fuel_amount or 0) for l in logs)

        return render_template(
            'vehicle_log_list.html',
            logs=logs,
            vehicles=vehicles,
            users=users,
            trip_options=trip_options,
            current_year=today.year,
            filters={
                'vehicle': vehicle,
                'user_id': user_id,
                'from': from_date.strftime('%Y-%m-%d') if from_date else '',
                'to': to_date.strftime('%Y-%m-%d') if to_date else '',
            },
            total_distance=total_distance,
            total_fuel=total_fuel,
            can_edit_map={l.id: _can_edit(l) for l in logs},
        )


# ===================================================================
# 1.5. 신규 등록 (PC)
# ===================================================================
@vehicle_log_bp.route('/vehicle-logs/create', methods=['POST'])
@menu_required('vehicle_log', write=True)
def log_create():
    """PC 신규 등록 — multipart/form-data (영수증 포함 가능)"""
    use_date_str = (request.form.get('use_date') or '').strip()
    vehicle = (request.form.get('vehicle') or '').strip()
    odo_start = request.form.get('odometer_start')
    odo_end = request.form.get('odometer_end')
    fuel = request.form.get('fuel_amount')
    origin = (request.form.get('origin') or '').strip()
    destination = (request.form.get('destination') or '').strip()
    purpose = (request.form.get('purpose') or '').strip()

    # 검증
    if not vehicle:
        return jsonify(ok=False, error='차량을 선택해주세요'), 400
    if not odo_end:
        return jsonify(ok=False, error='주행 후 km을 입력해주세요'), 400
    if not origin or not destination or not purpose:
        return jsonify(ok=False, error='출발지/도착지/사용목적을 입력해주세요'), 400

    try:
        odometer_end = int(odo_end)
        odometer_start = int(odo_start) if odo_start not in (None, '') else None
        fuel_amount = int(fuel) if fuel not in (None, '') else None
    except (ValueError, TypeError):
        return jsonify(ok=False, error='주행거리/주유금액은 숫자여야 합니다'), 400

    if odometer_start is not None and odometer_end < odometer_start:
        return jsonify(ok=False, error='주행 후 km이 주행 전보다 작습니다'), 400

    distance_km = (odometer_end - odometer_start) if odometer_start is not None else 0
    if distance_km < 0:
        distance_km = 0

    use_date = parse_date(use_date_str) or datetime.date.today()
    user_id = session.get('user_id')

    with get_db() as db:
        if vehicle not in _get_company_vehicles(db):
            return jsonify(ok=False, error='허용되지 않은 차량입니다'), 400

        user = db.query(User).get(user_id) if user_id else None
        log = VehicleLog(
            use_date=use_date,
            vehicle=vehicle,
            user_id=user_id,
            user_name=user.full_name if user else session.get('full_name', ''),
            user_department=user.user_group if user else None,
            user_position=getattr(user, 'position', None) if user else None,
            odometer_start=odometer_start,
            odometer_end=odometer_end,
            distance_km=distance_km,
            fuel_amount=fuel_amount,
            origin=origin,
            destination=destination,
            purpose=purpose,
        )
        db.add(log)
        db.flush()

        # 영수증 업로드
        receipt = request.files.get('receipt')
        if receipt and receipt.filename:
            try:
                path = _save_receipt(receipt, log.id)
                if path:
                    log.receipt_url = path
            except (ValueError, RuntimeError) as e:
                return jsonify(ok=False, error=str(e)), 400

        log_activity(db, 'vehicle_log', 'create',
                     f"운행일지 등록 #{log.id} ({log.vehicle} {log.use_date})",
                     ref_type='vehicle_log', ref_id=log.id,
                     ref_label=f"{log.vehicle} {log.use_date}")
        db.commit()
        return jsonify(ok=True, id=log.id, distance_km=log.distance_km)


# ===================================================================
# 2. 수정
# ===================================================================
@vehicle_log_bp.route('/vehicle-logs/<int:log_id>/edit', methods=['POST'])
@menu_required('vehicle_log', write=True)
def log_edit(log_id):
    with get_db() as db:
        log = db.query(VehicleLog).get(log_id)
        if not log:
            return jsonify(ok=False, error='not_found'), 404
        if not _can_edit(log):
            return jsonify(ok=False, error='forbidden'), 403

        use_date = parse_date(request.form.get('use_date')) or log.use_date
        vehicle = (request.form.get('vehicle') or '').strip() or log.vehicle
        odometer_start = request.form.get('odometer_start')
        odometer_end = request.form.get('odometer_end')
        fuel_amount = request.form.get('fuel_amount')
        origin = (request.form.get('origin') or '').strip() or log.origin
        destination = (request.form.get('destination') or '').strip() or log.destination
        purpose = (request.form.get('purpose') or '').strip() or log.purpose

        log.use_date = use_date
        log.vehicle = vehicle
        log.odometer_start = safe_int(odometer_start, log.odometer_start) if odometer_start else log.odometer_start
        log.odometer_end = safe_int(odometer_end, log.odometer_end) if odometer_end else log.odometer_end
        if log.odometer_start is not None and log.odometer_end is not None:
            log.distance_km = max(log.odometer_end - log.odometer_start, 0)
        log.fuel_amount = safe_int(fuel_amount, 0) if fuel_amount else log.fuel_amount
        log.origin = origin
        log.destination = destination
        log.purpose = purpose

        # 영수증 교체
        receipt = request.files.get('receipt')
        if receipt and receipt.filename:
            try:
                new_path = _save_receipt(receipt, log.id)
                if new_path:
                    log.receipt_url = new_path
            except (ValueError, RuntimeError) as e:
                return jsonify(ok=False, error=str(e)), 400

        log_activity(db, 'vehicle_log', 'update',
                     f"운행일지 수정 #{log.id} ({log.vehicle} {log.use_date})",
                     ref_type='vehicle_log', ref_id=log.id,
                     ref_label=f"{log.vehicle} {log.use_date}")
        db.commit()
        return jsonify(ok=True, item=_serialize_log(log))


# ===================================================================
# 3. 삭제
# ===================================================================
@vehicle_log_bp.route('/vehicle-logs/<int:log_id>/delete', methods=['POST'])
@menu_required('vehicle_log', write=True)
def log_delete(log_id):
    with get_db() as db:
        log = db.query(VehicleLog).get(log_id)
        if not log:
            return jsonify(ok=False, error='not_found'), 404
        if not _can_edit(log):
            return jsonify(ok=False, error='forbidden'), 403

        if log.receipt_url:
            try:
                delete_object(log.receipt_url)
            except Exception:
                pass

        log_activity(db, 'vehicle_log', 'delete',
                     f"운행일지 삭제 #{log.id} ({log.vehicle} {log.use_date})",
                     ref_type='vehicle_log', ref_id=log.id)
        db.delete(log)
        db.commit()
        return jsonify(ok=True)


# ===================================================================
# 4. 영수증 사진 프록시
# ===================================================================
@vehicle_log_bp.route('/vehicle-logs/<int:log_id>/receipt')
@menu_required('vehicle_log')
def log_receipt(log_id):
    with get_db() as db:
        log = db.query(VehicleLog).get(log_id)
        if not log or not log.receipt_url:
            abort(404)
        data = download_bytes(log.receipt_url)
        if not data:
            abort(404)
        ext = os.path.splitext(log.receipt_url)[1].lower().lstrip('.')
        mime_map = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                    'png': 'image/png', 'webp': 'image/webp'}
        mime = mime_map.get(ext, 'application/octet-stream')
        return Response(data, mimetype=mime, headers={
            'Content-Disposition': f'inline; filename="receipt_{log.id}.{ext}"'
        })


# ===================================================================
# 5. 별지서식 엑셀 다운로드
# ===================================================================
@vehicle_log_bp.route('/vehicle-logs/export.xlsx')
@menu_required('vehicle_log')
def log_export():
    vehicle = (request.args.get('vehicle') or '').strip()
    year = safe_int(request.args.get('year'), datetime.date.today().year)
    if not vehicle:
        flash('차량을 선택해주세요', 'error')
        return redirect(url_for('vehicle_log.log_list'))

    with get_db() as db:
        from_date = datetime.date(year, 1, 1)
        to_date = datetime.date(year, 12, 31)
        logs = (db.query(VehicleLog)
                .filter(VehicleLog.vehicle == vehicle)
                .filter(VehicleLog.use_date >= from_date)
                .filter(VehicleLog.use_date <= to_date)
                .order_by(VehicleLog.use_date.asc(), VehicleLog.id.asc())
                .all())

        bio = export_vehicle_log_excel(logs, vehicle, year)
        filename = make_filename(vehicle, year)
        return send_file(
            bio,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )


# ===================================================================
# 6. 직전 odometer 조회 (PC 폼용 헬퍼)
# ===================================================================
@vehicle_log_bp.route('/vehicle-logs/last-odometer')
@menu_required('vehicle_log')
def last_odometer():
    vehicle = (request.args.get('vehicle') or '').strip()
    if not vehicle:
        return jsonify(ok=True, odometer=None)
    with get_db() as db:
        last = _get_last_odometer(db, vehicle)
        return jsonify(ok=True, odometer=last)


@vehicle_log_bp.route('/vehicle-logs/trip-prefill/<int:trip_id>')
@menu_required('vehicle_log')
def trip_prefill(trip_id):
    """출장 → 운행일지 작성 프리필. 회사차량 출장이 아니면 ok=False."""
    from modules.models import BusinessTrip
    from modules.services.vehicle_log_trip_link import trip_to_log_defaults
    with get_db() as db:
        trip = db.get(BusinessTrip, trip_id)
        if not trip:
            return jsonify(ok=False, error='출장을 찾을 수 없습니다'), 404
        defaults = trip_to_log_defaults(db, trip)
        if not defaults:
            return jsonify(ok=False, error='회사차량 출장이 아니라 운행일지 대상이 아닙니다'), 400
        # 직전 계기판도 같이 내려 폼이 주행 전 km까지 채우게 함
        defaults['last_odometer'] = _get_last_odometer(db, defaults['vehicle'])
        return jsonify(ok=True, prefill=defaults)
