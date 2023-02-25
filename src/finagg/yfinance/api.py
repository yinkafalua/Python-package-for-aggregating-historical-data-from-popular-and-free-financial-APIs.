"""Simple wrappers for `yfinance.Ticker`."""

import pandas as pd
import yfinance as yf


def get(
    ticker: str,
    /,
    *,
    start: None | str = None,
    end: None | str = None,
    interval: str = "1d",
    period: str = "max",
    debug: bool = False,
) -> pd.DataFrame:
    """Get a ticker's stock price history.

    Does a simple transform on yfinance's ticker API
    dataframe result to be compatible with finagg's
    local SQL tables.

    Args:
        ticker: Ticker to get.
        start: Start date for stock price history.
        end: End date for stock price history.
        interval: Frequency at which stock price history is grapped.
        period: Time period to get in the past. `"max"` is the full
            stock price history.
        debug: Debug mode passed to yfinance.

    Returns:
        A dataframe with normalized column names and values.

    """
    stock = yf.Ticker(ticker)
    df = stock.history(
        period=period,
        interval=interval,
        start=start,
        end=end,
        auto_adjust=True,
        debug=debug,
    )
    df.index = pd.to_datetime(df.index).date
    df = df.rename_axis("date").reset_index()
    df["ticker"] = stock.ticker
    df = df.drop(columns=["Dividends", "Stock Splits"], errors="ignore")
    df.columns = map(str.lower, df.columns)
    return df  # type: ignore[no-any-return]
