"""
noi_common.py — 香港指数期货 NOI 公共模块
抓取 etnet 期货页面、解析 NOI、对比计算、生成 HTML、推送微信
"""
import re
import json
import os
import requests
from datetime import datetime, timedelta, timezone

# HKT 时区 (UTC+8)，GitHub Actions runner 默认 UTC
HKT = timezone(timedelta(hours=8))

# ── 常量 ──────────────────────────────────────────────
BASE_URL = "https://www.etnet.com.hk/www/tc/futures/index.php"
HOME_URL = "https://www.etnet.com.hk/www/tc/futures/"
SPOT_URLS = {
    "HSI": "https://www.etnet.com.hk/www/tc/home/index.php",
    "HHI": "https://www.etnet.com.hk/www/tc/stocks/indexes_detail.php?subtype=cei",
    "HTI": "https://www.etnet.com.hk/www/tc/stocks/indexes_detail.php?subtype=teh",
}
PRODUCT_NAMES = {
    "HSI": "恒生指数期货",
    "HHI": "恒生中国企业指数期货",
    "HTI": "恒生科技指数期货",
}
PRODUCT_SHORT = {
    "HSI": "恒指",
    "HHI": "国企",
    "HTI": "科技",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
HISTORY_FILE = os.path.join(DATA_DIR, "noi_history.json")
MORNING_FILE = os.path.join(DATA_DIR, "noi_morning_latest.json")


# ── 网络抓取 ──────────────────────────────────────────
def fetch_url(url, timeout=30):
    """抓取 URL，返回 HTML 文本"""
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def determine_contracts():
    """
    抓取首页，确定当前即月合约月份。
    返回 (near_month, far_month)，格式 "YYYYMM"。
    """
    html = fetch_url(HOME_URL)
    # 从页面提取即月合约，如 "恒生指數期貨(08/2026)"
    match = re.search(r'恒生指數期貨\((\d{2})/(\d{4})\)', html)
    if not match:
        # fallback: 用当前月份
        now = datetime.now(HKT)
        near = f"{now.year}{now.month:02d}"
    else:
        near = f"{match.group(2)}{match.group(1)}"

    # 计算下月
    year = int(near[:4])
    month = int(near[4:])
    if month == 12:
        far = f"{year + 1}01"
    else:
        far = f"{year}{month + 1:02d}"

    return near, far


def parse_futures_page(html):
    """
    从期货页面 HTML 中提取 NOI、到期日、今日升跌。
    返回 dict: {noi: int, expiry: str, change: str, change_pct: str}
    """
    result = {"noi": None, "expiry": None, "change": None, "change_pct": None}

    # NOI: "未平倉淨數 (NOI)︰ 27,702"
    noi_match = re.search(r'未平倉淨數\s*\(NOI\).*?(\d[\d,]+)', html, re.DOTALL)
    if noi_match:
        result["noi"] = int(noi_match.group(1).replace(",", ""))

    # 到期日: "到期日︰28/08/2026"
    expiry_match = re.search(r'到期日[︰:]\s*(\d{2}/\d{2}/\d{4})', html)
    if expiry_match:
        result["expiry"] = expiry_match.group(1)

    # 今日升跌: 清理 HTML 标签后搜索 "日市 25,408 -220 (-0.86%)"
    clean_text = re.sub(r'<[^>]+>', '\n', html)
    clean_text = re.sub(r'\n\s*\n', '\n', clean_text)
    change_match = re.search(r'日市\s+[\d,]+\s+(-?[\d,]+)\s*\((-?[\d.]+%)\)', clean_text)
    if change_match:
        result["change"] = change_match.group(1)
        result["change_pct"] = change_match.group(2)

    return result


def fetch_all_noi(contracts):
    """
    抓取三大品种 × 两个月份的 NOI 数据。
    contracts: (near_month, far_month)，格式 "YYYYMM"
    返回 dict: {"HSI_202608": {noi, expiry, change, change_pct}, ...}
    """
    data = {}
    for product in ["HSI", "HHI", "HTI"]:
        for month in contracts:
            key = f"{product}_{month}"
            url = f"{BASE_URL}?subtype={product}&month={month}&tab=interval"
            try:
                html = fetch_url(url)
                parsed = parse_futures_page(html)
                data[key] = parsed
                print(f"  ✅ {key}: NOI={parsed['noi']}, expiry={parsed['expiry']}, change={parsed['change']}")
            except Exception as e:
                print(f"  ❌ {key}: {e}")
                data[key] = {"noi": None, "expiry": None, "change": None, "change_pct": None}
    return data


def fetch_turnover(product):
    """抓取现货指数成交额"""
    url = SPOT_URLS.get(product)
    if not url:
        return None
    try:
        html = fetch_url(url)
        # 清理 HTML 标签
        clean_text = re.sub(r'<[^>]+>', '\n', html)
        clean_text = re.sub(r'\n\s*\n', '\n', clean_text)

        if product == "HSI":
            # HSI 首页: "大市成交 2,168億"
            match = re.search(r'大市成交\s*([\d,.]+\s*億?)', clean_text)
            if match:
                return match.group(1).strip()
        else:
            # HHI/HTI: "成份股成交金額 638.476億" 或 "成交金額 638.476億"
            match = re.search(r'(?:成份股)?成交金額\s*([\d,.]+\s*億?)', clean_text)
            if match:
                return match.group(1).strip()

        # Fallback: 任何 "成交" 后跟数字+亿
        match2 = re.search(r'成交[^\d]*([\d,.]+)\s*億', clean_text)
        if match2:
            return match2.group(1) + "億"
    except Exception as e:
        print(f"  ⚠️ Turnover fetch failed for {product}: {e}")
    return None


# ── 数据读写 ──────────────────────────────────────────
def load_json(path):
    """读取 JSON 文件，不存在返回 None"""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    """写入 JSON 文件"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 计算对比 ──────────────────────────────────────────
def calc_change(today_val, base_val):
    """计算变化，返回 (change, pct)"""
    if today_val is None or base_val is None:
        return None, None
    change = today_val - base_val
    if base_val == 0:
        pct = 0.0
    else:
        pct = (change / base_val) * 100
    return change, pct


def _get_noi(data, key):
    """从数据中提取 NOI 值，兼容 dict 和 int 两种格式"""
    if not data:
        return None
    val = data.get(key)
    if val is None:
        return None
    if isinstance(val, dict):
        return val.get("noi")
    return val  # int


def _get_field(data, key, field):
    """从数据中提取指定字段（如 expiry, change），仅对 dict 格式有效"""
    if not data:
        return None
    val = data.get(key)
    if isinstance(val, dict):
        return val.get(field)
    return None


def compute_summary(data_today, data_base, contracts):
    """
    计算每个品种和合约的变化。
    data_today: fetch_all_noi 返回的 dict（值为 dict）
    data_base: JSON 文件中的 data 字段（值为 int），或 fetch_all_noi 返回的 dict
    返回 list of dict，每个品种一个，含即月/下月/合计。
    """
    products = ["HSI", "HHI", "HTI"]
    results = []
    for product in products:
        near_key = f"{product}_{contracts[0]}"
        far_key = f"{product}_{contracts[1]}"
        today_near = _get_noi(data_today, near_key)
        today_far = _get_noi(data_today, far_key)
        base_near = _get_noi(data_base, near_key)
        base_far = _get_noi(data_base, far_key)

        near_change, near_pct = calc_change(today_near, base_near)
        far_change, far_pct = calc_change(today_far, base_far)

        today_total = (today_near or 0) + (today_far or 0)
        base_total = (base_near or 0) + (base_far or 0) if base_near is not None else None
        total_change, total_pct = calc_change(today_total, base_total) if base_total else (None, None)

        results.append({
            "product": product,
            "near_month": contracts[0],
            "far_month": contracts[1],
            "near_expiry": _get_field(data_today, near_key, "expiry"),
            "far_expiry": _get_field(data_today, far_key, "expiry"),
            "today_near": today_near,
            "today_far": today_far,
            "base_near": base_near,
            "base_far": base_far,
            "near_change": near_change,
            "near_pct": near_pct,
            "far_change": far_change,
            "far_pct": far_pct,
            "today_total": today_total,
            "base_total": base_total,
            "total_change": total_change,
            "total_pct": total_pct,
            "today_change": _get_field(data_today, near_key, "change"),
            "today_change_pct": _get_field(data_today, near_key, "change_pct"),
        })
    return results


# ── HTML 生成 ─────────────────────────────────────────
def generate_html(results, today_date, base_label, report_type, anomalies=None):
    """
    生成 HTML 报告。
    report_type: "daily" 或 "morning"
    base_label: 对比基准描述，如 "今早 08:30 数据"
    anomalies: 触发3%异常的品种分析列表
    """
    title_prefix = "NOI 日报" if report_type == "daily" else "NOI 早盘对比"
    badge_text = "晚间日市收盘" if report_type == "daily" else "夜市更新后"

    # 计算总计
    grand_today = sum(r["today_total"] for r in results)
    grand_base = sum(r["base_total"] for r in results if r["base_total"] is not None)
    grand_change = grand_today - grand_base if grand_base else None
    grand_pct = (grand_change / grand_base * 100) if grand_base else None

    def fmt_num(n):
        return f"{n:,}" if n is not None else "—"

    def fmt_change(n):
        if n is None:
            return '<span style="color:#6b7280;">无对比</span>'
        cls = "change-up arrow-up" if n >= 0 else "change-down arrow-down"
        sign = "+" if n >= 0 else ""
        return f'<span class="{cls}">{sign}{n:,}</span>'

    def fmt_pct(p):
        if p is None:
            return '<span style="color:#6b7280;">—</span>'
        cls = "change-up" if p >= 0 else "change-down"
        sign = "+" if p >= 0 else ""
        return f'<span class="{cls}">{sign}{p:.2f}%</span>'

    rows = ""
    for r in results:
        product = r["product"]
        tag_class = f"tag-{product.lower()}"
        alert_flag = ""
        if anomalies and any(a["product"] == product for a in anomalies):
            alert_flag = '<span style="color:#dc2626;font-size:12px;margin-left:8px;">⚠️ 触发3%预警</span>'

        rows += f"""
    <tr class="product-row">
      <td colspan="8">🇭🇰 {PRODUCT_NAMES[product]} <span class="product-tag {tag_class}">{product}</span>{alert_flag}</td>
    </tr>
    <tr>
      <td></td>
      <td>{r['near_month'][:4]}/{r['near_month'][4:]}</td>
      <td>{r['near_expiry'] or '—'}</td>
      <td style="text-align:right;">{fmt_num(r['today_near'])}</td>
      <td style="text-align:right;">{fmt_num(r['base_near'])}</td>
      <td style="text-align:right;">{fmt_change(r['near_change'])}</td>
      <td style="text-align:right;">{fmt_pct(r['near_pct'])}</td>
      <td style="text-align:right;" rowspan="2">{fmt_change(r['total_change'])}<br><b>{fmt_pct(r['total_pct'])}</b></td>
    </tr>
    <tr>
      <td></td>
      <td>{r['far_month'][:4]}/{r['far_month'][4:]}</td>
      <td>{r['far_expiry'] or '—'}</td>
      <td style="text-align:right;">{fmt_num(r['today_far'])}</td>
      <td style="text-align:right;">{fmt_num(r['base_far'])}</td>
      <td style="text-align:right;">{fmt_change(r['far_change'])}</td>
      <td style="text-align:right;">{fmt_pct(r['far_pct'])}</td>
    </tr>"""

    # 异常分析区域
    anomaly_html = ""
    if anomalies:
        anomaly_sections = ""
        for a in anomalies:
            product = a["product"]
            change_val = a["result"]["today_change"] or "—"
            change_pct_val = a["result"]["today_change_pct"] or "—"
            is_bullish = change_val != "—" and not change_val.startswith("-")
            candle = "阳线" if is_bullish else "阴线"
            turnover_today = a.get("turnover_today", "—")
            turnover_base = a.get("turnover_base", "—")
            turnover_note = f"{turnover_today} vs {turnover_base}" if turnover_base != "—" else f"{turnover_today} (无对比)"

            # 判断放量
            vol_amplified = ""
            if a.get("vol_amplified"):
                vol_amplified = f" 放大{a['vol_amplified']:.1f}%"
            else:
                vol_amplified = " 未显著放大"

            # 市场解读（2026-08-13 修正：采用实战派解读）
            # 用户原话：「连续阴线 + NOI 增 = 空头主导，淡仓在获利并加仓 short」，
            #           旧解读「多头逢低建仓」是教科书说法，未考虑连续性背景。
            # 新逻辑：所有"NOI 增 + 阴线"一律按「空头主导」解读；
            #        "NOI 增 + 阳线"才是多头建仓（多头推升价格且 NOI 增才合逻辑）。
            noi_up = a["total_pct"] >= 0
            if noi_up and not is_bullish:
                interpretation = (
                    "净多头增 + 阴线：空头主导（淡仓获利 + 加仓 short 压制），"
                    "若连续多日同方向，空头格局明确，警惕进一步下跌"
                )
            elif noi_up and is_bullish:
                interpretation = "净多头增 + 阳线：多头主动建仓推升价格，看多信号"
            elif not noi_up and not is_bullish:
                interpretation = (
                    "净多头减 + 阴线：多头止损离场 + 空头加仓 short，明确偏空信号"
                )
            else:
                interpretation = (
                    "净多头减 + 阳线：多头获利了结 + 空头回补，警惕上涨末期"
                )

            anomaly_sections += f"""
      <table style="margin-bottom:16px;">
        <thead>
          <tr><th>指标</th><th>数值</th><th>说明</th></tr>
        </thead>
        <tbody>
          <tr><td>NOI 合计变化</td><td class="change-up">+{a['total_change']:,} ({a['total_pct']:.2f}%)</td><td>净多头{'增加' if a['total_pct'] >= 0 else '减少'}</td></tr>
          <tr><td>价格涨跌</td><td>{change_val} ({change_pct_val})</td><td>{candle}</td></tr>
          <tr><td>成交额</td><td>{turnover_note}{vol_amplified}</td><td>—</td></tr>
        </tbody>
      </table>
      <div class="interpretation">→ <b>{interpretation}</b></div>"""

        anomaly_html = f"""
<div class="analysis-box">
  <h3>⚠️ 异常波动分析</h3>
  <div class="analysis-content">
    {anomaly_sections}
  </div>
</div>"""

    grand_change_html = fmt_change(grand_change)
    grand_pct_html = fmt_pct(grand_pct)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title_prefix} — {today_date}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f7fa; color: #1f2937; padding: 32px 16px; line-height: 1.6; }}
  .container {{ max-width: 1080px; margin: 0 auto; }}
  header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: #fff; padding: 28px 32px; border-radius: 12px 12px 0 0; box-shadow: 0 4px 16px rgba(102,126,234,0.25); }}
  header h1 {{ font-size: 24px; margin-bottom: 6px; }}
  header .subtitle {{ font-size: 14px; opacity: 0.92; }}
  header .badge {{ display: inline-block; margin-left: 12px; padding: 3px 10px; background: rgba(255,255,255,0.22); border: 1px solid rgba(255,255,255,0.4); border-radius: 999px; font-size: 12px; }}
  .meta-bar {{ background: #fff; padding: 16px 32px; border-bottom: 1px solid #e5e7eb; font-size: 14px; color: #4b5563; display: flex; flex-wrap: wrap; gap: 24px; }}
  .meta-bar b {{ color: #111827; }}
  .alert-banner {{ background: #fef3c7; border-left: 4px solid #f59e0b; padding: 14px 24px; font-size: 14px; color: #92400e; font-weight: 500; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; font-size: 14px; }}
  thead {{ background: #f9fafb; }}
  th {{ text-align: left; padding: 14px 16px; font-weight: 600; color: #374151; border-bottom: 2px solid #e5e7eb; font-size: 13px; }}
  td {{ padding: 14px 16px; border-bottom: 1px solid #f1f5f9; }}
  tr.product-row {{ background: #fafbfc; }}
  tr.product-row td {{ font-weight: 600; color: #1e3a8a; padding-top: 18px; padding-bottom: 8px; }}
  tr.total-row {{ background: linear-gradient(90deg, #fef3c7, #fde68a); }}
  tr.total-row td {{ font-weight: 700; color: #78350f; border-top: 3px solid #f59e0b; font-size: 15px; }}
  .product-tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin-left: 8px; }}
  .tag-hsi {{ background: #dbeafe; color: #1e40af; }}
  .tag-hhi {{ background: #fef3c7; color: #92400e; }}
  .tag-hti {{ background: #ede9fe; color: #5b21b6; }}
  .change-up {{ color: #dc2626; font-weight: 600; }}
  .change-down {{ color: #16a34a; font-weight: 600; }}
  .arrow-up::before {{ content: "▲ "; }}
  .arrow-down::before {{ content: "▼ "; }}
  .analysis-box {{ margin-top: 20px; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }}
  .analysis-box h3 {{ background: #fee2e2; color: #991b1b; padding: 14px 24px; font-size: 16px; border-bottom: 1px solid #fecaca; }}
  .analysis-content {{ padding: 20px 24px; }}
  .analysis-content table {{ border: 1px solid #e5e7eb; border-radius: 6px; }}
  .interpretation {{ margin-top: 14px; padding: 14px 18px; background: #fef9c3; border-left: 4px solid #eab308; border-radius: 4px; color: #713f12; font-size: 14px; }}
  .footer-note {{ background: #fff; padding: 16px 32px; border-top: 1px solid #e5e7eb; border-radius: 0 0 12px 12px; font-size: 12px; color: #6b7280; }}
  .legend {{ background: #fff; padding: 18px 32px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280; display: flex; gap: 24px; flex-wrap: wrap; }}
</style>
</head>
<body>
<div class="container">
<header>
  <h1>{title_prefix} <span class="badge">{badge_text}</span></h1>
  <div class="subtitle">{today_date} · 对比基准：{base_label}</div>
</header>
<div class="meta-bar">
  <div><b>日期：</b>{today_date}</div>
  <div><b>对比基准：</b>{base_label}</div>
  <div><b>活跃合约：</b>{results[0]['near_month'][:4]}/{results[0]['near_month'][4:]} + {results[0]['far_month'][:4]}/{results[0]['far_month'][4:]}</div>
</div>
{'<div class="alert-banner">⚠️ <b>异常波动预警：</b>有品种 NOI 变化超过 3%，详见下方分析。</div>' if anomalies else ''}
<table>
  <thead>
    <tr>
      <th>期货品种</th><th>合约月份</th><th>到期日</th>
      <th style="text-align:right;">今日 NOI</th><th style="text-align:right;">基准 NOI</th>
      <th style="text-align:right;">变化张数</th><th style="text-align:right;">变化 %</th>
      <th style="text-align:right;">品种合计 / 变化</th>
    </tr>
  </thead>
  <tbody>
    {rows}
    <tr class="total-row">
      <td colspan="3">📊 三大品种总计</td>
      <td style="text-align:right;">{fmt_num(grand_today)}</td>
      <td style="text-align:right;">{fmt_num(grand_base if grand_base else None)}</td>
      <td style="text-align:right;">{grand_change_html}</td>
      <td style="text-align:right;">{grand_pct_html}</td>
      <td style="text-align:right;">—</td>
    </tr>
  </tbody>
</table>
<div class="legend">
  <div>🔴 净多头增加（涨红）</div>
  <div>🟢 净多头减少（跌绿）</div>
  <div>⚠️ 异常波动阈值：|变化%| ≥ 3%</div>
</div>
{anomaly_html}
<div class="footer-note">
  <p>📌 数据源：etnet 經濟通 · 自动抓取生成</p>
  <p>📌 中国股市惯例：涨红跌绿</p>
</div>
</div>
</body>
</html>"""
    return html


# ── 微信推送 ──────────────────────────────────────────
def push_wechat(title, desp, key=None):
    """
    通过 Server酱 推送微信。
    key 从环境变量 SERVERCHAN_KEY 读取，或传入。
    """
    if key is None:
        key = os.environ.get("SERVERCHAN_KEY", "")
    if not key:
        print("⚠️ SERVERCHAN_KEY not set, skip WeChat push")
        return False

    url = f"https://sctapi.ftqq.com/{key}.send"
    try:
        resp = requests.post(url, data={"title": title, "desp": desp}, timeout=30)
        result = resp.json()
        if result.get("code") == 0:
            print(f"  ✅ WeChat push: {title} (pushid: {result.get('data', {}).get('pushid')})")
            return True
        else:
            print(f"  ❌ WeChat push failed: {result}")
            return False
    except Exception as e:
        print(f"  ❌ WeChat push error: {e}")
        return False


def build_wechat_summary(results):
    """构建微信推送的三行摘要文本"""
    lines = []
    for r in results:
        name = PRODUCT_SHORT[r["product"]]
        change = r["total_change"]
        pct = r["total_pct"]
        if change is None or pct is None:
            lines.append(f"{name}: {r['today_total']:,} (首次记录)")
        else:
            sign = "+" if change >= 0 else ""
            lines.append(f"{name}: {sign}{change:,} ({sign}{pct:.2f}%)")
    return "\n".join(lines)


# ── 异常分析 ──────────────────────────────────────────
def detect_anomalies(results, threshold=3.0):
    """检测品种合计 NOI 变化超过阈值的品种"""
    anomalies = []
    for r in results:
        if r["total_pct"] is not None and abs(r["total_pct"]) >= threshold:
            anomalies.append({
                "product": r["product"],
                "result": r,
                "total_change": r["total_change"],
                "total_pct": r["total_pct"],
            })
    return anomalies


def analyze_anomaly(anomaly, base_data):
    """
    对异常品种做深度分析：抓成交额、判断放量、给出市场解读。
    """
    product = anomaly["product"]
    r = anomaly["result"]

    # 抓今日成交额
    turnover_today = fetch_turnover(product)

    # 从基准数据读取昨日成交额
    base_turnover = None
    if base_data and "turnover" in base_data:
        base_turnover = base_data["turnover"].get(product)

    # 判断是否显著放量（增幅超过30%）
    vol_amplified = None
    if turnover_today and base_turnover:
        # 提取数字部分
        today_num = float(re.search(r'[\d.]+', turnover_today.replace(",", "")).group()) if re.search(r'[\d.]+', turnover_today.replace(",", "")) else None
        base_num = float(re.search(r'[\d.]+', base_turnover.replace(",", "")).group()) if re.search(r'[\d.]+', base_turnover.replace(",", "")) else None
        if today_num and base_num and base_num > 0:
            vol_amplified = ((today_num - base_num) / base_num) * 100

    anomaly["turnover_today"] = turnover_today or "—"
    anomaly["turnover_base"] = base_turnover or "—"
    anomaly["vol_amplified"] = vol_amplified if vol_amplified and vol_amplified >= 30 else None

    return anomaly


def build_wechat_alert(anomalies):
    """构建异常预警微信推送文本"""
    sections = []
    for a in anomalies:
        product = a["product"]
        name = PRODUCT_NAMES[product]
        r = a["result"]
        change_val = r["today_change"] or "—"
        change_pct_val = r["today_change_pct"] or "—"
        is_bullish = change_val != "—" and not change_val.startswith("-")
        candle = "阳线" if is_bullish else "阴线"
        direction = "上涨" if is_bullish else "下跌"

        turnover_line = f"成交{a['turnover_today']}"
        if a["turnover_base"] != "—":
            vol_note = f"放大{a['vol_amplified']:.1f}%" if a.get("vol_amplified") else "未显著放大"
            turnover_line += f" vs 昨日{a['turnover_base']} {vol_note}"
        else:
            turnover_line += " (无对比)"

        # 市场解读
        noi_up = a["total_pct"] >= 0
        if noi_up and not is_bullish:
            interp = "多头逢低建仓/空头回补，下跌中逆势做多"
        elif noi_up and is_bullish:
            interp = "多头积极建仓，看多信号"
        elif not noi_up and not is_bullish:
            interp = "多头止损离场"
        else:
            interp = "多头获利了结/空头回补"

        # 价格涨跌描述
        if change_pct_val and change_pct_val != "—":
            try:
                pct_num = abs(float(change_pct_val.rstrip("%")))
                price_line = f"{candle} {direction}{pct_num:.2f}%"
            except (ValueError, AttributeError):
                price_line = f"{candle}"
        else:
            price_line = f"{candle} (无数据)"

        section = f"""{name} NOI {'+' if noi_up else ''}{a['total_pct']:.2f}%
{price_line}
{turnover_line}
→ {interp}"""
        sections.append(section)
    return "\n\n".join(sections)


# ── 工具 ──────────────────────────────────────────────
def get_today_str():
    return datetime.now(HKT).strftime("%Y-%m-%d")


def get_today_compact():
    return datetime.now(HKT).strftime("%Y%m%d")


def save_turnover(results_data, contracts):
    """抓取三大品种成交额并附加到 data dict"""
    turnover = {}
    for product in ["HSI", "HHI", "HTI"]:
        t = fetch_turnover(product)
        if t:
            turnover[product] = t
            print(f"  ✅ Turnover {product}: {t}")
        else:
            turnover[product] = None
            print(f"  ⚠️ Turnover {product}: not found")
    return turnover
