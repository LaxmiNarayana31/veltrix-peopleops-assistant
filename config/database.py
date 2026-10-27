from contextlib import contextmanager
import logging
import sqlite3
from typing import Generator, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.exceptions.custom_exceptions import AppException, DatabaseException
from config.app_config import DB_PATH

logger = logging.getLogger(__name__)

# SQLite connection pragmas
PRAGMA_FOREIGN_KEYS = "PRAGMA foreign_keys = ON;"
SQL_BEGIN_IMMEDIATE = "BEGIN IMMEDIATE;"


class Base(DeclarativeBase):
    """Base declarative class for all SQLite database models."""
    pass


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Enforce foreign key constraints on SQLite connections."""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception as exc:
        logger.warning("Could not set SQLite PRAGMA foreign_keys: %s", exc)


class DatabaseManager:
    """Manages SQLite connections, SQLAlchemy sessions, transactions, and schema initialization."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initialize database manager with database path and SQLAlchemy engine."""
        self.db_path = db_path or DB_PATH
        self._engine: Optional[Engine] = None
        self._session_factory: Optional[sessionmaker] = None

    @property
    def engine(self) -> Engine:
        """Return lazily initialized SQLAlchemy engine."""
        if self._engine is None:
            self._engine = create_engine(
                f"sqlite:///{self.db_path}",
                connect_args={"check_same_thread": False},
            )
        return self._engine

    @property
    def session_factory(self) -> sessionmaker:
        """Return lazily initialized SQLAlchemy sessionmaker."""
        if self._session_factory is None:
            self._session_factory = sessionmaker(
                bind=self.engine,
                autoflush=False,
                expire_on_commit=False,
            )
        return self._session_factory

    def get_session(self) -> Session:
        """Create and return a new SQLAlchemy ORM Session."""
        try:
            return self.session_factory()
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed creating SQLAlchemy session")
            raise DatabaseException("Could not open database session") from exc

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """Context manager providing an SQLAlchemy ORM Session with automatic commit/rollback."""
        session = self.get_session()
        try:
            yield session
            session.commit()
        except AppException:
            session.rollback()
            raise
        except Exception as exc:
            session.rollback()
            logger.exception("Database session error; transaction rolled back")
            raise DatabaseException("Database transaction failed") from exc
        finally:
            session.close()

    def get_connection(self) -> sqlite3.Connection:
        """Create and configure a new SQLite connection with foreign keys enabled."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute(PRAGMA_FOREIGN_KEYS)
            return conn
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed to establish SQLite connection")
            raise DatabaseException("Could not connect to database") from exc

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager providing transactional access with BEGIN IMMEDIATE."""
        conn = self.get_connection()
        try:
            conn.execute(SQL_BEGIN_IMMEDIATE)
            yield conn
            conn.commit()
        except AppException:
            conn.rollback()
            raise
        except Exception as exc:
            conn.rollback()
            logger.exception("Database transaction failed and was rolled back")
            raise DatabaseException("Database transaction failed") from exc
        finally:
            conn.close()

    def init_database(self) -> None:
        """Create all application tables and indexes using SQLAlchemy model metadata."""
        try:
            # Ensure all models are imported so Base.metadata is fully registered
            import app.models.employee_model  # noqa: F401
            import app.models.holiday_model  # noqa: F401
            import app.models.ingestion_meta_model  # noqa: F401
            import app.models.leave_model  # noqa: F401

            Base.metadata.create_all(bind=self.engine)
            logger.info("All application database tables initialized successfully via SQLAlchemy metadata")
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Failed to initialize database tables")
            raise DatabaseException("Could not initialize database tables") from exc

    def init_extra_tables(self) -> None:
        """Backward-compatible alias for init_database."""
        self.init_database()


# Module-level factory functions
_db_manager: Optional[DatabaseManager] = None


def get_db_manager(db_path: Optional[str] = None) -> DatabaseManager:
    """Return singleton DatabaseManager instance, or an instance for the specified path."""
    global _db_manager
    if db_path is not None:
        return DatabaseManager(db_path=db_path)
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Convenience context manager providing an SQLAlchemy ORM Session."""
    with get_db_manager().session_scope() as session:
        yield session


def get_db_connection() -> sqlite3.Connection:
    """Convenience factory for a single connection."""
    return get_db_manager().get_connection()


@contextmanager
def db_transaction() -> Generator[sqlite3.Connection, None, None]:
    """Convenience context manager for transactions."""
    with get_db_manager().transaction() as conn:
        yield conn


def init_database(db_path: Optional[str] = None) -> None:
    """Initialize all application tables on the configured or specified database."""
    get_db_manager(db_path).init_database()
