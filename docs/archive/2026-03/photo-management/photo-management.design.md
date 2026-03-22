# Design: photo-management

## 1. 아키텍처 개요

```
Browser (PC/모바일)
  │  GET /photos, /photos/project/<id>
  │  POST /photos/api/upload  (XHR + FormData)
  │  DELETE /photos/api/photos/<id>
  ▼
routes/photos.py  (Flask Blueprint)
  │
  ├── ProjectPhoto (신규 SQLAlchemy 모델)
  │     project_id FK → projects
  │     contract_id FK → contracts (nullable)
  │
  ├── ContractItem  (기존 모델, 조회만)
  │
  └── modules/storage_adapter.py
        upload_bytes() / download_bytes() / delete_object()
        Bucket: company-files
        경로: storage/photos/project_{id}/{YYYYMMDD_HHMMSSfff}{ext}
```

---

## 2. DB 설계

### 2.1 신규 모델: `ProjectPhoto`

```python
class ProjectPhoto(Base):
    __tablename__ = 'project_photos'

    id          = Column(Integer, primary_key=True, autoincrement=True)
    project_id  = Column(Integer, ForeignKey('projects.id'), nullable=False)
    contract_id = Column(Integer, ForeignKey('contracts.id'), nullable=True)
    photo_type  = Column(String(30), default='기타')   # 상차/하차/설치/기타
    file_name   = Column(String(255), nullable=False)
    storage_path= Column(String(500), nullable=False)
    uploaded_by = Column(String(50),  default='사용자')
    created_at  = Column(DateTime,    default=datetime.datetime.now)

    project  = relationship("Project",  back_populates="project_photos")
    contract = relationship("Contract", back_populates="project_photos")
```

### 2.2 기존 모델 관계 추가

```python
# entities.py 에 추가
# Project:
project_photos = relationship("ProjectPhoto", back_populates="project", cascade="all, delete-orphan")
# Contract:
project_photos = relationship("ProjectPhoto", back_populates="contract")
```

### 2.3 DB 마이그레이션 (sql_editer.sql)

```sql
CREATE TABLE project_photos (
    id           SERIAL PRIMARY KEY,
    project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    contract_id  INTEGER REFERENCES contracts(id) ON DELETE SET NULL,
    photo_type   VARCHAR(30) DEFAULT '기타',
    file_name    VARCHAR(255) NOT NULL,
    storage_path VARCHAR(500) NOT NULL,
    uploaded_by  VARCHAR(50)  DEFAULT '사용자',
    created_at   TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_project_photos_project_id ON project_photos(project_id);
```

---

## 3. 파일 구조

```
routes/
  photos.py                 ← 신규 Blueprint
templates/
  photo_gallery.html        ← 메인 갤러리 (frontend-designer 설계)
```

---

## 4. API 명세

### 4.1 페이지 라우트

| Method | URL | 설명 |
|--------|-----|------|
| GET | `/photos` | 현장 목록 (첫 현장 자동 선택) |
| GET | `/photos/project/<project_id>` | 현장별 갤러리 |

### 4.2 Ajax API

| Method | URL | 입력 | 출력 |
|--------|-----|------|------|
| GET | `/photos/api/site/<project_id>` | - | `{site_name, contract_no, items:[{item_name, qty}]}` |
| GET | `/photos/api/photos?site_id=<id>` | query | `{photos:[{id, url, photo_type, uploaded_at, uploaded_by}]}` |
| POST | `/photos/api/upload` | FormData(file, site_id, csrf_token) | `{photo:{id, url, photo_type, uploaded_at}}` |
| DELETE | `/photos/api/photos/<id>` | X-CSRFToken header | `{ok: true}` |

### 4.3 사진 URL 생성 방식

```python
# storage_adapter.download_bytes() → Response(bytes)
# 썸네일 없으므로 동일 URL 사용 (원본 → 브라우저 lazy-load)
url = url_for('photos.photo_view', photo_id=photo.id)
```

---

## 5. routes/photos.py 구조

```python
photos_bp = Blueprint('photos', __name__, url_prefix='/photos')

# ── 페이지 ──
@photos_bp.route('')                              # 현장 목록
@photos_bp.route('/project/<int:project_id>')     # 현장별 갤러리

# ── Ajax API ──
@photos_bp.route('/api/site/<int:project_id>')    # 현장 헤더
@photos_bp.route('/api/photos')                   # 사진 목록 (GET)
@photos_bp.route('/api/upload', methods=['POST']) # 업로드
@photos_bp.route('/api/photos/<int:photo_id>', methods=['DELETE']) # 삭제
@photos_bp.route('/<int:photo_id>/view')          # 이미지 바이너리
```

---

## 6. 현장 목록 쿼리

```python
# 현장별 사진 수 포함
from sqlalchemy import func
sites = (
    db.query(
        Project.id,
        Project.project_no,
        Project.temp_name.label('site_name'),
        func.count(ProjectPhoto.id).label('photo_count'),
    )
    .outerjoin(ProjectPhoto, ProjectPhoto.project_id == Project.id)
    .group_by(Project.id)
    .order_by(func.count(ProjectPhoto.id).desc(), Project.created_at.desc())
    .all()
)
```

---

## 7. 업로드 처리

```python
@photos_bp.route('/api/upload', methods=['POST'])
@login_required
def api_upload():
    file       = request.files.get('file')
    site_id    = request.form.get('site_id', type=int)
    photo_type = request.form.get('photo_type', '기타')

    ext = os.path.splitext(secure_filename(file.filename))[1].lower() or '.jpg'
    ts  = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    storage_path = f"storage/photos/project_{site_id}/{ts}{ext}"

    ok, err = upload_bytes(storage_path, file.read(), file.mimetype or 'image/jpeg')
    if not ok:
        return jsonify({'error': err}), 500

    photo = ProjectPhoto(
        project_id   = site_id,
        photo_type   = photo_type,
        file_name    = file.filename,
        storage_path = storage_path,
        uploaded_by  = current_user,
    )
    db.add(photo)
    db.commit()

    return jsonify({'photo': {
        'id':          photo.id,
        'url':         url_for('photos.photo_view', photo_id=photo.id),
        'photo_type':  photo.photo_type,
        'uploaded_at': photo.created_at.isoformat(),
    }})
```

---

## 8. 납품관리 사진탭 제거 (FR-09)

- `templates/delivery_detail.html` → 사진 탭 섹션 제거
- `routes/delivery.py` → `photo_view`, `upload_photo`, `delete_photo` 라우트 제거
- `modules/services/delivery_actions.py` → `handle_upload_photo`, `handle_delete_photo` 제거
- `DeliveryPhoto` 모델은 **유지** (기존 데이터 보존)

---

## 9. config.py 메뉴 등록

```python
("photos", {"label": "사진관리", "group": "공유", "endpoint": "photos.photo_list"}),
```

---

## 10. 구현 순서

1. `entities.py` → `ProjectPhoto` 모델 추가 + 관계 설정
2. `sql_editer.sql` → DDL 실행
3. `routes/photos.py` → Blueprint 구현 (페이지 + API 6개)
4. `templates/photo_gallery.html` → frontend-designer 결과물 저장
5. `app.py` → Blueprint 등록
6. `config.py` → 메뉴 등록
7. `delivery_detail.html` + `delivery.py` → 사진탭 제거
