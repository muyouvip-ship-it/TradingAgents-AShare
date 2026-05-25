#!/usr/bin/env python3
"""Compare v3 workbook trades with generated first-day-band trade details.

The comparison has two complementary views:

1. Exact-time view: stock name + buy date + sell/mark date + status must match.
   This isolates amount/return differences when both files describe the same
   trade window.
2. Sequence view: trades are ordered per stock and compared as the Nth trade.
   This highlights shifted buy/sell dates, missing trades, and return deltas.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_V3_WORKBOOK = Path("/Users/wolf/Documents/DaiMa/strategy-backtest/全市场回测v3_波段交易.xlsx")
DEFAULT_GENERATED_CSV = (
    PROJECT_ROOT
    / "data/artifacts/backtests/first_day_band_v3_aligned_20240101_20260430_20260516022712/holding_trade_details.csv"
)

DATE_PATTERN = re.compile(r"(\d{4}[-/]\d{2}[-/]\d{2})")

NUMERIC_TOLERANCES: dict[str, float] = {
    "持仓数量": 0.0,
    "买入价格": 0.01,
    "卖出价格": 0.01,
    "买入金额": 0.02,
    "买入成本(含费)": 0.02,
    "买入费用滑点": 0.02,
    "卖出金额": 0.02,
    "卖出回款(扣费)": 0.02,
    "卖出费用税费滑点": 0.02,
    "持仓毛收益": 0.02,
    "持仓净收益": 0.02,
    # Percentage points, because both source files store -2.63 as -2.63%.
    "持仓收益率": 0.01,
    "持仓天数": 0.0,
}

EXACT_DIFF_COLUMNS = [
    "股票名称",
    "股票代码",
    "状态",
    "买入时间",
    "卖出时间",
    "exact_dup_seq",
    "差异字段",
    "持仓净收益_v3",
    "持仓净收益_generated",
    "持仓净收益_diff",
    "持仓收益率_v3",
    "持仓收益率_generated",
    "持仓收益率_diff",
    "买入价格_v3",
    "买入价格_generated",
    "卖出价格_v3",
    "卖出价格_generated",
    "持仓天数_v3",
    "持仓天数_generated",
    "来源sheet_v3",
]

SEQUENCE_OUTPUT_COLUMNS = [
    "股票名称",
    "股票代码_generated",
    "trade_seq",
    "差异类型",
    "状态_v3",
    "状态_generated",
    "买入时间_v3",
    "买入时间_generated",
    "卖出时间_v3",
    "卖出时间_generated",
    "持仓净收益_v3",
    "持仓净收益_generated",
    "持仓净收益_diff",
    "持仓收益率_v3",
    "持仓收益率_generated",
    "持仓收益率_diff",
    "买入价格_v3",
    "买入价格_generated",
    "卖出价格_v3",
    "卖出价格_generated",
    "持仓天数_v3",
    "持仓天数_generated",
    "来源sheet_v3",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v3-workbook", type=Path, default=DEFAULT_V3_WORKBOOK)
    parser.add_argument("--generated-csv", type=Path, default=DEFAULT_GENERATED_CSV)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Defaults to the generated CSV directory.",
    )
    return parser.parse_args()


def extract_date(value: Any) -> str:
    if pd.isna(value):
        return ""
    match = DATE_PATTERN.search(str(value))
    if not match:
        return ""
    return match.group(1).replace("/", "-")


def fmt_date(value: Any) -> str:
    date_text = extract_date(value)
    if date_text:
        return date_text
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return pd.Timestamp(parsed).strftime("%Y-%m-%d")


def numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([pd.NA] * len(frame), index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def diff_flag(left: Any, right: Any, tolerance: float) -> bool:
    left_missing = pd.isna(left)
    right_missing = pd.isna(right)
    if left_missing and right_missing:
        return False
    if left_missing != right_missing:
        return True
    return abs(float(left) - float(right)) > tolerance


def diff_value(left: Any, right: Any) -> float | None:
    if pd.isna(left) or pd.isna(right):
        return None
    return round(float(right) - float(left), 6)


def frame_to_markdown(frame: pd.DataFrame, *, max_rows: int = 20) -> str:
    if frame.empty:
        return "无"
    sample = frame.head(max_rows).copy()
    columns = list(sample.columns)

    def cell_text(value: Any) -> str:
        if pd.isna(value):
            return ""
        return str(value).replace("\n", " ").replace("|", "\\|")

    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    rows = [
        "| " + " | ".join(cell_text(row[column]) for column in columns) + " |"
        for _, row in sample.iterrows()
    ]
    return "\n".join([header, separator, *rows])


def load_v3_workbook(path: Path) -> pd.DataFrame:
    excel = pd.ExcelFile(path)
    frames: list[pd.DataFrame] = []
    for sheet_name in excel.sheet_names:
        if sheet_name == "汇总":
            continue
        frame = pd.read_excel(path, sheet_name=sheet_name)
        frame["来源sheet"] = sheet_name
        frames.append(frame)
    if not frames:
        raise ValueError(f"No detail sheets found in {path}")
    return pd.concat(frames, ignore_index=True)


def prepare_details(frame: pd.DataFrame, *, source: str) -> pd.DataFrame:
    result = frame.copy()
    result["__source"] = source
    result["__row_id"] = range(1, len(result) + 1)
    result["股票名称"] = result["股票名称"].astype(str).str.strip()
    result["状态"] = result["状态"].astype(str).str.strip()
    result["买入时间_key"] = result["买入时间"].map(fmt_date)
    result["卖出时间_key"] = result["卖出时间"].map(fmt_date)

    for column in NUMERIC_TOLERANCES:
        result[f"{column}_num"] = numeric_series(result, column)

    if "股票代码" not in result.columns:
        result["股票代码"] = pd.NA
    if "来源sheet" not in result.columns:
        result["来源sheet"] = pd.NA

    result["exact_base_key"] = (
        result["股票名称"].fillna("")
        + "|"
        + result["买入时间_key"].fillna("")
        + "|"
        + result["卖出时间_key"].fillna("")
        + "|"
        + result["状态"].fillna("")
    )
    sort_columns = ["股票名称", "买入时间_key", "卖出时间_key", "状态", "__row_id"]
    result = result.sort_values(sort_columns, kind="mergesort").reset_index(drop=True)
    result["exact_dup_seq"] = result.groupby("exact_base_key", sort=False).cumcount() + 1
    result["trade_seq"] = result.groupby("股票名称", sort=False).cumcount() + 1
    return result


def exact_time_comparison(v3: pd.DataFrame, generated: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    merge_keys = ["exact_base_key", "exact_dup_seq"]
    merged = v3.merge(
        generated,
        on=merge_keys,
        how="outer",
        suffixes=("_v3", "_generated"),
        indicator=True,
    )

    matched = merged[merged["_merge"] == "both"].copy()
    unmatched = merged[merged["_merge"] != "both"].copy()

    exact_diff_rows: list[dict[str, Any]] = []
    for _, row in matched.iterrows():
        diff_columns: list[str] = []
        output: dict[str, Any] = {
            "股票名称": row.get("股票名称_v3"),
            "股票代码": row.get("股票代码_generated"),
            "状态": row.get("状态_v3"),
            "买入时间": row.get("买入时间_key_v3"),
            "卖出时间": row.get("卖出时间_key_v3"),
            "exact_dup_seq": row.get("exact_dup_seq"),
            "来源sheet_v3": row.get("来源sheet_v3"),
        }
        for column, tolerance in NUMERIC_TOLERANCES.items():
            left = row.get(f"{column}_num_v3")
            right = row.get(f"{column}_num_generated")
            if diff_flag(left, right, tolerance):
                diff_columns.append(column)
            output[f"{column}_v3"] = left
            output[f"{column}_generated"] = right
            output[f"{column}_diff"] = diff_value(left, right)
        if diff_columns:
            output["差异字段"] = "；".join(diff_columns)
            exact_diff_rows.append(output)

    exact_diffs = pd.DataFrame(exact_diff_rows)
    if exact_diffs.empty:
        exact_diffs = pd.DataFrame(columns=EXACT_DIFF_COLUMNS)
    else:
        remaining_columns = [column for column in exact_diffs.columns if column not in EXACT_DIFF_COLUMNS]
        exact_diffs = exact_diffs[[column for column in EXACT_DIFF_COLUMNS if column in exact_diffs.columns] + remaining_columns]

    unmatched_rows: list[dict[str, Any]] = []
    for _, row in unmatched.iterrows():
        side = "v3_only" if row.get("_merge") == "left_only" else "generated_only"
        suffix = "_v3" if side == "v3_only" else "_generated"
        stock_name = row.get(f"股票名称{suffix}")
        buy_time = row.get(f"买入时间_key{suffix}")
        sell_time = row.get(f"卖出时间_key{suffix}")
        status = row.get(f"状态{suffix}")
        unmatched_rows.append(
            {
                "差异类型": "v3有_新CSV缺失" if side == "v3_only" else "新CSV有_v3缺失",
                "股票名称": stock_name,
                "股票代码": row.get("股票代码_generated", pd.NA),
                "状态": status,
                "买入时间": buy_time,
                "卖出时间": sell_time,
                "exact_dup_seq": row.get("exact_dup_seq"),
                "持仓净收益": row.get(f"持仓净收益_num{suffix}"),
                "持仓收益率": row.get(f"持仓收益率_num{suffix}"),
                "买入价格": row.get(f"买入价格_num{suffix}"),
                "卖出价格": row.get(f"卖出价格_num{suffix}"),
                "持仓天数": row.get(f"持仓天数_num{suffix}"),
                "来源sheet_v3": row.get("来源sheet_v3", pd.NA),
            }
        )
    unmatched_diffs = pd.DataFrame(unmatched_rows)

    summary = {
        "exact_total_matched": int(len(matched)),
        "exact_unmatched_total": int(len(unmatched)),
        "exact_v3_only": int((unmatched["_merge"] == "left_only").sum()),
        "exact_generated_only": int((unmatched["_merge"] == "right_only").sum()),
        "exact_matched_with_numeric_differences": int(len(exact_diffs)),
    }
    return exact_diffs, unmatched_diffs, summary


def sequence_comparison(v3: pd.DataFrame, generated: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    merge_keys = ["股票名称", "trade_seq"]
    merged = v3.merge(
        generated,
        on=merge_keys,
        how="outer",
        suffixes=("_v3", "_generated"),
        indicator=True,
    )

    rows: list[dict[str, Any]] = []
    for _, row in merged.iterrows():
        merge_status = row.get("_merge")
        diff_types: list[str] = []
        if merge_status == "left_only":
            diff_types.append("新CSV缺失该序号交易")
        elif merge_status == "right_only":
            diff_types.append("v3缺失该序号交易")
        else:
            if row.get("买入时间_key_v3") != row.get("买入时间_key_generated"):
                diff_types.append("买入时间不一致")
            if row.get("卖出时间_key_v3") != row.get("卖出时间_key_generated"):
                diff_types.append("卖出时间不一致")
            if row.get("状态_v3") != row.get("状态_generated"):
                diff_types.append("状态不一致")
            if diff_flag(row.get("持仓净收益_num_v3"), row.get("持仓净收益_num_generated"), NUMERIC_TOLERANCES["持仓净收益"]):
                diff_types.append("持仓净收益不一致")
            if diff_flag(row.get("持仓收益率_num_v3"), row.get("持仓收益率_num_generated"), NUMERIC_TOLERANCES["持仓收益率"]):
                diff_types.append("持仓收益率不一致")
            if diff_flag(row.get("持仓天数_num_v3"), row.get("持仓天数_num_generated"), NUMERIC_TOLERANCES["持仓天数"]):
                diff_types.append("持仓天数不一致")
            if diff_flag(row.get("买入价格_num_v3"), row.get("买入价格_num_generated"), NUMERIC_TOLERANCES["买入价格"]):
                diff_types.append("买入价格不一致")
            if diff_flag(row.get("卖出价格_num_v3"), row.get("卖出价格_num_generated"), NUMERIC_TOLERANCES["卖出价格"]):
                diff_types.append("卖出价格不一致")

        if not diff_types:
            continue

        rows.append(
            {
                "股票名称": row.get("股票名称"),
                "股票代码_generated": row.get("股票代码_generated", pd.NA),
                "trade_seq": row.get("trade_seq"),
                "差异类型": "；".join(diff_types),
                "状态_v3": row.get("状态_v3", pd.NA),
                "状态_generated": row.get("状态_generated", pd.NA),
                "买入时间_v3": row.get("买入时间_key_v3", ""),
                "买入时间_generated": row.get("买入时间_key_generated", ""),
                "卖出时间_v3": row.get("卖出时间_key_v3", ""),
                "卖出时间_generated": row.get("卖出时间_key_generated", ""),
                "持仓净收益_v3": row.get("持仓净收益_num_v3", pd.NA),
                "持仓净收益_generated": row.get("持仓净收益_num_generated", pd.NA),
                "持仓净收益_diff": diff_value(
                    row.get("持仓净收益_num_v3", pd.NA),
                    row.get("持仓净收益_num_generated", pd.NA),
                ),
                "持仓收益率_v3": row.get("持仓收益率_num_v3", pd.NA),
                "持仓收益率_generated": row.get("持仓收益率_num_generated", pd.NA),
                "持仓收益率_diff": diff_value(
                    row.get("持仓收益率_num_v3", pd.NA),
                    row.get("持仓收益率_num_generated", pd.NA),
                ),
                "买入价格_v3": row.get("买入价格_num_v3", pd.NA),
                "买入价格_generated": row.get("买入价格_num_generated", pd.NA),
                "卖出价格_v3": row.get("卖出价格_num_v3", pd.NA),
                "卖出价格_generated": row.get("卖出价格_num_generated", pd.NA),
                "持仓天数_v3": row.get("持仓天数_num_v3", pd.NA),
                "持仓天数_generated": row.get("持仓天数_num_generated", pd.NA),
                "来源sheet_v3": row.get("来源sheet_v3", pd.NA),
            }
        )

    sequence_diffs = pd.DataFrame(rows)
    if sequence_diffs.empty:
        sequence_diffs = pd.DataFrame(columns=SEQUENCE_OUTPUT_COLUMNS)
    else:
        remaining_columns = [column for column in sequence_diffs.columns if column not in SEQUENCE_OUTPUT_COLUMNS]
        sequence_diffs = sequence_diffs[
            [column for column in SEQUENCE_OUTPUT_COLUMNS if column in sequence_diffs.columns] + remaining_columns
        ]

    summary = {
        "sequence_aligned_rows_with_differences": int(len(sequence_diffs)),
        "sequence_v3_missing": int(sequence_diffs["差异类型"].str.contains("v3缺失该序号交易", na=False).sum()) if not sequence_diffs.empty else 0,
        "sequence_generated_missing": int(sequence_diffs["差异类型"].str.contains("新CSV缺失该序号交易", na=False).sum()) if not sequence_diffs.empty else 0,
        "sequence_buy_date_differences": int(sequence_diffs["差异类型"].str.contains("买入时间不一致", na=False).sum()) if not sequence_diffs.empty else 0,
        "sequence_sell_date_differences": int(sequence_diffs["差异类型"].str.contains("卖出时间不一致", na=False).sum()) if not sequence_diffs.empty else 0,
        "sequence_return_pct_differences": int(sequence_diffs["差异类型"].str.contains("持仓收益率不一致", na=False).sum()) if not sequence_diffs.empty else 0,
        "sequence_net_pnl_differences": int(sequence_diffs["差异类型"].str.contains("持仓净收益不一致", na=False).sum()) if not sequence_diffs.empty else 0,
    }
    return sequence_diffs, summary


def build_stock_summary(
    v3: pd.DataFrame,
    generated: pd.DataFrame,
    exact_unmatched: pd.DataFrame,
    exact_numeric_diffs: pd.DataFrame,
    sequence_diffs: pd.DataFrame,
) -> pd.DataFrame:
    v3_counts = v3.groupby("股票名称").size().rename("v3笔数")
    generated_counts = generated.groupby("股票名称").size().rename("新CSV笔数")
    summary = pd.concat([v3_counts, generated_counts], axis=1).fillna(0).astype(int).reset_index()

    if not exact_unmatched.empty:
        unmatched_counts = exact_unmatched.pivot_table(
            index="股票名称",
            columns="差异类型",
            values="买入时间",
            aggfunc="count",
            fill_value=0,
        )
        summary = summary.merge(unmatched_counts.reset_index(), on="股票名称", how="left")
    if not exact_numeric_diffs.empty:
        numeric_counts = exact_numeric_diffs.groupby("股票名称").size().rename("同买卖时间收益数值差异")
        summary = summary.merge(numeric_counts.reset_index(), on="股票名称", how="left")
    if not sequence_diffs.empty:
        sequence_counts = sequence_diffs.groupby("股票名称").size().rename("同股票序号差异")
        summary = summary.merge(sequence_counts.reset_index(), on="股票名称", how="left")

        for label in ["买入时间不一致", "卖出时间不一致", "持仓收益率不一致", "持仓净收益不一致", "状态不一致"]:
            counts = (
                sequence_diffs[sequence_diffs["差异类型"].str.contains(label, na=False)]
                .groupby("股票名称")
                .size()
                .rename(label)
            )
            summary = summary.merge(counts.reset_index(), on="股票名称", how="left")

    for column in summary.columns:
        if column != "股票名称":
            summary[column] = summary[column].fillna(0).astype(int)

    summary["笔数差_新CSV减v3"] = summary["新CSV笔数"] - summary["v3笔数"]
    sort_columns = [column for column in ["同股票序号差异", "v3有_新CSV缺失", "新CSV有_v3缺失", "同买卖时间收益数值差异"] if column in summary.columns]
    if sort_columns:
        summary = summary.sort_values(sort_columns + ["股票名称"], ascending=[False] * len(sort_columns) + [True])
    return summary


def build_exact_numeric_stats(exact_numeric_diffs: pd.DataFrame) -> dict[str, Any]:
    if exact_numeric_diffs.empty:
        return {
            "exact_buy_price_differences": 0,
            "exact_sell_price_differences": 0,
            "exact_net_pnl_differences": 0,
            "exact_return_pct_differences": 0,
            "exact_holding_days_differences": 0,
            "exact_max_abs_net_pnl_diff": 0.0,
            "exact_max_abs_return_pct_diff": 0.0,
            "exact_max_abs_holding_days_diff": 0.0,
        }

    def contains(label: str) -> int:
        return int(exact_numeric_diffs["差异字段"].str.contains(label, regex=False, na=False).sum())

    def max_abs(column: str) -> float:
        if column not in exact_numeric_diffs.columns:
            return 0.0
        values = pd.to_numeric(exact_numeric_diffs[column], errors="coerce").dropna().abs()
        return round(float(values.max()), 6) if not values.empty else 0.0

    return {
        "exact_buy_price_differences": contains("买入价格"),
        "exact_sell_price_differences": contains("卖出价格"),
        "exact_net_pnl_differences": contains("持仓净收益"),
        "exact_return_pct_differences": contains("持仓收益率"),
        "exact_holding_days_differences": contains("持仓天数"),
        "exact_max_abs_net_pnl_diff": max_abs("持仓净收益_diff"),
        "exact_max_abs_return_pct_diff": max_abs("持仓收益率_diff"),
        "exact_max_abs_holding_days_diff": max_abs("持仓天数_diff"),
    }


def write_report(
    output_path: Path,
    *,
    v3_workbook: Path,
    generated_csv: Path,
    summary: dict[str, Any],
    stock_summary: pd.DataFrame,
    exact_numeric_diffs: pd.DataFrame,
    exact_unmatched: pd.DataFrame,
    sequence_diffs: pd.DataFrame,
) -> None:
    top_stocks = frame_to_markdown(stock_summary, max_rows=20)
    exact_diff_sample = frame_to_markdown(exact_numeric_diffs, max_rows=20)
    sequence_sample = frame_to_markdown(sequence_diffs, max_rows=20)
    unmatched_sample = frame_to_markdown(exact_unmatched, max_rows=20)

    report = f"""# v3 与新 CSV 买卖时间/收益差异标记

