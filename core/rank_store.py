"""Son siralama sonuclarini kaydet / yukle."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from rank_checker import RankResult

BASE_DIR = Path(__file__).resolve().parent.parent
RANK_FILE = BASE_DIR / "data" / "rank_latest.json"


@dataclass
class RankSnapshot:
    updated_at: str
    product_url: str
    product_id: str
    results: list[RankResult]

    @property
    def display_time(self) -> str:
        try:
            dt = datetime.fromisoformat(self.updated_at)
            return dt.strftime("%d.%m.%Y %H:%M:%S")
        except Exception:
            return self.updated_at


def _result_to_dict(r: RankResult) -> dict:
    return asdict(r)


def _result_from_dict(d: dict) -> RankResult:
    return RankResult(
        keyword=str(d.get("keyword", "")),
        product_id=str(d.get("product_id", "")),
        found=bool(d.get("found", False)),
        page=int(d.get("page", 0)),
        position_on_page=int(d.get("position_on_page", 0)),
        estimated_rank=int(d.get("estimated_rank", 0)),
        products_on_page=int(d.get("products_on_page", 0)),
        pages_scanned=int(d.get("pages_scanned", 0)),
        timestamp=str(d.get("timestamp", "")),
    )


def save_snapshot(product_url: str, results: list[RankResult]) -> RankSnapshot:
    pid = results[0].product_id if results else ""
    snap = RankSnapshot(
        updated_at=datetime.now().isoformat(timespec="seconds"),
        product_url=product_url.strip(),
        product_id=pid,
        results=list(results),
    )
    RANK_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": snap.updated_at,
        "product_url": snap.product_url,
        "product_id": snap.product_id,
        "results": [_result_to_dict(r) for r in snap.results],
    }
    RANK_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return snap


def load_snapshot() -> RankSnapshot | None:
    if not RANK_FILE.is_file():
        return None
    try:
        data = json.loads(RANK_FILE.read_text(encoding="utf-8"))
        results = [_result_from_dict(x) for x in data.get("results", [])]
        return RankSnapshot(
            updated_at=str(data.get("updated_at", "")),
            product_url=str(data.get("product_url", "")),
            product_id=str(data.get("product_id", "")),
            results=results,
        )
    except Exception:
        return None
