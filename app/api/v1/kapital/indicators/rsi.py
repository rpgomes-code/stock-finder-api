import logging
import pandas as pd
import yfinance as yf

from datetime import (
    datetime, 
    timedelta
)
from fastapi import (
    APIRouter, 
    HTTPException, 
    Query
)

from app.models.kapital.indicators import RSIResponse

from app.utils.kapital.rsi import calculate_rsi
from app.utils.redis.cache_decorator import redis_cache
from app.utils.yfinance.error_handler import handle_yf_request
from app.utils.yfinance.yfinance_data_manager import clean_yfinance_data

# Create a router with a specific prefix and tag
router = APIRouter(prefix="/v1/kapital/indicators", tags=["Kapital Indicators"])

# Logger for this module
logger = logging.getLogger(__name__)

# RSI - Relative Strength Index
@router.get("/rsi", response_model=RSIResponse)
@handle_yf_request
@redis_cache(ttl="1 day", invalidate_at_midnight=True)
@clean_yfinance_data
async def get_rsi(
        ticker: str = Query(..., description="Stock ticker symbol (e.g., AAPL, MSFT)"),
        start: str = Query(..., description="Start date in YYYY-MM-DD format"),
        end: str = Query(..., description="End date in YYYY-MM-DD format"),
        period: int = Query(14, description="RSI calculation period (default: 14 days)", ge=1, le=100)
):
    """
    Calculate Relative Strength Index (RSI) for a specific ticker.

    The RSI is a momentum oscillator developed by J. Welles Wilder that measures the speed and
    change of price movements. It oscillates between 0 and 100 and is typically used to identify
    overbought or oversold conditions in a traded security.

    Trading signals based on RSI:
    - RSI values of 70 or above indicate that a security may be **overbought** - potentially overvalued
    - RSI values of 30 or below indicate that a security may be **oversold** - potentially undervalued
    - Divergences between price and RSI can signal potential trend reversals
    - The centerline (50) can act as support/resistance in trending markets

    Parameters:
    - **ticker**: Stock ticker symbol
    - **start**: Start date for historical data (YYYY-MM-DD)
    - **end**: End date for historical data (YYYY-MM-DD)
    - **period**: RSI calculation period (default: 14 days)

    Returns:
    - **RSIResponse**: Object containing the time series of RSI values

    Example response:
    ```json
    {
        "values": [
            {
                "Date": "2023-01-01T00:00:00",
                "RSI": 65.42
            },
            {
                "Date": "2023-01-02T00:00:00",
                "RSI": 68.31
            }
        ]
    }
    ```

    Notes:
    - This implementation uses Wilder's smoothing method for the RSI calculation,
      which is the traditional approach used by most trading platforms
    - The calculation requires at least (period + 1) data points to generate valid RSI values
    - The endpoint automatically fetches additional historical data before the start date
      to ensure accurate RSI calculation for the requested period
    """
    try:
        # Convert string dates to datetime objects
        start_date = datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.strptime(end, "%Y-%m-%d")

        # Add some buffer days before start date to have enough data for RSI calculation
        buffer_start_date = start_date - timedelta(days=period * 2)

        # Get historical data
        ticker_data = yf.Ticker(ticker)
        history = ticker_data.history(start=buffer_start_date, end=end_date, interval="1d")

        # Check if we have enough data
        if len(history) < period + 1:
            raise HTTPException(
                status_code=400,
                detail=f"Not enough historical data for RSI calculation with period={period}"
            )

        # Calculate RSI
        rsi_values = calculate_rsi(history['Close'], period=period)

        # Create result dataframe with Date and RSI (without including index in response)
        result = pd.DataFrame({
            'Date': history.index,
            'RSI': rsi_values.values
        }, index=None)

        # Filter for the requested date range (remove buffer period)
        # Convert dates to timezone-naive for consistent comparison
        start_ts = pd.Timestamp(start_date).tz_localize(None)
        end_ts = pd.Timestamp(end_date).tz_localize(None)

        # For comparison, make the Date column timezone-naive if it has timezone info
        if result['Date'].dt.tz is not None:
            date_filter = result['Date'].dt.tz_localize(None)
            result = result[(date_filter >= start_ts) & (date_filter <= end_ts)]
        else:
            result = result[(result['Date'] >= start_ts) & (result['Date'] <= end_ts)]

        # Handle any NaN values
        result = result.dropna()

        # Convert to records and explicitly reset index to avoid it being included in the output
        result_records = result.reset_index(drop=True).to_dict(orient='records')

        # Wrap in the values field for our Pydantic model
        return {"values": result_records}

    except Exception as e:
        logger.error(f"Error calculating RSI for {ticker}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error calculating RSI: {str(e)}")