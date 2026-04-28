#!/usr/bin/env python3
"""
RiskRadar — 股市風險預警系統
抓取 18 項市場指標，計算風險分數，生成 HTML 儀表板
"""

import os, json, time
from datetime import datetime, timedelta
import yfinance as yf
import requests

DATA_FILE = "data/result.json"
HTML_FILE = "index.html"
os.makedirs("data", exist_ok=True)


# ── 工具函式 ────────────────────────────────────────────────────

def yf_get(symbol, period="7d"):
    try:
        close = yf.Ticker(symbol).history(period=period)["Close"].dropna()
        if len(close) < 1:
            return None, None, None
        latest = float(close.iloc[-1])
        prev   = float(close.iloc[-2]) if len(close) >= 2 else latest
        chg    = round((latest - prev) / prev * 100, 2) if prev else 0
        return round(latest, 2), round(prev, 2), chg
    except Exception as e:
        print(f"  ⚠ {symbol}: {e}")
        return None, None, None


def yf_ma(symbol, days):
    try:
        close = yf.Ticker(symbol).history(period=f"{days*2}d")["Close"].dropna()
        return round(float(close.rolling(days).mean().iloc[-1]), 2) if len(close) >= days else None
    except:
        return None


def twse_get(url, parser):
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        d = r.json()
        if d.get("stat") == "OK" and d.get("data"):
            return parser(d["data"])
    except Exception as e:
        print(f"  ⚠ TWSE: {e}")
    return None


# ── 資料抓取 ────────────────────────────────────────────────────

