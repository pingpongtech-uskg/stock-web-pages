"""
資料擷取層：yfinance 主力 → FinMind 備援
所有輸出格式相容 FinMind（date/type/value），讓 scoring 邏輯不需修改。
"""
import json, os, time, threading
from collections import defaultdict, deque
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf

# ── FinMind rate limiter（滑動視窗，避免被 ban）──
# 上限 600/hr，我們保守限制 400/hr + 8/min
_fm_lock = threading.Lock()
_fm_timestamps = deque()  # 記錄過去 1hr 內的所有請求時間


def _fm_wait():
    """等待直到 rate limit 允許發出請求，回傳等待秒數"""
    global _fm_timestamps
    now = time.time()
    with _fm_lock:
        # 清除超過 1hr 的紀錄
        while _fm_timestamps and now - _fm_timestamps[0] > 3600:
            _fm_timestamps.popleft()
        
        # 檢查 1hr 限制（400次）
        if len(_fm_timestamps) >= 400:
            wait = _fm_timestamps[0] + 3600 - now
            if wait > 0:
                return wait
        
        # 檢查 1min 限制（8次）
        recent_min = [t for t in _fm_timestamps if now - t < 60]
        if len(recent_min) >= 8:
            wait = recent_min[0] + 60 - now
            if wait > 0:
                return wait
        
        # 檢查 5s 限制（至少間隔 5 秒）
        if _fm_timestamps and now - _fm_timestamps[-1] < 5:
            return _fm_timestamps[-1] + 5 - now
        
        return 0


def _fm_register():
    """記錄一次 FinMind API 請求"""
    with _fm_lock:
        _fm_timestamps.append(time.time())

# yfinance → FinMind 欄位對照
FIN_FIELD_MAP = {
    'Total Revenue': 'Revenue',
    'Gross Profit': 'GrossProfit',
    'Operating Income': 'OperatingIncome',
    'Pretax Income': 'PreTaxIncome',
    'Net Income': 'IncomeAfterTaxes',
    'Basic EPS': 'EPS',
}

CF_FIELD_MAP = {
    'Operating Cash Flow': 'CashFlowsFromOperatingActivities',
    'Capital Expenditure': 'PropertyPlantAndEquipment',
    'Free Cash Flow': 'FreeCashFlow',
    'Net Income From Continuing Operations': 'IncomeAfterTaxes',
}

BS_FIELD_MAP = {
    'Accounts Receivable': 'AccountsReceivableNet',
    'Inventory': 'Inventories',
    'Current Assets': 'CurrentAssets',
    'Current Liabilities': 'CurrentLiabilities',
    'Total Debt': 'TotalDebt',
    'Long Term Debt': 'LongTermDebt',
}


def _yf_ticker(code):
    """Get yfinance Ticker with proper suffix"""
    suffix = '.TW'  # TWSE default
    # Check OTC from database if possible
    if hasattr(_yf_ticker, '_db_exchange'):
        exchange = _yf_ticker._db_exchange.get(code)
        if exchange == 'OTC':
            suffix = '.TWO'
    try:
        return yf.Ticker(f"{code}{suffix}")
    except:
        return None


def _yf_to_df(yf_data, field_map, stock_id=''):
    """Convert yfinance DataFrame (cols=dates, idx=fields) → FinMind format"""
    rows = []
    if yf_data is None or yf_data.empty:
        return None
    for col in yf_data.columns:
        date_str = str(col.date()) if hasattr(col, 'date') else str(col)[:10]
        for yf_field, fm_field in field_map.items():
            if yf_field in yf_data.index:
                val = yf_data.loc[yf_field, col]
                if pd.notna(val) and val != 0:
                    rows.append({
                        'date': date_str,
                        'stock_id': stock_id,
                        'type': fm_field,
                        'value': float(val),
                        'origin_name': '',
                    })
    if not rows:
        return None
    return pd.DataFrame(rows)


def yf_financials(code):
    """yfinance 損益表（季度優先，年度備援）"""
    try:
        ticker = _yf_ticker(code)
        if ticker is None:
            return None
        q = ticker.quarterly_financials
        if q is not None and not q.empty:
            df = _yf_to_df(q, FIN_FIELD_MAP, code)
            if df is not None and len(df) >= 10:
                return df
        a = ticker.financials
        return _yf_to_df(a, FIN_FIELD_MAP, code)
    except:
        return None


def yf_cashflow(code):
    """yfinance 現金流量表"""
    try:
        ticker = _yf_ticker(code)
        if ticker is None:
            return None
        cf = ticker.cashflow
        return _yf_to_df(cf, CF_FIELD_MAP, code)
    except:
        return None


def yf_balance_sheet(code):
    """yfinance 資產負債表"""
    try:
        ticker = _yf_ticker(code)
        if ticker is None:
            return None
        bs = ticker.balance_sheet
        return _yf_to_df(bs, BS_FIELD_MAP, code)
    except:
        return None


