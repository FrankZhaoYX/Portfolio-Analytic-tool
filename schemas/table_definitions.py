"""Single source of truth for KDB-X DB Service table schemas.

Each entry is a dict of keyword arguments for `session.create_table(**kwargs)`.
See db-service/schemas/create_tables.py for how these are applied.
"""

TABLES = {
    "trades": {
        "table": "trades",
        "type": "partitioned",
        "prtnCol": "tradedate",
        "sortColsDisk": ["symbol"],
        "sortColsOrd": ["symbol"],
        "columns": [
            {"name": "tradeid", "type": "symbol"},
            {"name": "tradedate", "type": "timestamp", "attrDisk": "parted"},
            {"name": "symbol", "type": "symbol", "attrMem": "grouped", "attrDisk": "parted"},
            {"name": "exchange", "type": "symbol"},
            {"name": "side", "type": "symbol"},
            {"name": "qty", "type": "float"},
            {"name": "price", "type": "float"},
            {"name": "fees", "type": "float"},
            {"name": "currency", "type": "symbol"},
            {"name": "notes", "type": "string"},
            {"name": "createdat", "type": "timestamp"},
        ],
    },
    "eod_prices": {
        "table": "eod_prices",
        "type": "partitioned",
        "prtnCol": "date",
        "sortColsDisk": ["symbol"],
        "sortColsOrd": ["symbol"],
        "columns": [
            {"name": "date", "type": "timestamp", "attrDisk": "parted"},
            {"name": "symbol", "type": "symbol", "attrMem": "grouped", "attrDisk": "parted"},
            {"name": "exchange", "type": "symbol"},
            {"name": "open", "type": "float"},
            {"name": "high", "type": "float"},
            {"name": "low", "type": "float"},
            {"name": "close", "type": "float"},
            {"name": "adjclose", "type": "float"},
            {"name": "volume", "type": "long"},
        ],
    },
    "quotes": {
        "table": "quotes",
        "type": "partitioned",
        "prtnCol": "ts",
        "sortColsDisk": ["symbol"],
        "sortColsOrd": ["symbol"],
        "columns": [
            {"name": "ts", "type": "timestamp", "attrDisk": "parted"},
            {"name": "symbol", "type": "symbol", "attrMem": "grouped", "attrDisk": "parted"},
            {"name": "price", "type": "float"},
            {"name": "change", "type": "float"},
            {"name": "changepct", "type": "float"},
            {"name": "volume", "type": "long"},
        ],
    },
    "fundamentals": {
        "table": "fundamentals",
        "type": "partitioned",
        "prtnCol": "asofdate",
        "sortColsDisk": ["symbol"],
        "sortColsOrd": ["symbol"],
        "columns": [
            {"name": "asofdate", "type": "timestamp", "attrDisk": "parted"},
            {"name": "symbol", "type": "symbol", "attrMem": "grouped", "attrDisk": "parted"},
            {"name": "exchange", "type": "symbol"},
            {"name": "name", "type": "symbol"},
            {"name": "sector", "type": "symbol"},
            {"name": "industry", "type": "symbol"},
            {"name": "country", "type": "symbol"},
            {"name": "currency", "type": "symbol"},
            {"name": "assettype", "type": "symbol"},
            {"name": "marketcap", "type": "float"},
        ],
    },
}
