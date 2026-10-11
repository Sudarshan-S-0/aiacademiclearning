from datetime import datetime
from sqlalchemy import String, Text, Integer, Float, Boolean, ForeignKey, DateTime, func, UniqueConstraint, Index, column
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base

class User(Base):
    __tablename__="users"
    __table_args__ = (
        Index(
            "uq_users_email_normalized",
            func.lower(func.trim(column("email"))),
            unique=True,
        ),
    )
    id:Mapped[int]=mapped_column(primary_key=True)
    full_name:Mapped[str]=mapped_column(String(120))
    email:Mapped[str]=mapped_column(String(255),unique=True,index=True)
    password_hash:Mapped[str|None]=mapped_column(String(255),nullable=True)
    role:Mapped[str]=mapped_column(String(20),index=True)
    is_active:Mapped[bool]=mapped_column(Boolean,default=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
class Department(Base):
    __tablename__="departments"
    id:Mapped[int]=mapped_column(primary_key=True)
    code:Mapped[str]=mapped_column(String(20),unique=True)
    name:Mapped[str]=mapped_column(String(150),unique=True)
class Semester(Base):
    __tablename__="semesters"
    __table_args__ = (
        Index(
            "uq_semester_department_year_number",
            "department_id",
            func.lower(func.trim(column("academic_year"))),
            "semester_number",
            unique=True,
        ),
    )
    id:Mapped[int]=mapped_column(primary_key=True)
    department_id:Mapped[int]=mapped_column(ForeignKey("departments.id"))
    academic_year:Mapped[str]=mapped_column(String(20))
    semester_number:Mapped[int]=mapped_column(Integer)
    regulation:Mapped[str|None]=mapped_column(String(40),nullable=True)
class Section(Base):
    __tablename__="sections"
    __table_args__ = (
        Index(
            "uq_section_semester_name_normalized",
            "semester_id",
            func.lower(func.trim(column("name"))),
            unique=True,
        ),
    )
    id:Mapped[int]=mapped_column(primary_key=True)
    semester_id:Mapped[int]=mapped_column(ForeignKey("semesters.id"))
    name:Mapped[str]=mapped_column(String(30))
class Subject(Base):
    __tablename__="subjects"
    __table_args__ = (
        Index("uq_subject_semester_code_normalized", "semester_id", func.lower(func.trim(column("code"))), unique=True),
    )
    id:Mapped[int]=mapped_column(primary_key=True)
    semester_id:Mapped[int]=mapped_column(ForeignKey("semesters.id"))
    code:Mapped[str]=mapped_column(String(30),index=True)
    name:Mapped[str]=mapped_column(String(200))
    description:Mapped[str|None]=mapped_column(Text,nullable=True)
    weeks:Mapped[int]=mapped_column(Integer,default=16)
    hours_per_week:Mapped[int]=mapped_column(Integer,default=4)
    lecture_duration_minutes:Mapped[int]=mapped_column(Integer,default=60)
    status:Mapped[str]=mapped_column(String(20),default="ACTIVE")
class TeacherSubject(Base):
    __tablename__="teacher_subject_assignments"
    id:Mapped[int]=mapped_column(primary_key=True)
    teacher_id:Mapped[int]=mapped_column(ForeignKey("users.id"))
    subject_id:Mapped[int]=mapped_column(ForeignKey("subjects.id"))
    section_id:Mapped[int|None]=mapped_column(ForeignKey("sections.id"),nullable=True)
    academic_year:Mapped[str]=mapped_column(String(20))
    __table_args__=(
        UniqueConstraint("teacher_id","subject_id","section_id","academic_year"),
        Index(
            "uq_teacher_assignment_normalized",
            "teacher_id",
            "subject_id",
            func.coalesce(column("section_id"), 0),
            func.lower(func.trim(column("academic_year"))),
            unique=True,
        ),
    )
class Enrollment(Base):
    __tablename__="student_enrollments"
    id:Mapped[int]=mapped_column(primary_key=True)
    student_id:Mapped[int]=mapped_column(ForeignKey("users.id"))
    subject_id:Mapped[int]=mapped_column(ForeignKey("subjects.id"))
    section_id:Mapped[int|None]=mapped_column(ForeignKey("sections.id"),nullable=True)
    academic_year:Mapped[str]=mapped_column(String(20))
    __table_args__=(
        UniqueConstraint("student_id","subject_id","academic_year"),
        Index(
            "uq_enrollment_normalized_year",
            "student_id",
            "subject_id",
            func.lower(func.trim(column("academic_year"))),
            unique=True,
        ),
    )
class Resource(Base):
    __tablename__="resources"
    id:Mapped[int]=mapped_column(primary_key=True)
    subject_id:Mapped[int]=mapped_column(ForeignKey("subjects.id"))
    uploaded_by:Mapped[int]=mapped_column(ForeignKey("users.id"))
    title:Mapped[str]=mapped_column(String(255))
    resource_type:Mapped[str]=mapped_column(String(40))
    storage_key:Mapped[str|None]=mapped_column(String(500),nullable=True)
    status:Mapped[str]=mapped_column(String(30),default="DRAFT")
    version:Mapped[int]=mapped_column(Integer,default=1)
    extracted_text:Mapped[str|None]=mapped_column(Text,nullable=True)
    page_count:Mapped[int]=mapped_column(Integer,default=0)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
    parent_resource_id:Mapped[int|None]=mapped_column(ForeignKey("resources.id"),nullable=True)
class SyllabusVersion(Base):
    __tablename__="syllabus_versions"
    id:Mapped[int]=mapped_column(primary_key=True)
    subject_id:Mapped[int]=mapped_column(ForeignKey("subjects.id"))
    version:Mapped[int]=mapped_column(Integer)
    source_resource_id:Mapped[int|None]=mapped_column(ForeignKey("resources.id"),nullable=True)
    status:Mapped[str]=mapped_column(String(20),default="ACTIVE")
    summary:Mapped[str|None]=mapped_column(Text,nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
class Topic(Base):
    __tablename__="syllabus_topics"
    __table_args__ = (
        Index(
            "uq_topic_subject_name_normalized",
            "subject_id",
            func.lower(func.trim(column("topic_name"))),
            unique=True,
        ),
    )
    id:Mapped[int]=mapped_column(primary_key=True)
    subject_id:Mapped[int]=mapped_column(ForeignKey("subjects.id"))
    unit_number:Mapped[int]=mapped_column(Integer)
    topic_name:Mapped[str]=mapped_column(String(255))
    sequence_order:Mapped[int]=mapped_column(Integer)
    estimated_hours:Mapped[float]=mapped_column(Float,default=1)
    version:Mapped[int]=mapped_column(Integer,default=1)
    status:Mapped[str]=mapped_column(String(20),default="ACTIVE")
    completed:Mapped[bool]=mapped_column(Boolean,default=False)
class PYQQuestion(Base):
    __tablename__="pyq_questions"
    id:Mapped[int]=mapped_column(primary_key=True)
    subject_id:Mapped[int]=mapped_column(ForeignKey("subjects.id"))
    resource_id:Mapped[int|None]=mapped_column(ForeignKey("resources.id"),nullable=True)
    year:Mapped[int|None]=mapped_column(Integer,nullable=True)
    question_no:Mapped[str|None]=mapped_column(String(30),nullable=True)
    question_text:Mapped[str]=mapped_column(Text)
    marks:Mapped[float]=mapped_column(Float,default=1)
    topic_id:Mapped[int|None]=mapped_column(ForeignKey("syllabus_topics.id"),nullable=True)
    unit_number:Mapped[int|None]=mapped_column(Integer,nullable=True)
    frequency_key:Mapped[str|None]=mapped_column(String(255),nullable=True)
    mapping_confidence:Mapped[float|None]=mapped_column(Float,nullable=True)
class TopicWeightage(Base):
    __tablename__="topic_weightage"
    id:Mapped[int]=mapped_column(primary_key=True)
    subject_id:Mapped[int]=mapped_column(ForeignKey("subjects.id"))
    topic_id:Mapped[int]=mapped_column(ForeignKey("syllabus_topics.id"))
    question_count:Mapped[int]=mapped_column(Integer,default=0)
    total_marks:Mapped[float]=mapped_column(Float,default=0)
    percentage:Mapped[float]=mapped_column(Float,default=0)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now())
class TeachingPlan(Base):
    __tablename__="teaching_plan_items"
    id:Mapped[int]=mapped_column(primary_key=True)
    subject_id:Mapped[int]=mapped_column(ForeignKey("subjects.id"))
    topic_id:Mapped[int]=mapped_column(ForeignKey("syllabus_topics.id"))
    planned_week:Mapped[int]=mapped_column(Integer)
    planned_hours:Mapped[float]=mapped_column(Float)
    status:Mapped[str]=mapped_column(String(20),default="PLANNED")
    teacher_note:Mapped[str|None]=mapped_column(Text,nullable=True)
    actual_hours:Mapped[float]=mapped_column(Float,default=0)
class Content(Base):
    __tablename__="content_items"
    id:Mapped[int]=mapped_column(primary_key=True)
    subject_id:Mapped[int]=mapped_column(ForeignKey("subjects.id"))
    topic_id:Mapped[int|None]=mapped_column(ForeignKey("syllabus_topics.id"),nullable=True)
    title:Mapped[str]=mapped_column(String(255))
    content_type:Mapped[str]=mapped_column(String(40))
    body:Mapped[str]=mapped_column(Text)
    status:Mapped[str]=mapped_column(String(30),default="DRAFT")
    source_reference:Mapped[str|None]=mapped_column(String(1000),nullable=True)
    version:Mapped[int]=mapped_column(Integer,default=1)
    generated_by_ai:Mapped[bool]=mapped_column(Boolean,default=False)
    created_by:Mapped[int|None]=mapped_column(ForeignKey("users.id"),nullable=True)
class Quiz(Base):
    __tablename__="quizzes"
    id:Mapped[int]=mapped_column(primary_key=True)
    subject_id:Mapped[int]=mapped_column(ForeignKey("subjects.id"))
    title:Mapped[str]=mapped_column(String(255))
    status:Mapped[str]=mapped_column(String(30),default="DRAFT")
    duration_minutes:Mapped[int]=mapped_column(Integer,default=30)
class QuizQuestion(Base):
    __tablename__="quiz_questions"
    id:Mapped[int]=mapped_column(primary_key=True)
    quiz_id:Mapped[int]=mapped_column(ForeignKey("quizzes.id"))
    topic_id:Mapped[int|None]=mapped_column(ForeignKey("syllabus_topics.id"),nullable=True)
    question_text:Mapped[str]=mapped_column(Text)
    marks:Mapped[int]=mapped_column(Integer,default=1)
    correct_answer:Mapped[str]=mapped_column(String(255))
    options_json:Mapped[str|None]=mapped_column(Text,nullable=True)
class Attempt(Base):
    __tablename__="quiz_attempts"
    id:Mapped[int]=mapped_column(primary_key=True)
    quiz_id:Mapped[int]=mapped_column(ForeignKey("quizzes.id"))
    student_id:Mapped[int]=mapped_column(ForeignKey("users.id"))
    score:Mapped[float]=mapped_column(Float,default=0)
    total:Mapped[float]=mapped_column(Float,default=0)
    completed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
class AttemptAnswer(Base):
    __tablename__="attempt_answers"
    id:Mapped[int]=mapped_column(primary_key=True)
    attempt_id:Mapped[int]=mapped_column(ForeignKey("quiz_attempts.id"))
    question_id:Mapped[int]=mapped_column(ForeignKey("quiz_questions.id"))
    answer:Mapped[str]=mapped_column(Text)
    is_correct:Mapped[bool]=mapped_column(Boolean,default=False)
    marks_awarded:Mapped[float]=mapped_column(Float,default=0)
class Progress(Base):
    __tablename__="student_progress"
    id:Mapped[int]=mapped_column(primary_key=True)
    student_id:Mapped[int]=mapped_column(ForeignKey("users.id"))
    subject_id:Mapped[int]=mapped_column(ForeignKey("subjects.id"))
    topic_id:Mapped[int|None]=mapped_column(ForeignKey("syllabus_topics.id"),nullable=True)
    assignment_submission_id:Mapped[int|None]=mapped_column(ForeignKey("assignment_submissions.id"),nullable=True,index=True)
    activity_type:Mapped[str]=mapped_column(String(40))
    score:Mapped[float]=mapped_column(Float,default=0)
    max_score:Mapped[float]=mapped_column(Float,default=0)
    completed:Mapped[bool]=mapped_column(Boolean,default=False)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now())
