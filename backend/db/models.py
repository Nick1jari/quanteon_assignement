from sqlalchemy import Column, String, Integer, Text, DateTime, Boolean, JSON
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime
import uuid


class Base(DeclarativeBase):
    pass


class DeidentificationRecord(Base):
    __tablename__ = "deidentification_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    original_text = Column(Text, nullable=False)
    redacted_text = Column(Text, nullable=False)
    phi_entities = Column(JSON, nullable=False, default=list)
    phi_summary = Column(JSON, nullable=False, default=dict)
    phi_count = Column(Integer, default=0)
    ocr_used = Column(Boolean, default=False)
    processing_time_ms = Column(Integer, default=0)
    mode = Column(String, default="synthetic")  # 'synthetic' or 'placeholder'
