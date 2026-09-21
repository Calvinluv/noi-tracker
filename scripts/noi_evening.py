"""
noi_evening.py — 晚间任务入口
工作日 21:35 HKT 运行，抓取日市收盘后的 NOI，与今早数据对比。
写入 noi_history.json（含 turnover），作为次日早盘的对比基准。

2026-08-24 修复：etnet 未平仓净数更新时间点晚于 21:10，
导致晚间抓到的是早晨快照的旧数据（变化全为 0）。
新增：数据陈旧检测 + 自动重试（每 15 分钟重试，最多 5 次，
覆盖 21:10–22:10；周六/日不重试，因为数据本就不更新）。

2026-09-21 补充：
- 抓取不完整（missing_keys 非空）同样进入重试，不再把 None 当 0 参与合计；
- 与 noi_common 的 None-safe compute_summary 配套：缺失时不出合计、不触发异常预警、
  不写 history，避免残缺基准污染次日早盘对比。
"""
import sys
import os
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from noi_common import *

# 重试配置
RETRY_INTERVAL_SEC = 15 * 60   # 每次重试间隔 15 分钟
MAX_ATTEMPTS = 5               # 总尝试次数（含首次）


def is_data_stale(today_data, morning_data, contracts):
    """
    判断抓取数据是否"疑似陈旧"：
    1. 存在抓取失败（missing_keys 非空）→ 需要重试；
    2. 六个合约的 NOI 与今早快照完全一致 → 疑似 etnet 尚未更新
       （真实交易中三个品种 × 两个合约同时零变化几乎不可能）。
    """
    if missing_keys(today_data):
        return True

    keys = [f"{p}_{m}" for p in ["HSI", "HHI", "HTI"] for m in contracts]
    nois = [today_data.get(k, {}).get("noi") for k in keys]

    if not morning_data or not morning_data.get("data"):
        return False  # 无基准可比对，无法判断
    base = morning_data["data"]
    if not all(k in base for k in keys):
        return False  # 基准不完整（如合约切换日），跳过判断
    if all(nois[i] == base[k] for i, k in enumerate(keys)):
        return True  # 与今早完全一致 → 疑似未更新

    return False


def fetch_with_retry(contracts, morning_data):
    """带陈旧检测的抓取循环，返回 (today_data, was_stale)"""
    is_weekend = datetime.now(HKT).weekday() >= 5
    was_stale = False

    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"\n[步骤1] 抓取今晚 NOI 数据（第 {attempt}/{MAX_ATTEMPTS} 次）...")
        today_data = fetch_all_noi(contracts)

        if is_weekend:
            print("  ℹ️ 周末非交易日，数据不更新属正常，不做陈旧重试")
            return today_data, was_stale

        if not is_data_stale(today_data, morning_data, contracts):
            return today_data, was_stale

        was_stale = True
        missing = missing_keys(today_data)
        if missing:
            print(f"  ⚠️ 抓取不完整，缺失: {', '.join(missing)}")
        else:
            print("  ⚠️ 抓取数据与今早快照完全一致，疑似 etnet 数据未更新")

        if attempt < MAX_ATTEMPTS:
            print(f"  ⏳ 等待 {RETRY_INTERVAL_SEC // 60} 分钟后重试...")
            time.sleep(RETRY_INTERVAL_SEC)
        else:
            print("  ⚠️ 已达最大重试次数，按当前数据生成报告（变化可能为 0）")

    return today_data, was_stale