class AuditLog(Base):
    __tablename__="audit_logs"
    id:Mapped[int]=mapped_column(primary_key=True)
    actor_id:Mapped[int|None]=mapped_column(ForeignKey("users.id"),nullable=True)
    action:Mapped[str]=mapped_column(String(80))
    entity_type:Mapped[str]=mapped_column(String(80))
    entity_id:Mapped[int|None]=mapped_column(Integer,nullable=True)
    details:Mapped[str|None]=mapped_column(Text,nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())


class ResourceChunk(Base):
    __tablename__="resource_chunks"
    id:Mapped[int]=mapped_column(primary_key=True)
    resource_id:Mapped[int]=mapped_column(ForeignKey("resources.id"))
    subject_id:Mapped[int]=mapped_column(ForeignKey("subjects.id"))
    chunk_index:Mapped[int]=mapped_column(Integer)
    text:Mapped[str]=mapped_column(Text)
    page_number:Mapped[int|None]=mapped_column(Integer,nullable=True)
    section:Mapped[str|None]=mapped_column(String(255),nullable=True)
    qdrant_point_id:Mapped[str|None]=mapped_column(String(100),nullable=True)

class SyllabusChange(Base):
    __tablename__="syllabus_changes"
    id:Mapped[int]=mapped_column(primary_key=True)
    subject_id:Mapped[int]=mapped_column(ForeignKey("subjects.id"))
    from_version:Mapped[int]=mapped_column(Integer)
    to_version:Mapped[int]=mapped_column(Integer)
    change_type:Mapped[str]=mapped_column(String(20))
    old_topic:Mapped[str|None]=mapped_column(String(255),nullable=True)
    new_topic:Mapped[str|None]=mapped_column(String(255),nullable=True)
    details:Mapped[str|None]=mapped_column(Text,nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())

