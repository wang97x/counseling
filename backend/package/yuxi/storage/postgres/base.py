"""共享 PostgreSQL ORM 基类与 JSON 类型。"""

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()
JSON_VALUE = JSON().with_variant(JSONB, "postgresql")
