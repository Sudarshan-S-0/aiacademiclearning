from passlib.context import CryptContext
from app.core.config import settings
from app.db.session import Base,engine,SessionLocal
from app.models.models import *

if settings.environment.strip().lower() in {"production", "prod"}:
    raise RuntimeError(
        "Demo seed data is disabled in production because it creates accounts "
        "with publicly documented demo passwords."
    )

Base.metadata.create_all(bind=engine)
pwd=CryptContext(schemes=["bcrypt"],deprecated="auto");db=SessionLocal()
try:
    users={}
    for name,email,password,role in [("System Admin","admin@example.com","Admin@123","ADMIN"),("Demo Teacher","teacher@example.com","Teacher@123","TEACHER"),("Demo Student","student@example.com","Student@123","STUDENT")]:
        u=db.query(User).filter_by(email=email).first()
        if not u:u=User(full_name=name,email=email,password_hash=pwd.hash(password),role=role);db.add(u);db.flush()
        users[role]=u
    dept=db.query(Department).filter_by(code="AIDS").first()
    if not dept:dept=Department(code="AIDS",name="Artificial Intelligence and Data Science");db.add(dept);db.flush()
    sem=db.query(Semester).filter_by(department_id=dept.id,semester_number=8).first()
    if not sem:sem=Semester(department_id=dept.id,academic_year="2026-27",semester_number=8,regulation="R2021");db.add(sem);db.flush()
    sec=db.query(Section).filter_by(semester_id=sem.id,name="A").first()
    if not sec:sec=Section(semester_id=sem.id,name="A");db.add(sec);db.flush()
    sub=db.query(Subject).filter_by(code="AIML401").first()
    if not sub:sub=Subject(semester_id=sem.id,code="AIML401",name="Applied AI Systems",description="Demo subject for the academic platform",weeks=16,hours_per_week=4,lecture_duration_minutes=60);db.add(sub);db.flush()
    if not db.query(TeacherSubject).filter_by(teacher_id=users["TEACHER"].id,subject_id=sub.id).first():db.add(TeacherSubject(teacher_id=users["TEACHER"].id,subject_id=sub.id,section_id=sec.id,academic_year="2026-27"))
    if not db.query(Enrollment).filter_by(student_id=users["STUDENT"].id,subject_id=sub.id).first():db.add(Enrollment(student_id=users["STUDENT"].id,subject_id=sub.id,section_id=sec.id,academic_year="2026-27"))
    for name,unit,order,hours in [("Introduction to AI",1,1,4),("Machine Learning Foundations",1,2,6),("Model Evaluation",2,3,4),("Responsible AI",2,4,4)]:
        if not db.query(Topic).filter_by(subject_id=sub.id,topic_name=name).first():db.add(Topic(subject_id=sub.id,unit_number=unit,topic_name=name,sequence_order=order,estimated_hours=hours))
    db.commit();print("Seed complete.")
finally:db.close()
