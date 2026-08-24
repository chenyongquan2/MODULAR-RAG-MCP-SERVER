"""把一份已归档的评估报告标记为其 collection 的当前基线。

change: BACKLOG 梯队一 B2。仪表盘之外唯一的基线标记入口 —— 此前只能从
Streamlit 面板点,批处理场景(切换金标代次后重标基线)没有非交互路径。

⚠️ **不要并发跑它**。`BaselineManager._write_store_atomic` 是原子写但**无锁**
(`mkstemp` + `os.replace`),并发标基线不会写坏文件,但会**静默丢掉一次更新且
不报错** —— 本项目的招牌失败模式。

用法:
    python -u scripts/dev/mark_baseline.py --report-id <uuid> --marked-by <label>
    python -u scripts/dev/mark_baseline.py --report-id <uuid> --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.settings import load_settings  # noqa: E402
from src.observability.evaluation.baseline_manager import BaselineManager  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report-id", required=True, help="已归档报告的 UUID4")
    ap.add_argument("--marked-by", default="manual", help="标记者标识,会写进 baselines.json")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要标记的内容与当前基线,不写 baselines.json",
    )
    args = ap.parse_args()

    settings = load_settings()
    manager = BaselineManager(settings)
    report = manager.load_report(args.report_id)

    # collection / status / 检索模式全部从报告本身读,不让调用方手填 ——
    # 手填就有填错的可能,而填错的基线会静默污染之后每一次 delta。
    collection = str(report.get("collection") or "")
    if not collection:
        print("报告里没有 collection 字段,无法确定该基线绑定哪个集合", file=sys.stderr)
        return 2
    status = str(report.get("acceptance_status") or "fail")
    retrieval_mode = str(report.get("retrieval_mode") or "")
    corpus_validity = str(report.get("corpus_validity") or "")
    labeling_method = str(report.get("labeling_method") or "dense-top-k")

    prev = manager.get_current_baseline(collection)
    print(f"collection        : {collection}")
    print(f"labeling_method   : {labeling_method}")
    print(f"acceptance_status : {status}")
    print(f"retrieval_mode    : {retrieval_mode or '(未标注)'}")
    print(f"corpus_validity   : {corpus_validity or '(未标注)'}")
    print(f"当前基线          : {prev.report_id if prev else '(无)'}")
    if prev is not None:
        print("  → 会被降级进 history,不会删除")

    if args.dry_run:
        print("\n[dry-run] 未写入 baselines.json")
        return 0

    baseline = manager.mark_as_baseline(
        report_id=args.report_id,
        collection=collection,
        acceptance_status=status,  # type: ignore[arg-type]
        marked_by=args.marked_by,
        retrieval_mode=retrieval_mode,
        corpus_validity=corpus_validity,
    )
    # 不要在这里用 emoji:Windows 控制台默认 GBK 编码,写 emoji 会抛
    # UnicodeEncodeError,而它发生在 mark_as_baseline **之后** ——
    # 结果是「基线其实标成功了、脚本却报错退出」,最容易被误读成失败。
    print("")
    print("[OK] marked as baseline: "
          f"{baseline.report_id} (marked_by={args.marked_by})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
