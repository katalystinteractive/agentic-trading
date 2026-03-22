#!/usr/bin/env python3
"""Sector Registry — centralized ticker→sector mapping for the entire system.

Two taxonomies (different purposes, both preserved):
- FINE_SECTOR_MAP: ticker → fine-grained label (e.g., "Crypto", "Nuclear", "Fintech")
- BROAD_SECTOR_MAP: fine → broad mapping for market context (11 ETF sectors)
- SECTOR_ETF: broad sector → ETF ticker (e.g., "Technology" → "XLK")
- SECTOR_GROUPS: group fine sectors into monitoring shards (12 groups)

Usage:
    from sector_registry import FINE_SECTOR_MAP, BROAD_SECTOR_MAP, SECTOR_ETF
    from sector_registry import get_sector, get_broad_sector, shard_tickers
"""
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CACHE_PATH = _ROOT / "data" / "sector_cache.json"

# ---------------------------------------------------------------------------
# Fine-grained sector map (ticker → subsector label)
# Canonical source — merged from surgical_screener.py (174 entries)
# ---------------------------------------------------------------------------
FINE_SECTOR_MAP = {
    # Tech / Software / AI
    "PLTR": "Tech", "HOOD": "Fintech", "RKLB": "Space", "SMCI": "AI/Infra",
    "PATH": "Tech", "NET": "Tech", "DDOG": "Tech", "MDB": "Tech",
    "SQ": "Fintech", "PINS": "Tech", "SNAP": "Tech", "ROKU": "Tech",
    "ABNB": "Tech", "DASH": "Tech", "LYFT": "Tech", "UBER": "Tech",
    "AFRM": "Fintech", "UPST": "Fintech", "LMND": "Fintech", "OPEN": "Tech",
    "RDFN": "Tech", "BBAI": "AI", "AI": "AI",
    "OKTA": "Tech", "ZS": "Tech", "CRWD": "Tech", "SNOW": "Tech", "SHOP": "Tech",
    # Space / Quantum / Frontier
    "JOBY": "Space", "LILM": "Space", "ASTS": "Space", "RDW": "Space",
    "LUNR": "Space", "OKLO": "Nuclear", "SMR": "Nuclear", "NNE": "Nuclear",
    "RGTI": "Quantum", "QBTS": "Quantum",
    # Crypto-adjacent
    "COIN": "Crypto", "RIOT": "Crypto", "MARA": "Crypto", "HUT": "Crypto",
    "BITF": "Crypto", "CLSK": "Crypto", "MSTR": "Crypto",
    # Energy / Solar / Nuclear
    "FSLR": "Solar", "ENPH": "Solar", "RUN": "Solar", "NOVA": "Solar",
    "OXY": "Energy", "DVN": "Energy", "MRO": "Energy", "HAL": "Energy",
    "SLB": "Energy", "CTRA": "Energy", "EQT": "Energy", "RRC": "Energy",
    "VST": "Energy", "CEG": "Nuclear",
    # EV / Clean Energy
    "PLUG": "EV/Clean", "BE": "EV/Clean", "BLNK": "EV/Clean", "CHPT": "EV/Clean",
    "QS": "EV/Clean", "RIVN": "EV/Clean", "LCID": "EV/Clean", "NKLA": "EV/Clean",
    "GOEV": "EV/Clean", "WKHS": "EV/Clean",
    # Biotech / Health
    "MRNA": "Biotech", "BNTX": "Biotech", "NVAX": "Biotech", "DNA": "Biotech",
    "BEAM": "Biotech", "CRSP": "Biotech", "EDIT": "Biotech", "NTLA": "Biotech",
    "PACB": "Biotech", "HIMS": "Health", "DOCS": "Health", "EXAS": "Health",
    # Materials / Mining / Steel
    "FCX": "Materials", "NEM": "Materials", "GOLD": "Materials", "AA": "Materials",
    "X": "Steel", "NUE": "Steel", "STLD": "Steel", "MP": "Materials", "TMC": "Materials",
    # Finance / Fintech
    "PYPL": "Fintech", "ALLY": "Finance", "LC": "Fintech",
    # Retail / Consumer
    "CHWY": "Retail", "DKS": "Retail", "CROX": "Retail", "ETSY": "Retail",
    "W": "Retail", "GME": "Retail", "AMC": "Retail", "BB": "Tech",
    # China ADR
    "BABA": "China ADR", "JD": "China ADR", "PDD": "China ADR", "NIO": "China ADR",
    "XPEV": "China ADR", "LI": "China ADR", "BIDU": "China ADR", "FUTU": "China ADR",
    # Defense / Industrial
    "KTOS": "Defense", "AVAV": "Defense", "IREN": "Crypto",
    # Misc volatile
    "CLOV": "Health", "TTWO": "Gaming", "EA": "Gaming", "WOLF": "Tech",
    "ON": "Semi", "MRVL": "Semi", "ARM": "Semi",
    "SWAV": "Health", "TEM": "AI", "RXRX": "Biotech", "SOUN": "AI",
    "NNOX": "Health", "VLD": "Tech", "PSNY": "EV/Clean",
    "LAZR": "Tech", "OUST": "Tech", "LIDR": "Tech", "TOST": "Tech",
    "GRAB": "Tech", "SE": "Tech", "CPNG": "Retail",
    "DUOL": "Tech", "MNDY": "Tech", "GLBE": "Tech", "CAVA": "Retail",
    "CART": "Retail", "DLO": "Fintech",
    # Portfolio tickers not in screening universe
    "IONQ": "Quantum", "ACHR": "eVTOL", "APLD": "Crypto",
    "CIFR": "Crypto", "CLF": "Steel", "INTC": "Semi",
    "NU": "Fintech", "STIM": "Biotech",
    "UAMY": "Materials", "USAR": "Materials", "AR": "Energy",
    "VALE": "Mining", "RKT": "Fintech", "SEDG": "Solar",
    # REITs
    "AGNC": "REIT", "NLY": "REIT", "MPW": "REIT",
    # Telecom / Media
    "PARA": "Media", "WBD": "Media",
    # Additional volatile mid-caps
    "BILL": "Tech", "GTLB": "Tech", "CFLT": "Tech", "ESTC": "Tech",
    "ZI": "Tech", "BRZE": "Tech",
    "APP": "Tech", "PUBM": "Tech", "MGNI": "Tech", "TTD": "Tech",
    "CELH": "Consumer", "MNST": "Consumer",
    "DKNG": "Gaming", "PENN": "Gaming", "RSI": "Gaming", "GENI": "Gaming",
}

