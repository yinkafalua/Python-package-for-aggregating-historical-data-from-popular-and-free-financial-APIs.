"""SQLAlchemy interfaces for fundamental features."""

from functools import cache

from sqlalchemy import Column, Float, MetaData, String, Table, create_engine, func
from sqlalchemy.engine import Engine

from .. import backend


def _define_db(
    url: str = backend.database_url,
) -> tuple[tuple[Engine, MetaData], tuple[Table, ...]]:
    """Utility method for defining the SQLAlchemy elements.

    Used for the main SQL tables and for creating test
    databases.

    Args:
        url: SQLAlchemy database URL.
        path: Path to database file.

    Returns:
        The engine, metadata, and tables associated with
        the database definition.

    """
    engine = backend.engine if url == backend.engine.url else create_engine(url)
    metadata = MetaData()
    fundamental_features = Table(
        "fundamental_features",
        metadata,
        Column("ticker", String, primary_key=True, doc="Unique company ticker."),
        Column("date", String, primary_key=True, doc="Filing and stock price dates."),
        Column("name", String, primary_key=True, doc="Feature name."),
        Column("value", Float, doc="Feature value."),
    )
    return (engine, metadata), (fundamental_features,)


(engine, metadata), (fundamental_features,) = _define_db()


@cache
def get_id_set() -> set[str]:
    """Get all unique tickers in the feature SQL tables."""
    with engine.begin() as conn:
        tickers = set()
        for ticker in conn.execute(
            fundamental_features.select().distinct(fundamental_features.c.ticker)
        ):
            (ticker,) = ticker
            tickers.add(str(ticker))
    return tickers


@cache
def get_tickers_with_at_least(lb: int, /) -> set[str]:
    """Get all unique tickers in the feature SQL tables that have a minmum
    number of rows.

    """
    with engine.begin() as conn:
        tickers = set()
        for ticker in conn.execute(
            fundamental_features.select()
            .distinct(fundamental_features.c.ticker)
            .group_by(fundamental_features.c.ticker)
            .having(func.count(fundamental_features.c.date) >= lb)
        ):
            (ticker,) = ticker
            tickers.add(str(ticker))
    return tickers