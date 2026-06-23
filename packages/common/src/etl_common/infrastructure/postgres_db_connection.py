import logging

from sqlalchemy import Connection, create_engine
from sqlalchemy.engine import Engine

from ..core.base import Base
from ..core.singleton_meta import SingletonMeta

_logger = logging.getLogger(__name__)


class PostgresDBConnection(metaclass=SingletonMeta):
    """Singleton that owns a SQLAlchemy engine and active connection to Postgres."""

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
    ) -> None:
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.engine: Engine = create_engine(
            f"postgresql+psycopg2://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )
        self.connection: Connection = self.engine.connect()

    def create_tables(self) -> None:
        Base.metadata.create_all(self.engine)