def yf_dividends(code):
    """yfinance 股息 → DataFrame with date/CashEarningsDistribution"""
    try:
        ticker = _yf_ticker(code)
        if ticker is None:
            return None
        div = ticker.dividends
        if div is None or div.empty:
            return None
        rows = []
        for dt, val in div.items():
            rows.append({
                'date': str(dt.date()) if hasattr(dt, 'date') else str(dt)[:10],
                'stock_id': code,
                'CashEarningsDistribution': float(val),
                'year': str(dt.year),
            })
        return pd.DataFrame(rows)
    except:
        return None


def yf_quarterly_revenue(code):
    """yfinance 季度營收（給 g1 fallback）"""
    ticker = _yf_ticker(code)
    if ticker is None:
        return None
    q = ticker.quarterly_financials
    if q is None or q.empty or 'Total Revenue' not in q.index:
        return None
    rows = []
    for col in q.columns:
        date_str = str(col.date()) if hasattr(col, 'date') else str(col)[:10]
        val = q.loc['Total Revenue', col]
        if pd.notna(val):
            rows.append({'date': date_str, 'revenue': float(val)})
    if not rows:
        return None
    return pd.DataFrame(rows).sort_values('date')


def fm_sg(api, func, stock_id, **kw):
    """FinMind API 含 rate limit 控管 — 被拒直接跳過不重試"""
    wait = _fm_wait()
    if wait > 0:
        time.sleep(wait)
    _fm_register()
    
    try:
        df = getattr(api, func)(stock_id=stock_id, **kw)
        if df is not None:
            return df
    except Exception as e:
        err = str(e)
        if 'illegal' in err.lower() or 'upper limit' in err.lower():
            pass  # rate limit，直接放棄
        else:
            time.sleep(5)  # 其他錯誤重試一次
            try:
                df = getattr(api, func)(stock_id=stock_id, **kw)
                return df
            except:
                pass
    return None


# ── 雙源擷取 API（給 scoring 使用）──

def fetch_data(stock_id, data_type, finmind_api=None, **kw):
    """
    統一資料擷取：yfinance 主力 → FinMind 備援
    data_type: 'month_revenue' | 'financial_statement' | 'cash_flow' | 'balance_sheet' | 'dividend'
    回傳格式相容 FinMind DataFrame
    """
    now = datetime.now()
    
    def _yf_recent_enough(df, min_points=4, max_age_days=100):
        """檢查 yfinance 資料是否夠新夠多"""
        if df is None:
            return False
        if 'date' in df.columns:
            dates = sorted(df['date'].unique())
            if len(dates) < min_points:
                return False
            try:
                latest = datetime.strptime(dates[-1], '%Y-%m-%d')
                if (now - latest).days > max_age_days:
                    return False
            except:
                pass
        return True
    
    # ── yfinance 主力 ──
    yf_data = None
    if data_type == 'financial_statement':
        yf_data = yf_financials(stock_id)
    elif data_type == 'cash_flow':
        yf_data = yf_cashflow(stock_id)
    elif data_type == 'balance_sheet':
        yf_data = yf_balance_sheet(stock_id)
    elif data_type == 'dividend':
        yf_data = yf_dividends(stock_id)
    elif data_type == 'month_revenue':
        pass
    
    if data_type != 'month_revenue':
        # 有 FinMind 備援時嚴格檢查，無備援時直接接受 yfinance
        age_limits = {'financial_statement': 100, 'cash_flow': 365, 'balance_sheet': 365, 'dividend': 365}
        age_limit = age_limits.get(data_type, 100)
        yf_ok = yf_data is not None and _yf_recent_enough(yf_data, min_points=3, max_age_days=age_limit)
        
        if yf_ok:
            return yf_data
        # yfinance 不夠新 → 試 FinMind
        if finmind_api is not None:
            func_map = {
                'month_revenue': 'taiwan_stock_month_revenue',
                'financial_statement': 'taiwan_stock_financial_statement',
                'cash_flow': 'taiwan_stock_cash_flows_statement',
                'balance_sheet': 'taiwan_stock_balance_sheet',
                'dividend': 'taiwan_stock_dividend',
            }
            func_name = func_map.get(data_type)
            if func_name:
                fm_df = fm_sg(finmind_api, func_name, stock_id, **kw)
                if fm_df is not None:
                    return fm_df
        # FinMind 也失敗 → 回頭用 yfinance（有總比沒有好）
        if yf_data is not None:
            return yf_data
        return None

    # ── FinMind 備援 ──
    if finmind_api is None:
        return None

    func_map = {
        'month_revenue': 'taiwan_stock_month_revenue',
        'financial_statement': 'taiwan_stock_financial_statement',
        'cash_flow': 'taiwan_stock_cash_flows_statement',
        'balance_sheet': 'taiwan_stock_balance_sheet',
        'dividend': 'taiwan_stock_dividend',
    }
    func_name = func_map.get(data_type)
    if func_name is None:
        return None
    return fm_sg(finmind_api, func_name, stock_id, **kw)


def import_data():
    """讓 daily_monitor.py 可以 import 此模組"""
    pass
