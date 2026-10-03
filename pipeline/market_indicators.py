"""Official TWSE volume participation indicators for the dashboard."""
from __future__ import annotations
import json, math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from pipeline.source_receipts import read_raw, capture_raw, write_bundle, safe_directory
from pipeline.trading_calendar import is_open
FORMULA_VERSION="twse-volume-multiple-v1"; SYMBOL="00631L"; NAME="元大台灣50正2"; THRESHOLD=2.0; TWSE_STOCK_DAY="https://www.twse.com.tw/exchangeReport/STOCK_DAY"
def _date(value):
 text=str(value or '').strip().replace('-','/'); parts=text.split('/')
 if len(parts)==3:
  try:
   y,m,d=(int(x) for x in parts); y=y+1911 if y<1911 else y; return date(y,m,d)
  except ValueError: return None
 try: return date.fromisoformat(text[:10])
 except ValueError: return None
def _volume(value):
 if value in (None,'','-','--','N/A'): return None
 try: n=float(str(value).replace(',','').strip())
 except (TypeError,ValueError): return None
 return n if math.isfinite(n) and n>=0 else None
def _unavailable(reason,market_date=None):
 return {'symbol':SYMBOL,'name':NAME,'market':'TWSE','marketDate':market_date.isoformat() if market_date else None,'currentVolume':None,'previous5AverageVolume':None,'multiple':None,'threshold':THRESHOLD,'displayOnly':True,'priorFiveSessions':[],'signal':'unknown','status':'unavailable','formulaVersion':FORMULA_VERSION,'sourceRefs':[],'reason':reason}
def compute_volume_multiple(rows,*,as_of=None):
 points={}
 for row in rows:
  if not isinstance(row,dict): continue
  day=_date(row.get('date') or row.get('日期'))
  if day is None or (as_of is not None and day>as_of): continue
  volume=_volume(row.get('volume') if 'volume' in row else row.get('成交股數'))
  points[day]=volume
 ordered=sorted(points)
 if len(ordered)<6: return _unavailable('需要目前交易日與前五個完成交易日的成交量資料')
 current_day=ordered[-1]; previous=ordered[-6:-1]; current=points[current_day]
 if current is None or any(points[d] is None for d in previous): return _unavailable('目前日或前五個交易日成交量資料不完整',market_date=current_day)
 average=sum(points[d] for d in previous)/5.0
 if not math.isfinite(average) or average<=0: return _unavailable('前五個交易日平均成交量不可用',market_date=current_day)
 multiple=current/average
 if not math.isfinite(multiple): return _unavailable('成交量倍數不可用',market_date=current_day)
 return {'symbol':SYMBOL,'name':NAME,'market':'TWSE','marketDate':current_day.isoformat(),'currentVolume':int(current) if current.is_integer() else current,'previous5AverageVolume':average,'multiple':multiple,'threshold':THRESHOLD,'displayOnly':True,'priorFiveSessions':[{'date':d.isoformat(),'volume':int(points[d]) if points[d].is_integer() else points[d]} for d in previous],'signal':'green' if multiple>=THRESHOLD else 'yellow','status':'available','formulaVersion':FORMULA_VERSION,'sourceRefs':[],'reason':'今日成交量 ÷ 前五個完成交易日平均成交量（不含今日）'}
