import os
from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Text
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime

DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "mysql+pymysql://root:@localhost:3306/sheet_score"
)

# Use pool_recycle to prevent "MySQL server has gone away" error
engine = create_engine(DATABASE_URL, pool_recycle=3600)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class AnswerKeyDB(Base):
    __tablename__ = "answer_keys"

    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(255))
    form_type = Column(String(10))
    answers_json = Column(Text)
    question_count = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

class GradingSessionDB(Base):
    __tablename__ = "grading_sessions"

    id = Column(String(50), primary_key=True, index=True)
    answer_key_id = Column(String(50), index=True)
    answer_key_name = Column(String(255))
    form_type = Column(String(10))
    average_percentage = Column(Float)
    file_count = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class GradingResultDB(Base):
    __tablename__ = "grading_results"

    id = Column(String(50), primary_key=True, index=True)
    batch_id = Column(String(50), index=True, nullable=True)
    filename = Column(String(255), nullable=True)
    answer_key_id = Column(String(50), index=True)
    score = Column(Float)
    total = Column(Integer)
    percentage = Column(Float)
    subject_code = Column(String(50), nullable=True)
    student_id = Column(String(50), nullable=True)
    details_json = Column(Text, nullable=True) # JSON dump of the answers
    image_url = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# Create tables in the database if they don't exist
try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"Failed to create tables: {e}")

# Dependency function
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
