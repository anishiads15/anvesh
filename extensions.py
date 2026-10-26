from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session


class Database:
    """SQLAlchemy Database Manager supporting Flask application lifecycle."""

    def __init__(self):
        self.Base = declarative_base()
        self.engine = None
        self.session_factory = None
        self._session = None

    def init_app(self, app):
        db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "sqlite:///instance/aicte_monitoring.db")
        echo = app.config.get("SQLALCHEMY_ECHO", False)

        # Connect args for SQLite to ensure proper timeout and multithread support
        connect_args = {}
        if db_uri.startswith("sqlite"):
            connect_args = {"check_same_thread": False, "timeout": 30}

        self.engine = create_engine(db_uri, echo=echo, connect_args=connect_args)

        # Enforce foreign keys on SQLite connections
        if db_uri.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self._session = scoped_session(self.session_factory)

        @app.teardown_appcontext
        def shutdown_session(exception=None):
            if self._session is not None:
                self._session.remove()

    @property
    def session(self):
        if self._session is None:
            raise RuntimeError("Database not initialized with init_app")
        return self._session

    def create_all(self):
        self.Base.metadata.create_all(bind=self.engine)

    def drop_all(self):
        self.Base.metadata.drop_all(bind=self.engine)


db = Database()
