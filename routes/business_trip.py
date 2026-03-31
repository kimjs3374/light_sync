"""출장관리 라우트"""
import json
import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from modules.auth_decorators import menu_required, admin_required
from modules.db_context import get_db
from modules.utils import safe_int, parse_date
from modules.pagination import make_pagination
from modules.activity import log_activity
from modules.kakaowork_notifier import send_group_notification
from modules.models import (
    BusinessTrip, BusinessTripMember, User, DashboardSetting,
    TRIP_STATUS_CHOICES, VEHICLE_CHOICES,
)

business_trip_bp = Blueprint("business_trip", __name__)

VEHICLE_SETTING_KEY = 'business_trip_vehicles'


def _get_vehicle_choices(db):
    """DB에서 차량 프리셋 로드, 없으면 기본값 저장 후 반환"""
    row = db.query(DashboardSetting).filter_by(setting_key=VEHICLE_SETTING_KEY).first()
    if row:
        try:
            return json.loads(row.setting_value)
        except (json.JSONDecodeError, TypeError):
            pass
    # 최초: 기본값을 DB에 저장
    defaults = [v[0] for v in VEHICLE_CHOICES]
    row = DashboardSetting(setting_key=VEHICLE_SETTING_KEY,
                           setting_value=json.dumps(defaults, ensure_ascii=False))
    db.add(row)
    db.commit()
    return defaults


