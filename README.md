# AI Academic Teaching and Learning System

A role-controlled academic platform connecting **Admin → Teacher → Approved Resources → AI/RAG → Student → Assessment → Progress**.

## Implemented
- JWT authentication and Admin / Teacher / Student RBAC
- Subjects, teacher assignment and student enrollment
- Syllabus topics and version records
- PDF, DOCX, PPTX and text extraction
- MinIO/S3-compatible resource storage
- Approved-resource lifecycle and grounded AI assistant
- Qdrant chunk-indexing adapter
- Gemini generation adapter with no-key deterministic fallback
- Teacher-reviewed AI content: IN_REVIEW → APPROVED → PUBLISHED
- PYQ capture, topic mapping and topic/unit weightage analysis
- Dynamic teaching-plan generation and update actions
- Quizzes, questions, student attempts and topic progress
- Student weak-topic aggregation
- Audit logging
- React + TypeScript dashboard

## Stack
React + TypeScript + Vite · FastAPI · PostgreSQL · SQLAlchemy · MinIO · Qdrant · Gemini · JWT/RBAC · pytest

## Run
```bash
docker compose up -d postgres minio qdrant
cd backend
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env
python seed.py
uvicorn app.main:app --reload
```

In another terminal:
```bash
cd frontend
npm install
npm run dev
```

API: http://localhost:8000/docs  
Frontend: http://localhost:5173  
MinIO: http://localhost:9001  
Qdrant: http://localhost:6333

## Demo accounts
- Admin: admin@example.com / Admin@123
- Teacher: teacher@example.com / Teacher@123
- Student: student@example.com / Student@123

Change demo passwords and JWT_SECRET before real deployment.
