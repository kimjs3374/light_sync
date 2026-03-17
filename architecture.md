# Project Architecture

## Folder Structure

```
light_sync/
├── app.py
├── ASPose_CAD_SETUP.md
├── MASTER_GUIDE.md
├── requirements.txt
├── DB/
│   └── light_sync.db
├── modules/
│   ├── models.back
│   ├── models.py
├── routes/
│   ├── auth.py
│   ├── contract.py
│   ├── dashboard.py
│   ├── drawing.py
│   ├── project.back
│   ├── project.py
│   └── technical.py
├── storage/
│   └── drawings/
│       └── project_2/
│           └── drawing_1/
│               ├── v1/
│               │   └── 260225.dwg
│               └── v2/
│                   ├── 260225.dwg
│                   └── 260225.pdf
└── templates/
    ├── admin_settings.html
    ├── base.html
    ├── contract_detail.html
    ├── contract_list.html
    ├── dashboard.html
    ├── drawings_index.html
    ├── drawings_project.html
    ├── login.html
    ├── lux_calculator.html
    ├── project_create.html
    ├── project_detail.html
    ├── project_list.html
    └── shared_pdf_view.html
```

## Key Files and Their Roles

- **app.py**: The main entry point of the application.
- **ASPose_CAD_SETUP.md**: Documentation for setting up ASPOSE CAD.
- **MASTER_GUIDE.md**: Master guide for the project.
- **requirements.txt**: List of Python packages required for the project.

### Models

- **modules/models.back**: Backup file for models.
- **modules/models.py**: Contains all the data models for the application.

### Routes

- **routes/auth.py**: Handles authentication routes.
- **routes/contract.py**: Handles contract-related routes.
- **routes/dashboard.py**: Handles dashboard-related routes.
- **routes/drawing.py**: Handles drawing-related routes.
- **routes/project.back**: Backup file for project routes.
- **routes/project.py**: Handles project-related routes.
- **routes/technical.py**: Handles technical documentation or support routes.

### Storage

- **storage/drawings/**: Directory to store drawing files.

### Templates

- Various HTML templates used in the application.

## Technology Stack

The current Light-Sync project is built using Python and Flask.
```
<task_progress>
- [x] 터미널에서 `dir /s /b /a-d` 명령어를 실행해서 전체 파일 목록을 파악해.
- [x] node_modules, .git, __pycache__, venv 폴더는 분석에서 제외해.
- [x] 파악된 구조를 바탕으로 architecture.md 파일을 만들고 다음 내용을 포함해:
  - 전체 폴더 구조 (Tree 형태)
  - 각 주요 파일(예: models.py, views.py, app.py 등)의 핵심 역할 요약
  - 현재 진행 중인 'Light-Sync' 프로젝트의 주요 기술 스택 (Python, Flask/Django 등)
- [ ] 생성된 architecture.md 파일을 검토하는 것을 알려줘.
</task_progress>
</write_to_file>