def _parse_datetime(date_str, time_str):
    """날짜 + 시간 문자열을 datetime으로 변환"""
    if not date_str:
        return None
    d = parse_date(date_str)
    if not d:
        return None
    if time_str:
        try:
            parts = time_str.strip().split(':')
            return datetime.datetime(d.year, d.month, d.day, int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            pass
    return datetime.datetime(d.year, d.month, d.day, 8, 0)


def _save_members(db, trip, form):
    """폼에서 출장인원 파싱 후 저장"""
    # 기존 멤버 삭제
    for m in trip.members[:]:
        db.delete(m)
    db.flush()

    user_ids = request.form.getlist('member_user_id')
    names = request.form.getlist('member_name')
    positions = request.form.getlist('member_position')
    departments = request.form.getlist('member_department')

    for i in range(len(names)):
        name = names[i].strip() if i < len(names) else ''
        if not name:
            continue
        uid = safe_int(user_ids[i]) if i < len(user_ids) else 0
        pos = positions[i].strip() if i < len(positions) else ''
        dept = departments[i].strip() if i < len(departments) else ''
        db.add(BusinessTripMember(
            trip_id=trip.id,
            user_id=uid if uid else None,
            user_name=name,
            position=pos or None,
            department=dept or None,
        ))


@business_trip_bp.route('/business-trips')
@menu_required('business_trip')
def trip_list():
    page = safe_int(request.args.get('page'), 1)
    per_page = 50
    status_filter = request.args.get('status', '').strip()
    search = request.args.get('search', '').strip()

    with get_db() as db:
        from sqlalchemy.orm import joinedload
        query = db.query(BusinessTrip).options(
            joinedload(BusinessTrip.members)
        ).order_by(BusinessTrip.departure_date.desc())
        if status_filter:
            query = query.filter(BusinessTrip.status == status_filter)
        if search:
            like = f'%{search}%'
            query = query.filter(
                (BusinessTrip.title.ilike(like)) |
                (BusinessTrip.destination.ilike(like)) |
                (BusinessTrip.purpose.ilike(like))
            )
        total = db.query(BusinessTrip).filter(query.whereclause).count() if query.whereclause is not None else db.query(BusinessTrip).count()
        pagination = make_pagination(page, per_page, total)
        trips = query.offset((pagination['page'] - 1) * per_page).limit(per_page).all()
        # unique 처리 (joinedload + limit 조합 시 중복 방지)
        seen = set()
        unique_trips = []
        for t in trips:
            if t.id not in seen:
                seen.add(t.id)
                unique_trips.append(t)
        trips = unique_trips

        # 상태별 건수
        from sqlalchemy import func
        status_counts = dict(
            db.query(BusinessTrip.status, func.count(BusinessTrip.id))
            .group_by(BusinessTrip.status).all()
        )

        vehicles = _get_vehicle_choices(db)

        return render_template('business_trip_list.html',
                               trips=trips,
                               pagination=pagination,
                               status_choices=TRIP_STATUS_CHOICES,
                               status_counts=status_counts,
                               vehicle_choices=vehicles,
                               filters={'status': status_filter, 'search': search})


@business_trip_bp.route('/business-trips/create', methods=['GET', 'POST'])
@menu_required('business_trip', write=True)
def trip_create():
    with get_db() as db:
        if request.method == 'POST':
            trip = BusinessTrip(
                title=request.form.get('title', '').strip(),
                destination=request.form.get('destination', '').strip(),
                purpose=request.form.get('purpose', '').strip() or None,
                vehicle=request.form.get('vehicle', '').strip() or None,
                status=request.form.get('status', '예정'),
                departure_date=_parse_datetime(
                    request.form.get('departure_date'),
                    request.form.get('departure_time')),
                return_date=_parse_datetime(
                    request.form.get('return_date'),
                    request.form.get('return_time')),
                note=request.form.get('note', '').strip() or None,
                created_by=session['user_id'],
            )
            db.add(trip)
            db.flush()
            _save_members(db, trip, request.form)
            db.commit()

            log_activity(db, 'business_trip', 'create',
                         f'출장 등록: {trip.title} ({trip.destination})',
                         ref_type='BusinessTrip', ref_id=trip.id,
                         user_name=session.get('full_name'))
            db.commit()

            # 카카오워크 그룹채팅 알림
            member_labels = [
                f"{m.user_name} {m.position}".strip() if m.position else m.user_name
                for m in trip.members if m.user_name
            ]
            creator_user = db.query(User).get(session['user_id'])
            creator_label = session.get('full_name', '-')
            if creator_user and creator_user.position:
                creator_label = f"{creator_user.full_name} {creator_user.position}"
            dep_str = trip.departure_date.strftime('%Y-%m-%d %H:%M') if trip.departure_date else '-'
            ret_str = trip.return_date.strftime('%Y-%m-%d %H:%M') if trip.return_date else '-'
            notify_text = (
                f"[출장등록] {trip.title}\n"
                f"목적지: {trip.destination}\n"
                f"출발: {dep_str}\n"
                f"귀환: {ret_str}\n"
                f"차량: {trip.vehicle or '-'}\n"
                f"인원: {', '.join(member_labels) or '-'}\n"
                f"등록자: {creator_label}"
            )
            send_group_notification(notify_text)

            flash('출장이 등록되었습니다.', 'success')
            return redirect(url_for('business_trip.trip_list'))

        users = db.query(User).filter(
            User.is_active.is_(True),
            User.is_approved.is_(True)
        ).order_by(User.full_name).all()
        vehicles = _get_vehicle_choices(db)

        return render_template('business_trip_form.html',
                               trip=None,
                               users=users,
                               status_choices=TRIP_STATUS_CHOICES,
                               vehicle_choices=vehicles)


@business_trip_bp.route('/business-trips/<int:trip_id>')
@menu_required('business_trip')
def trip_detail(trip_id):
    with get_db() as db:
        from sqlalchemy.orm import joinedload
        trip = db.query(BusinessTrip).options(
            joinedload(BusinessTrip.members),
            joinedload(BusinessTrip.creator),
        ).get(trip_id)
        if not trip:
            flash('출장 정보를 찾을 수 없습니다.', 'danger')
            return redirect(url_for('business_trip.trip_list'))
        return render_template('business_trip_detail.html',
                               trip=trip,
                               status_choices=TRIP_STATUS_CHOICES)


@business_trip_bp.route('/business-trips/<int:trip_id>/edit', methods=['GET', 'POST'])
@menu_required('business_trip', write=True)
def trip_edit(trip_id):
    with get_db() as db:
        from sqlalchemy.orm import joinedload
        trip = db.query(BusinessTrip).options(
            joinedload(BusinessTrip.members),
            joinedload(BusinessTrip.creator),
        ).get(trip_id)
        if not trip:
            flash('출장 정보를 찾을 수 없습니다.', 'danger')
            return redirect(url_for('business_trip.trip_list'))

        if request.method == 'POST':
            trip.title = request.form.get('title', '').strip()
            trip.destination = request.form.get('destination', '').strip()
            trip.purpose = request.form.get('purpose', '').strip() or None
            trip.vehicle = request.form.get('vehicle', '').strip() or None
            trip.status = request.form.get('status', trip.status)
            trip.departure_date = _parse_datetime(
                request.form.get('departure_date'),
                request.form.get('departure_time'))
            trip.return_date = _parse_datetime(
                request.form.get('return_date'),
                request.form.get('return_time'))
            trip.note = request.form.get('note', '').strip() or None
            _save_members(db, trip, request.form)
            db.commit()

            log_activity(db, 'business_trip', 'update',
                         f'출장 수정: {trip.title}',
                         ref_type='BusinessTrip', ref_id=trip.id,
                         user_name=session.get('full_name'))
            db.commit()

            flash('출장이 수정되었습니다.', 'success')
            return redirect(url_for('business_trip.trip_detail', trip_id=trip.id))

        users = db.query(User).filter(
            User.is_active.is_(True),
            User.is_approved.is_(True)
        ).order_by(User.full_name).all()
        vehicles = _get_vehicle_choices(db)

        return render_template('business_trip_form.html',
                               trip=trip,
                               users=users,
                               status_choices=TRIP_STATUS_CHOICES,
                               vehicle_choices=vehicles)


@business_trip_bp.route('/business-trips/<int:trip_id>/delete', methods=['POST'])
@menu_required('business_trip', write=True)
def trip_delete(trip_id):
    with get_db() as db:
        trip = db.query(BusinessTrip).get(trip_id)
        if trip:
            log_activity(db, 'business_trip', 'delete',
                         f'출장 삭제: {trip.title}',
                         ref_type='BusinessTrip', ref_id=trip.id,
                         user_name=session.get('full_name'))
            db.delete(trip)
            db.commit()
            flash('출장이 삭제되었습니다.', 'success')
    return redirect(url_for('business_trip.trip_list'))


@business_trip_bp.route('/business-trips/<int:trip_id>/status', methods=['POST'])
@menu_required('business_trip', write=True)
def trip_status_change(trip_id):
    """상태 빠른 변경 (AJAX or form)"""
    new_status = request.form.get('status', '')
    with get_db() as db:
        trip = db.query(BusinessTrip).get(trip_id)
        if trip and new_status:
            old = trip.status
            trip.status = new_status
            log_activity(db, 'business_trip', 'status_change',
                         f'출장 상태변경: {trip.title} ({old}→{new_status})',
                         ref_type='BusinessTrip', ref_id=trip.id,
                         user_name=session.get('full_name'))
            db.commit()
            flash(f'상태가 {new_status}(으)로 변경되었습니다.', 'success')
    return redirect(request.referrer or url_for('business_trip.trip_list'))


@business_trip_bp.route('/business-trips/vehicles', methods=['GET', 'POST'])
@admin_required
def vehicle_settings():
    """차량 프리셋 관리 (admin only)"""
    with get_db() as db:
        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            vehicles = [v.strip() for v in data.get('vehicles', []) if v.strip()]
            row = db.query(DashboardSetting).filter_by(setting_key=VEHICLE_SETTING_KEY).first()
            if row:
                row.setting_value = json.dumps(vehicles, ensure_ascii=False)
            else:
                db.add(DashboardSetting(
                    setting_key=VEHICLE_SETTING_KEY,
                    setting_value=json.dumps(vehicles, ensure_ascii=False)))
            db.commit()
            return jsonify(ok=True, vehicles=vehicles)
        # GET
        vehicles = _get_vehicle_choices(db)
        return jsonify(vehicles=vehicles)
