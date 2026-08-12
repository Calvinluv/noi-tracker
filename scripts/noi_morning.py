"""
noi_morning.py — 早盘任务入口
工作日 08:30 HKT 运行，抓取夜市结束后的 NOI，与昨晚数据对比。
不覆盖 noi_history.json，只写入 noi_morning_latest.json。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from noi_common import *


def main():
    today = get_today_str()
    today_compact = get_today_compact()
    print(f"=== NOI 早盘对比 {today} ===")

    # 步骤0：确定合约月份
    print("\n[步骤0] 确定合约月份...")
    contracts = determine_contracts()
    print(f"  即月: {contracts[0]}, 下月: {contracts[1]}")

    # 步骤1：抓取今早数据
    print("\n[步骤1] 抓取今早 NOI 数据...")
    today_data = fetch_all_noi(contracts)

    # 步骤2：读取昨晚数据
    print("\n[步骤2] 读取昨晚数据（对比基准）...")
    base_data = load_json(HISTORY_FILE)
    if base_data:
        base_date = base_data.get("date", "未知")
        print(f"  基准日期: {base_date}")
    else:
        base_date = "无"
        print("  无历史数据，首次记录")

    # 检查合约月份是否匹配
    if base_data and base_data.get("contracts") != list(contracts):
        print(f"  ⚠️ 合约月份不匹配（基准: {base_data.get('contracts')}, 今日: {list(contracts)}），标记为无对比")
        base_data = None
        base_date = "合约切换"

    # 步骤3：计算对比
    print("\n[步骤3] 计算对比...")
    base_noi = base_data.get("data", {}) if base_data else {}
    results = compute_summary(today_data, base_noi, contracts)
    for r in results:
        print(f"  {r['product']}: 合计 {r['today_total']:,} vs {r['base_total'] or '—'}, "
              f"变化 {r['total_change'] or '—'} ({r['total_pct']:.2f}%)" if r['total_pct'] else
              f"  {r['product']}: 合计 {r['today_total']:,} (首次记录)")

    # 步骤3.5：检测异常
    print("\n[步骤3.5] 检测异常波动...")
    anomalies = detect_anomalies(results)
    if anomalies:
        print(f"  ⚠️ {len(anomalies)} 个品种触发 3% 阈值")
        for a in anomalies:
            print(f"    {a['product']}: {a['total_pct']:.2f}%")
    else:
        print("  无异常")

    # 步骤3.6：保存今早数据
    print("\n[步骤3.6] 保存今早数据...")
    morning_data = {
        "date": today,
        "time": "08:30",
        "contracts": list(contracts),
        "data": {k: v["noi"] for k, v in today_data.items() if v["noi"] is not None}
    }
    save_json(MORNING_FILE, morning_data)
    print(f"  ✅ 已保存 {MORNING_FILE}")

    # 步骤4：生成 HTML
    print("\n[步骤4] 生成 HTML...")
    base_label = f"昨晚 {base_date} 数据" if base_data else "无对比数据（首次记录）"
    if anomalies:
        for a in anomalies:
            analyze_anomaly(a, base_data)
    html = generate_html(results, today, base_label, "morning", anomalies if anomalies else None)
    html_path = os.path.join(DOCS_DIR, f"noi_morning_{today_compact}.html")
    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✅ 已生成 {html_path}")

    # 更新 index.html
    update_index(today, "morning")

    # 步骤5：微信推送
    print("\n[步骤5] 微信推送...")
    summary = build_wechat_summary(results)
    push_wechat(f"NOI早盘对比 {today}", summary)

    # 异常预警
    if anomalies:
        alert_text = build_wechat_alert(anomalies)
        push_wechat(f"⚠️ NOI夜市异常波动 {today}", alert_text)

    print(f"\n=== 早盘任务完成 ===")


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
