from __future__ import annotations

import csv
import json
import traceback
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from flight_tracker.timezone import now_taipei, now_taipei_iso


DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
RANGE_QUERY_DIR = DATA_ROOT / "range_queries"

SUCCESS = "SUCCESS"
TIMEOUT = "TIMEOUT"
NO_RESULT = "NO_RESULT"
PARSE_ERROR = "PARSE_ERROR"
BLOCKED = "BLOCKED"
UNKNOWN_ERROR = "UNKNOWN_ERROR"

VALID_STATUSES = {SUCCESS, TIMEOUT, NO_RESULT, PARSE_ERROR, BLOCKED, UNKNOWN_ERROR}

RANGE_QUERY_FIELDS = [
    "query_id",
    "route_id",
    "route_name",
    "departure_date",
    "return_date",
    "source",
    "airline",
    "departure_time",
    "return_time",
    "price",
    "status",
    "error_message",
    "query_started_at",
    "query_finished_at",
    "url",
    "debug_screenshot",
    "debug_html",
    "debug_dom",
    "selected_lowest",
]


@dataclass(frozen=True)
class RangeQueryRow:
    query_id: str
    route_id: str
    route_name: str
    departure_date: str
    return_date: str
    source: str
    airline: str = ""
    departure_time: str = ""
    return_time: str = ""
    price: int | str = ""
    status: str = NO_RESULT
    error_message: str = ""
    query_started_at: str = ""
    query_finished_at: str = ""
    url: str = ""
    debug_screenshot: str = ""
    debug_html: str = ""
    debug_dom: str = ""
    selected_lowest: str = ""


@dataclass(frozen=True)
class RangeSearchSummary:
    enabled: bool
    query_id: str
    route_id: str
    route_name: str
    departure_start: str
    departure_end: str
    return_start: str
    return_end: str
    total_combinations: int
    success_combinations: int
    failed_combinations: int
    best_quote: dict[str, Any] | None
    detail_path: str
    warning: str = ""
    error: str = ""

    @property
    def log_line(self) -> str:
        base = f"範圍查詢完成：成功 {self.success_combinations} 組，失敗 {self.failed_combinations} 組"
        return f"{base}。{self.warning}" if self.warning else base

    def normalized(self) -> dict[str, Any]:
        data = asdict(self)
        data["log"] = self.log_line
        return data


def range_config(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("range_search") or {}


def is_enabled(config: dict[str, Any]) -> bool:
    return bool(range_config(config).get("enabled", False))


def parse_date(value: str | None, field_name: str) -> date:
    if not value:
        raise ValueError(f"{field_name} is required.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD.") from exc


def validate_range_config(config: dict[str, Any]) -> tuple[date, date, date, date]:
    settings = range_config(config)
    departure_start = parse_date(settings.get("departure_start_date"), "departure_start_date")
    departure_end = parse_date(settings.get("departure_end_date"), "departure_end_date")
    return_start = parse_date(settings.get("return_start_date"), "return_start_date")
    return_end = parse_date(settings.get("return_end_date"), "return_end_date")

    if departure_start > departure_end:
        raise ValueError("departure_start_date cannot be later than departure_end_date.")
    if return_start > return_end:
        raise ValueError("return_start_date cannot be later than return_end_date.")
    if return_end <= departure_start:
        raise ValueError("At least one return date must be later than the departure date.")
    return departure_start, departure_end, return_start, return_end


def date_range(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def generate_date_pairs(
    departure_start: date,
    departure_end: date,
    return_start: date,
    return_end: date,
) -> list[tuple[str, str]]:
    pairs = []
    for departure in date_range(departure_start, departure_end):
        for return_date in date_range(return_start, return_end):
            if return_date > departure:
                pairs.append((departure.isoformat(), return_date.isoformat()))
    return pairs


def config_with_dates(config: dict[str, Any], departure_date: str, return_date: str) -> dict[str, Any]:
    query_config = deepcopy(config)
    query_config.setdefault("trip", {})
    query_config["trip"]["departure_date"] = departure_date
    query_config["trip"]["return_date"] = return_date
    return query_config


def classify_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}".lower()
    if "timeout" in text:
        return TIMEOUT
    if "captcha" in text or "blocked" in text or "robot" in text:
        return BLOCKED
    if "parse" in text:
        return PARSE_ERROR
    return UNKNOWN_ERROR


def source_url(source: Any, config: dict[str, Any], route: dict[str, Any]) -> str:
    build_url = getattr(source, "build_url", None)
    if not build_url:
        return ""
    try:
        return str(build_url(config, route))
    except Exception:
        return ""


def positive_price(value: Any) -> int | None:
    try:
        price = int(value)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def validate_quote(quote: dict[str, Any], departure_date: str, return_date: str) -> str:
    if positive_price(quote.get("price")) is None:
        return "price must be a positive integer."
    if not str(quote.get("airline") or "").strip():
        return "airline cannot be empty."
    if not str(quote.get("outbound_time") or "").strip():
        return "outbound_time cannot be empty."
    if not str(quote.get("return_time") or "").strip():
        return "return_time cannot be empty."
    if quote.get("departure_date") != departure_date:
        return "result departure_date does not match requested date."
    if quote.get("return_date") != return_date:
        return "result return_date does not match requested date."
    if parse_date(return_date, "return_date") <= parse_date(departure_date, "departure_date"):
        return "return_date must be later than departure_date."
    return ""


def row_from_quote(
    *,
    query_id: str,
    route: dict[str, Any],
    departure_date: str,
    return_date: str,
    source_name: str,
    quote: dict[str, Any],
    status: str,
    error_message: str,
    started_at: str,
    finished_at: str,
    url: str,
) -> RangeQueryRow:
    return RangeQueryRow(
        query_id=query_id,
        route_id=route.get("id", ""),
        route_name=route.get("name", ""),
        departure_date=departure_date,
        return_date=return_date,
        source=source_name,
        airline=str(quote.get("airline") or ""),
        departure_time=str(quote.get("outbound_time") or ""),
        return_time=str(quote.get("return_time") or ""),
        price=positive_price(quote.get("price")) or "",
        status=status,
        error_message=error_message,
        query_started_at=started_at,
        query_finished_at=finished_at,
        url=url or str(quote.get("booking_url") or ""),
        debug_screenshot=str(quote.get("debug_screenshot") or ""),
        debug_html=str(quote.get("debug_html") or ""),
        debug_dom=str(quote.get("debug_dom") or ""),
    )


def choose_best(rows: list[RangeQueryRow]) -> RangeQueryRow | None:
    candidates = [row for row in rows if row.status == SUCCESS and positive_price(row.price) is not None]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda row: (
            int(row.price),
            row.departure_date,
            row.return_date,
            row.airline,
            row.departure_time,
            row.return_time,
        ),
    )


