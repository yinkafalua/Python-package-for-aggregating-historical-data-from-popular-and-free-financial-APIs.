import pandas as pd
import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

import finagg


@pytest.fixture
def engine() -> Engine:
    yield from finagg.testing.sqlite_engine(
        finagg.backend.database_path, creator=finagg.fundamentals.store._define_db
    )


def test_fundamental_features_to_from_store(engine: Engine) -> None:
    df1 = finagg.fundamentals.features.fundamentals.from_api("AAPL")
    finagg.fundamentals.features.fundamentals.to_store(
        "AAPL",
        df1,
        engine=engine,
    )
    with pytest.raises(IntegrityError):
        finagg.fundamentals.features.fundamentals.to_store(
            "AAPL",
            df1,
            engine=engine,
        )

    df2 = finagg.fundamentals.features.fundamentals.from_store(
        "AAPL",
        engine=engine,
    )
    pd.testing.assert_frame_equal(df1, df2)