def _fetch_stock_day(month, *, timeout=30, source_cache_dir=None):
 if not isinstance(month, date) or type(timeout) not in (int, float) or not 0 < timeout <= 30:
  raise ValueError('invalid official volume request')
 if source_cache_dir is not None: source_cache_dir=safe_directory(source_cache_dir)
 query=urlencode({'response':'json','date':month.strftime('%Y%m01'),'stockNo':SYMBOL}); url=f'{TWSE_STOCK_DAY}?{query}'
 req=Request(url,headers={'User-Agent':'stock-web-pages/1.0'})
 with urlopen(req,timeout=timeout) as response: raw=read_raw(response)
 receipt=capture_raw(source_cache_dir,prefix='stock-day-'+month.strftime('%Y-%m'),raw=raw,source_url=url,
                     unit='shares',request_period={'requestMonth':month.strftime('%Y-%m')},
                     retrieved_at=datetime.now(timezone.utc).isoformat()) if source_cache_dir is not None else None
 payload=json.loads(raw)
 if not isinstance(payload,dict) or payload.get('stat')!='OK': raise ValueError('TWSE STOCK_DAY unavailable')
 reported=_date(payload.get('date'))
 if reported is None or (reported.year,reported.month)!=(month.year,month.month): raise ValueError('official volume report month mismatch')
 if not isinstance(payload.get('fields'),list) or payload['fields'][:2]!=['日期','成交股數']:
  raise ValueError('official volume units unavailable')
 if not isinstance(payload.get('data'),list): raise ValueError('invalid official volume rows')
 rows=[]; seen=set()
 for row in payload['data']:
  if not isinstance(row,list) or len(row)<2: raise ValueError('invalid official volume row')
  day=_date(row[0]); volume=_volume(row[1])
  if day is None or (day.year,day.month)!=(month.year,month.month) or day in seen:
   raise ValueError('official volume row date mismatch')
  if volume is None or not volume.is_integer() or volume>2**53-1: raise ValueError('invalid official volume shares')
  seen.add(day); rows.append({'date':row[0],'volume':row[1]})
 if receipt is not None: receipt={**receipt,'reportedDate':reported.isoformat(),'reportedDates':sorted(day.isoformat() for day in seen)}
 return rows,url,receipt


def fetch_twse_stock_day(month,*,timeout=30,source_cache_dir=None):
 rows,url,_receipt=_fetch_stock_day(month,timeout=timeout,source_cache_dir=source_cache_dir)
 return rows,url
def _previous_month(month): return ((month.replace(day=1)-timedelta(days=1)).replace(day=1))
def _capture_volume_dates(calendar,target):
 if not isinstance(calendar,dict) or not is_open(calendar,target.isoformat()): raise ValueError('official calendar unavailable')
 days=[]; current=target
 for _ in range(60):
  if is_open(calendar,current.isoformat()): days.append(current.isoformat())
  if len(days)==7: return sorted(days)
  current-=timedelta(days=1)
 raise ValueError('official volume session window unavailable')


def build_00631l_volume_indicator(as_of=None,*,source_cache_dir=None,calendar=None):
 target=_date(as_of) if as_of is not None else date.today()
 if target is None: return _unavailable('marketDate 格式錯誤')
 try:
  if source_cache_dir is not None:
   if as_of is None: raise ValueError('capture requires explicit market date')
   dates=_capture_volume_dates(calendar,target)
   rows_a,source_a,receipt_a=_fetch_stock_day(target,source_cache_dir=source_cache_dir)
   rows_b,source_b,receipt_b=_fetch_stock_day(_previous_month(target),source_cache_dir=source_cache_dir)
   values={_date(row['date']).isoformat():int(_volume(row['volume'])) for row in rows_a+rows_b}
   if any(day not in values for day in dates): raise ValueError('official volume session missing')
   normalized={'rows':[{'marketDate':day,'code':SYMBOL,'volume':values[day],'unit':'shares'} for day in dates]}
   write_bundle(Path(source_cache_dir),prefix='volume',receipts=[receipt_b,receipt_a],normalized=normalized,
                group={'kind':'volume','market':'TWSE','codes':[SYMBOL],'dates':dates,'unit':'shares','sourceUrl':TWSE_STOCK_DAY})
   indicator_rows=[{'date':day,'volume':values[day]} for day in dates]
  else:
   rows_a,source_a=fetch_twse_stock_day(target); rows_b,source_b=fetch_twse_stock_day(_previous_month(target))
   indicator_rows=rows_a+rows_b
  result=compute_volume_multiple(indicator_rows,as_of=target); result['sourceRefs']=[source_b,source_a]; return result
 except Exception as exc:
  result=_unavailable(f'TWSE 官方成交量來源不可用：{type(exc).__name__}',market_date=target); result['sourceRefs']=[]; return result
