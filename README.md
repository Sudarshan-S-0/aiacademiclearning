# AI Academic Teaching and Learning System

A role-based academic platform connecting Admin -> Teacher -> Approved Academic Resources -> AI/RAG -> Student -> Assessment -> Progress.

## Implemented workflow

### Admin
- Manage users, departments, semesters, sections and subjects.
- Assign teachers to subjects and enroll students.
- Configure weeks, hours/week and lecture duration.
- Monitor users, resources, content and audit activity.

### Teacher
- Work only with assigned subjects.
- Upload syllabus, reference books, staff material, PYQs and question banks.
- Version resources and compare syllabus revisions as added / removed / modified / unchanged.
- Approve resources before they become AI knowledge.
- Generate grounded notes, assignments, question banks, revision material, quizzes and PPTX drafts.
- Review AI drafts before approval/publication.
- Generate and dynamically edit teaching plans by hours, order, completion and week.
- Reanalyze PYQs, repeated questions, year trends and unit/topic weightage.
- View subject-level teaching analytics.

### Student
- Access assigned subjects only.
- See published resources/content only.
- Read published academic material.
- Ask the AI assistant questions grounded in approved resources.
- Take published quizzes and submit assignments.
- View progress, weak topics and revision recommendations.

## AI/RAG controls

- Original files are stored in MinIO/S3-compatible storage.
- Documents are extracted with page/slide metadata.
- Chunks are stored in PostgreSQL and indexed in Qdrant.
- Semantic embeddings use sentence-transformers when installed.
- Gemini is used for grounded generation when GEMINI_API_KEY is configured.
- Retrieved documents are treated as untrusted data; embedded instructions are ignored.
- AI generation is restricted to approved resources.
- Unsupported questions return exactly:
  Information not found in the approved academic resources for this subject.
- Generated material enters teacher review and is never automatically published.
- Source citations preserve resource/page/slide/section information.

## Stack

- Frontend: React + TypeScript + Vite
- Backend: Python + FastAPI
- Database: PostgreSQL + SQLAlchemy
- Object storage: MinIO / S3-compatible
- Vector database: Qdrant
- AI: Google Gemini
- Embeddings: sentence-transformers
- Authentication: JWT + bcrypt + RBAC
- Testing: pytest
- Infrastructure: Docker Compose

## Run locally

Start infrastructure:

    docker compose up -d postgres minio qdrant

Backend:

    cd backend
    python -m venv .venv

Windows PowerShell:

    .venv\Scripts\Activate.ps1

Install:

    pip install -r requirements.txt
    copy .env.example .env
    python -m alembic -c alembic.ini upgrade head

Seed demo data:

    python seed.py

Start API:

    uvicorn app.main:app --reload

Frontend:

    cd frontend
    npm install
    npm run dev

## Demo accounts

- Admin: admin@example.com / Admin@123
- Teacher: teacher@example.com / Teacher@123
- Student: student@example.com / Student@123

Change demo passwords and JWT_SECRET before real deployment.

## Main API groups

- /api/auth/*
- /api/users
- /api/departments
- /api/semesters
- /api/sections
- /api/subjects
- /api/assignments
- /api/enrollments
- /api/topics
- /api/resources/upload-v2
- /api/syllabus/compare-v2
- /api/ai/ask-v2
- /api/ai/generate
- /api/pyq/*
- /api/teaching-plan/*
- /api/quizzes/*
- /api/assignments/submit
- /api/student/*
- /api/analytics/*
- /api/audit

## Security

- JWT authentication with expiry.
- Password hashing with bcrypt.
- Role-based authorization.
- Object-level subject access checks.
- Student filtering to published resources/content.
- File size validation.
- AI rate limiting.
- Audit logs for important academic and AI actions.
- Archive/status lifecycle for resources and content.

## Notes

Database schema changes are managed with Alembic. Run `python -m alembic -c alembic.ini upgrade head` from `backend/` before starting the API on a fresh database. The initial migration uses frozen v1 model metadata; do not edit released migration files. Create and review a new migration for every later schema change.

## Production readiness

The application validates critical settings when `ENVIRONMENT=production` (or `prod`). Configure these values through the deployment platform's secret/configuration manager; do not commit a real `.env` file.

- Set a unique `JWT_SECRET` with at least 32 characters.
- Set `DATABASE_URL` to a managed or otherwise non-local database host.
- Set `CORS_ORIGINS` to the exact HTTPS frontend origin(s), separated by commas.
- Set unique `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY` values and `MINIO_SECURE=true` when the object-storage endpoint supports TLS.
- Set `MINIO_ENDPOINT`, `QDRANT_URL`, and `GEMINI_API_KEY` to the intended deployment services/configuration.
- Do not run `backend/seed.py` in production; the script is blocked when production mode is enabled.
- Terminate HTTPS at a trusted reverse proxy or hosting platform and restrict database, MinIO, and Qdrant network access to the application.

**Database migration note:** the repository now has an Alembic baseline. For an existing database that already matches the baseline schema, take a backup and verify the schema before running `python -m alembic -c alembic.ini stamp 0001_initial_schema` from `backend/`; do not run the initial `upgrade` against tables that already exist. For every subsequent schema change, generate a new revision with `python -m alembic -c alembic.ini revision --autogenerate -m "describe change"`, review the generated operations, and test both fresh installs and upgrades against disposable PostgreSQL databases. Never stamp an existing database without confirming that its schema matches the baseline.

The production configuration checks are a safety baseline, not a complete deployment certification. Verify backups/restoration, monitoring, TLS, least-privilege service credentials, and provider-specific network rules before launch.
