import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://logistics:logistics123@localhost:5432/logistics")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base = declarative_base()
