"""CLI and tools for yfinance."""

import logging
import multiprocessing as mp

import click
import pandas as pd
from sqlalchemy.exc import IntegrityError
from tqdm import tqdm

from .. import backend, indices
from . import api as _api
from . import features as _features
from . import sql as _sql

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


def _install_raw_data(ticker: str, /) -> tuple[bool, int]:
    """Helper for getting raw daily Yahoo! Finance data.

    Args:
        ticker: Ticker to aggregate data for.

    Returns:
        The ticker and the raw data dataframe.

    """
    errored = False
    total_rows = 0
    with backend.engine.begin() as conn:
        try:
            df = _api.get(ticker, interval="1d", period="max")
            rowcount = len(df.index)
            if not rowcount:
                logger.debug(f"Skipping {ticker} due to missing data")
                return True, 0

            conn.execute(_sql.prices.insert(), df.to_dict(orient="records"))  # type: ignore[arg-type]
            total_rows += rowcount
        except (IntegrityError, pd.errors.EmptyDataError) as e:
            logger.debug(f"Skipping {ticker} due to {e}")
            return True, total_rows
    logger.debug(f"{total_rows} total rows written for {ticker}")
    return errored, total_rows


@click.group(help="Yahoo! finance tools.")
def entry_point() -> None:
    ...


@entry_point.command(
    help=(
        "Drop and recreate tables, and install the recommended "
        "tables into the SQL database."
    ),
)
@click.option(
    "--raw",
    "-r",
    is_flag=True,
    default=False,
    help="Whether to install raw Yahoo! Finance historical price data.",
)
@click.option(
    "--feature",
    "-f",
    type=click.Choice(["daily"]),
    multiple=True,
    help=(
        "Feature tables to install. This requires raw data to be "
        "installed beforehand using the `--raw` flag or for the "
        "`--raw` flag to be set when this option is provided."
    ),
)
@click.option(
    "--all",
    "-a",
    "all_",
    is_flag=True,
    default=False,
    help="Whether to install all defined tables (including all feature tables).",
)
@click.option(
    "--processes",
    "-n",
    type=int,
    default=mp.cpu_count() - 1,
    help=("Number of background processes to use for installing feature data. "),
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Sets the log level to DEBUG to show installation errors for each ticker.",
)
def install(
    raw: bool = False,
    feature: list[str] = [],
    all_: bool = False,
    processes: int = mp.cpu_count() - 1,
    verbose: bool = False,
) -> int:
    if verbose:
        logger.setLevel(logging.DEBUG)

    total_rows = 0
    if all_ or raw:
        _sql.prices.drop(backend.engine, checkfirst=True)
        _sql.prices.create(backend.engine)

        tickers = indices.api.get_ticker_set()
        total_errors = 0
        with tqdm(
            total=len(tickers),
            desc="Installing raw daily Yahoo! Finance data",
            position=0,
            leave=True,
            disable=verbose,
        ) as pbar:
            for ticker in tickers:
                errored, rowcount = _install_raw_data(ticker)
                total_errors += errored
                total_rows += rowcount
                pbar.update()

        logger.info(
            f"{pbar.total - total_errors}/{pbar.total} company datasets "
            "sucessfully written"
        )

    features = set()
    if all_:
        features = {"daily"}
    elif feature:
        features = set(feature)

    if "daily" in features:
        total_rows += _features.daily.install(processes=processes)

    if all_ or features or raw:
        logger.info(f"{total_rows} total rows written")
    else:
        logger.info(
            "Skipping installation because no installation options are provided"
        )
    return total_rows