# Backward-compatible alias used by surgical_screener.py and its consumers
SECTOR_MAP = FINE_SECTOR_MAP

# ---------------------------------------------------------------------------
# Broad sector map (fine label → 11 ETF-aligned broad sectors)
# Used by market context tools for sector ETF alignment
# ---------------------------------------------------------------------------
BROAD_SECTOR_MAP = {
    # Tech-adjacent → Technology
    "Tech": "Technology",
    "AI": "Technology",
    "AI/Infra": "Technology",
    "Semi": "Technology",
    "Quantum": "Technology",
    "Crypto": "Technology",
    # Finance
    "Fintech": "Financial",
    "Finance": "Financial",
    # Energy
    "Energy": "Energy",
    "Solar": "Energy",
    "Nuclear": "Utilities",
    # Space / Aerospace
    "Space": "Industrial",
    "eVTOL": "Industrial",
    "Defense": "Industrial",
    # Materials
    "Materials": "Materials",
    "Mining": "Materials",
    "Steel": "Materials",
    # Biotech / Health
    "Biotech": "Healthcare",
    "Health": "Healthcare",
    # Consumer / Retail
    "Retail": "Cons Cyclical",
    "Consumer": "Cons Cyclical",
    "Gaming": "Cons Cyclical",
    # EV / Clean
    "EV/Clean": "Industrial",
    # China ADR (map to broad sector by business)
    "China ADR": "Cons Cyclical",
    # Real Estate
    "REIT": "Real Estate",
    # Media
    "Media": "Comm Services",
}