def main():
    today = get_today_str()
    today_compact = get_today_compact()
    print(f"=== NOI 日报（晚间）{today} ===")

    # 步骤0：确定合约月份
    print("\n[步骤0] 确定合约月份...")
    contracts = determine_contracts()
    print(f"  即月: {contracts[0]}, 下月: {contracts[1]}")

    # 步骤0.5：先读取今早数据（供陈旧检测与后续对比共用）
    morning_data = load_json(MORNING_FILE)

    # 步骤1：抓取今晚数据（带陈旧检测与重试）
    today_data, was_stale = fetch_with_retry(contracts, morning_data)

    missing = missing_keys(today_data)

    # 步骤2：确定对比基准
    print("\n[步骤2] 确定对比基准...")
    base_data = None
    base_label = ""

    if morning_data:
        morning_date = morning_data.get("date", "未知")
        if morning_data.get("contracts") == list(contracts):
            base_data = morning_data
            base_label = f"今早 {morning_date} 08:30 数据"
            print(f"  ✅ 使用今早数据: {morning_date}")
        else:
            print(f"  ⚠️ 今早合约月份不匹配，尝试 fallback")

    if base_data is None:
        # Fallback: 读取昨晚数据
        history_data = load_json(HISTORY_FILE)
        if history_data and history_data.get("contracts") == list(contracts):
            base_data = history_data
            base_label = f"昨晚 {history_data.get('date')} 数据（早盘数据缺失）"
            print(f"  ⚠️ Fallback 到昨晚数据: {history_data.get('date')}")
        else:
            base_label = "无对比数据（首次记录）"
            print("  ⚠️ 无对比基准")

    if was_stale:
        base_label += "（⚠️ 数据源更新延迟，已经重试等待）"

    # 步骤3：计算对比（None-safe：缺失项不参与合计与异常判定）
    print("\n[步骤3] 计算对比...")
    base_noi = base_data.get("data", {}) if base_data else {}
    results = compute_summary(today_data, base_noi, contracts)
    for r in results:
        if r["today_total"] is None:
            print(f"  {r['product']}: ⚠️ 数据不完整，合计置空")
        elif r['total_pct'] is not None:
            print(f"  {r['product']}: 合计 {r['today_total']:,} vs {r['base_total'] or '—'}, "
                  f"变化 {r['total_change'] or '—'} ({r['total_pct']:+.2f}%)")
        else:
            print(f"  {r['product']}: 合计 {r['today_total']:,} (首次记录)")

    # 步骤3.5：检测异常
    print("\n[步骤3.5] 检测异常波动...")
    anomalies = detect_anomalies(results)
    if anomalies:
        print(f"  ⚠️ {len(anomalies)} 个品种触发 3% 阈值")
        for a in anomalies:
            print(f"    {a['product']}: {a['total_pct']:+.2f}%")
    else:
        print("  无异常")

    # 步骤4：生成 HTML
    print("\n[步骤4] 生成 HTML...")
    if anomalies:
        for a in anomalies:
            analyze_anomaly(a, base_data)
    html = generate_html(results, today, base_label, "daily", anomalies if anomalies else None)
    html_path = os.path.join(DOCS_DIR, f"noi_daily_{today_compact}.html")
    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✅ 已生成 {html_path}")

    # 更新 index.html
    update_index(today, "daily")

    # 步骤5：保存今晚数据（最后才写！）
    # 2026-09-21：抓取不完整时不写 history，避免残缺基准污染次日早盘对比。
    print("\n[步骤5] 保存今晚数据...")
    if missing:
        print(f"  🚫 抓取不完整（缺失: {', '.join(missing)}），跳过写 {HISTORY_FILE}")
    else:
        print("\n[步骤5a] 抓取成交额...")
        turnover = save_turnover(today_data, contracts)

        history_data = {
            "date": today,
            "contracts": list(contracts),
            "data": {k: v["noi"] for k, v in today_data.items() if v["noi"] is not None},
            "turnover": turnover
        }
        save_json(HISTORY_FILE, history_data)
        print(f"  ✅ 已保存 {HISTORY_FILE}")

    # 步骤6：微信推送
    print("\n[步骤6] 微信推送...")
    summary = build_wechat_summary(results)
    if missing:
        summary = f"🚫 抓取不完整（缺失: {', '.join(missing)}），合计与变化已置空\n" + summary
    if was_stale:
        summary = "⚠️ 注意：数据源更新延迟，以下变化可能不完整\n" + summary
    push_wechat(f"NOI日报 {today}", summary)

    # 异常预警
    if anomalies:
        alert_text = build_wechat_alert(anomalies)
        push_wechat(f"⚠️ NOI异常波动 {today}", alert_text)

    print(f"\n=== 晚间任务完成 ===")


def update_index(today, report_type):
    """更新 docs/index.html 为最新报告入口"""
    today_compact = get_today_compact()
    filename = f"noi_{'daily' if report_type == 'daily' else 'morning'}_{today_compact}.html"

    index_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="0; url={filename}">
<title>NOI 报告 — {today}</title>
</head>
<body>
<p>正在跳转到最新报告...</p>
<p>如未自动跳转，请<a href="{filename}">点击这里</a></p>
</body>
</html>"""
    with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)


if __name__ == "__main__":
    main()