def row_to_best_quote(row: RangeQueryRow) -> dict[str, Any]:
    return {
        "departure_date": row.departure_date,
        "return_date": row.return_date,
        "airline": row.airline,
        "departure_time": row.departure_time,
        "return_time": row.return_time,
        "price": int(row.price),
        "source": row.source,
        "success": True,
    }


def write_rows(path: Path, rows: list[RangeQueryRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RANGE_QUERY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)


def debug_dir_for(query_id: str, route_id: str) -> Path:
    return RANGE_QUERY_DIR / query_id / route_id


def range_debug_config(config: dict[str, Any], query_id: str, route: dict[str, Any]) -> dict[str, Any]:
    query_config = deepcopy(config)
    settings = query_config.setdefault("range_search", {})
    if settings.get("debug"):
        settings["_debug_dir"] = str(debug_dir_for(query_id, route.get("id", "route")))
    return query_config


def append_source_result_rows(
    *,
    rows: list[RangeQueryRow],
    successful_pairs: set[tuple[str, str]],
    query_id: str,
    route: dict[str, Any],
    source_name: str,
    source: Any | None,
    query_config: dict[str, Any],
    departure_date: str,
    return_date: str,
    started_at: str,
    quotes: list[Any] | None = None,
    exc: Exception | None = None,
) -> None:
    url = source_url(source, query_config, route) if source else ""
    if exc:
        rows.append(
            RangeQueryRow(
                query_id=query_id,
                route_id=route.get("id", ""),
                route_name=route.get("name", ""),
                departure_date=departure_date,
                return_date=return_date,
                source=source_name,
                status=classify_error(exc),
                error_message=f"{exc}\n{''.join(traceback.format_exception(type(exc), exc, exc.__traceback__, limit=3))}",
                query_started_at=started_at,
                query_finished_at=now_taipei_iso(),
                url=url,
            )
        )
        return

    finished_at = now_taipei_iso()
    normalized_quotes = [quote.normalized() for quote in quotes or []]
    if not normalized_quotes:
        rows.append(
            RangeQueryRow(
                query_id=query_id,
                route_id=route.get("id", ""),
                route_name=route.get("name", ""),
                departure_date=departure_date,
                return_date=return_date,
                source=source_name,
                status=NO_RESULT,
                error_message="No valid quote returned by source.",
                query_started_at=started_at,
                query_finished_at=finished_at,
                url=url,
            )
        )
        return

    for quote in normalized_quotes:
        error_message = validate_quote(quote, departure_date, return_date)
        status = PARSE_ERROR if error_message else SUCCESS
        if status == SUCCESS:
            successful_pairs.add((departure_date, return_date))
        rows.append(
            row_from_quote(
                query_id=query_id,
                route=route,
                departure_date=departure_date,
                return_date=return_date,
                source_name=source_name,
                quote=quote,
                status=status,
                error_message=error_message,
                started_at=started_at,
                finished_at=finished_at,
                url=url,
            )
        )


def run_range_search(
    config: dict[str, Any],
    route: dict[str, Any],
    source_registry: dict[str, Any],
    query_id: str | None = None,
) -> RangeSearchSummary:
    settings = range_config(config)
    current_query_id = query_id or now_taipei().strftime("%Y%m%d_%H%M%S")
    detail_path = RANGE_QUERY_DIR / f"{current_query_id}_{route.get('id', 'route')}.csv"

    try:
        departure_start, departure_end, return_start, return_end = validate_range_config(config)
    except ValueError as exc:
        summary = RangeSearchSummary(
            enabled=True,
            query_id=current_query_id,
            route_id=route.get("id", ""),
            route_name=route.get("name", ""),
            departure_start=str(settings.get("departure_start_date") or ""),
            departure_end=str(settings.get("departure_end_date") or ""),
            return_start=str(settings.get("return_start_date") or ""),
            return_end=str(settings.get("return_end_date") or ""),
            total_combinations=0,
            success_combinations=0,
            failed_combinations=0,
            best_quote=None,
            detail_path=str(detail_path),
            error=str(exc),
        )
        write_rows(detail_path, [])
        return summary

    pairs = generate_date_pairs(departure_start, departure_end, return_start, return_end)
    source_names = config.get("sources", {}).get("enabled", ["mock"])
    if config.get("sources", {}).get("fallback_to_mock") and "mock" not in source_names:
        source_names = [*source_names, "mock"]

    rows: list[RangeQueryRow] = []
    successful_pairs: set[tuple[str, str]] = set()

    for source_name in source_names:
        source_cls = source_registry.get(source_name)
        if not source_cls:
            for departure_date, return_date in pairs:
                rows.append(
                    RangeQueryRow(
                        query_id=current_query_id,
                        route_id=route.get("id", ""),
                        route_name=route.get("name", ""),
                        departure_date=departure_date,
                        return_date=return_date,
                        source=source_name,
                        status=UNKNOWN_ERROR,
                        error_message=f"Unknown source: {source_name}",
                        query_started_at=now_taipei_iso(),
                        query_finished_at=now_taipei_iso(),
                    )
                )
            continue

        source = source_cls()
        search_range_dates = getattr(source, "search_range_dates", None)
        if search_range_dates:
            query_config = range_debug_config(deepcopy(config), current_query_id, route)
            for result in search_range_dates(query_config, route, pairs):
                departure_date, return_date, quotes, exc = result[:4]
                started_at = result[4] if len(result) > 4 else now_taipei_iso()
                append_source_result_rows(
                    rows=rows,
                    successful_pairs=successful_pairs,
                    query_id=current_query_id,
                    route=route,
                    source_name=source_name,
                    source=source,
                    query_config=config_with_dates(query_config, departure_date, return_date),
                    departure_date=departure_date,
                    return_date=return_date,
                    started_at=started_at,
                    quotes=quotes,
                    exc=exc,
                )
            continue

        for departure_date, return_date in pairs:
            started_at = now_taipei_iso()
            query_config = range_debug_config(config_with_dates(config, departure_date, return_date), current_query_id, route)
            try:
                quotes = source.search(query_config, route)
                append_source_result_rows(
                    rows=rows,
                    successful_pairs=successful_pairs,
                    query_id=current_query_id,
                    route=route,
                    source_name=source_name,
                    source=source,
                    query_config=query_config,
                    departure_date=departure_date,
                    return_date=return_date,
                    started_at=started_at,
                    quotes=quotes,
                )
            except Exception as exc:
                append_source_result_rows(
                    rows=rows,
                    successful_pairs=successful_pairs,
                    query_id=current_query_id,
                    route=route,
                    source_name=source_name,
                    source=source,
                    query_config=query_config,
                    departure_date=departure_date,
                    return_date=return_date,
                    started_at=started_at,
                    exc=exc,
                )

    best = choose_best(rows)
    if best:
        rows = [
            RangeQueryRow(**{**asdict(row), "selected_lowest": "YES" if row == best else ""})
            for row in rows
        ]

    write_rows(detail_path, rows)

    total = len(pairs)
    success_count = len(successful_pairs)
    failed_count = max(0, total - success_count)
    warning = ""
    if total and success_count / total < float(settings.get("success_warning_threshold", 0.5)):
        warning = f"警告：範圍查詢成功比例過低 ({success_count}/{total})"

    return RangeSearchSummary(
        enabled=True,
        query_id=current_query_id,
        route_id=route.get("id", ""),
        route_name=route.get("name", ""),
        departure_start=departure_start.isoformat(),
        departure_end=departure_end.isoformat(),
        return_start=return_start.isoformat(),
        return_end=return_end.isoformat(),
        total_combinations=total,
        success_combinations=success_count,
        failed_combinations=failed_count,
        best_quote=row_to_best_quote(best) if best else None,
        detail_path=str(detail_path),
        warning=warning,
    )


def save_debug_artifact(path: Path, content: str | bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return str(path)


def save_debug_manifest(path: Path, payload: dict[str, Any]) -> str:
    return save_debug_artifact(path, json.dumps(payload, ensure_ascii=False, indent=2))