# ---------------------------------------------------------------------------
# Sector ETF mapping (broad sector → ETF ticker)
# Must match market_pulse.py SECTORS dict
# ---------------------------------------------------------------------------
SECTOR_ETF = {
    "Technology": "XLK",
    "Financial": "XLF",
    "Energy": "XLE",
    "Healthcare": "XLV",
    "Industrial": "XLI",
    "Comm Services": "XLC",
    "Cons Cyclical": "XLY",
    "Cons Defensive": "XLP",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Materials": "XLB",
}

# ---------------------------------------------------------------------------
# Sector groups for monitoring shards (12 groups)
# ---------------------------------------------------------------------------
SECTOR_GROUPS = {
    "Tech/AI": ["Tech", "AI", "AI/Infra", "Semi"],
    "Crypto": ["Crypto"],
    "Energy": ["Energy", "Solar"],
    "Space/Quantum": ["Space", "Quantum", "eVTOL"],
    "Materials": ["Materials", "Mining", "Steel"],
    "Biotech": ["Biotech", "Health"],
    "Finance": ["Fintech", "Finance"],
    "Consumer": ["Retail", "Consumer", "Gaming"],
    "EV/Clean": ["EV/Clean"],
    "Defense/Industrial": ["Defense"],
    "China ADR": ["China ADR"],
    "Other": ["Nuclear", "REIT", "Media"],
}

# Reverse lookup: fine_sector → group name
_FINE_TO_GROUP = {}
for _group, _fine_sectors in SECTOR_GROUPS.items():
    for _fs in _fine_sectors:
        _FINE_TO_GROUP[_fs] = _group


# ---------------------------------------------------------------------------
# Lookup functions
# ---------------------------------------------------------------------------

def _load_cache():
    """Load sector cache from disk."""
    try:
        return json.loads(_CACHE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(cache):
    """Save sector cache to disk."""
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache, indent=2) + "\n")


def get_sector(ticker):
    """Look up fine-grained sector for a ticker.

    1. Check FINE_SECTOR_MAP (fast, no network)
    2. Check data/sector_cache.json (persisted yfinance lookups)
    3. Fall back to yfinance .info["sector"] with cache write

    Returns sector string or "Unknown".
    """
    # Fast path: static map
    if ticker in FINE_SECTOR_MAP:
        return FINE_SECTOR_MAP[ticker]

    # Check persistent cache
    cache = _load_cache()
    if ticker in cache:
        return cache[ticker]

    # yfinance fallback
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        sector = info.get("sector", "Unknown")
        if sector and sector != "Unknown":
            cache[ticker] = sector
            _save_cache(cache)
        return sector
    except Exception:
        return "Unknown"


def get_broad_sector(ticker):
    """Look up broad (11-ETF-aligned) sector for a ticker.

    Maps fine sector → broad sector via BROAD_SECTOR_MAP.
    Returns broad sector string or "Unknown".
    """
    fine = get_sector(ticker)
    return BROAD_SECTOR_MAP.get(fine, fine if fine in SECTOR_ETF else "Unknown")


def shard_tickers(tickers):
    """Group tickers by SECTOR_GROUPS for monitoring shards.

    Returns dict[group_name, list[ticker]].
    """
    shards = {group: [] for group in SECTOR_GROUPS}
    for ticker in tickers:
        fine = get_sector(ticker)
        group = _FINE_TO_GROUP.get(fine, "Other")
        shards[group].append(ticker)
    # Remove empty groups
    return {k: v for k, v in shards.items() if v}


# ---------------------------------------------------------------------------
# Backward-compatible helper for market_context_gatherer consumers
# ---------------------------------------------------------------------------

def get_broad_sector_map_for_tickers(tickers):
    """Build a ticker→broad_sector dict for a list of tickers.

    Replaces the old market_context_gatherer.SECTOR_MAP (which was broad).
    """
    return {t: get_broad_sector(t) for t in tickers}
