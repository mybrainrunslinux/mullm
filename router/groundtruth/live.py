"""
Groundtruth live data resolvers — optional, requires network.

Sources (all free, no API key required):
  - Crypto:  CoinGecko /simple/price
  - Stock:   Yahoo Finance unofficial endpoint
  - Weather: Open-Meteo

Cache backend: Redis on port 8179 (ephemeral RAM cache).
TTLs: crypto=300s, stock=300s, weather=600s

Extracted from oldcode/groundtruth_live.py.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request

from .registry import CategoryPlugin, register_category

# ---------------------------------------------------------------------------
# Redis cache helpers (mullm-redis-ram, port 8179)
# ---------------------------------------------------------------------------

_redis = None


def _get_redis():
    global _redis
    if _redis is None:
        try:
            import redis as _r
            _redis = _r.Redis(
                host="127.0.0.1", port=8179, db=2,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            _redis.ping()
        except Exception:
            _redis = None
    return _redis


def _cache_get(key: str) -> str | None:
    r = _get_redis()
    if not r:
        return None
    try:
        return r.get(key)
    except Exception:
        return None


def _cache_set(key: str, value: str, ttl: int) -> None:
    r = _get_redis()
    if not r:
        return
    try:
        r.setex(key, ttl, value)
    except Exception:
        pass


def _fetch(url: str, timeout: int = 8) -> dict | None:
    if not url.startswith("https://"):
        return None  # only permit HTTPS; blocks file:// and custom schemes
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mullm/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310
            return json.loads(r.read())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Crypto price (CoinGecko free tier)
# ---------------------------------------------------------------------------

_CRYPTO_IDS: dict[str, str] = {
    "bitcoin": "bitcoin",   "btc": "bitcoin",
    "ethereum": "ethereum", "eth": "ethereum",
    "solana": "solana",     "sol": "solana",
    "cardano": "cardano",   "ada": "cardano",
    "binancecoin": "binancecoin", "bnb": "binancecoin",
    "ripple": "ripple",     "xrp": "ripple",
    "dogecoin": "dogecoin", "doge": "dogecoin",
    "polkadot": "polkadot", "dot": "polkadot",
    "chainlink": "chainlink", "link": "chainlink",
    "avalanche": "avalanche-2", "avax": "avalanche-2",
    "polygon": "matic-network", "matic": "matic-network",
    "litecoin": "litecoin", "ltc": "litecoin",
    "stellar": "stellar",   "xlm": "stellar",
}


def get_crypto_price(coin_name: str) -> str | None:
    coin_id = _CRYPTO_IDS.get(coin_name.lower())
    if not coin_id:
        return None
    cache_key = f"gt:crypto:{coin_id}"
    cached = _cache_get(cache_key)
    if cached:
        return cached
    url = (
        f"https://api.coingecko.com/api/v3/simple/price"
        f"?ids={coin_id}&vs_currencies=usd"
        f"&include_24hr_change=true&include_market_cap=true"
    )
    data = _fetch(url)
    if not data or coin_id not in data:
        return None
    info = data[coin_id]
    price  = info.get("usd", 0)
    change = info.get("usd_24h_change", 0)
    mcap   = info.get("usd_market_cap", 0)
    arrow  = "up" if change >= 0 else "down"
    display_name = coin_name.upper() if len(coin_name) <= 4 else coin_name.title()
    result = (
        f"**{display_name}** (live from CoinGecko)\n\n"
        f"Price: **${price:,.2f} USD**\n"
        f"24h change: {arrow} {abs(change):.2f}%\n"
        f"Market cap: ${mcap / 1e9:.1f}B\n\n"
        f"*Cached 5 min · {time.strftime('%H:%M')} local*"
    )
    _cache_set(cache_key, result, ttl=300)
    return result


# ---------------------------------------------------------------------------
# Stock price (Yahoo Finance)
# ---------------------------------------------------------------------------

_COMMON_TICKERS: dict[str, str] = {
    "aapl": "AAPL", "apple": "AAPL",
    "googl": "GOOGL", "google": "GOOGL", "alphabet": "GOOGL",
    "msft": "MSFT", "microsoft": "MSFT",
    "amzn": "AMZN", "amazon": "AMZN",
    "meta": "META", "facebook": "META",
    "tsla": "TSLA", "tesla": "TSLA",
    "nvda": "NVDA", "nvidia": "NVDA",
    "amd": "AMD",
    "intc": "INTC", "intel": "INTC",
    "nflx": "NFLX", "netflix": "NFLX",
    "spy": "SPY", "qqq": "QQQ", "voo": "VOO",
}


def get_stock_price(ticker_or_name: str) -> str | None:
    key = ticker_or_name.lower().strip()
    ticker = _COMMON_TICKERS.get(key, ticker_or_name.upper())
    cache_key = f"gt:stock:{ticker}"
    cached = _cache_get(cache_key)
    if cached:
        return cached
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{urllib.parse.quote(ticker)}?interval=1d&range=1d"
    )
    data = _fetch(url)
    if not data:
        return None
    try:
        meta = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice", 0)
        prev_close = meta.get("chartPreviousClose", price)
        change = price - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0
        currency = meta.get("currency", "USD")
        market_state = meta.get("marketState", "")
        exchange = meta.get("exchangeName", "")
    except (KeyError, IndexError, TypeError):
        return None
    arrow = "up" if change >= 0 else "down"
    state_note = " *(market closed)*" if market_state in ("CLOSED", "PRE", "POST") else ""
    result = (
        f"**{ticker}** ({exchange}){state_note} — live from Yahoo Finance\n\n"
        f"Price: **{price:.2f} {currency}**\n"
        f"Change: {arrow} {abs(change):.2f} ({abs(change_pct):.2f}%)\n"
        f"Prev close: {prev_close:.2f}\n\n"
        f"*Cached 5 min · {time.strftime('%H:%M')} local*"
    )
    _cache_set(cache_key, result, ttl=300)
    return result


# ---------------------------------------------------------------------------
# Weather (Open-Meteo, zero API key)
# ---------------------------------------------------------------------------

_WEATHER_CITIES: dict[str, tuple[float, float, str]] = {
    "new york": (40.7128, -74.0060, "New York, US"),
    "nyc": (40.7128, -74.0060, "New York, US"),
    "london": (51.5074, -0.1278, "London, UK"),
    "paris": (48.8566, 2.3522, "Paris, France"),
    "tokyo": (35.6762, 139.6503, "Tokyo, Japan"),
    "berlin": (52.5200, 13.4050, "Berlin, Germany"),
    "sydney": (-33.8688, 151.2093, "Sydney, Australia"),
    "toronto": (43.6532, -79.3832, "Toronto, Canada"),
    "singapore": (1.3521, 103.8198, "Singapore"),
    "dubai": (25.2048, 55.2708, "Dubai, UAE"),
    "moscow": (55.7558, 37.6173, "Moscow, Russia"),
    "beijing": (39.9042, 116.4074, "Beijing, China"),
    "shanghai": (31.2304, 121.4737, "Shanghai, China"),
    "mumbai": (19.0760, 72.8777, "Mumbai, India"),
    "delhi": (28.7041, 77.1025, "New Delhi, India"),
    "chicago": (41.8781, -87.6298, "Chicago, US"),
    "los angeles": (34.0522, -118.2437, "Los Angeles, US"),
    "la": (34.0522, -118.2437, "Los Angeles, US"),
    "san francisco": (37.7749, -122.4194, "San Francisco, US"),
    "seattle": (47.6062, -122.3321, "Seattle, US"),
    "miami": (25.7617, -80.1918, "Miami, US"),
    "amsterdam": (52.3676, 4.9041, "Amsterdam, Netherlands"),
    "stockholm": (59.3293, 18.0686, "Stockholm, Sweden"),
    "seoul": (37.5665, 126.9780, "Seoul, South Korea"),
    "bangkok": (13.7563, 100.5018, "Bangkok, Thailand"),
}

_WMO_CODES: dict[int, str] = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Severe hail storm",
}

_WEATHER_RE = re.compile(
    r"(?:weather(?: in| for| at)?|temperature(?: in| of)?|how(?:\'s| is) the weather(?: in)?)\s+"
    r"([\w\s]{2,30?}?)(?:\s*\?|$)",
    re.IGNORECASE,
)


def get_weather(city: str) -> str | None:
    city_key = city.lower().strip()
    loc = _WEATHER_CITIES.get(city_key)
    if not loc:
        return None
    lat, lon, display = loc
    cache_key = f"gt:weather:{city_key}"
    cached = _cache_get(cache_key)
    if cached:
        return cached
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
        f"precipitation,wind_speed_10m,weathercode"
        f"&wind_speed_unit=kmh&temperature_unit=celsius"
    )
    data = _fetch(url)
    if not data or "current" not in data:
        return None
    cur = data["current"]
    temp_c = cur.get("temperature_2m", "?")
    feels_c = cur.get("apparent_temperature", "?")
    humidity = cur.get("relative_humidity_2m", "?")
    wind = cur.get("wind_speed_10m", "?")
    precip = cur.get("precipitation", 0)
    wmo = cur.get("weathercode", 0)
    condition = _WMO_CODES.get(wmo, f"Code {wmo}")
    try:
        temp_f  = round(temp_c  * 9 / 5 + 32, 1)
        feels_f = round(feels_c * 9 / 5 + 32, 1)
    except (TypeError, ValueError):
        temp_f = feels_f = "?"
    precip_str = f", {precip}mm precip" if precip and precip > 0 else ""
    result = (
        f"**Weather in {display}** (Open-Meteo)\n\n"
        f"{condition}\n"
        f"Temp: **{temp_c}C / {temp_f}F** (feels like {feels_c}C / {feels_f}F)\n"
        f"Humidity: {humidity}% · Wind: {wind} km/h{precip_str}\n\n"
        f"*Cached 10 min · {time.strftime('%H:%M')} local*"
    )
    _cache_set(cache_key, result, ttl=600)
    return result


# ---------------------------------------------------------------------------
# Combined live resolver
# ---------------------------------------------------------------------------

_CRYPTO_RE = re.compile(
    r"(?:price of |how much is |what(?:\'s| is) (?:the )?(?:current )?(?:price of )?)"
    r"(bitcoin|btc|ethereum|eth|solana|sol|cardano|ada|dogecoin|doge|"
    r"ripple|xrp|binancecoin|bnb|polkadot|dot|chainlink|link|avalanche|avax|"
    r"polygon|matic|litecoin|ltc|stellar|xlm)\b",
    re.IGNORECASE,
)

_STOCK_RE = re.compile(
    r"(?:stock price of |price of |how much is |what(?:\'s| is) (?:the )?(?:stock )?(?:price of )?)"
    r"(aapl|apple|googl|google|msft|microsoft|amzn|amazon|meta|facebook|tsla|tesla|"
    r"nvda|nvidia|amd|intc|intel|nflx|netflix|spy|qqq|voo)\b",
    re.IGNORECASE,
)


def _resolve_live(q: str) -> str | None:
    lower = q.lower()

    # Crypto
    m = _CRYPTO_RE.search(lower)
    if m:
        result = get_crypto_price(m.group(1))
        if result:
            return result

    # Stock
    m = _STOCK_RE.search(lower)
    if m:
        result = get_stock_price(m.group(1))
        if result:
            return result

    # Weather
    m = _WEATHER_RE.search(lower)
    if m:
        city = m.group(1).strip().rstrip("?.,")
        result = get_weather(city)
        if result:
            return result

    return None


def register_live() -> None:
    register_category(CategoryPlugin(
        name="live",
        patterns=[],
        resolver=_resolve_live,
    ))
