"""Features from yfinance sources."""

import pandas as pd
from sqlalchemy.engine import Engine

from .. import utils
from . import api, sql, store


class _DailyFeatures:
    """Methods for gathering daily stock data from Yahoo! finance."""

    #: Columns within this feature set.
    columns = ("price", "open", "high", "low", "close", "volume")

    @classmethod
    def _normalize(cls, df: pd.DataFrame, /) -> pd.DataFrame:
        """Normalize daily features columns."""
        df = (
            df.drop(columns=["ticker"])
            .fillna(method="ffill")
            .dropna()
            .set_index("date")
            .astype(float)
            .sort_index()
        )
        df["price"] = df["close"]
        df = utils.quantile_clip(df)
        pct_change_columns = ["open", "high", "low", "close", "volume"]
        df[pct_change_columns] = df[pct_change_columns].apply(utils.safe_pct_change)
        df.columns = df.columns.rename(None)
        return df.dropna()

    @classmethod
    def from_api(
        cls, ticker: str, /, *, start: None | str = None, end: None | str = None
    ) -> pd.DataFrame:
        """Get daily features directly from the yfinance API.

        Args:
            ticker: Company ticker.
            start: The start date of the stock history.
                Defaults to the first recorded date.
            end: The end date of the stock history.
                Defaults to the last recorded date.

        Returns:
            Daily stock price dataframe. Sorted by date.

        """
        df = api.get(ticker, start=start, end=end)
        return cls._normalize(df)

    @classmethod
    def from_sql(
        cls,
        ticker: str,
        /,
        *,
        start: None | str = None,
        end: None | str = None,
        engine: Engine = sql.engine,
    ) -> pd.DataFrame:
        """Get daily features from local SQL tables.

        Args:
            ticker: Company ticker.
            start: The start date of the stock history.
                Defaults to the first recorded date.
            end: The end date of the stock history.
                Defaults to the last recorded date.
            engine: Raw store database engine.

        Returns:
            Daily stock price dataframe. Sorted by date.

        """
        table = sql.prices
        with engine.begin() as conn:
            stmt = table.c.ticker == ticker
            if start:
                stmt &= table.c.date >= start
            if end:
                stmt &= table.c.date <= end
            df = pd.DataFrame(conn.execute(table.select().where(stmt)))
        return cls._normalize(df)

    @classmethod
    def from_store(
        cls,
        ticker: str,
        /,
        *,
        start: None | str = None,
        end: None | str = None,
        engine: Engine = store.engine,
    ) -> pd.DataFrame:
        """Get features from the feature-dedicated local SQL tables.

        This is the preferred method for accessing features for
        offline analysis (assuming data in the local SQL tables
        is current).

        Args:
            ticker: Company ticker.
            start: The start date of the observation period.
                Defaults to the first recorded date.
            end: The end date of the observation period.
                Defaults to the last recorded date.
            engine: Feature store database engine.

        Returns:
            Daily stock price dataframe. Sorted by date.

        """
        table = store.daily_features
        with engine.begin() as conn:
            stmt = table.c.ticker == ticker
            if start:
                stmt &= table.c.date >= start
            if end:
                stmt &= table.c.date <= end
            df = pd.DataFrame(conn.execute(table.select().where(stmt)))
        df = df.pivot(index="date", values="value", columns="name").sort_index()
        df.columns = df.columns.rename(None)
        df = df[list(cls.columns)]
        return df

    @classmethod
    def to_store(
        cls,
        ticker: str,
        df: pd.DataFrame,
        /,
        *,
        engine: Engine = store.engine,
    ) -> int:
        """Write the dataframe to the feature store for `ticker`.

        Does the necessary handling to transform columns to
        prepare the dataframe to be written to a dynamically-defined
        local SQL table.

        Args:
            ticker: Company ticker.
            df: Dataframe to store completely as rows in a local SQL
                table.
            engine: Feature store database engine.

        Returns:
            Number of rows written to the SQL table.

        """
        df = df.reset_index(names="date")
        df = df.melt("date", var_name="name", value_name="value")
        df["ticker"] = ticker
        table = store.daily_features
        with engine.begin() as conn:
            conn.execute(table.insert(), df.to_dict(orient="records"))  # type: ignore[arg-type]
        return len(df.index)


#: Public-facing API.
daily_features = _DailyFeatures()
