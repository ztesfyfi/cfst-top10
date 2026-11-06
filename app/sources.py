import ipaddress
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 100_000

@dataclass(frozen=True)
class ParseResult:
    entries: tuple[str, ...]
    invalid: int
    duplicates: int

def parse_ip_list(raw: str) -> ParseResult:
    if len(raw.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("来源文件超过 8 MiB")
    values, seen, invalid, duplicates = [], set(), 0, 0
    for line in raw.splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        try:
            parsed = ipaddress.ip_network(value, strict=False) if "/" in value else ipaddress.ip_address(value)
            normalized = str(parsed)
        except ValueError:
            invalid += 1
            continue
        if normalized in seen:
            duplicates += 1
            continue
        seen.add(normalized)
        values.append(normalized)
        if len(values) > MAX_ENTRIES:
            raise ValueError(f"单个来源超过 {MAX_ENTRIES} 条限制")
    return ParseResult(tuple(values), invalid, duplicates)

def merge_ip_sources(contents: Iterable[str]) -> ParseResult:
    values, seen, invalid, duplicates = [], set(), 0, 0
    for raw in contents:
        parsed = parse_ip_list(raw)
        invalid += parsed.invalid
        duplicates += parsed.duplicates
        for value in parsed.entries:
            if value in seen:
                duplicates += 1
                continue
            seen.add(value)
            values.append(value)
            if len(values) > MAX_ENTRIES:
                raise ValueError(f"合并结果超过 {MAX_ENTRIES} 条限制")
    return ParseResult(tuple(values), invalid, duplicates)

def read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("来源文件超过 8 MiB")
    return raw.decode("utf-8-sig")
