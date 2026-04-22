from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.database import ImportedPortfolioPositionDB, get_db_ctx, init_db
from api.services.portfolio_import_service import is_tracking_board_source


def main() -> None:
    init_db()
    with get_db_ctx() as db:
        rows = db.query(ImportedPortfolioPositionDB).all()
        isolated_rows = [row for row in rows if not is_tracking_board_source(row.source)]
        source_counts: dict[str, int] = {}
        for row in isolated_rows:
            source_counts[row.source or ""] = source_counts.get(row.source or "", 0) + 1
            db.delete(row)
        db.commit()

    print(f"deleted={len(isolated_rows)}")
    for source, count in sorted(source_counts.items()):
        print(f"{source}: {count}")


if __name__ == "__main__":
    main()