class ContentSource(Base):
    __tablename__="content_sources"
    id:Mapped[int]=mapped_column(primary_key=True)
    content_id:Mapped[int]=mapped_column(ForeignKey("content_items.id"))
    resource_id:Mapped[int]=mapped_column(ForeignKey("resources.id"))
    chunk_id:Mapped[int|None]=mapped_column(ForeignKey("resource_chunks.id"),nullable=True)
    citation:Mapped[str]=mapped_column(String(1000))

class GeneratedArtifact(Base):
    __tablename__="generated_artifacts"
    id:Mapped[int]=mapped_column(primary_key=True)
    subject_id:Mapped[int]=mapped_column(ForeignKey("subjects.id"))
    content_id:Mapped[int|None]=mapped_column(ForeignKey("content_items.id"),nullable=True)
    title:Mapped[str]=mapped_column(String(255))
    artifact_type:Mapped[str]=mapped_column(String(40))
    storage_key:Mapped[str]=mapped_column(String(500))
    created_by:Mapped[int]=mapped_column(ForeignKey("users.id"))
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())

class AssignmentSubmission(Base):
    __tablename__="assignment_submissions"
    __table_args__ = (
        UniqueConstraint("content_id", "student_id", name="uq_assignment_submission_content_student"),
    )
    id:Mapped[int]=mapped_column(primary_key=True)
    content_id:Mapped[int]=mapped_column(ForeignKey("content_items.id"))
    student_id:Mapped[int]=mapped_column(ForeignKey("users.id"))
    answer_text:Mapped[str]=mapped_column(Text)
    score:Mapped[float|None]=mapped_column(Float,nullable=True)
    feedback:Mapped[str|None]=mapped_column(Text,nullable=True)
    submitted_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
