"""Features from yfinance sources."""

import multiprocessing as mp
from functools import cache, partial

import pandas as pd
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from tqdm import tqdm

from .. import backend, utils
from . import api, sql


def _install_daily_features(ticker: str, /) -> tuple[str, pd.DataFrame]:
    """Helper for getting daily Yahoo! Finance data in a
    multiprocessing pool.

    Args:
        ticker: Ticker to create features for.

    Returns:
        The ticker and the returned feature dataframe.

    """
    df = DailyFeatures.from_raw(ticker)
    return ticker, df


class DailyFeatures:
    """Methods for gathering daily stock data from Yahoo! finance."""

    #: Columns within this feature set.
    columns = (
        "price",
        "open_pct_change",
        "high_pct_change",
        "low_pct_change",
        "close_pct_change",
        "volume_pct_change",
    )

    #: Columns that're replaced with their respective percent changes.
    pct_change_columns = ("open", "high", "low", "close", "volume")

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
        pct_change_columns = [f"{col}_pct_change" for col in cls.pct_change_columns]
        df[pct_change_columns] = df[list(cls.pct_change_columns)].apply(
            utils.safe_pct_change
        )
        df.columns = df.columns.rename(None)
        df = df[list(cls.columns)]
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
    def from_raw(
        cls,
        ticker: str,
        /,
        *,
        start: str = "0000-00-00",
        end: str = "9999-99-99",
        engine: Engine = backend.engine,
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
        with engine.begin() as conn:
            df = pd.DataFrame(
                conn.execute(
                    sql.prices.select().where(
                        sql.prices.c.ticker == ticker,
                        sql.prices.c.date >= start,
                        sql.prices.c.date <= end,
                    )
                )
            )
        return cls._normalize(df)

    @classmethod
    def from_refined(
        cls,
        ticker: str,
        /,
        *,
        start: str = "0000-00-00",
        end: str = "9999-99-99",
        engine: Engine = backend.engine,
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
        with engine.begin() as conn:
            df = pd.DataFrame(
                conn.execute(
                    sql.daily_features.select().where(
                        sql.daily_features.c.ticker == ticker,
                        sql.daily_features.c.date >= start,
                        sql.daily_features.c.date <= end,
                    )
                )
            )
        df = df.pivot(index="date", columns="name", values="value").sort_index()
        df.columns = df.columns.rename(None)
        df = df[list(cls.columns)]
        return df

    #: The candidate set is just the raw SQL ticker set.
    get_candidate_id_set = sql.get_id_set

    @classmethod
    @cache
    def get_id_set(
        cls,
        lb: int = 1,
    ) -> set[str]:
        """Get all unique tickers in the feature's SQL table.

        Args:
            lb: Minimum number of rows required to include a ticker in the
                returned set.

        Returns:
            All unique tickers that contain all the columns for creating
            daily features that also have at least `lb` rows.

        """
        with backend.engine.begin() as conn:
            tickers = set()
            for row in conn.execute(
                sa.select(sql.daily_features.c.ticker)
                .distinct()
                .group_by(sql.daily_features.c.ticker)
                .having(
                    *[
                        sa.func.count(sql.daily_features.c.name == col) >= lb
                        for col in cls.columns
                    ]
                )
            ):
                (ticker,) = row
                tickers.add(str(ticker))
        return tickers

    @classmethod
    def install(cls, *, processes: int = mp.cpu_count() - 1) -> int:
        """Drop the feature's table, create a new one, and insert data
        transformed from another raw SQL table.

        Args:
            processes: Number of background processes to use for installation.

        Returns:
            Number of rows written to the feature's SQL table.

        """
        sql.daily_features.drop(backend.engine, checkfirst=True)
        sql.daily_features.create(backend.engine)

        tickers = cls.get_candidate_id_set()
        total_rows = 0
        with (
            tqdm(
                total=len(tickers),
                desc="Installing daily Yahoo! Finance features",
                position=0,
                leave=True,
            ) as pbar,
            mp.Pool(
                processes=processes,
                initializer=partial(backend.engine.dispose, close=False),
            ) as pool,
        ):
            for ticker, df in pool.imap_unordered(_install_daily_features, tickers):
                rowcount = len(df.index)
                if rowcount:
                    cls.to_refined(ticker, df)
                total_rows += rowcount
                pbar.update()
        return total_rows

    @classmethod
    def to_refined(
        cls,
        ticker: str,
        df: pd.DataFrame,
        /,
        *,
        engine: Engine = backend.engine,
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
        with engine.begin() as conn:
            conn.execute(sql.daily_features.insert(), df.to_dict(orient="records"))  # type: ignore[arg-type]
        return len(df.index)


#: Public-facing API.
daily = DailyFeatures()