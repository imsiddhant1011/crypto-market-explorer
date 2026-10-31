#!/usr/bin/env python3
"""Build the Crypto Market Explorer Power BI project (PBIP).

A .pbix can only be produced by Power BI Desktop on Windows. This script
creates the officially supported, text-based Power BI Project format (PBIP),
which Power BI Desktop opens directly and can then save as .pbix.

Run from anywhere:

    python3 powerbi/build_pbip.py

Output:

    powerbi/CryptoMarketExplorer/
        CryptoMarketExplorer.pbip
        CryptoMarketExplorer.Report/
        CryptoMarketExplorer.SemanticModel/

The generated folder is self-contained apart from the PostgreSQL database it
imports. On Windows: open the .pbip, refresh (enter the DB credentials), then
File > Save as > .pbix.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths and identifiers
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "CryptoMarketExplorer"
REPORT = OUT / "CryptoMarketExplorer.Report"
MODEL = OUT / "CryptoMarketExplorer.SemanticModel"

THEME_TEMPLATE = ROOT / "theme.json"
BASE_THEME_TEMPLATE = ROOT / "templates" / "Fluent2-CY26SU10.json"

PAGE_OVERVIEW = hashlib.sha1(b"page:market-overview").hexdigest()[:20]
PAGE_COMPARE = hashlib.sha1(b"page:compare-pairs").hexdigest()[:20]
PAGE_QUALITY = hashlib.sha1(b"page:data-quality").hexdigest()[:20]


def oid(label: str) -> str:
    """Stable 20-char lowercase hex object id (PBIR convention)."""
    return hashlib.sha1(label.encode("utf-8")).hexdigest()[:20]


# ---------------------------------------------------------------------------
# Schema versions (current Power BI Desktop, October 2026)
# ---------------------------------------------------------------------------

SCHEMA_PBIP = "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json"
SCHEMA_PLATFORM = "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json"
SCHEMA_PBIR = "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json"
SCHEMA_VERSION = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json"
SCHEMA_REPORT = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.3.0/schema.json"
SCHEMA_PAGES = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json"
SCHEMA_PAGE = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json"
SCHEMA_VISUAL = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.11.0/schema.json"
SCHEMA_PBISM = "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json"

REPORT_VERSIONS = {"visual": "2.11.0", "report": "3.4.0", "page": "2.3.1"}

# ---------------------------------------------------------------------------
# Small JSON / expression helpers
# ---------------------------------------------------------------------------


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_json(path: Path, obj) -> None:
    write_text(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def literal(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def txt(value: str) -> dict:
    """PBIR text literal: single quotes, embedded quotes doubled."""
    return literal("'" + value.replace("'", "''") + "'")


def boolean(value: bool) -> dict:
    return literal("true" if value else "false")


def number(value: float | int, suffix: str = "D") -> dict:
    return literal(f"{value}{suffix}")


def color(hex_value: str) -> dict:
    return {"solid": {"color": txt(hex_value)}}


def field_col(entity: str, prop: str, display: str | None = None) -> dict:
    projection = {
        "field": {
            "Column": {
                "Expression": {"SourceRef": {"Entity": entity}},
                "Property": prop,
            }
        },
        "queryRef": f"{entity}.{prop}",
        "nativeQueryRef": display or prop,
    }
    if display:
        projection["displayName"] = display
    return projection


def field_measure(entity: str, prop: str, display: str | None = None) -> dict:
    projection = {
        "field": {
            "Measure": {
                "Expression": {"SourceRef": {"Entity": entity}},
                "Property": prop,
            }
        },
        "queryRef": f"{entity}.{prop}",
        "nativeQueryRef": display or prop,
    }
    if display:
        projection["displayName"] = display
    return projection


def container(
    title: str | None,
    *,
    background: bool = True,
    border: bool = True,
    padding: int = 10,
    alt_text: str = "",
    title_size: int = 11,
) -> dict:
    vco: dict = {
        "title": [
            {
                "properties": {
                    "show": boolean(title is not None),
                    "text": txt(title or ""),
                    "fontSize": number(title_size),
                    "bold": boolean(True),
                    "fontColor": color("#0F172A"),
                }
            }
        ],
        "background": [
            {
                "properties": {
                    "show": boolean(background),
                    "color": color("#FFFFFF"),
                    "transparency": number(0),
                }
            }
        ],
        "border": [
            {
                "properties": {
                    "show": boolean(border),
                    "color": color("#E2E8F0"),
                    "radius": number(8),
                    "width": number(1),
                }
            }
        ],
        "dropShadow": [{"properties": {"show": boolean(False)}}],
        "visualHeader": [{"properties": {"show": boolean(False)}}],
        "padding": [
            {
                "properties": {
                    "left": number(padding),
                    "top": number(padding),
                    "right": number(padding),
                    "bottom": number(padding),
                }
            }
        ],
    }
    if alt_text:
        vco["general"] = [{"properties": {"altText": txt(alt_text)}}]
    return vco


def frame(name: str, x: int, y: int, w: int, h: int, z: int = 0) -> dict:
    return {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": z}


# ---------------------------------------------------------------------------
# Report visuals
# ---------------------------------------------------------------------------


def textbox(label: str, x: int, y: int, w: int, h: int, paragraphs: list[dict], alt: str) -> dict:
    return {
        "$schema": SCHEMA_VISUAL,
        "name": oid(f"v:{label}"),
        "position": frame(oid(f"v:{label}"), x, y, w, h, 0),
        "visual": {
            "visualType": "textbox",
            "objects": {"general": [{"properties": {"paragraphs": paragraphs}}]},
            "visualContainerObjects": {
                "title": [{"properties": {"show": boolean(False)}}],
                "background": [{"properties": {"show": boolean(False)}}],
                "border": [{"properties": {"show": boolean(False)}}],
                "dropShadow": [{"properties": {"show": boolean(False)}}],
                "visualHeader": [{"properties": {"show": boolean(False)}}],
                "general": [{"properties": {"altText": txt(alt)}}],
            },
            "drillFilterOtherVisuals": True,
        },
    }


def title_visual(label: str, title: str, subtitle: str) -> dict:
    return textbox(
        label,
        24,
        16,
        1232,
        54,
        [
            {
                "textRuns": [
                    {
                        "value": title,
                        "textStyle": {
                            "fontFamily": "Segoe UI Semibold",
                            "fontSize": "22pt",
                            "fontWeight": "bold",
                            "color": "#0F172A",
                        },
                    }
                ]
            },
            {
                "textRuns": [
                    {
                        "value": subtitle,
                        "textStyle": {
                            "fontFamily": "Segoe UI",
                            "fontSize": "10pt",
                            "color": "#64748B",
                        },
                    }
                ]
            },
        ],
        f"Page title: {title}. {subtitle}",
    )


def note_box(label: str, x: int, y: int, w: int, h: int, text: str, alt: str) -> dict:
    """A textbox with a subtle card background, used for page help text."""
    visual = textbox(
        label,
        x,
        y,
        w,
        h,
        [
            {
                "textRuns": [
                    {
                        "value": text,
                        "textStyle": {
                            "fontFamily": "Segoe UI",
                            "fontSize": "10pt",
                            "color": "#475569",
                        },
                    }
                ]
            }
        ],
        alt,
    )
    visual["visual"]["visualContainerObjects"] = {
        "title": [{"properties": {"show": boolean(False)}}],
        "background": [
            {
                "properties": {
                    "show": boolean(True),
                    "color": color("#F8FAFC"),
                    "transparency": number(0),
                }
            }
        ],
        "border": [
            {
                "properties": {
                    "show": boolean(True),
                    "color": color("#E2E8F0"),
                    "radius": number(8),
                    "width": number(1),
                }
            }
        ],
        "dropShadow": [{"properties": {"show": boolean(False)}}],
        "visualHeader": [{"properties": {"show": boolean(False)}}],
        "padding": [
            {
                "properties": {
                    "left": number(12),
                    "top": number(12),
                    "right": number(12),
                    "bottom": number(12),
                }
            }
        ],
        "general": [{"properties": {"altText": txt(alt)}}],
    }
    return visual


def slicer(
    label: str,
    x: int,
    y: int,
    w: int,
    h: int,
    entity: str,
    column: str,
    display_name: str,
    *,
    mode: str = "Dropdown",
    preselect: str | None = None,
    single: bool = True,
    alt: str,
) -> dict:
    projection = field_col(entity, column, display_name)
    projection["active"] = True
    visual = {
        "visualType": "slicer",
        "query": {"queryState": {"Values": {"projections": [projection]}}},
        "objects": {
            "data": [{"properties": {"mode": txt(mode)}}],
        },
        "visualContainerObjects": container(
            None, padding=8, alt_text=alt, title_size=10
        ),
        "drillFilterOtherVisuals": True,
    }
    if mode != "Between":
        visual["objects"]["selection"] = [
            {"properties": {"strictSingleSelect": boolean(single)}}
        ]
    if mode == "Between":
        visual["objects"]["selection"] = [
            {"properties": {"singleDate": boolean(False)}}
        ]

    if preselect:
        visual["objects"]["general"] = [
            {
                "properties": {
                    "filter": {
                        "filter": {
                            "Version": 2,
                            "From": [
                                {"Name": "s", "Entity": entity, "Type": 0}
                            ],
                            "Where": [
                                {
                                    "Condition": {
                                        "In": {
                                            "Expressions": [
                                                {
                                                    "Column": {
                                                        "Expression": {
                                                            "SourceRef": {"Source": "s"}
                                                        },
                                                        "Property": column,
                                                    }
                                                }
                                            ],
                                            "Values": [
                                                [
                                                    {
                                                        "Literal": {
                                                            "Value": "'"
                                                            + preselect.replace("'", "''")
                                                            + "'"
                                                        }
                                                    }
                                                ]
                                            ],
                                        }
                                    }
                                }
                            ],
                        }
                    }
                }
            }
        ]

    return {
        "$schema": SCHEMA_VISUAL,
        "name": oid(f"v:{label}"),
        "position": frame(oid(f"v:{label}"), x, y, w, h, 10),
        "visual": visual,
    }


def card(
    label: str,
    x: int,
    y: int,
    w: int,
    h: int,
    entity: str,
    measure: str,
    caption: str,
    alt: str,
    *,
    value_size: int = 22,
) -> dict:
    return {
        "$schema": SCHEMA_VISUAL,
        "name": oid(f"v:{label}"),
        "position": frame(oid(f"v:{label}"), x, y, w, h, 20),
        "visual": {
            "visualType": "cardVisual",
            "query": {
                "queryState": {
                    "Data": {"projections": [field_measure(entity, measure)]}
                }
            },
            "objects": {
                "label": [
                    {
                        "properties": {
                            "show": boolean(True),
                            "text": txt(caption),
                            "fontSize": number(10),
                            "fontColor": color("#64748B"),
                        }
                    }
                ],
                "value": [
                    {
                        "properties": {
                            "fontSize": number(value_size),
                            "bold": boolean(True),
                            "fontColor": color("#0F172A"),
                        }
                    }
                ],
            },
            "visualContainerObjects": container(None, padding=12, alt_text=alt),
            "drillFilterOtherVisuals": True,
        },
    }


def line_chart(
    label: str,
    x: int,
    y: int,
    w: int,
    h: int,
    title: str,
    category: dict,
    values: dict,
    *,
    series: dict | None = None,
    markers: bool = False,
    alt: str,
) -> dict:
    query_state: dict = {
        "Category": {"projections": [category]},
        "Y": {"projections": [values]},
    }
    if series is not None:
        query_state["Series"] = {"projections": [series]}

    objects: dict = {
        "categoryAxis": [
            {
                "properties": {
                    "showAxisTitle": boolean(False),
                    "gridlineShow": boolean(False),
                    "fontSize": number(9),
                }
            }
        ],
        "valueAxis": [
            {
                "properties": {
                    "showAxisTitle": boolean(False),
                    "fontSize": number(9),
                }
            }
        ],
        "lineStyles": [
            {
                "properties": {
                    "strokeWidth": number(2),
                    "showMarker": boolean(markers),
                    "markerSize": number(4),
                }
            }
        ],
        "legend": [
            {
                "properties": {
                    "show": boolean(series is not None),
                    "position": txt("Bottom"),
                    "showTitle": boolean(False),
                }
            }
        ],
    }

    return {
        "$schema": SCHEMA_VISUAL,
        "name": oid(f"v:{label}"),
        "position": frame(oid(f"v:{label}"), x, y, w, h, 30),
        "visual": {
            "visualType": "lineChart",
            "query": {"queryState": query_state},
            "objects": objects,
            "visualContainerObjects": container(title, padding=10, alt_text=alt),
            "drillFilterOtherVisuals": True,
        },
    }


def column_chart(
    label: str,
    x: int,
    y: int,
    w: int,
    h: int,
    title: str,
    category: dict,
    values: dict,
    *,
    series: dict | None = None,
    data_labels: bool = False,
    alt: str,
) -> dict:
    query_state: dict = {
        "Category": {"projections": [category]},
        "Y": {"projections": [values]},
    }
    if series is not None:
        query_state["Series"] = {"projections": [series]}

    objects: dict = {
        "categoryAxis": [
            {
                "properties": {
                    "showAxisTitle": boolean(False),
                    "fontSize": number(9),
                }
            }
        ],
        "valueAxis": [
            {
                "properties": {
                    "showAxisTitle": boolean(False),
                    "fontSize": number(9),
                }
            }
        ],
        "labels": [
            {
                "properties": {
                    "show": boolean(data_labels),
                    "labelPrecision": literal("0L"),
                }
            }
        ],
        "legend": [
            {
                "properties": {
                    "show": boolean(series is not None),
                    "position": txt("Bottom"),
                    "showTitle": boolean(False),
                }
            }
        ],
    }

    return {
        "$schema": SCHEMA_VISUAL,
        "name": oid(f"v:{label}"),
        "position": frame(oid(f"v:{label}"), x, y, w, h, 30),
        "visual": {
            "visualType": "clusteredColumnChart",
            "query": {"queryState": query_state},
            "objects": objects,
            "visualContainerObjects": container(title, padding=10, alt_text=alt),
            "drillFilterOtherVisuals": True,
        },
    }


def table(
    label: str,
    x: int,
    y: int,
    w: int,
    h: int,
    title: str,
    projections: list[dict],
    alt: str,
) -> dict:
    return {
        "$schema": SCHEMA_VISUAL,
        "name": oid(f"v:{label}"),
        "position": frame(oid(f"v:{label}"), x, y, w, h, 30),
        "visual": {
            "visualType": "tableEx",
            "query": {"queryState": {"Values": {"projections": projections}}},
            "objects": {},
            "visualContainerObjects": container(title, padding=8, alt_text=alt),
            "drillFilterOtherVisuals": True,
        },
    }


# ---------------------------------------------------------------------------
# Report pages
# ---------------------------------------------------------------------------


def write_page(page_id: str, display_name: str, visuals: list[dict]) -> None:
    page_dir = REPORT / "definition" / "pages" / page_id
    write_json(
        page_dir / "page.json",
        {
            "$schema": SCHEMA_PAGE,
            "name": page_id,
            "displayName": display_name,
            "displayOption": "FitToPage",
            "height": 720,
            "width": 1280,
            "objects": {
                "outspace": [
                    {
                        "properties": {
                            "color": {
                                "solid": {"color": txt("#EEF2F7")}
                            }
                        }
                    }
                ]
            },
        },
    )
    for visual in visuals:
        write_json(
            page_dir / "visuals" / visual["name"] / "visual.json", visual
        )


def build_report() -> None:
    title_overview = title_visual(
        "title-overview",
        "Crypto Market Data Explorer",
        "30 days · 1-minute candles · UTC · 28 Sep – 27 Oct 2026",
    )
    title_compare = title_visual(
        "title-compare",
        "Crypto Market Data Explorer",
        "Compare pairs · daily returns · volume · 30-day window",
    )
    title_quality = title_visual(
        "title-quality",
        "Crypto Market Data Explorer",
        "Data quality & coverage · 7 pairs · 302,400 stored 1-minute candles",
    )

    overview = [
        title_overview,
        slicer(
            "slicer-pair-overview",
            24,
            80,
            300,
            88,
            "Symbols",
            "display_name",
            "Pair",
            preselect="Bitcoin / Tether",
            alt="Filter the market overview by trading pair.",
        ),
        slicer(
            "slicer-interval-overview",
            336,
            80,
            220,
            88,
            "Candles",
            "interval",
            "Timeframe",
            preselect="15m",
            alt="Filter candles by timeframe: 1m, 5m, 15m or 30m.",
        ),
        slicer(
            "slicer-date-overview",
            568,
            80,
            360,
            88,
            "Date",
            "Date",
            "UTC date range",
            mode="Between",
            alt="Filter the report by UTC date.",
        ),
        card(
            "card-data-through",
            940,
            80,
            316,
            88,
            "Candles",
            "Data Through",
            "Data through (UTC)",
            "Latest candle timestamp in the current selection.",
            value_size=16,
        ),
        card(
            "card-latest-close",
            24,
            184,
            232,
            92,
            "LatestPrices",
            "Latest Close",
            "Latest close",
            "Latest close price for the selected pair.",
        ),
        card(
            "card-period-return",
            274,
            184,
            232,
            92,
            "Candles",
            "Period Return %",
            "Period return",
            "Return from the first open to the last close in the current selection.",
        ),
        card(
            "card-period-high",
            524,
            184,
            232,
            92,
            "Candles",
            "Period High",
            "Period high",
            "Highest price in the current selection.",
        ),
        card(
            "card-period-low",
            774,
            184,
            232,
            92,
            "Candles",
            "Period Low",
            "Period low",
            "Lowest price in the current selection.",
        ),
        card(
            "card-period-volume",
            1024,
            184,
            232,
            92,
            "Candles",
            "Period Volume",
            "Period volume",
            "Total traded volume in the current selection.",
        ),
        line_chart(
            "line-price",
            24,
            292,
            780,
            280,
            "Price · close",
            field_col("Candles", "bucket_start", "Time (UTC)"),
            field_measure("Candles", "Close Price", "Close"),
            alt="Line chart of the close price over the selected date range and timeframe.",
        ),
        column_chart(
            "column-volume",
            816,
            292,
            440,
            280,
            "Daily volume",
            field_col("DailyCandles", "day_start", "Day (UTC)"),
            field_measure("DailyCandles", "Daily Volume", "Volume"),
            alt="Column chart of daily traded volume over the selected date range.",
        ),
        line_chart(
            "line-daily-close",
            24,
            584,
            1232,
            120,
            "Daily close · month trend",
            field_col("DailyCandles", "day_start", "Day (UTC)"),
            field_measure("DailyCandles", "Daily Close", "Close"),
            markers=True,
            alt="Line chart of the daily close for the selected pair across the month.",
        ),
    ]

    compare = [
        title_compare,
        slicer(
            "slicer-date-compare",
            24,
            80,
            360,
            88,
            "Date",
            "Date",
            "UTC date range",
            mode="Between",
            alt="Filter the pair comparison by UTC date.",
        ),
        slicer(
            "slicer-interval-compare",
            396,
            80,
            220,
            88,
            "Candles",
            "interval",
            "Timeframe",
            preselect="15m",
            alt="Filter the pair comparison by timeframe.",
        ),
        note_box(
            "note-compare",
            628,
            80,
            300,
            88,
            "Daily return = (close − open) / open per complete UTC day. Volume uses the selected timeframe.",
            "Explains how daily return and period volume are calculated.",
        ),
        card(
            "card-pairs-compared",
            940,
            80,
            316,
            88,
            "Symbols",
            "Pairs Compared",
            "Pairs compared",
            "Number of trading pairs in the model.",
            value_size=22,
        ),
        line_chart(
            "line-daily-return",
            24,
            184,
            780,
            300,
            "Daily return % by pair",
            field_col("DailyCandles", "day_start", "Day (UTC)"),
            field_measure("DailyCandles", "Daily Return %", "Daily return"),
            series=field_col("Symbols", "display_name", "Pair"),
            alt="Line chart comparing daily returns across all trading pairs.",
        ),
        column_chart(
            "column-volume-pair",
            816,
            184,
            440,
            300,
            "Period volume by pair",
            field_col("Symbols", "display_name", "Pair"),
            field_measure("Candles", "Period Volume", "Volume"),
            data_labels=True,
            alt="Column chart comparing traded volume across pairs.",
        ),
        table(
            "table-compare",
            24,
            500,
            1232,
            204,
            "Pair comparison",
            [
                field_col("Symbols", "display_name", "Pair"),
                field_measure("LatestPrices", "Latest Close", "Latest close"),
                field_measure("Candles", "Period Return %", "Period return"),
                field_measure("DailyCandles", "30-Day High", "30-day high"),
                field_measure("DailyCandles", "30-Day Low", "30-day low"),
                field_measure(
                    "DailyCandles", "Average Daily Volume", "Avg daily volume"
                ),
            ],
            alt="Table comparing latest close, return, 30-day range and average volume by pair.",
        ),
    ]

    quality = [
        title_quality,
        slicer(
            "slicer-pair-quality",
            24,
            80,
            300,
            88,
            "Symbols",
            "display_name",
            "Pair",
            single=False,
            alt="Filter the coverage page by one or more trading pairs.",
        ),
        slicer(
            "slicer-interval-quality",
            336,
            80,
            220,
            88,
            "Candles",
            "interval",
            "Timeframe",
            preselect="15m",
            alt="Filter the candle count by timeframe.",
        ),
        note_box(
            "note-coverage",
            568,
            80,
            688,
            88,
            "Coverage is measured on the stored 1-minute table. The interval slicer only changes the candle-count card.",
            "Explains how coverage is measured on the stored one-minute candles.",
        ),
        card(
            "card-selected-pair",
            24,
            184,
            296,
            92,
            "Symbols",
            "Selected Pair",
            "Selected pair",
            "The selected trading pair, or all pairs when the slicer has multiple values.",
            value_size=18,
        ),
        card(
            "card-candle-count",
            336,
            184,
            296,
            92,
            "Candles",
            "Candle Count",
            "Candles in view",
            "Number of candle rows for the selected interval and pairs.",
        ),
        card(
            "card-days-covered",
            648,
            184,
            296,
            92,
            "DailyCandles",
            "Days Covered",
            "Days covered",
            "Number of complete UTC days in the daily-candle table.",
        ),
        card(
            "card-all-rows",
            960,
            184,
            296,
            92,
            "Candles",
            "All Interval Rows",
            "All interval rows",
            "Total candle rows across all four intervals, ignoring the interval slicer.",
        ),
        table(
            "table-coverage",
            24,
            292,
            780,
            400,
            "Coverage by pair",
            [
                field_col("SymbolSummary", "symbol", "Symbol"),
                field_col("SymbolSummary", "first_open_time", "First candle"),
                field_col("SymbolSummary", "last_open_time", "Last candle"),
                field_measure("SymbolSummary", "1m Candles", "1m candles"),
            ],
            alt="Table of first and last candle timestamps and row counts for every pair.",
        ),
        column_chart(
            "column-coverage",
            816,
            292,
            440,
            400,
            "Stored 1-minute candles per pair",
            field_col("Symbols", "display_name", "Pair"),
            field_measure("SymbolSummary", "1m Candles", "1m candles"),
            data_labels=True,
            alt="Bar chart of the stored one-minute candle count for each pair.",
        ),
    ]

    write_page(PAGE_OVERVIEW, "Market Overview", overview)
    write_page(PAGE_COMPARE, "Compare Pairs", compare)
    write_page(PAGE_QUALITY, "Data Quality", quality)

    # ---- report definition -------------------------------------------------
    write_json(
        REPORT / "definition" / "version.json",
        {"$schema": SCHEMA_VERSION, "version": "2.0.0"},
    )
    write_json(
        REPORT / "definition" / "pages" / "pages.json",
        {
            "$schema": SCHEMA_PAGES,
            "pageOrder": [PAGE_OVERVIEW, PAGE_COMPARE, PAGE_QUALITY],
            "activePageName": PAGE_OVERVIEW,
            "landingPageName": PAGE_OVERVIEW,
        },
    )

    theme = json.loads(THEME_TEMPLATE.read_text(encoding="utf-8"))
    custom_theme = {
        "name": "CryptoMarketExplorerTheme.json",
        "dataColors": theme["dataColors"],
        "background": "#FFFFFF",
        "foreground": "#1E293B",
        "tableAccent": "#0EA5E9",
        "textClasses": {
            "label": {
                "color": "#475569",
                "fontSize": 10,
                "fontFace": "Segoe UI",
            },
            "callout": {
                "color": "#0F172A",
                "fontSize": 24,
                "fontFace": "Segoe UI Semibold",
                "fontWeight": "bold",
            },
            "title": {
                "color": "#0F172A",
                "fontSize": 12,
                "fontFace": "Segoe UI Semibold",
                "fontWeight": "bold",
            },
            "header": {
                "color": "#1E293B",
                "fontSize": 10,
                "fontFace": "Segoe UI Semibold",
                "fontWeight": "bold",
            },
            "largeTitle": {
                "color": "#0F172A",
                "fontSize": 16,
                "fontFace": "Segoe UI Semibold",
                "fontWeight": "bold",
            },
        },
    }
    write_json(
        REPORT
        / "StaticResources"
        / "RegisteredResources"
        / "CryptoMarketExplorerTheme.json",
        custom_theme,
    )

    write_json(
        REPORT / "definition" / "report.json",
        {
            "$schema": SCHEMA_REPORT,
            "themeCollection": {
                "baseTheme": {
                    "name": "Fluent2-CY26SU10",
                    "reportVersionAtImport": REPORT_VERSIONS,
                    "type": "SharedResources",
                },
                "customTheme": {
                    "name": "CryptoMarketExplorerTheme.json",
                    "reportVersionAtImport": REPORT_VERSIONS,
                    "type": "RegisteredResources",
                },
            },
            "resourcePackages": [
                {
                    "name": "SharedResources",
                    "type": "SharedResources",
                    "items": [
                        {
                            "name": "Fluent2-CY26SU10",
                            "path": "BaseThemes/Fluent2-CY26SU10.json",
                            "type": "BaseTheme",
                        }
                    ],
                },
                {
                    "name": "RegisteredResources",
                    "type": "RegisteredResources",
                    "items": [
                        {
                            "name": "CryptoMarketExplorerTheme.json",
                            "path": "CryptoMarketExplorerTheme.json",
                            "type": "CustomTheme",
                        }
                    ],
                },
            ],
            "settings": {
                "useStylableVisualContainerHeader": True,
                "exportDataMode": "AllowSummarized",
                "defaultDrillFilterOtherVisuals": True,
                "allowChangeFilterTypes": True,
                "useEnhancedTooltips": True,
                "useDefaultAggregateDisplayName": True,
            },
        },
    )

    write_json(
        REPORT / "definition.pbir",
        {
            "$schema": SCHEMA_PBIR,
            "version": "4.0",
            "datasetReference": {
                "byPath": {"path": "../CryptoMarketExplorer.SemanticModel"}
            },
        },
    )
    write_json(
        REPORT / ".platform",
        {
            "$schema": SCHEMA_PLATFORM,
            "metadata": {
                "type": "Report",
                "displayName": "CryptoMarketExplorer",
            },
            "config": {
                "version": "2.0",
                "logicalId": "c3f4b6c1-1a2d-4e5f-8a9b-0c1d2e3f4a5b",
            },
        },
    )

    # Base theme resource (official Fluent2 theme; copied verbatim).
    base_theme_dest = (
        REPORT
        / "StaticResources"
        / "SharedResources"
        / "BaseThemes"
        / "Fluent2-CY26SU10.json"
    )
    base_theme_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BASE_THEME_TEMPLATE, base_theme_dest)


# ---------------------------------------------------------------------------
# Semantic model (TMDL)
# ---------------------------------------------------------------------------

TABLE_COLUMNS = {
    "Symbols": [
        # name, dataType, sourceColumn, hidden, formatString, summarizeBy, isKey
        ("symbol", "string", "symbol", False, None, None, True),
        ("base_asset", "string", "base_asset", False, None, None, False),
        ("quote_asset", "string", "quote_asset", False, None, None, False),
        ("display_name", "string", "display_name", False, None, None, False),
    ],
    "Candles": [
        ("symbol", "string", "symbol", True, None, None, False),
        ("interval", "string", "interval", False, None, None, False),
        ("interval_minutes", "int64", "interval_minutes", True, "0", "none", False),
        ("bucket_start", "dateTime", "bucket_start", False, "yyyy-mm-dd hh:mm", "none", False),
        ("open", "double", "open", True, "#,0.00##", "none", False),
        ("high", "double", "high", True, "#,0.00##", "none", False),
        ("low", "double", "low", True, "#,0.00##", "none", False),
        ("close", "double", "close", True, "#,0.00##", "none", False),
        ("volume", "double", "volume", True, "#,0", "none", False),
        ("source_candles", "int64", "source_candles", True, "#,0", "none", False),
    ],
    "DailyCandles": [
        ("symbol", "string", "symbol", True, None, None, False),
        ("day_start", "dateTime", "day_start", False, "yyyy-mm-dd", "none", False),
        ("open", "double", "open", True, "#,0.00##", "none", False),
        ("high", "double", "high", True, "#,0.00##", "none", False),
        ("low", "double", "low", True, "#,0.00##", "none", False),
        ("close", "double", "close", True, "#,0.00##", "none", False),
        ("volume", "double", "volume", True, "#,0", "none", False),
        ("source_candles", "int64", "source_candles", True, "#,0", "none", False),
    ],
    "LatestPrices": [
        ("symbol", "string", "symbol", True, None, None, False),
        ("last_open_time", "dateTime", "last_open_time", True, "yyyy-mm-dd hh:mm", "none", False),
        ("last_close", "double", "last_close", True, "#,0.00##", "none", False),
        ("last_minute_volume", "double", "last_minute_volume", True, "#,0", "none", False),
    ],
    "SymbolSummary": [
        ("symbol", "string", "symbol", False, None, None, False),
        ("first_open_time", "dateTime", "first_open_time", False, "yyyy-mm-dd hh:mm", "none", False),
        ("last_open_time", "dateTime", "last_open_time", False, "yyyy-mm-dd hh:mm", "none", False),
        ("candle_count", "int64", "candle_count", True, "#,0", "none", False),
    ],
}

TABLE_SOURCES = {
    "Symbols": ("public", "symbols"),
    "Candles": ("reporting", "candles"),
    "DailyCandles": ("reporting", "daily_candles"),
    "LatestPrices": ("reporting", "latest_prices"),
    "SymbolSummary": ("reporting", "symbol_summary"),
}

M_TYPES = {
    "string": "type text",
    "int64": "Int64.Type",
    "double": "type number",
    "dateTime": "type datetimezone",
}

MEASURES = {
    "Symbols": [
        (
            "Selected Pair",
            "The selected pair name, or All pairs / Multiple pairs for a multi-selection.",
            'VAR PairCount = COUNTROWS ( VALUES ( Symbols[display_name] ) )\nVAR AllPairs = COUNTROWS ( ALL ( Symbols[display_name] ) )\nRETURN\n    IF (\n        PairCount = 1,\n        SELECTEDVALUE ( Symbols[display_name] ),\n        IF ( PairCount = AllPairs, "All pairs", "Multiple pairs" )\n    )',
            "@",
        ),
        (
            "Pairs Compared",
            "Number of trading pairs in the model.",
            "COUNTROWS ( Symbols )",
            "#,0",
        ),
    ],
    "Candles": [
        (
            "Close Price",
            "Close price at the current candle granularity.",
            "AVERAGE ( Candles[close] )",
            "#,0.00##",
        ),
        (
            "Period High",
            "Highest price in the current selection.",
            "MAX ( Candles[high] )",
            "#,0.00##",
        ),
        (
            "Period Low",
            "Lowest price in the current selection.",
            "MIN ( Candles[low] )",
            "#,0.00##",
        ),
        (
            "Period Volume",
            "Total traded volume in the current selection.",
            "SUM ( Candles[volume] )",
            "#,0",
        ),
        (
            "Candle Count",
            "Number of candle rows in the current selection.",
            "COUNTROWS ( Candles )",
            "#,0",
        ),
        (
            "All Interval Rows",
            "Number of candle rows across all intervals, ignoring the interval slicer.",
            "CALCULATE ( COUNTROWS ( Candles ), REMOVEFILTERS ( Candles[interval] ) )",
            "#,0",
        ),
        (
            "Period Return %",
            "Return from the first open to the last close of the selected window.",
            "VAR FirstOpen =\n    CALCULATE ( MIN ( Candles[open] ), FIRSTDATE ( Candles[bucket_start] ) )\nVAR LastClose =\n    CALCULATE ( MAX ( Candles[close] ), LASTDATE ( Candles[bucket_start] ) )\nRETURN\n    DIVIDE ( LastClose - FirstOpen, FirstOpen )",
            "#,0.0%;-#,0.0%;#,0.0%",
        ),
        (
            "Data Through",
            "Latest candle timestamp in the current selection.",
            "MAX ( Candles[bucket_start] )",
            "yyyy-mm-dd hh:mm",
        ),
    ],
    "LatestPrices": [
        (
            "Latest Close",
            "Last close of the newest imported minute for the selected pair.",
            "IF (\n    HASONEVALUE ( Symbols[symbol] ),\n    SUM ( LatestPrices[last_close] )\n)",
            "#,0.00##",
        ),
    ],
    "DailyCandles": [
        (
            "Daily Close",
            "Close price for the day.",
            "AVERAGE ( DailyCandles[close] )",
            "#,0.00##",
        ),
        (
            "Daily Volume",
            "Total traded volume for the day.",
            "SUM ( DailyCandles[volume] )",
            "#,0",
        ),
        (
            "Daily Return %",
            "Daily return for the current symbol and day.",
            "DIVIDE (\n    SUM ( DailyCandles[close] ) - SUM ( DailyCandles[open] ),\n    SUM ( DailyCandles[open] )\n)",
            "#,0.0%;-#,0.0%;#,0.0%",
        ),
        (
            "30-Day High",
            "Highest daily high in the last 30 days of the current selection.",
            "CALCULATE (\n    MAX ( DailyCandles[high] ),\n    DATESINPERIOD (\n        DailyCandles[day_start],\n        MAX ( DailyCandles[day_start] ),\n        -30,\n        DAY\n    )\n)",
            "#,0.00##",
        ),
        (
            "30-Day Low",
            "Lowest daily low in the last 30 days of the current selection.",
            "CALCULATE (\n    MIN ( DailyCandles[low] ),\n    DATESINPERIOD (\n        DailyCandles[day_start],\n        MAX ( DailyCandles[day_start] ),\n        -30,\n        DAY\n    )\n)",
            "#,0.00##",
        ),
        (
            "Days Covered",
            "Number of complete UTC days available for the current selection.",
            "DISTINCTCOUNT ( DailyCandles[day_start] )",
            "#,0",
        ),
        (
            "Average Daily Volume",
            "Average daily volume over the selected period.",
            "AVERAGEX (\n    VALUES ( DailyCandles[day_start] ),\n    CALCULATE ( SUM ( DailyCandles[volume] ) )\n)",
            "#,0",
        ),
    ],
    "SymbolSummary": [
        (
            "1m Candles",
            "Stored one-minute candles for the current pair.",
            "SUM ( SymbolSummary[candle_count] )",
            "#,0",
        ),
    ],
}


def tmdl_quote(name: str) -> str:
    if name and (name[0].isalpha() or name[0] == "_") and all(
        c.isalnum() or c == "_" for c in name
    ):
        return name
    return "'" + name.replace("'", "''") + "'"


def indent_lines(text: str, prefix: str) -> list[str]:
    return [prefix + line if line else "" for line in text.split("\n")]


def tmdl_table(name: str, *, data_category: str | None = None) -> str:
    lines = [f"table {tmdl_quote(name)}"]
    if data_category:
        lines.append(f"\tdataCategory: {data_category}")

    for (
        col_name,
        data_type,
        source_col,
        hidden,
        fmt,
        summarize,
        is_key,
    ) in TABLE_COLUMNS[name]:
        lines.append(f"\tcolumn {tmdl_quote(col_name)}")
        lines.append(f"\t\tdataType: {data_type}")
        if is_key:
            lines.append("\t\tisKey")
        if hidden:
            lines.append("\t\tisHidden")
            lines.append("\t\tisAvailableInMdx: false")
        if fmt:
            lines.append(f"\t\tformatString: {fmt}")
        if summarize:
            lines.append(f"\t\tsummarizeBy: {summarize}")
        if source_col:
            lines.append(f"\t\tsourceColumn: {tmdl_quote(source_col)}")

    # Calculated column required to join the timestamp to the date table.
    if name == "Candles":
        lines.extend(
            [
                "\tcolumn bucket_date = DATE ( YEAR ( Candles[bucket_start] ), MONTH ( Candles[bucket_start] ), DAY ( Candles[bucket_start] ) )",
                "\t\tdataType: dateTime",
                "\t\tisHidden",
                "\t\tisAvailableInMdx: false",
                "\t\tformatString: yyyy-mm-dd",
                "\t\tsummarizeBy: none",
            ]
        )

    for measure_name, description, expression, fmt in MEASURES.get(name, []):
        if description:
            lines.append(f"\t/// {description}")
        if "\n" in expression:
            lines.append(f"\tmeasure {tmdl_quote(measure_name)} =")
            lines.extend(indent_lines(expression, "\t\t\t"))
        else:
            lines.append(
                f"\tmeasure {tmdl_quote(measure_name)} = {expression}"
            )
        if fmt:
            lines.append(f"\t\tformatString: {fmt}")

    if name == "Date":
        lines.extend(
            [
                "\tpartition Date = calculated",
                "\t\tmode: import",
                "\t\tsource = CALENDAR ( DATE ( 2026, 9, 28 ), DATE ( 2026, 10, 27 ) )",
            ]
        )
    else:
        schema, item = TABLE_SOURCES[name]
        m_lines = [
            "let",
            "    Source = PostgreSQL.Database(PostgresServer, PostgresDatabase),",
            f'    Data = Source{{[Schema = "{schema}", Item = "{item}"]}}[Data],',
            "    ChangedTypes = Table.TransformColumnTypes(",
            "        Data,",
            "        {",
        ]
        type_pairs = [
            f'            {{"{col_name}", {M_TYPES[data_type]}}}'
            for col_name, data_type, *_ in TABLE_COLUMNS[name]
        ]
        for index, pair in enumerate(type_pairs):
            m_lines.append(pair + ("," if index < len(type_pairs) - 1 else ""))
        m_lines.extend(
            [
                "        }",
                "    )",
                "in",
                "    ChangedTypes",
            ]
        )
        lines.append(f"\tpartition {tmdl_quote(name)} = m")
        lines.append("\t\tmode: import")
        lines.append("\t\tsource =")
        lines.extend(indent_lines("\n".join(m_lines), "\t\t\t"))

    return "\n".join(lines) + "\n"


def build_model() -> None:
    definition = MODEL / "definition"
    write_text(
        definition / "database.tmdl",
        "database\n\tcompatibilityLevel: 1600\n",
    )
    write_text(
        definition / "model.tmdl",
        "\n".join(
            [
                "model Model",
                "\tculture: en-US",
                "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
                "\tsourceQueryCulture: en-US",
                "\tdataAccessOptions",
                "\t\tlegacyRedirects",
                "\t\treturnErrorValuesAsNull",
                "",
                "annotation __PBI_TimeIntelligenceEnabled = 0",
                'annotation PBI_QueryOrder = ["Symbols","Date","Candles","DailyCandles","LatestPrices","SymbolSummary"]',
                "",
            ]
        ),
    )
    write_text(
        definition / "expressions.tmdl",
        "\n".join(
            [
                'expression PostgresServer = "localhost:5432" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]',
                'expression PostgresDatabase = "crypto_market_explorer" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]',
                "",
            ]
        ),
    )
    write_text(
        definition / "relationships.tmdl",
        "\n\n".join(
            [
                "relationship Symbols_Candles\n\tfromColumn: Candles.symbol\n\ttoColumn: Symbols.symbol",
                "relationship Symbols_DailyCandles\n\tfromColumn: DailyCandles.symbol\n\ttoColumn: Symbols.symbol",
                "relationship Symbols_LatestPrices\n\tfromColumn: LatestPrices.symbol\n\ttoColumn: Symbols.symbol",
                "relationship Symbols_SymbolSummary\n\tfromColumn: SymbolSummary.symbol\n\ttoColumn: Symbols.symbol",
                "relationship Date_Candles\n\tfromColumn: Candles.bucket_date\n\ttoColumn: Date.Date",
                "relationship Date_DailyCandles\n\tfromColumn: DailyCandles.day_start\n\ttoColumn: Date.Date",
            ]
        )
        + "\n",
    )

    for name in TABLE_COLUMNS:
        write_text(definition / "tables" / f"{name}.tmdl", tmdl_table(name))

    write_text(
        definition / "tables" / "Date.tmdl",
        "\n".join(
            [
                "table Date",
                "\tdataCategory: Time",
                "\tcolumn Date",
                "\t\tdataType: dateTime",
                "\t\tisKey",
                "\t\tformatString: yyyy-mm-dd",
                "\t\tsummarizeBy: none",
                "\tpartition Date = calculated",
                "\t\tmode: import",
                "\t\tsource = CALENDAR ( DATE ( 2026, 9, 28 ), DATE ( 2026, 10, 27 ) )",
                "",
            ]
        ),
    )

    write_json(
        MODEL / "definition.pbism",
        {"$schema": SCHEMA_PBISM, "version": "4.0", "settings": {}},
    )
    write_json(
        MODEL / ".platform",
        {
            "$schema": SCHEMA_PLATFORM,
            "metadata": {
                "type": "SemanticModel",
                "displayName": "CryptoMarketExplorer",
            },
            "config": {
                "version": "2.0",
                "logicalId": "7a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d",
            },
        },
    )


# ---------------------------------------------------------------------------
# Project file
# ---------------------------------------------------------------------------


def build_project_file() -> None:
    write_json(
        OUT / "CryptoMarketExplorer.pbip",
        {
            "$schema": SCHEMA_PBIP,
            "version": "1.0",
            "artifacts": [
                {"report": {"path": "CryptoMarketExplorer.Report"}}
            ],
            "settings": {"enableAutoRecovery": True},
        },
    )
    write_text(
        OUT / ".gitignore",
        "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n",
    )
    write_text(
        OUT / "README.txt",
        "\n".join(
            [
                "Crypto Market Explorer - Power BI project (PBIP)",
                "",
                "A .pbix is produced by Power BI Desktop on Windows; this folder is the",
                "text-based Power BI Project that Desktop opens directly.",
                "",
                "Windows steps",
                "-------------",
                "1. Install the latest 64-bit Power BI Desktop.",
                "2. Copy this whole folder (keep the .pbip, .Report and .SemanticModel",
                "   together) to Windows.",
                "3. Start the project database and make it reachable:",
                "     docker compose up -d db backend",
                "   Default connection: localhost:5432 / crypto_market_explorer",
                "   User: crypto   Password: crypto_dev_password",
                "   If Desktop runs in a VM or on another PC, use",
                "   Home > Transform data > Edit parameters > PostgresServer and set the",
                "   database host's LAN IP instead of localhost.",
                "4. Open CryptoMarketExplorer.pbip.",
                "   The first open has no cached data, so visuals are blank.",
                "5. Home > Refresh, enter the database credentials, and wait for the import.",
                "   If Power BI asks for Npgsql, install the 64-bit Npgsql provider and",
                "   restart Desktop.",
                "6. File > Save as > Power BI file (*.pbix). The refreshed .pbix embeds the",
                "   imported data and is self-contained.",
                "",
                "Pages: Market Overview, Compare Pairs, Data Quality.",
                "The pair slicer starts on Bitcoin, the timeframe on 15m, and the date",
                "slicer covers 2026-09-28 to 2026-10-27 (UTC).",
                "",
                "See powerbi/README.md section 1.1 in the repository for the full",
                "explanation and troubleshooting.",
                "",
            ]
        ),
    )


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    build_model()
    build_report()
    build_project_file()

    print(f"Built {OUT}")
    print(f"Open on Windows: {OUT / 'CryptoMarketExplorer.pbip'}")


if __name__ == "__main__":
    main()
