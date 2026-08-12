"""
noi_evening.py — 晚间任务入口
工作日 21:35 HKT 运行，抓取日市收盘后的 NOI，与今早数据对比。
写入 noi_history.json（含 turnover），作为次日早盘的对比基准。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from noi_common import *


def main():
    today = get_today_str()
    today_compact = get_today_compact()
    print(f"=== NOI 日报（晚间）{today} ===")

    # 步骤0：确定合约月份
    print("\n[步骤0] 确定合约月份...")
    contracts = determine_contracts()
    print(f"  即月: {contracts[0]}, 下月: {contracts[1]}")

    # 步骤1：抓取今晚数据
    print("\n[步骤1] 抓取今晚 NOI 数据...")
    today_data = fetch_all_noi(contracts)

    # 步骤2：读取今早数据（对比基准）
    print("\n[步骤2] 读取今早数据...")
    morning_data = load_json(MORNING_FILE)
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

    # 步骤3：计算对比
    print("\n[步骤3] 计算对比...")
    base_noi = base_data.get("data", {}) if base_data else {}
    results = compute_summary(today_data, base_noi, contracts)
    for r in results:
        if r['total_pct'] is not None:
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
    print("\n[步骤5] 保存今晚数据...")
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