def collect():
    print("📡 抓取市場數據...")
    d = {}

    yf_map = {
        "vix":    "^VIX",
        "sp500":  "^GSPC",
        "sox":    "^SOX",
        "us3m":   "^IRX",
        "us10y":  "^TNX",
        "hyg":    "HYG",
        "gold":   "GC=F",
        "oil":    "CL=F",
        "copper": "HG=F",
        "jpy":    "JPY=X",
        "dxy":    "DX-Y.NYB",
        "twii":   "^TWII",
        "tsmc":   "2330.TW",
        "usdtwd": "TWD=X",
        "sse":    "000001.SS",
    }

    for key, sym in yf_map.items():
        v, p, c = yf_get(sym)
        d[key] = {"value": v, "prev": p, "change_pct": c}
        print(f"   {key:10s} = {v}")
        time.sleep(0.5)

    d["sp500_ma200"] = yf_ma("^GSPC", 200)
    d["twii_ma20"]   = yf_ma("^TWII", 20)
    d["tsmc_ma60"]   = yf_ma("2330.TW", 60)

    # CNN 恐貪指數
    try:
        r = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            timeout=10, headers={"User-Agent": "Mozilla/5.0"}
        )
        fg = r.json()["fear_and_greed"]
        d["fear_greed"] = {"value": round(float(fg["score"]), 1), "rating": fg["rating"]}
        print(f"   fear_greed = {d['fear_greed']['value']}")
    except Exception as e:
        d["fear_greed"] = {"value": None, "rating": "N/A"}
        print(f"  ⚠ Fear&Greed: {e}")

    # 三大法人買賣超（合計最後一欄）
    def parse_foreign(rows):
        raw = rows[-1][-1].replace(",", "").replace("+", "")
        return round(float(raw) / 1e8, 1)

    d["twse_foreign"] = {"value": twse_get(
        "https://www.twse.com.tw/rwd/zh/fund/BFI82U?type=day&response=json",
        parse_foreign
    )}

    # 融資餘額
    def parse_margin(rows):
        if len(rows) < 2:
            return None
        v1 = float(rows[-1][4].replace(",", ""))
        v2 = float(rows[-2][4].replace(",", ""))
        chg = round((v1 - v2) / v2 * 100, 2) if v2 else 0
        return {"value": round(v1 / 1e8, 1), "change_pct": chg}

    margin = twse_get(
        "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=json",
        parse_margin
    )
    d["twse_margin"] = margin if isinstance(margin, dict) else {"value": None, "change_pct": None}

    # 大盤成交量
    def parse_volume(rows):
        raw = rows[-1][2].replace(",", "")
        return round(float(raw) / 1e8, 1)

    d["twse_volume"] = {"value": twse_get(
        "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?response=json",
        parse_volume
    )}

    now = datetime.utcnow()
    d["updated_utc"] = now.strftime("%Y-%m-%d %H:%M UTC")
    d["updated_tw"]  = (now + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M 台灣時間")

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print("✅ 數據已儲存")
    return d


# ── 評分引擎 ────────────────────────────────────────────────────

def calc_score(d):
    total = 0
    signals = []

    def val(k):
        x = d.get(k)
        return x.get("value") if isinstance(x, dict) else x

    def chg(k):
        x = d.get(k)
        return x.get("change_pct") if isinstance(x, dict) else None

    def add(icon, name, v_str, desc, pts):
        nonlocal total
        total += pts
        signals.append((icon, name, v_str, desc, pts))

    # VIX（15分）
    vix = val("vix")
    if vix:
        if vix >= 35:   add("🔴", "VIX 恐慌指數",  f"{vix:.1f}", "極度恐慌", 15)
        elif vix >= 25: add("🟠", "VIX 恐慌指數",  f"{vix:.1f}", "市場緊張", 10)
        elif vix >= 18: add("🟡", "VIX 恐慌指數",  f"{vix:.1f}", "輕微波動", 5)
        else:           add("🟢", "VIX 恐慌指數",  f"{vix:.1f}", "市場平穩", 0)

    # 恐貪指數（10分）
    fg = val("fear_greed")
    if fg is not None:
        rating = d.get("fear_greed", {}).get("rating", "")
        if fg <= 20:   add("🔴", "恐貪指數", f"{fg:.0f} {rating}", "極度恐懼", 10)
        elif fg <= 35: add("🟠", "恐貪指數", f"{fg:.0f} {rating}", "偏恐懼", 6)
        elif fg >= 80: add("🟠", "恐貪指數", f"{fg:.0f} {rating}", "極度貪婪（反向警示）", 8)
        elif fg >= 65: add("🟡", "恐貪指數", f"{fg:.0f} {rating}", "偏貪婪", 3)
        else:          add("🟢", "恐貪指數", f"{fg:.0f} {rating}", "中性", 0)

    # 殖利率曲線（8分）
    us3m = val("us3m"); us10y = val("us10y")
    if us3m and us10y:
        spread = us10y - us3m
        s = f"{spread:+.2f}%"
        if spread < -0.5:   add("🔴", "殖利率曲線(3M-10Y)", s, "嚴重倒掛（衰退訊號）", 8)
        elif spread < 0:    add("🟠", "殖利率曲線(3M-10Y)", s, "輕微倒掛", 4)
        elif spread < 0.5:  add("🟡", "殖利率曲線(3M-10Y)", s, "接近倒掛", 1)
        else:               add("🟢", "殖利率曲線(3M-10Y)", s, "正常", 0)

    # SOX 半導體（8分）
    sox_c = chg("sox"); sox_v = val("sox")
    if sox_c is not None:
        if sox_c <= -5:   add("🔴", "SOX 半導體",  f"{sox_v:,.0f} ({sox_c:+.2f}%)", "急跌（台積電預警）", 8)
        elif sox_c <= -2: add("🟠", "SOX 半導體",  f"{sox_v:,.0f} ({sox_c:+.2f}%)", "走弱", 4)
        else:             add("🟢", "SOX 半導體",  f"{sox_v:,.0f} ({sox_c:+.2f}%)", "平穩/走強", 0)

    # 高收益債 HYG（8分）
    hyg_c = chg("hyg"); hyg_v = val("hyg")
    if hyg_c is not None:
        if hyg_c <= -1.5: add("🔴", "高收益債 HYG", f"${hyg_v:.2f} ({hyg_c:+.2f}%)", "信用崩壞", 8)
        elif hyg_c <= -0.5: add("🟠", "高收益債 HYG", f"${hyg_v:.2f} ({hyg_c:+.2f}%)", "信用緊縮", 4)
        else:             add("🟢", "高收益債 HYG", f"${hyg_v:.2f} ({hyg_c:+.2f}%)", "信用平穩", 0)

    # S&P500 vs 200MA（5分）
    sp500 = val("sp500"); sp500_ma = d.get("sp500_ma200")
    if sp500 and sp500_ma:
        if sp500 < sp500_ma:
            add("🔴", "S&P500 vs 200MA", f"{sp500:,.0f}（MA:{sp500_ma:,.0f}）", "跌破200日均線", 5)
        else:
            add("🟢", "S&P500 vs 200MA", f"{sp500:,.0f}（MA:{sp500_ma:,.0f}）", "站上200日均線", 0)

    # 黃金（5分）
    gold_c = chg("gold"); gold_v = val("gold")
    if gold_c is not None:
        if gold_c >= 2:   add("🟠", "黃金",         f"${gold_v:,.0f} ({gold_c:+.2f}%)", "急漲（避險情緒高）", 5)
        elif gold_c >= 1: add("🟡", "黃金",         f"${gold_v:,.0f} ({gold_c:+.2f}%)", "小漲", 2)
        else:             add("🟢", "黃金",         f"${gold_v:,.0f} ({gold_c:+.2f}%)", "平穩", 0)

    # 原油（4分）
    oil_c = chg("oil"); oil_v = val("oil")
    if oil_c is not None:
        if oil_c <= -4:   add("🔴", "原油 WTI",    f"${oil_v:.1f} ({oil_c:+.2f}%)", "暴跌（需求崩潰）", 4)
        elif oil_c >= 4:  add("🟠", "原油 WTI",    f"${oil_v:.1f} ({oil_c:+.2f}%)", "暴漲（通膨壓力）", 3)
        else:             add("🟢", "原油 WTI",    f"${oil_v:.1f} ({oil_c:+.2f}%)", "平穩", 0)

    # 銅（3分）
    copper_c = chg("copper"); copper_v = val("copper")
    if copper_c is not None:
        if copper_c <= -2: add("🔴", "銅價（景氣計）", f"${copper_v:.2f} ({copper_c:+.2f}%)", "下跌（景氣衰退）", 3)
        else:              add("🟢", "銅價（景氣計）", f"${copper_v:.2f} ({copper_c:+.2f}%)", "平穩/上漲", 0)

    # 日圓（5分）USD/JPY 下跌 = 日圓升值 = 套利爆倉風險
    jpy_c = chg("jpy"); jpy_v = val("jpy")
    if jpy_c is not None:
        if jpy_c <= -1:     add("🔴", "日圓 USD/JPY", f"{jpy_v:.2f} ({jpy_c:+.2f}%)", "日圓急升（套利爆倉）", 5)
        elif jpy_c <= -0.5: add("🟡", "日圓 USD/JPY", f"{jpy_v:.2f} ({jpy_c:+.2f}%)", "日圓升值", 2)
        else:               add("🟢", "日圓 USD/JPY", f"{jpy_v:.2f} ({jpy_c:+.2f}%)", "套利交易平穩", 0)

    # DXY（3分）
    dxy_c = chg("dxy"); dxy_v = val("dxy")
    if dxy_c is not None:
        if dxy_c >= 0.8:    add("🟠", "DXY 美元指數", f"{dxy_v:.2f} ({dxy_c:+.2f}%)", "強升（壓制股市）", 3)
        else:               add("🟢", "DXY 美元指數", f"{dxy_v:.2f} ({dxy_c:+.2f}%)", "平穩/走弱", 0)

    # ── 台股 ──

    # 三大法人買賣超（15分）
    foreign = val("twse_foreign")
    if foreign is not None:
        if foreign <= -200:  add("🔴", "三大法人買賣超", f"{foreign:+.1f}億", "大幅賣超（資金撤出）", 15)
        elif foreign <= -50: add("🟠", "三大法人買賣超", f"{foreign:+.1f}億", "賣超（注意）", 8)
        else:                add("🟢", "三大法人買賣超", f"{foreign:+.1f}億", "買超/平衡", 0)

    # 台積電 vs 60MA（8分）
    tsmc = val("tsmc"); tsmc_ma = d.get("tsmc_ma60")
    if tsmc and tsmc_ma:
        if tsmc < tsmc_ma * 0.95:
            add("🔴", "台積電 2330", f"NT${tsmc:.0f}（MA60:{tsmc_ma:.0f}）", "跌破60MA超過5%", 8)
        elif tsmc < tsmc_ma:
            add("🟠", "台積電 2330", f"NT${tsmc:.0f}（MA60:{tsmc_ma:.0f}）", "低於60MA", 4)
        else:
            add("🟢", "台積電 2330", f"NT${tsmc:.0f}（MA60:{tsmc_ma:.0f}）", "站上60MA", 0)

    # 台股加權 vs 20MA（5分）
    twii = val("twii"); twii_ma = d.get("twii_ma20")
    if twii and twii_ma:
        if twii < twii_ma:
            add("🔴", "台股加權", f"{twii:,.0f}（MA20:{twii_ma:,.0f}）", "跌破20日均線", 5)
        else:
            add("🟢", "台股加權", f"{twii:,.0f}（MA20:{twii_ma:,.0f}）", "站上20日均線", 0)

    # 融資餘額（7分）
    margin_c = d.get("twse_margin", {}).get("change_pct") if isinstance(d.get("twse_margin"), dict) else None
    if margin_c is not None:
        mv = val("twse_margin")
        if margin_c >= 5:   add("🔴", "融資餘額變化", f"{mv:.1f}億 ({margin_c:+.2f}%)", "急增（頂部警訊）", 7)
        elif margin_c >= 2: add("🟠", "融資餘額變化", f"{mv:.1f}億 ({margin_c:+.2f}%)", "增加（注意槓桿）", 4)
        else:               add("🟢", "融資餘額變化", f"{mv:.1f}億 ({margin_c:+.2f}%)", "平穩/去化", 0)

    # 台幣匯率（3分）
    twd_c = chg("usdtwd"); twd_v = val("usdtwd")
    if twd_c is not None:
        if twd_c >= 1:     add("🔴", "台幣 USD/TWD", f"{twd_v:.3f} ({twd_c:+.2f}%)", "台幣急貶（外資出走）", 3)
        elif twd_c >= 0.5: add("🟡", "台幣 USD/TWD", f"{twd_v:.3f} ({twd_c:+.2f}%)", "台幣小貶", 1)
        else:              add("🟢", "台幣 USD/TWD", f"{twd_v:.3f} ({twd_c:+.2f}%)", "台幣穩定", 0)

    # 上海綜指（2分）
    sse_c = chg("sse"); sse_v = val("sse")
    if sse_c is not None:
        if sse_c <= -2:  add("🔴", "上海綜指", f"{sse_v:,.0f} ({sse_c:+.2f}%)", "下跌（中國風險外溢）", 2)
        else:            add("🟢", "上海綜指", f"{sse_v:,.0f} ({sse_c:+.2f}%)", "平穩/上漲", 0)

    total = min(total, 100)

    if total >= 81:   label, action = "⛔ 極高風險", "建議全數出場，持現金等待"
    elif total >= 66: label, action = "🔴 高風險",   "出場 70%，僅留核心部位"
    elif total >= 46: label, action = "🟠 中高風險",  "開始分批獲利了結 30~50%"
    elif total >= 26: label, action = "🟡 中等風險",  "留意訊號，縮減高風險部位"
    else:             label, action = "🟢 低風險",   "正常持倉，可評估加碼"

    return total, label, action, signals


# ── HTML 生成 ────────────────────────────────────────────────────

def generate_html(d, total, label, action, signals):
    if total >= 81:   sc, bg = "#ff1744", "#250008"
    elif total >= 66: sc, bg = "#ff4444", "#200008"
    elif total >= 46: sc, bg = "#ff6d00", "#1f0e00"
    elif total >= 26: sc, bg = "#ffea00", "#1a1700"
    else:             sc, bg = "#00e676", "#001a08"

    rows = ""
    for icon, name, v_str, desc, pts in signals:
        if pts > 0:
            pc = "#ff1744" if pts >= 8 else "#ff6d00"
            ps = f"+{pts}"
        else:
            pc = "#00e676"; ps = "✓"
        rows += f"""<tr>
<td style="font-size:1.3em;padding:8px 4px 8px 12px">{icon}</td>
<td style="padding:8px 4px;color:#e0e0f0;font-size:.9em">{name}</td>
<td style="padding:8px 4px;font-family:monospace;color:#999;font-size:.84em">{v_str}</td>
<td class="dc" style="padding:8px;color:#666;font-size:.82em">{desc}</td>
<td style="padding:8px 12px 8px 4px;color:{pc};font-weight:700;text-align:right;font-size:.9em">{ps}</td>
</tr>"""

    updated = d.get("updated_tw", "N/A")

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta http-equiv="refresh" content="3600">
<meta name="theme-color" content="#080810">
<title>RiskRadar 市場風險儀表板</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#080810;color:#f0f0f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh}}
.hdr{{position:sticky;top:0;z-index:100;background:rgba(8,8,16,.95);border-bottom:1px solid #1a1a2e;padding:12px 16px;display:flex;align-items:center;gap:10px}}
.logo{{font-size:1.25em;font-weight:700}}.time{{font-size:.75em;color:#555;margin-top:2px}}
.wrap{{max-width:600px;margin:0 auto;padding:14px}}
.sc{{background:{bg};border:1.5px solid {sc}40;border-radius:14px;padding:24px 16px;text-align:center;margin-bottom:14px}}
.sn{{font-size:5em;font-weight:800;color:{sc};line-height:1;letter-spacing:-3px}}
.sl{{font-size:1.4em;font-weight:700;margin:6px 0 4px}}
.sa{{display:inline-block;background:#ffffff12;padding:7px 14px;border-radius:8px;font-size:.9em;color:#ccc;margin-top:6px}}
.bb{{background:#141420;border-radius:8px;height:10px;margin:14px 0 0;overflow:hidden}}
.bf{{height:100%;border-radius:8px;background:linear-gradient(90deg,#00e676 0%,#ffea00 45%,#ff6d00 70%,#ff1744 100%)}}
.sec{{font-size:.7em;letter-spacing:2px;text-transform:uppercase;color:#444;margin:18px 0 8px 2px}}
.card{{background:#0d0d1c;border:1px solid #1a1a2e;border-radius:12px;overflow:hidden;margin-bottom:12px}}
table{{width:100%;border-collapse:collapse}}
tr:not(:last-child){{border-bottom:1px solid #1a1a2c}}
.rs{{padding:10px 14px;font-weight:700}}.rd{{padding:10px 14px;color:#777;font-size:.88em}}
.foot{{text-align:center;font-size:.72em;color:#333;padding:20px 0 30px;line-height:1.8}}
@media(max-width:480px){{.dc{{display:none}}}}
</style>
</head>
<body>
<div class="hdr">
  <span style="font-size:1.5em">📡</span>
  <div><div class="logo">RiskRadar</div><div class="time">⏱ {updated}</div></div>
</div>
<div class="wrap">
  <div class="sc">
    <div class="sn">{total}</div>
    <div class="sl">{label}</div>
    <div class="sa">{action}</div>
    <div class="bb"><div class="bf" style="width:{total}%"></div></div>
  </div>
  <div class="sec">⚡ 風險信號詳情</div>
  <div class="card"><table>
    <thead><tr style="background:#111120;font-size:.7em;color:#333;text-transform:uppercase">
      <th style="padding:8px 4px 8px 12px;width:36px"></th>
      <th style="padding:8px 4px;text-align:left">指標</th>
      <th style="padding:8px 4px;text-align:left">數值</th>
      <th class="dc" style="padding:8px;text-align:left">說明</th>
      <th style="padding:8px 12px 8px 4px;text-align:right">分數</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
  <div class="sec">📋 出場參考</div>
  <div class="card"><table><tbody>
    <tr><td class="rs" style="color:#00e676">0–25</td><td class="rd">🟢 低風險｜正常持倉，可評估加碼</td></tr>
    <tr><td class="rs" style="color:#ffea00">26–45</td><td class="rd">🟡 中等風險｜留意訊號，縮減高風險部位</td></tr>
    <tr><td class="rs" style="color:#ff6d00">46–65</td><td class="rd">🟠 中高風險｜分批獲利了結 30~50%</td></tr>
    <tr><td class="rs" style="color:#ff4444">66–80</td><td class="rd">🔴 高風險｜出場 70%，僅留核心部位</td></tr>
    <tr><td class="rs" style="color:#ff1744">81–100</td><td class="rd">⛔ 極高風險｜全數出場，持現金等待</td></tr>
  </tbody></table></div>
  <div class="foot">
    RiskRadar｜數據：Yahoo Finance · CNN · 台灣證交所<br>
    每日 08:00 / 18:00 台灣時間自動更新｜本頁僅供參考，非投資建議
  </div>
</div>
</body>
</html>"""

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print("✅ index.html 已生成")


# ── 主程式 ────────────────────────────────────────────────────────

if __name__ == "__main__":
    data   = collect()
    total, label, action, signals = calc_score(data)
    generate_html(data, total, label, action, signals)
    print(f"\n🎯 風險分數：{total}/100 {label}")
    print(f"💡 建議：{action}")