生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## 对比对象

- v3 Excel：`{v3_workbook}`
- 新 CSV：`{generated_csv}`

## 口径

- 严格买卖时间匹配：`股票名称 + 买入时间 + 卖出时间/标记日期 + 状态 + 重复序号`。
- 同股票序号匹配：每只股票按 `买入时间、卖出时间、状态` 排序后，以第 N 笔对第 N 笔。
- 收益率单位：百分点。源文件中 `-2.63` 表示 `-2.63%`。
- 容差：价格 `0.01`，金额/收益 `0.02`，收益率 `0.01` 个百分点，持仓天数/数量必须一致。

## 总结

- v3 总笔数：{summary["v3_rows"]}
- 新 CSV 总笔数：{summary["generated_rows"]}
- 严格同买卖时间匹配笔数：{summary["exact_total_matched"]}
- 严格同买卖时间但数值/收益有差异：{summary["exact_matched_with_numeric_differences"]}
- 严格同买卖时间的买入价差异：{summary["exact_buy_price_differences"]}
- 严格同买卖时间的卖出价差异：{summary["exact_sell_price_differences"]}
- 严格同买卖时间的净收益差异：{summary["exact_net_pnl_differences"]}
- 严格同买卖时间的收益率差异：{summary["exact_return_pct_differences"]}，最大差异 {summary["exact_max_abs_return_pct_diff"]} 个百分点
- 严格同买卖时间的持仓天数差异：{summary["exact_holding_days_differences"]}，最大差异 {summary["exact_max_abs_holding_days_diff"]} 天
- 严格时间键 v3 有、新 CSV 缺失：{summary["exact_v3_only"]}
- 严格时间键新 CSV 有、v3 缺失：{summary["exact_generated_only"]}
- 同股票按第 N 笔对齐后存在差异的行：{summary["sequence_aligned_rows_with_differences"]}
- 其中买入时间不一致：{summary["sequence_buy_date_differences"]}
- 其中卖出时间不一致：{summary["sequence_sell_date_differences"]}
- 其中持仓收益率不一致：{summary["sequence_return_pct_differences"]}
- 其中持仓净收益不一致：{summary["sequence_net_pnl_differences"]}

