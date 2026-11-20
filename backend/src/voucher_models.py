from sqlalchemy import String, Integer, ForeignKey, Text, CheckConstraint, Double
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base
class ScoreVoucher(Base):
    __tablename__='score_vouchers'
    __table_args__=(CheckConstraint("state in ('pending','scoring','ready','failed')"),)
    id:Mapped[int]=mapped_column(primary_key=True)
    claim_id:Mapped[int]=mapped_column(ForeignKey('claims.id'),unique=True)
    attempt:Mapped[int]=mapped_column(Integer,default=0)
    state:Mapped[str]=mapped_column(String(20),default='pending')
    risk:Mapped[float|None]=mapped_column(Double,nullable=True)
    inputs_json:Mapped[str]=mapped_column(Text,default='')
    model_json:Mapped[str]=mapped_column(Text,default='')
    metrics_json:Mapped[str]=mapped_column(Text,default='')
    digest:Mapped[str]=mapped_column(String(64),default='')
    error:Mapped[str]=mapped_column(Text,default='')
    updated_at:Mapped[str]=mapped_column(String(40),default='')