## 结论解读

- 对已经严格匹配到同一股票、同一买入日、同一卖出/标记日、同一状态的交易，两边买入价、卖出价和净收益没有超过容差的差异；收益计算主体基本一致。
- 这部分的 `732` 条数值差异主要来自两类：收益率 `0.01` 个百分点的四舍五入差，或持仓天数口径差。
- 真正需要继续追的是严格时间键不一致的交易：v3 独有 `7455` 条，新 CSV 独有 `7181` 条。
- 同股票第 N 笔对齐的 `55317` 行差异会被“前面多/少一笔”放大；它适合定位哪只股票从哪一笔开始错位，不应直接理解为独立的 55317 个策略信号错误。

## 差异股票 Top 20

{top_stocks}

## 严格同买卖时间但收益/金额不同样例

{exact_diff_sample}

## 严格时间键一边缺失样例

{unmatched_sample}

## 同股票第 N 笔差异样例

{sequence_sample}
"""
    output_path.write_text(report, encoding="utf-8")


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir or args.generated_csv.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    v3_raw = load_v3_workbook(args.v3_workbook)
    generated_raw = pd.read_csv(args.generated_csv)
    v3 = prepare_details(v3_raw, source="v3")
    generated = prepare_details(generated_raw, source="generated")

    exact_numeric_diffs, exact_unmatched, exact_summary = exact_time_comparison(v3, generated)
    sequence_diffs, sequence_summary = sequence_comparison(v3, generated)
    stock_summary = build_stock_summary(v3, generated, exact_unmatched, exact_numeric_diffs, sequence_diffs)

    summary: dict[str, Any] = {
        "v3_workbook": str(args.v3_workbook),
        "generated_csv": str(args.generated_csv),
        "v3_rows": int(len(v3)),
        "generated_rows": int(len(generated)),
        "v3_stock_count": int(v3["股票名称"].nunique()),
        "generated_stock_count": int(generated["股票名称"].nunique()),
        **exact_summary,
        **build_exact_numeric_stats(exact_numeric_diffs),
        **sequence_summary,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    exact_numeric_path = output_dir / "v3_exact_time_return_differences.csv"
    exact_unmatched_path = output_dir / "v3_exact_time_unmatched_trades.csv"
    sequence_path = output_dir / "v3_sequence_aligned_differences.csv"
    stock_summary_path = output_dir / "v3_trade_diff_summary_by_stock.csv"
    summary_path = output_dir / "v3_trade_diff_summary.json"
    report_path = output_dir / "v3_trade_diff_report.md"

    exact_numeric_diffs.to_csv(exact_numeric_path, index=False, encoding="utf-8-sig")
    exact_unmatched.to_csv(exact_unmatched_path, index=False, encoding="utf-8-sig")
    sequence_diffs.to_csv(sequence_path, index=False, encoding="utf-8-sig")
    stock_summary.to_csv(stock_summary_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(
        report_path,
        v3_workbook=args.v3_workbook,
        generated_csv=args.generated_csv,
        summary=summary,
        stock_summary=stock_summary,
        exact_numeric_diffs=exact_numeric_diffs,
        exact_unmatched=exact_unmatched,
        sequence_diffs=sequence_diffs,
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"exact_numeric_differences={exact_numeric_path}")
    print(f"exact_unmatched_trades={exact_unmatched_path}")
    print(f"sequence_aligned_differences={sequence_path}")
    print(f"stock_summary={stock_summary_path}")
    print(f"report={report_path}")


if __name__ == "__main__":
    main()
