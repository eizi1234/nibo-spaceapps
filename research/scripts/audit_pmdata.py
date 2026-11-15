"""Read-only PMData audit. No model fitting or target imputation.

python scripts/audit_pmdata.py --input C:/path/pmdata.zip
Also accepts an extracted directory. All participant outputs stay local.
"""
from __future__ import annotations
import argparse
import collections
import csv
import datetime as dt
import hashlib
import io
import json
import math
import platform
import pickle
import os
from pathlib import Path
import sys
import time
import zipfile

import ijson
import numpy as np
import pandas as pd
os.environ.setdefault('MPLCONFIGDIR',str(Path(__file__).resolve().parents[1]/'.mplconfig'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns

ROOT = Path(__file__).resolve().parents[1]
DOC = 'https://datasets.simula.no/pmdata/'
FITBIT = 'https://dev.fitbit.com/build/reference/web-api/sleep/get-sleep-log-by-date/'
START, END = dt.date(2019, 11, 1), dt.date(2020, 3, 31)
DAYS = [START + dt.timedelta(days=i) for i in range((END-START).days+1)]
REQUIRED = ['pmsys/wellness.csv', 'pmsys/srpe.csv', 'pmsys/injury.csv',
            'googledocs/reporting.csv', 'fitbit/sleep.json', 'fitbit/sleep_score.csv',
            'fitbit/heart_rate.json', 'fitbit/resting_heart_rate.json', 'fitbit/steps.json',
            'fitbit/exercise.json', 'fitbit/calories.json', 'fitbit/distance.json',
            'fitbit/lightly_active_minutes.json', 'fitbit/moderately_active_minutes.json',
            'fitbit/very_active_minutes.json', 'fitbit/sedentary_minutes.json',
            'fitbit/time_in_heart_rate_zones.json']


class Source:
    def __init__(self, path):
        self.path = Path(path)
        self.z = zipfile.ZipFile(path) if self.path.is_file() else None
        self.names = sorted(self.z.namelist() if self.z else
                            [p.relative_to(self.path).as_posix() for p in self.path.rglob('*') if p.is_file()])
    def open(self, n):
        return self.z.open(n) if self.z else (self.path/n).open('rb')
    def size(self, n):
        return self.z.getinfo(n).file_size if self.z else (self.path/n).stat().st_size


def parse_time(value, dayfirst=False):
    if value is None or str(value).strip() == '':
        return None
    s = str(value)
    try:
        return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        for fmt in (['%d/%m/%Y %H:%M:%S', '%d/%m/%Y'] if dayfirst else
                    ['%m/%d/%y %H:%M:%S', '%m/%d/%y', '%m/%d/%Y %H:%M:%S']):
            try:
                return dt.datetime.strptime(s, fmt)
            except ValueError:
                pass
    return None


def flat(record, prefix=''):
    out = {}
    for k, v in record.items():
        key = prefix + k
        if isinstance(v, dict):
            out.update(flat(v, key+'.'))
        else:
            out[key] = v
    return out


def missing(v):
    return v is None or (isinstance(v, str) and not v.strip())


def numeric(v):
    try:
        return float(v) if not missing(v) else np.nan
    except (ValueError, TypeError):
        return np.nan


def table(df):
    # No optional tabulate dependency.
    if df.empty:
        return '(none)'
    def cell(x):
        if isinstance(x, float):
            return f'{x:.3f}'
        return str(x).replace('|', '/').replace('\n', ' ')
    return '| ' + ' | '.join(map(str, df.columns)) + ' |\n|' + '|'.join(['---']*len(df.columns)) + '|\n' + '\n'.join('| ' + ' | '.join(cell(v) for v in row) + ' |' for row in df.itertuples(index=False, name=None))


def write_csv(rows, path):
    pd.DataFrame(rows).to_csv(path, index=False)


# Description, unit, expected range, role, interpretation. Undocumented fields remain explicit.
DEFS = {
    'fatigue': ('Subjective freshness/fatigue; lower scores indicate worse condition', 'ordered score', '1..5', 'target; historical feature', '1 very tired; 2 more tired than normal; 3 normal; 4 fresh; 5 very fresh'),
    'readiness': ('Readiness to exercise, not objective cognition', 'ordered score', '0..10', 'historical feature', '0 not ready; 10 fully ready'),
    'mood': ('Subjective mood', 'ordered score', '1..5', 'historical feature', 'higher is better mood'),
    'stress': ('Subjective stress condition', 'ordered score', '1..5', 'historical feature', 'higher is more favorable / less stressed, not greater stress'),
    'soreness': ('Subjective muscle condition', 'ordered score', '1..5', 'historical feature', 'higher is more favorable / less sore'),
    'sleep_quality': ('Self-rated sleep quality', 'ordered score', '1..5', 'historical feature', 'higher is better'),
    'sleep_duration_h': ('Self-reported previous sleep duration', 'hours', '0..24 plausibility screen', 'historical feature', 'not Fitbit total sleep time'),
    'effective_time_frame': ('PMSys effective event datetime, not a verified upload time', 'ISO datetime', 'valid timestamp', 'alignment metadata', 'Z denotes UTC; retrospective entry latency unknown'),
    'minutesAsleep': ('Fitbit estimated total sleep time', 'minutes', '0..1440 screen', 'sleep target; historical feature', 'sum of estimated asleep minutes; not time in bed'),
    'timeInBed': ('Episode time in bed', 'minutes', '0..1440 screen', 'historical feature', 'includes awake time'),
    'minutesAwake': ('Awake time during sleep episode', 'minutes', '0..1440 screen', 'historical feature', 'not total sleep time'),
    'minutesToFallAsleep': ('Device-reported sleep latency', 'minutes', '0..1440 screen', 'optional historical feature', 'zeros may be device convention'),
    'minutesAfterWakeup': ('Time in bed after waking', 'minutes', '0..1440 screen', 'optional historical feature', 'device estimate'),
    'efficiency': ('Fitbit sleep efficiency; unsupported for staged logs', 'percent', '0..100', 'exclude staged; optional classic only', 'official Fitbit docs say ignore for stages; optional derived asleep/bed fraction must have a new name'),
    'dateOfSleep': ('Device sleep date', 'date', 'calendar date', 'alignment metadata', 'test against start/end; use actual datetimes'),
    'startTime': ('Episode or exercise start datetime', 'datetime', 'valid timestamp', 'target timing / historical feature', 'timezone-naive in this export'),
    'endTime': ('Episode end datetime', 'datetime', 'end >= start', 'alignment metadata', 'sleep start/end midpoint is interval midpoint, not sleep-stage weighted midpoint'),
    'mainSleep': ('Device main sleep flag', 'boolean', 'true/false', 'target selection', 'do not merge naps into main sleep'),
    'duration': ('Elapsed duration; source-specific units', 'milliseconds for Fitbit; minutes for PMSys', 'nonnegative', 'historical feature', 'not sleep TST; inspect source before conversion'),
    'activeDuration': ('Exercise active duration', 'milliseconds', 'nonnegative', 'historical feature', 'exclude future exercise'),
    'overall_score': ('Fitbit sleep score', 'score', '0..100', 'historical feature', 'not a cognition label'),
    'composition_score': ('Proprietary sleep composition score', 'score', 'component range not verified', 'optional historical feature', 'device algorithm'),
    'revitalization_score': ('Proprietary revitalization score', 'score', 'component range not verified', 'optional historical feature', 'device algorithm'),
    'duration_score': ('Proprietary sleep duration score', 'score', 'component range not verified', 'optional historical feature', 'device algorithm'),
    'deep_sleep_in_minutes': ('Estimated deep sleep', 'minutes', 'nonnegative', 'optional historical feature', 'consumer estimate'),
    'resting_heart_rate': ('Sleep-score-associated resting heart rate', 'bpm', '25..220 broad screen', 'optional historical feature', 'different source from daily resting heart rate'),
    'restlessness': ('Device restlessness fraction', 'fraction', '0..1 screen', 'optional historical feature', 'proprietary'),
    'value.bpm': ('Optical wearable heart rate', 'bpm', '25..220 broad screen', 'historical feature', 'not beat-to-beat intervals'),
    'value.confidence': ('Fitbit heart-rate confidence', 'ordinal device code', '0..3 observed convention', 'quality metadata', 'confidence mapping not validated'),
    'rpe': ('Rating of perceived exertion', 'score', '0..10 conventional; verify observed', 'historical feature', 'sRPE load = RPE times minutes'),
    'perceived_exertion': ('Rating of perceived exertion', 'score', '0..10 conventional', 'historical feature', 'sRPE load = RPE times minutes'),
    'duration_min': ('Reported training session duration', 'minutes', 'nonnegative', 'historical feature', 'multiply by perceived_exertion for session load'),
    'end_date_time': ('Reported session end datetime', 'ISO datetime', 'valid timestamp', 'alignment metadata', 'Z UTC; does not establish actual upload time'),
    'weight': ('Reported weight', 'kg', '30..300 broad screen', 'excluded MVP feature', 'self-report and late reporting'),
    'glasses_of_fluid': ('Reported fluid intake', 'glass count', 'nonnegative', 'excluded MVP feature', 'glass size unspecified'),
    'alcohol_consumed': ('Reported alcohol consumption', 'category', 'see observed values', 'excluded MVP feature', 'amount unknown'),
    'date': ('Date the Google report concerns', 'date', 'DD/MM/YYYY', 'alignment metadata', 'not submission time'),
    'timestamp': ('Google submission time or Fitbit sleep score timestamp', 'datetime', 'source-specific format', 'alignment metadata', 'sleep score Z conflicts with naive Fitbit times; join by log ID'),
    'sleep_log_entry_id': ('Sleep log identifier', 'identifier', 'unique per episode expected', 'metadata', 'join to sleep.logId'),
    'logId': ('Device episode identifier', 'identifier', 'unique expected', 'metadata', 'exclude as predictive variable'),
    'soreness_area': ('Body area codes', 'code list', 'not decoded', 'excluded', 'codebook absent'),
}


def variable_info(source, field):
    if field in DEFS:
        return DEFS[field]
    if field == 'value' or field == 'value.value':
        stem = Path(source).stem
        unit = {'steps':'steps/minute', 'distance':'centimeters/minute', 'calories':'kcal/minute', 'resting_heart_rate':'bpm'}.get(stem, 'minutes/day' if stem.endswith('_minutes') else 'source-specific / undocumented')
        return (stem.replace('_', ' '), unit, 'nonnegative; HR 25..220 screen' if 'heart_rate' in stem else 'nonnegative', 'historical feature', 'daily summaries lag one completed day; minute streams aggregate observed intervals')
    if field == 'dateTime':
        return ('Measurement or summary date; midnight is not availability', 'datetime', 'valid timestamp', 'alignment metadata', 'timezone unspecified')
    if field.startswith('levels.summary.') and field.endswith('.minutes'):
        return ('Estimated sleep stage minutes', 'minutes', 'nonnegative', 'optional historical feature', 'consumer sleep staging, not PSG')
    if field.endswith('thirtyDayAvgMinutes'):
        return ('Vendor rolling sleep-stage average', 'minutes', 'nonnegative', 'excluded', 'opaque window/availability; recompute backward-looking baseline')
    if field.endswith('.error'):
        return ('Device error estimate', 'undocumented', 'undocumented', 'quality metadata', 'not clinical uncertainty interval')
    if field in ('Age', 'Height', 'Gender', 'A or B person', 'Max heart rate', 'Stride walk', 'Stride run', 'Participant ID', 'Minutes', 'Seconds', 'Date'):
        return ('Participant metadata: '+field, {'Age':'years','Height':'cm','Max heart rate':'bpm','Stride walk':'cm','Stride run':'cm','Minutes':'minutes','Seconds':'seconds'}.get(field,'category/datetime'), 'see observed values', 'metadata; excluded MVP', 'collection availability not proven; physical tests may occur after cutoff')
    return (field.replace('.', ' ').replace('_', ' '), 'undocumented / source-specific', 'see observed range/categories', 'excluded pending documentation', 'do not infer scientific meaning from name alone')


class Audit:
    def __init__(self, source):
        self.src = source
        self.inv, self.fields, self.errors = [], {}, []
        self.daily = collections.defaultdict(dict)
        self.small = collections.defaultdict(list)
        self.sleeps, self.wellness, self.scores = [], [], []
        self.issues = collections.Counter()
        self.daily_sensor = []
        self.participants = sorted({n.split('/')[0] for n in source.names if n.split('/')[0].startswith('p') and n.split('/')[0][1:].isdigit()})

    def record_fields(self, source, f, n=1):
        for k,v in f.items():
            key = (source,k)
            if key not in self.fields:
                self.fields[key] = {'present':0,'nonmissing':0,'types':collections.Counter(),'min':None,'max':None,'values':set()}
            s = self.fields[key]
            s['present'] += n
            s['types'][type(v).__name__] += n
            if missing(v):
                continue
            s['nonmissing'] += n
            num = numeric(v)
            if math.isfinite(num):
                s['min'] = num if s['min'] is None else min(s['min'],num)
                s['max'] = num if s['max'] is None else max(s['max'],num)
            if len(s['values']) < 30:
                s['values'].add(str(v)[:120])

    def scan(self):
        progress=ROOT/'.audit_cache/progress.pkl'
        fingerprint=(str(self.src.path.resolve()),self.src.path.stat().st_size,self.src.path.stat().st_mtime_ns)
        done=[]
        if progress.exists():
            with progress.open('rb') as f:state=pickle.load(f)
            if state['fingerprint']==fingerprint:
                self.__dict__.update(state['audit']);done=state['done']
                print('Resuming completed participants:',','.join(done),flush=True)
        for pid in self.participants:
            if pid in done:continue
            print('Inspecting',pid,flush=True)
            for n in self.src.names:
                if not n.startswith(pid+'/') or n.endswith('/'):
                    continue
                self.scan_file(n,pid)
            for rel in REQUIRED:
                if pid+'/'+rel not in self.src.names:
                    self.inv.append({'participant_id':pid,'file_path':pid+'/'+rel,'source_file':rel,'status':'missing','file_size':0,'records':0})
            done.append(pid)
            with progress.open('wb') as f:pickle.dump({'fingerprint':fingerprint,'done':done,'audit':{k:v for k,v in self.__dict__.items() if k!='src'}},f)
        for n in self.src.names:
            if '/' not in n and not n.endswith('/'):
                self.scan_file(n,'metadata')

    def scan_file(self,n,pid):
        suffix = Path(n).suffix.lower()
        source = '/'.join(n.split('/')[1:]) if pid != 'metadata' else n
        row = dict(participant_id=pid,file_path=n,source_file=source,data_modality=n.split('/')[1] if '/' in n else 'metadata',file_format=suffix,file_size=self.src.size(n),records=0,status='ok',parsing_error='',duplicate_records=0,duplicate_timestamps=0,conflicting_timestamps=0,invalid_timestamps=0)
        try:
            if Path(n).stem=='heart_rate':
                self.scan_hr(n,pid,source,row)
                self.inv.append(row)
                return
            if suffix in ('.jpg','.jpeg','.png'):
                from PIL import Image
                with self.src.open(n) as f:
                    im = Image.open(f)
                    exif = im.getexif()
                    row.update(records=1,fields=3,columns='width,height,EXIF_datetime',dtypes='integer,integer,optional EXIF',earliest_timestamp=str(exif.get(306,'')),latest_timestamp=str(exif.get(306,'')))
                    im.verify()
                self.inv.append(row)
                return
            if suffix == '.xlsx':
                with self.src.open(n) as f:
                    df = pd.read_excel(io.BytesIO(f.read()),header=1)
                self.metadata = df
                rows = df.where(pd.notna(df),None).to_dict('records')
            elif suffix == '.csv':
                with self.src.open(n) as f:
                    rows = list(csv.DictReader(io.TextIOWrapper(f,encoding='utf-8-sig',newline='')))
            elif suffix == '.json':
                rows = None
            else:
                row['status']='unparsed binary; excluded'
                self.inv.append(row)
                return
            names,types,seen,seen_times = set(),collections.defaultdict(set),set(),{}
            times=[]
            hr = Path(n).stem == 'heart_rate'
            sensor = Path(n).stem in ('heart_rate','steps','calories','distance')
            agg = collections.defaultdict(lambda: dict(records=0,value_sum=0.,value_min=float('inf'),value_max=float('-inf'),zero_records=0,positive_records=0,invalid_values=0,confidence_zero=0,first=None,last=None))
            if rows is None:
                stream = self.src.open(n)
                rows = ijson.items(stream,'item',use_float=True)
            for record in rows:
                row['records'] += 1
                f = flat(record)
                self.record_fields(source,f)
                names.update(f)
                for k,v in f.items():
                    types[k].add(type(v).__name__)
                rawtime = record.get('dateTime',record.get('effective_time_frame',record.get('startTime',record.get('end_date_time',record.get('timestamp')))))
                ts = parse_time(rawtime, 'googledocs' in n)
                if rawtime is not None and ts is None:
                    row['invalid_timestamps']+=1
                if ts:
                    # Preserve original offset in inventory; compare ordering as encoded wall clock only.
                    times.append(ts.isoformat()) if not sensor else None
                    iso=ts.isoformat()
                    if not row.get('earliest_timestamp') or iso<row['earliest_timestamp']:
                        row['earliest_timestamp']=iso
                    if not row.get('latest_timestamp') or iso>row['latest_timestamp']:
                        row['latest_timestamp']=iso
                signature = (record.get('value',{}).get('bpm'),record.get('value',{}).get('confidence')) if hr else hashlib.blake2b(json.dumps(record,sort_keys=True,default=str).encode(),digest_size=16).digest()
                if hr:
                    # Timestamp->small tuple, never materialize the multi-million-row dataframe.
                    if rawtime in seen_times:
                        row['duplicate_timestamps']+=1
                        if signature==seen_times[rawtime]: row['duplicate_records']+=1
                        else: row['conflicting_timestamps']+=1
                    seen_times[rawtime]=signature
                else:
                    if signature in seen: row['duplicate_records']+=1
                    seen.add(signature)
                    if rawtime is not None:
                        if rawtime in seen_times:
                            row['duplicate_timestamps']+=1
                            if seen_times[rawtime]!=signature: row['conflicting_timestamps']+=1
                        seen_times[rawtime]=signature
                if sensor and ts:
                    d=agg[ts.date()]
                    val=numeric(f.get('value.bpm',f.get('value')))
                    d['records']+=1
                    if math.isfinite(val):
                        d['value_sum']+=val;d['value_min']=min(d['value_min'],val);d['value_max']=max(d['value_max'],val)
                        d['zero_records']+=int(val==0);d['positive_records']+=int(val>0)
                        d['invalid_values']+=int((val<25 or val>220) if hr else val<0)
                    else: d['invalid_values']+=1
                    if hr: d['confidence_zero']+=int(f.get('value.confidence')==0)
                    d['first']=ts if d['first'] is None else min(d['first'],ts)
                    d['last']=ts if d['last'] is None else max(d['last'],ts)
                if not sensor:
                    r=dict(record,participant_id=pid,source=source)
                    self.small[Path(n).stem].append(r)
                    if source=='pmsys/wellness.csv': self.wellness.append(r)
                    if source=='fitbit/sleep.json': self.sleeps.append(r)
                    if source=='fitbit/sleep_score.csv': self.scores.append(r)
                if ts and START<=ts.date()<=END:
                    self.daily[(pid,ts.date())][Path(n).stem]=True
            if suffix=='.json':stream.close()
            for date,d in agg.items():
                self.daily_sensor.append(dict(participant_id=pid,date=str(date),source=Path(n).stem,**{k:(v.isoformat() if isinstance(v,dt.datetime) else v) for k,v in d.items()}))
            row.update(fields=len(names),columns=json.dumps(sorted(names)),dtypes=json.dumps({k:sorted(v) for k,v in types.items()},sort_keys=True))
        except Exception as e:
            row.update(status='parse_error',parsing_error=f'{type(e).__name__}: {e}')
            self.errors.append(dict(file=n,error=row['parsing_error']))
        self.inv.append(row)

    def scan_hr(self,n,pid,source,row):
        """Specialized streaming path: bounded to one participant and no dataframe of raw HR."""
        seen={};agg={};fields={};types=collections.defaultdict(set)
        count=0;low=None;high=None;conf_low=None;conf_high=None
        nonmissing_bpm=0;nonmissing_conf=0;nonmissing_time=0;time_min=None;time_max=None
        for record in ijson.items(self.src.open(n),'item',use_float=True):
            count+=1
            stamp=record.get('dateTime');value=record.get('value') or {}
            bpm=value.get('bpm');confidence=value.get('confidence')
            types['dateTime'].add(type(stamp).__name__);types['value.bpm'].add(type(bpm).__name__);types['value.confidence'].add(type(confidence).__name__)
            if set(record)!= {'dateTime','value'} or set(value)!= {'bpm','confidence'}:
                self.issues['hr_schema_deviation']+=1
                self.record_fields(source,flat(record))
            signature=(bpm,confidence)
            if stamp in seen:
                row['duplicate_timestamps']+=1
                if signature==seen[stamp]:row['duplicate_records']+=1
                else:row['conflicting_timestamps']+=1
            seen[stamp]=signature
            timestamp=parse_time(stamp)
            if timestamp is None:row['invalid_timestamps']+=1;continue
            nonmissing_time+=1
            time_min=stamp if time_min is None or stamp<time_min else time_min
            time_max=stamp if time_max is None or stamp>time_max else time_max
            date=timestamp.date()
            if date not in agg:agg[date]=dict(records=0,value_sum=0.,value_min=float('inf'),value_max=float('-inf'),zero_records=0,positive_records=0,invalid_values=0,confidence_zero=0,first=stamp,last=stamp)
            d=agg[date];d['records']+=1;d['last']=max(d['last'],stamp);d['first']=min(d['first'],stamp)
            if isinstance(bpm,(int,float)):
                nonmissing_bpm+=1;low=bpm if low is None else min(low,bpm);high=bpm if high is None else max(high,bpm)
                d['value_sum']+=bpm;d['value_min']=min(d['value_min'],bpm);d['value_max']=max(d['value_max'],bpm)
                d['zero_records']+=int(bpm==0);d['positive_records']+=int(bpm>0);d['invalid_values']+=int(bpm<25 or bpm>220)
            else:d['invalid_values']+=1
            if isinstance(confidence,(int,float)):
                nonmissing_conf+=1;conf_low=confidence if conf_low is None else min(conf_low,confidence);conf_high=confidence if conf_high is None else max(conf_high,confidence)
            d['confidence_zero']+=int(confidence==0)
        for field,nonmissing_count,lo,hi in [('dateTime',nonmissing_time,None,None),('value.bpm',nonmissing_bpm,low,high),('value.confidence',nonmissing_conf,conf_low,conf_high)]:
            self.fields[(source,field)]={'present':count,'nonmissing':nonmissing_count,'types':collections.Counter({t:1 for t in types[field]}),'min':lo,'max':hi,'values':set()}
        for date,d in agg.items():
            self.daily_sensor.append(dict(participant_id=pid,date=str(date),source='heart_rate',**d))
            if START<=date<=END:self.daily[(pid,date)]['heart_rate']=True
        row.update(records=count,earliest_timestamp=time_min,latest_timestamp=time_max,fields=len(types),columns=json.dumps(sorted(types)),dtypes=json.dumps({k:sorted(v) for k,v in types.items()}))

    def dictionary(self):
        totals=collections.Counter()
        for r in self.inv:
            if r['status']=='ok':totals[r['source_file']]+=r['records']
        result=[]
        for (source,field),s in sorted(self.fields.items()):
            description,unit,valid,role,interpretation=variable_info(source,field)
            count=totals[source]
            reference='https://home.simula.no/~paalh/publications/files/cbmi2019-PMSYS.pdf (Table I); '+DOC if field in ['fatigue','stress','soreness','mood','sleep_quality'] else FITBIT if 'sleep.json' in source and field in DEFS else DOC if field in DEFS or field in ('value','value.value','dateTime') else 'raw schema; meaning not independently verified'
            result.append(dict(original_variable_name=field,source_file=source,description=description,data_type=';'.join(s['types']),unit=unit,valid_range_or_categories=valid,interpretation=interpretation,temporal_granularity='per episode' if 'sleep.json' in source or 'exercise' in source else 'participant static' if '.xlsx' in source else 'per report' if '.csv' in source else 'daily summary' if '_minutes' in source or 'resting_heart_rate' in source or 'zones' in source else 'irregular seconds' if 'heart_rate.json' in source else 'minute',missing_value_percentage=100*(count-s['nonmissing'])/count if count else np.nan,record_denominator=count,field_present=s['present'],nonmissing=s['nonmissing'],measurement_type='self-reported' if 'pmsys' in source or 'googledocs' in source else 'metadata' if '.xlsx' in source else 'device-derived estimate',potential_role=role,leakage_risk='all t+1 values excluded from inputs; require source availability <= cutoff; vendor aggregates and metadata need review',scientific_relevance=description,documentation_source=reference,observed_min=s['min'],observed_max=s['max'],observed_examples=json.dumps(sorted(s['values']))))
        return pd.DataFrame(result)


def build_analysis(a, offsets):
    out=ROOT/'reports';out.mkdir(exist_ok=True)
    well=pd.DataFrame(a.wellness)
    for c in ['fatigue','readiness','stress','mood','soreness','sleep_quality','sleep_duration_h']:
        well[c]=pd.to_numeric(well[c],errors='coerce')
    well['utc']=pd.to_datetime(well.effective_time_frame,utc=True,errors='coerce')
    sleep=pd.DataFrame([{k:v for k,v in r.items() if k!='levels'} for r in a.sleeps])
    sleep['start']=pd.to_datetime(sleep.startTime,format='mixed',errors='coerce')
    sleep['end']=pd.to_datetime(sleep.endTime,format='mixed',errors='coerce')
    for c in ['minutesAsleep','timeInBed','duration','efficiency','minutesAwake']:
        sleep[c]=pd.to_numeric(sleep[c],errors='coerce')
    sleep['elapsed_minutes']=(sleep.end-sleep.start).dt.total_seconds()/60
    sleep['valid_tst']=sleep.minutesAsleep.between(1,1440)&sleep.end.gt(sleep.start)&sleep.minutesAsleep.le(sleep.elapsed_minutes+1)
    sleep['main_flag']=sleep.get('mainSleep',pd.Series(False,index=sleep.index)).eq(True)
    sleep['onset_hour']=sleep.start.dt.hour+sleep.start.dt.minute/60+sleep.start.dt.second/3600
    sleep['wake_hour']=sleep.end.dt.hour+sleep.end.dt.minute/60+sleep.end.dt.second/3600
    sleep['midpoint']=sleep.start+(sleep.end-sleep.start)/2
    sleep['midpoint_hour']=sleep.midpoint.dt.hour+sleep.midpoint.dt.minute/60
    sleep['date_end_match']=sleep.dateOfSleep.eq(sleep.end.dt.strftime('%Y-%m-%d'))
    sleep['date_start_match']=sleep.dateOfSleep.eq(sleep.start.dt.strftime('%Y-%m-%d'))
    sleep.to_csv(out/'sleep_episode_audit.csv',index=False)
    # Unique log IDs; conflicting duplicates are excluded instead of arbitrarily choosing a value.
    conflict_ids=sleep.groupby(['participant_id','logId']).filter(lambda x:len(x[['startTime','endTime','minutesAsleep']].drop_duplicates())>1)
    conflict_set=set(zip(conflict_ids.participant_id,conflict_ids.logId))
    sleep['conflicting_id']=[(p,l) in conflict_set for p,l in zip(sleep.participant_id,sleep.logId)]
    eligible=sleep[sleep.main_flag & sleep.valid_tst & ~sleep.conflicting_id].drop_duplicates(['participant_id','logId']).copy()
    # A main episode starting 20:00..next 12:00 belongs to cutoff day t.
    # Daytime-only candidates and starts before cutoff are explicitly not silently substituted.
    eligible['cutoff_day']=[(s-dt.timedelta(days=1)).date() if s.hour<12 else s.date() if s.hour>=20 else None for s in eligible.start]
    eligible=eligible[eligible.cutoff_day.notna()]
    eligible=eligible[[s>dt.datetime.combine(d,dt.time(20)) for s,d in zip(eligible.start,eligible.cutoff_day)]]
    ambiguity=eligible.groupby(['participant_id','cutoff_day']).size()
    ambiguous_keys=set(ambiguity[ambiguity>1].index)
    eligible=eligible[[ (p,d) not in ambiguous_keys for p,d in zip(eligible.participant_id,eligible.cutoff_day)]]
    eligible=eligible[eligible.cutoff_day.isin(DAYS)]
    sleepmap={(r.participant_id,r.cutoff_day):r for r in eligible.itertuples()}
    sen=pd.DataFrame(a.daily_sensor)
    sen.to_csv(out/'daily_sensor_audit.csv',index=False)
    # Daily quality gates count positive samples, not simply existence of zero-filled export rows.
    sensor_map={(r.participant_id,dt.date.fromisoformat(r.date),r.source):r for r in sen.itertuples()}
    rhr={}
    for r in a.small['resting_heart_rate']:
        timestamp=parse_time(r.get('dateTime'))
        val=numeric(r.get('value',{}).get('value'))
        if timestamp and 25<=val<=220:rhr[(r['participant_id'],timestamp.date())]=val
    coverage=[];samples=[];sensitivities=[];well_daily=[];transitions=[];repeat=[]
    for off in offsets:
        w=well.copy()
        # Sensitivity only: constant UTC offset, NOT a claim about participant timezone.
        w['local_assumed']=w.utc+pd.Timedelta(hours=off)
        w['day']=w.local_assumed.dt.date
        w=w.dropna(subset=['day']).sort_values('utc')
        wm={}
        for (pid,day),g in w.groupby(['participant_id','day']):
            valid=g[g.fatigue.between(1,5)]
            if len(g)>1:
                repeat.append(dict(offset_hours=off,participant_id=pid,date=str(day),reports=len(g),distinct_fatigue=valid.fatigue.nunique(),conflict=valid.fatigue.nunique()>1))
            if not valid.empty:
                # Earliest observed next-day label; never use target-day values as predictors.
                wm[(pid,day)]=valid.iloc[0]
        for pid in a.participants:
            wp=w[w.participant_id.eq(pid)]
            wd={d:g for d,g in wp.groupby('day')}
            for day in DAYS:
                prev=day-dt.timedelta(days=1);nxt=day+dt.timedelta(days=1)
                history=sleep[(sleep.participant_id==pid)&sleep.valid_tst&sleep.main_flag&~sleep.conflicting_id&sleep.end.dt.date.eq(prev)]
                # Conservative lag: previous completed day only, even if same-day data exists.
                hs=not history.empty
                hw=prev in wd
                hr=(pid,prev) in rhr
                sensor=sensor_map.get((pid,prev,'steps'));heart=sensor_map.get((pid,prev,'heart_rate'))
                ha=sensor is not None and (sensor.positive_records>0 or (heart is not None and heart.positive_records>0 and sensor.records>=1200))
                label=wm.get((pid,nxt));sl=sleepmap.get((pid,day))
                fatigue=float(label.fatigue) if label is not None else np.nan
                samples.append(dict(offset_hours=off,participant_id=pid,cutoff_date=str(day),sleep_history=hs,wellness_history=hw,rhr_history=hr,activity_history=ha,fatigue_label=fatigue,elevated_fatigue=int(fatigue<=2) if math.isfinite(fatigue) else np.nan,sleep_target_valid=sl is not None,sleep_target_minutes=float(sl.minutesAsleep) if sl is not None else np.nan,onset_hour=float(sl.onset_hour) if sl is not None else np.nan,midpoint_hour=float(sl.midpoint_hour) if sl is not None else np.nan,target_sleep_log_id=str(sl.logId) if sl is not None else '',sleep_history_count=len(history),has_same_day_fatigue=(pid,day) in wm))
            if off==0:
                for day,g in wd.items():
                    row=g.iloc[0]
                    well_daily.append(dict(participant_id=pid,date=str(day),**{c:row[c] for c in ['fatigue','readiness','stress','mood','soreness','sleep_quality','sleep_duration_h']}))
                for day in DAYS[:-1]:
                    x,y=wm.get((pid,day)),wm.get((pid,day+dt.timedelta(days=1)))
                    if x is not None and y is not None:
                        transitions.append(dict(participant_id=pid,date=str(day),from_score=int(x.fatigue),to_score=int(y.fatigue)))
                sleepdays=set(sleep.loc[(sleep.participant_id==pid)&sleep.valid_tst&sleep.main_flag,'end'].dt.date)&set(DAYS)
                phys={d for p,d in rhr if p==pid}&set(DAYS)
                activity={d for (p,d,src),r in sensor_map.items() if p==pid and src=='steps' and (r.positive_records>0 or (r.records>=1200 and sensor_map.get((p,d,'heart_rate')) is not None and sensor_map[(p,d,'heart_rate')].positive_records>0))}&set(DAYS)
                union={d for p,d in a.daily if p==pid}&set(DAYS)
                coverage.append(dict(participant_id=pid,total_observation_days=len(union),study_window_days=len(DAYS),wellness_days=len(set(wd)&set(DAYS)),sleep_days=len(sleepdays),physiological_data_days=len(phys),heart_rate_days=sum(1 for p,d,s in sensor_map if p==pid and s=='heart_rate' and d in DAYS),activity_data_days=len(activity),overlapping_observation_days=len(set(wd)&sleepdays&phys&activity),missing_all_modality_days=len(DAYS)-len(union),missing_wellness_days=len(DAYS)-len(set(wd)&set(DAYS)),missing_sleep_days=len(DAYS)-len(sleepdays)))
    samples=pd.DataFrame(samples)
    base=samples[samples.offset_hours.eq(0)].copy()
    coverage=pd.DataFrame(coverage)
    for idx,r in coverage.iterrows():
        p=base[base.participant_id.eq(r.participant_id)]
        cf=p[p.sleep_history&p.fatigue_label.notna()]
        coverage.loc[idx,'valid_next_day_fatigue_prediction_samples']=len(cf)
        coverage.loc[idx,'valid_next_night_sleep_prediction_samples']=int((p.sleep_history&p.sleep_target_valid).sum())
        coverage.loc[idx,'positive_fatigue_labels']=int(cf.elevated_fatigue.eq(1).sum())
        coverage.loc[idx,'negative_fatigue_labels']=int(cf.elevated_fatigue.eq(0).sum())
        coverage.loc[idx,'all_modal_fatigue_samples']=int((p.sleep_history&p.wellness_history&p.rhr_history&p.activity_history&p.fatigue_label.notna()).sum())
        coverage.loc[idx,'all_modal_sleep_samples']=int((p.sleep_history&p.wellness_history&p.rhr_history&p.activity_history&p.sleep_target_valid).sum())
    coverage.to_csv(out/'participant_coverage.csv',index=False)
    samples.to_csv(out/'prediction_sample_eligibility.csv',index=False)
    wd=pd.DataFrame(well_daily);wd.to_csv(out/'wellness_daily_audit.csv',index=False)
    write_csv(repeat,out/'repeated_wellness_reports.csv');write_csv(transitions,out/'fatigue_transitions.csv')
    target_counts=[]
    for pid,g in well.groupby('participant_id'):
        for score in range(1,6):
            target_counts.append(dict(participant_id=pid,fatigue_score=score,raw_reports=int(g.fatigue.eq(score).sum())))
    write_csv(target_counts,out/'fatigue_score_counts.csv')
    masks={'sleep_history_only':lambda g:g.sleep_history,'sleep_and_wellness':lambda g:g.sleep_history&g.wellness_history,'sleep_and_rhr':lambda g:g.sleep_history&g.rhr_history,'sleep_and_activity':lambda g:g.sleep_history&g.activity_history,'all_four':lambda g:g.sleep_history&g.wellness_history&g.rhr_history&g.activity_history}
    eff=[]
    for off,g in samples.groupby('offset_hours'):
        for name,fn in masks.items():
            mask=fn(g)
            c=g[mask&g.fatigue_label.notna()];s=g[mask&g.sleep_target_valid]
            eff.append(dict(offset_hours=off,feature_requirement=name,cognitive_samples=len(c),positive_labels=int(c.elevated_fatigue.eq(1).sum()),negative_labels=int(c.elevated_fatigue.eq(0).sum()),cognitive_participants=c.participant_id.nunique(),sleep_samples=len(s),sleep_participants=s.participant_id.nunique()))
    eff=pd.DataFrame(eff);eff.to_csv(out/'effective_sample_sizes.csv',index=False)
    # Backward-only personalization eligibility; definition is exploratory, not clinical.
    personalized=[]
    for pid,g in base.groupby('participant_id'):
        for r in g[g.fatigue_label.notna()].itertuples():
            cutoff=dt.date.fromisoformat(r.cutoff_date)
            hist=wd[(wd.participant_id==pid)&(pd.to_datetime(wd.date).dt.date<=cutoff-dt.timedelta(days=1))].dropna(subset=['fatigue']).tail(28)
            if len(hist)>=14:
                med=float(hist.fatigue.median())
                personalized.append(dict(participant_id=pid,cutoff_date=r.cutoff_date,history_reports=len(hist),past_median=med,target_fatigue=r.fatigue_label,deterioration=int(r.fatigue_label<=med-1),sleep_history=r.sleep_history))
    personalized=pd.DataFrame(personalized);personalized.to_csv(out/'personalized_target_audit.csv',index=False)
    splits=[]
    # Fixed global calendar boundaries avoid participant-specific future windows.
    for task,target in [('fatigue','fatigue_label'),('sleep','sleep_target_minutes')]:
        g=base[base.sleep_history&base[target].notna()].copy()
        g['split']=np.where(g.cutoff_date<'2020-02-01','train',np.where(g.cutoff_date<'2020-03-01','validation','test'))
        # Purge next-day outcomes crossing train/validation/test boundaries.
        g=g[~g.cutoff_date.isin(['2020-01-31','2020-02-29'])]
        for (pid,split),h in g.groupby(['participant_id','split']):
            splits.append(dict(task=task,participant_id=pid,split=split,n=len(h),positive=int(h.elevated_fatigue.eq(1).sum()) if task=='fatigue' else np.nan,negative=int(h.elevated_fatigue.eq(0).sum()) if task=='fatigue' else np.nan,distinct_target_values=h[target].nunique()))
    splits=pd.DataFrame(splits);splits.to_csv(out/'validation_split_audit.csv',index=False)
    group=[]
    for i,pid in enumerate(a.participants):
        h=base[base.participant_id.eq(pid)&base.sleep_history]
        group.append(dict(participant_id=pid,deterministic_group_fold=i%4,fatigue_n=h.fatigue_label.notna().sum(),positive=h.elevated_fatigue.eq(1).sum(),negative=h.elevated_fatigue.eq(0).sum(),sleep_n=h.sleep_target_valid.sum(),fatigue_categories=h.fatigue_label.nunique()))
    group=pd.DataFrame(group);group.to_csv(out/'subject_holdout_audit.csv',index=False)
    align=[]
    unique_history=sleep[sleep.main_flag&sleep.valid_tst&~sleep.conflicting_id].drop_duplicates(['participant_id','logId']).copy()
    unique_history['end_day']=unique_history.end.dt.date
    for r in eligible.itertuples():
        last=r.cutoff_day-dt.timedelta(days=1);first=last-dt.timedelta(days=27)
        history=unique_history[(unique_history.participant_id==r.participant_id)&(unique_history.end_day>=first)&(unique_history.end_day<=last)].sort_values('minutesAsleep',ascending=False).drop_duplicates('end_day')
        if len(history)<14:continue
        angles=2*np.pi*history.midpoint_hour/24
        vector=np.mean(np.exp(1j*angles));concentration=abs(vector)
        if concentration<0.5:continue
        reference=(np.angle(vector)%(2*np.pi))*24/(2*np.pi)
        align.append(dict(participant_id=r.participant_id,cutoff_date=str(r.cutoff_day),history_days=len(history),reference_midpoint_hour=reference,resultant_length=concentration,target_midpoint_hour=r.midpoint_hour,signed_deviation_minutes=((r.midpoint_hour-reference+12)%24-12)*60))
    write_csv(align,out/'schedule_alignment_audit.csv')
    make_figures(a,well,wd,sleep,eligible,sen,coverage,transitions)
    generate_reports(a,well,wd,sleep,eligible,base,coverage,eff,personalized,splits,group,len(ambiguous_keys))
    return {'wellness_reports':len(well),'sleep_episodes':len(sleep),'eligible_sleep_targets':len(eligible),'participants':len(a.participants),'effective_sample_sizes':eff.to_dict('records')}


def make_figures(a,well,wd,sleep,eligible,sen,coverage,transitions):
    folder=ROOT/'reports/figures';folder.mkdir(exist_ok=True)
    sns.set_theme(style='whitegrid',font_scale=.9)
    def save(name):
        plt.tight_layout();plt.savefig(folder/name,dpi=150,bbox_inches='tight');plt.close()
    cols=['wellness_days','sleep_days','physiological_data_days','activity_data_days','overlapping_observation_days']
    plt.figure(figsize=(10,7));sns.heatmap(coverage.set_index('participant_id')[cols],annot=True,fmt='.0f',vmin=0,vmax=len(DAYS),cmap='YlGnBu');plt.title('Observed days by modality (152-day study window)');save('participant_coverage.png')
    fig,axes=plt.subplots(2,3,figsize=(13,7))
    for ax,c in zip(axes.flat,['fatigue','readiness','stress','mood','sleep_quality','sleep_duration_h']):
        sns.histplot(well[c].dropna(),discrete=True,ax=ax);ax.set_title(c)
    fig.suptitle('Raw self-reports: count includes repeated reports');save('wellness_distributions.png')
    p=well.groupby(['participant_id','fatigue']).size().unstack(fill_value=0).reindex(columns=range(1,6),fill_value=0)
    p.div(p.sum(axis=1),axis=0).plot.bar(stacked=True,figsize=(12,5),colormap='viridis');plt.ylabel('Fraction of raw reports');plt.title('Fatigue by participant: 1-2 elevated, 3-5 non-elevated');save('fatigue_by_participant.png')
    fig,axes=plt.subplots(2,2,figsize=(12,8))
    for ax,col,label in zip(axes.flat,['minutesAsleep','onset_hour','wake_hour','midpoint_hour'],['TST (minutes)','Episode onset (wall-clock hour)','Wake (wall-clock hour)','Interval midpoint (wall-clock hour)']):
        sns.histplot(sleep.loc[sleep.main_flag,col].dropna(),ax=ax,bins=35);ax.set_xlabel(label)
    save('sleep_distributions.png')
    plt.figure(figsize=(12,6));sns.boxplot(data=sleep[sleep.main_flag],x='participant_id',y='minutesAsleep');plt.ylabel('Estimated TST (minutes)');plt.title('Main-sleep duration by participant; outliers retained');save('sleep_by_participant.png')
    if transitions:
        tr=pd.DataFrame(transitions);matrix=pd.crosstab(tr.from_score,tr.to_score).reindex(index=range(1,6),columns=range(1,6),fill_value=0).fillna(0)
        plt.figure(figsize=(6,5));sns.heatmap(matrix,annot=True,fmt='.0f',cmap='Blues');plt.title('Fatigue transitions on consecutive calendar dates (UTC sensitivity)');save('fatigue_transitions.png')
    rows=[]
    for pid in a.participants:
        for day in DAYS:
            vals=a.daily.get((pid,day),{})
            rows.append(dict(participant_id=pid,date=str(day),modalities=sum(bool(vals.get(x)) for x in ['wellness','sleep','resting_heart_rate','steps'])))
    piv=pd.DataFrame(rows).pivot(index='participant_id',columns='date',values='modalities')
    plt.figure(figsize=(15,6));sns.heatmap(piv,cmap='viridis',vmin=0,vmax=4,xticklabels=15);plt.title('Temporal coverage: files with records across four modalities (presence, not wear proof)');save('temporal_coverage.png')
    activity=sen[sen.source.eq('steps')].copy();activity['daily_steps']=activity.value_sum
    plt.figure(figsize=(12,5));sns.boxplot(data=activity,x='participant_id',y='daily_steps');plt.title('Steps per recorded day: zero-filled exports may represent non-wear');save('activity_by_participant.png')
    rhr=[]
    for r in a.small['resting_heart_rate']:
        rhr.append({'participant_id':r['participant_id'],'bpm':numeric(r.get('value',{}).get('value'))})
    plt.figure(figsize=(12,5));sns.boxplot(data=pd.DataFrame(rhr),x='participant_id',y='bpm');plt.title('Daily resting heart rate');save('resting_hr_by_participant.png')
    ex=pd.DataFrame(a.small['srpe'])
    if not ex.empty:
        rpecol=next((c for c in ['rpe','perceived_exertion','RPE'] if c in ex),None)
        if rpecol and 'duration_min' in ex:
            ex['load']=pd.to_numeric(ex[rpecol],errors='coerce')*pd.to_numeric(ex.duration_min,errors='coerce')
            plt.figure(figsize=(12,5));sns.boxplot(data=ex,x='participant_id',y='load');plt.title('Session load = perceived exertion x reported minutes');save('exercise_load.png')
    miss=a.dictionary()
    miss=miss[miss.source_file.isin(['pmsys/wellness.csv','fitbit/sleep.json','fitbit/sleep_score.csv'])].sort_values('missing_value_percentage',ascending=False).head(25)
    plt.figure(figsize=(11,8));sns.barplot(data=miss,x='missing_value_percentage',y=miss.source_file+': '+miss.original_variable_name);plt.xlabel('Missing field values (% of source records, not missing days)');save('field_missingness.png')


def generate_reports(a,well,wd,sleep,eligible,base,cov,eff,personal,splits,group,ambiguous):
    out=ROOT/'reports';research=ROOT/'research'
    inv=pd.DataFrame(a.inv);main=sleep[sleep.main_flag];target=base[base.sleep_history&base.fatigue_label.notna()]
    starget=base[base.sleep_history&base.sleep_target_valid]
    counts=well.fatigue.value_counts().reindex(range(1,6),fill_value=0)
    repeated=well.assign(day=well.utc.dt.date).groupby(['participant_id','day']).size()
    conflict=well.assign(day=well.utc.dt.date).groupby(['participant_id','day']).fatigue.nunique().gt(1).sum()
    problems=[]
    for col,lo,hi in [('fatigue',1,5),('mood',1,5),('stress',1,5),('soreness',1,5),('sleep_quality',1,5),('readiness',0,10),('sleep_duration_h',0,24)]:
        problems.append(dict(variable=col,missing=int(well[col].isna().sum()),outside_screen=int((well[col].notna()&~well[col].between(lo,hi)).sum()),minimum=well[col].min(),maximum=well[col].max()))
    write_csv(problems,out/'wellness_quality_checks.csv')
    stats=[]
    for pid,g in well.groupby('participant_id'):
        for c in ['fatigue','readiness','stress','mood','sleep_quality','sleep_duration_h']:
            q=g[c].describe().to_dict();stats.append(dict(participant_id=pid,variable=c,**q))
    for pid,g in sleep.groupby('participant_id'):
        for c in ['minutesAsleep','efficiency','onset_hour','wake_hour','midpoint_hour']:
            stats.append(dict(participant_id=pid,variable=c,**g[c].describe().to_dict()))
    write_csv(stats,out/'participant_descriptive_statistics.csv')
    observed=inv[inv.status.eq('ok')]
    structured=observed.copy()
    structured['source_file']=structured.source_file.map(lambda s:'food-images/* (images)' if str(s).startswith('food-images/') else s)
    rawtotals=structured.groupby('source_file').records.sum().reset_index()
    rawtotals.to_csv(out/'record_counts_by_source.csv',index=False)
    baseeff=eff[eff.offset_hours.eq(0)]
    sleepstats=pd.DataFrame({c:main[c].describe() for c in ['minutesAsleep','timeInBed','elapsed_minutes','efficiency','onset_hour','midpoint_hour','wake_hour']}).round(3)
    timing=[]
    for col in ['minutesAsleep','onset_hour','midpoint_hour']:
        v=eligible[col].dropna();angle=2*np.pi*v/24
        timing.append(dict(candidate=col,valid_unique_targets=len(v),participants=eligible.participant_id.nunique(),minimum=v.min(),median=v.median(),maximum=v.max(),circular_mean_hour=float(np.angle(np.exp(1j*angle).mean())%(2*np.pi)*24/(2*np.pi)) if col!='minutesAsleep' else np.nan))
    alignment=pd.read_csv(out/'schedule_alignment_audit.csv')
    timing.append(dict(candidate='schedule_alignment_signed_minutes',valid_unique_targets=len(alignment),participants=alignment.participant_id.nunique(),minimum=alignment.signed_deviation_minutes.min(),median=alignment.signed_deviation_minutes.median(),maximum=alignment.signed_deviation_minutes.max()))
    write_csv(timing,out/'sleep_candidate_summary.csv')
    targettext=f'''# Target audit

Generated from the actual archive by `scripts/audit_pmdata.py`. No models trained. Counts are retrospective eligibility counts, not independent statistical sample sizes or confirmed online availability. Offset 0 uses UTC wellness dates against unzoned Fitbit wall-clock dates as an explicitly provisional sensitivity scenario. See offset +1/+2 in effective_sample_sizes.csv.

## Cognitive proxy: CONDITIONAL GO

Use **next-calendar-day elevated self-reported fatigue**, scores 1-2 versus 3-5, as a wellness proxy. Never call this measured cognitive impairment. The PMSys questionnaire anchors and PMData description support lower-is-worse coding; readiness describes ability to exercise, not objective cognition.

Raw wellness reports: {len(well)}. Missing fatigue values: {well.fatigue.isna().sum()}. Scores:

{table(counts.rename_axis('fatigue_score').reset_index(name='raw_reports'))}

Repeated participant-days (UTC date): {int(repeated.gt(1).sum())}; conflicting fatigue days: {conflict}. Select the earliest valid report on t+1 for the target. Do not average ordinal labels, impute labels, or replace a missing t+1 by a later date. Score counts above include repeated reports. Target pair counts use deduplicated participant-dates.

With previous-completed-day main-sleep history, {len(target)} candidate pairs: {int(target.elevated_fatigue.eq(1).sum())} elevated and {int(target.elevated_fatigue.eq(0).sum())} non-elevated ({target.elevated_fatigue.mean():.1%} elevated), across {target.participant_id.nunique()} participants. Consecutive t/t+1 fatigue transitions are separately counted in fatigue_transitions.csv; pairs do not require a fatigue report on t when sleep history is the input.

### Candidate target comparison

| Formulation | Assessment |
|---|---|
| Binary scores 1-2 | Recommended MVP; interpretable lower-than-normal fatigue condition; threshold is operational, not clinical |
| Ordered categories 1..5 | Scientifically faithful secondary analysis; extreme classes sparse; report macro metrics and support |
| Numeric regression | Exploratory only; equal spacing between subjective categories is an assumption; MAE is descriptive |
| Personalized deterioration | At least 14 prior reports, median of last 28 reports ending no later than t-1, deterioration >=1 score below historical median; {len(personal)} label-eligible rows, {int(personal.deterioration.sum()) if not personal.empty else 0} deteriorations, {int(personal.sleep_history.sum()) if not personal.empty else 0} with conservative sleep history. Sparse labels and baseline drift make this secondary |

Per-person class balance and raw score support: participant_coverage.csv and fatigue_score_counts.csv. Do not drop single-class participants automatically; exclude undefined AUC folds from AUC aggregation and show their sample support and other metrics.

## Sleep target: CONDITIONAL GO

Primary: **next main-episode Fitbit-estimated TST in minutes (`minutesAsleep`)**. It differs from `duration` (milliseconds), elapsed end-start, and `timeInBed`. It is a wearable estimate, not polysomnography. Optional secondary: **interval midpoint wall-clock timing**, represented on a circle; onset uses episode `startTime`, which need not be physiological sleep onset. Do not add device latency to manufacture precise onset.

Raw episodes {len(sleep)}; mainSleep=true {len(main)}; invalid TST consistency screens {int((~sleep.valid_tst).sum())}; missing TST {int(sleep.minutesAsleep.isna().sum())}; missing/unparseable start {int(sleep.start.isna().sum())}; missing/unparseable end {int(sleep.end.isna().sum())}. Main episodes span {main.participant_id.nunique()} participants. Raw non-main episodes {int((~sleep.main_flag).sum())}, treated as naps/secondary episodes rather than added to the nightly label.

Target association rule: main episode starts in (20:00 on t, 12:00 on t+1), with finite 1..1440 TST, end>start, TST<=elapsed+1 minute; no conflicting log ID. Multiple main candidates for a cutoff are excluded ({ambiguous} ambiguous cutoff-days). Do not skip to another night across a gap. Exact 20:00 starts are excluded because the target must start after cutoff. This provisional overnight window needs schedule review for shift workers.

Eligible episode targets within the study cutoff grid: {len(eligible)} across {eligible.participant_id.nunique()} participants. With previous-completed-day main-sleep history: **{len(starget)} supervised rows** across {starget.participant_id.nunique()} participants. Onset and midpoint use this same valid set; missed calendar opportunities = {len(a.participants)*len(DAYS)-len(eligible)} of {len(a.participants)*len(DAYS)}, which includes study boundaries and absence of an eligible episode rather than field-level nulls.

{table(pd.DataFrame(timing))}

Schedule-alignment audit uses at least 14 historical days from [t-28,t-1], the longest valid main episode when a historical day has multiple episodes, circular midpoint reference, and resultant length >=0.5 as a provisional concentration screen. It yields {len(alignment)} candidate deviations. This reference is a descriptive personal schedule, not an external mission schedule or biological phase. The screen and reference window need domain approval before use as a target.

Main-episode distributions below retain outliers. Clock-hour arithmetic summaries are descriptive only; circular references and errors are required for modeling.

{table(sleepstats.reset_index(names='statistic'))}

Schedule alignment is signed circular distance to a past-only personal reference: wrap(hour-reference+12,24)-12. Compute circular mean from sine/cosine over prior 28 days with >=14 observed days; report resultant length and abstain when concentration is low. This audit evaluates the construction; it does not validate a biological reference. Circadian phase prediction: **NO-GO** without biological phase labels. Objective cognitive-performance prediction: **NO-GO** without performance labels. FD-CSR is outside this implementation.

## Cross-modality sample requirements

All input modalities are from t-1, the last completed day; sleep history here means a valid main episode ending on t-1, not the latest record regardless of gaps. This deliberately loses rows to avoid unverified same-day availability. No actual online ingestion timestamps exist.

{table(baseeff.drop(columns='offset_hours'))}

Do not require all modalities by default. Use missingness masks and evaluate incremental modality value with the above denominators. Eligibility does not guarantee sufficient minutes of wear or causal feature availability. Offset sensitivities are in effective_sample_sizes.csv.

## Evaluation feasibility

Personalized chronological split: train November-January, validate February, test March; remove January 31 and February 29 cutoff rows so next-day labels cannot cross split boundaries. Freeze preprocessing on training data. Historical feature state may advance through observed past validation/test inputs; report this online adaptation policy explicitly. Split details and per-person target diversity are in validation_split_audit.csv.

{table(splits.groupby(['task','split'])[['n','positive','negative']].sum().reset_index())}

LOSO estimates generalization to an unseen person (16 possible held-out people); subject_holdout_audit.csv lists support and classes for every held-out participant. Four deterministic subject folds (participant index modulo 4) are tabulated there; a proper GroupKFold split should be instantiated only during pipeline development, with train-only transformations and inner time-aware tuning. Group folds alone do not test future deployment under calendar drift. No identity-based historical baseline is available for a truly new subject without an explicit calibration period.

{table(group)}

Baseline proposals only: training prevalence/majority; fatigue persistence with a declared stale-label policy; participant past median; sleep last valid completed episode and past-only 7-day median; circular historical timing. Fatigue metrics: balanced accuracy, macro F1, sensitivity/specificity, PR-AUC, ROC-AUC only where both classes exist, Brier/calibration; report participant-macro and pooled results. Ordinal: MAE and quadratic weighted kappa with category support. TST: MAE minutes, RMSE, per-person error and persistence improvement. Timing: circular MAE minutes and angular error; sine/cosine outputs projected with atan2. Confidence intervals should resample participants, not individual rows. Random row splitting is unsuitable.
'''
    (out/'target_audit.md').write_text(targettext,encoding='utf-8')
    # Activity zero/non-wear and daily device quality.
    sen=pd.DataFrame(a.daily_sensor);hr=sen[sen.source.eq('heart_rate')];steps=sen[sen.source.eq('steps')]
    zero=steps[steps.value_sum.eq(0)]
    sparse=hr[hr.records.lt(3600)]
    quality=[
        ('sleep_nonpositive_elapsed',int(sleep.elapsed_minutes.le(0).sum())),
        ('sleep_tst_exceeds_elapsed',int(sleep.minutesAsleep.gt(sleep.elapsed_minutes+1).sum())),
        ('sleep_duration_ms_mismatch_gt_1_min',int((sleep.duration/60000-sleep.elapsed_minutes).abs().gt(1).sum())),
        ('sleep_tib_mismatch_gt_1_min',int((sleep.timeInBed-sleep.elapsed_minutes).abs().gt(1).sum())),
        ('sleep_efficiency_outside_0_100',int((sleep.efficiency.notna()&~sleep.efficiency.between(0,100)).sum())),
        ('sleep_efficiency_diff_from_tst_over_tib_gt_5_points',int((sleep.efficiency-100*sleep.minutesAsleep/sleep.timeInBed).abs().gt(5).sum())),
        ('sleep_tst_below_180_or_above_720',int((main.minutesAsleep.lt(180)|main.minutesAsleep.gt(720)).sum())),
        ('hr_outside_25_220_bpm',int(hr.invalid_values.sum())),
        ('hr_confidence_zero',int(hr.confidence_zero.sum())),
        ('zero_step_days',len(zero)),('hr_sparse_days_under_3600_observations',len(sparse)),
    ]
    activity_days=collections.defaultdict(float)
    for source in ['sedentary_minutes','lightly_active_minutes','moderately_active_minutes','very_active_minutes']:
        invalid=0
        for r in a.small[source]:
            value=numeric(r.get('value'));stamp=parse_time(r.get('dateTime'))
            invalid+=int(math.isfinite(value) and not 0<=value<=1440)
            if stamp and math.isfinite(value):activity_days[(r['participant_id'],stamp.date())]+=value
        quality.append((source+'_outside_0_1440',invalid))
    quality.append(('summed_activity_minutes_above_1440',sum(v>1440 for v in activity_days.values())))
    quality.append(('rhr_outside_25_220',sum(math.isfinite(numeric(r.get('value',{}).get('value'))) and not 25<=numeric(r.get('value',{}).get('value'))<=220 for r in a.small['resting_heart_rate'])))
    quality.append(('srpe_exertion_outside_0_10',sum(math.isfinite(numeric(r.get('perceived_exertion'))) and not 0<=numeric(r.get('perceived_exertion'))<=10 for r in a.small['srpe'])))
    quality.append(('srpe_duration_outside_0_1440',sum(math.isfinite(numeric(r.get('duration_min'))) and not 0<=numeric(r.get('duration_min'))<=1440 for r in a.small['srpe'])))
    quality.append(('exercise_duration_negative',sum(numeric(r.get('duration'))<0 for r in a.small['exercise'])))
    quality.append(('sleep_awake_minutes_negative',int(sleep.minutesAwake.lt(0).sum())))
    for source in ['steps','distance','calories']:
        quality.append((source+'_negative_or_invalid_values',int(sen.loc[sen.source.eq(source),'invalid_values'].sum())))
    checks=pd.DataFrame(quality,columns=['check','count']);checks.to_csv(out/'quality_check_summary.csv',index=False)
    # Google report lag audit: preserve date and actual submission time separately.
    reporting=[]
    for r in a.small['reporting']:
        event=parse_time(r.get('date'),True);submit=parse_time(r.get('timestamp'),True)
        reporting.append(dict(participant_id=r['participant_id'],date=r.get('date'),submission=r.get('timestamp'),lag_hours=(submit-event).total_seconds()/3600 if event and submit else np.nan,invalid_date=event is None,invalid_submission=submit is None))
    reporting=pd.DataFrame(reporting);reporting.to_csv(out/'reporting_timestamp_audit.csv',index=False)
    # Sleep score timestamps can carry Z without matching an actual timezone conversion.
    score=pd.DataFrame(a.scores)
    score['sleep_log_entry_id']=pd.to_numeric(score.sleep_log_entry_id,errors='coerce')
    joinable=sleep[~sleep.conflicting_id].drop_duplicates(['participant_id','logId'])
    matched=score.merge(joinable[['participant_id','logId','endTime']],left_on=['participant_id','sleep_log_entry_id'],right_on=['participant_id','logId'],how='left',validate='many_to_one')
    matched['timestamp_clock']=pd.to_datetime(matched.timestamp,utc=True,errors='coerce').dt.tz_localize(None)
    matched['end_clock']=pd.to_datetime(matched.endTime,format='mixed',errors='coerce')
    matched['clock_delta_minutes']=(matched.timestamp_clock-matched.end_clock).dt.total_seconds()/60
    matched[['participant_id','sleep_log_entry_id','timestamp','endTime','clock_delta_minutes']].to_csv(out/'sleep_score_timestamp_comparison.csv',index=False)
    schema=inv[inv.file_format.isin(['.json','.csv','.xlsx'])].groupby('source_file').agg(files=('file_path','size'),column_schema_variants=('columns','nunique'),type_schema_variants=('dtypes','nunique')).reset_index()
    schema.to_csv(out/'schema_variants.csv',index=False)
    additional=[]
    for pid,g in sen.groupby('participant_id'):
        for source,h in g.groupby('source'):
            var='daily_'+source+'_sum' if source!='heart_rate' else 'daily_mean_heart_rate'
            values=h.value_sum if source!='heart_rate' else h.value_sum/h.records
            additional.append(dict(participant_id=pid,variable=var,**values.describe().to_dict()))
    exertion=[]
    for r in a.small['srpe']:
        load=numeric(r.get('perceived_exertion'))*numeric(r.get('duration_min'))
        exertion.append(dict(participant_id=r['participant_id'],load=load))
    exertion=pd.DataFrame(exertion)
    for pid,g in exertion.groupby('participant_id'):
        additional.append(dict(participant_id=pid,variable='session_rpe_load',**g.load.describe().to_dict()))
    for pid,g in pd.DataFrame(a.small['resting_heart_rate']).groupby('participant_id'):
        values=pd.Series([numeric(v.get('value')) for v in g.value])
        additional.append(dict(participant_id=pid,variable='resting_heart_rate',**values.describe().to_dict()))
    write_csv(stats+additional,out/'participant_descriptive_statistics.csv')
    inv['invalid_timestamps']=pd.to_numeric(inv.invalid_timestamps,errors='coerce').fillna(0)
    report=f'''# Data audit report

This is an actual-data research audit, not a trained pipeline. Full per-file inventory, parse failures and missing expected files are in research/dataset_inventory.csv. Participant-level derived data stays local and is ignored by Git.

## Scope and provenance

Participants: {len(a.participants)} ({', '.join(a.participants)}). Archive bytes: {a.src.path.stat().st_size if a.src.z else 'directory input'}. File records inventory includes structured files and images; raw sensor measurements are not supervised samples. Source observation window used for denominators: {START} through {END}, inclusive ({len(DAYS)} days). Files may contain records outside the window; inventory preserves their actual extrema, while sample eligibility uses the stated grid.

{table(rawtotals)}

Inventory missing expected files: {int(inv.status.eq('missing').sum())}; parse errors: {int(inv.status.eq('parse_error').sum())}; invalid primary timestamps: {int(inv.invalid_timestamps.sum())}. No silent parse success is claimed when a file fails. Image headers are verified with Pillow; EXIF dates are optional, and photos are excluded from numeric EDA.

## Completeness and schema

{table(cov)}

Field null rates (dictionary) use all records within each source-file type as denominator, counting absent optional nested fields as missing. Missing records/days are separate; continuous streams may have nonwear gaps despite exported zero rows. Daily sensor records, extrema, confidence-zero counts and coverage indicators are in daily_sensor_audit.csv. Exported days alone do not establish device wear. Numeric-looking CSV cells remain strings in raw-schema typing and are converted explicitly only in analysis. Nested objects are flattened; arrays remain arrays to avoid multiplying the record denominator. Array element schemas are profiled separately in nested_array_schema.csv.

## Consistency checks

Exact duplicate records, repeated primary timestamps and different contents at the same timestamp are counted per file in the inventory. A same-timestamp conflict can reflect multiple legitimate exercise sessions or reports; it is a review flag rather than a deletion rule. Sleep ID conflicts are excluded only from target selection. Raw files are never changed.

{table(structured.groupby('source_file')[['duplicate_records','duplicate_timestamps','conflicting_timestamps','invalid_timestamps']].sum().reset_index())}

{table(pd.DataFrame(problems))}

{table(checks)}

Physiological screens are broad audit flags, not diagnoses. Retain raw outliers; review isolated spikes against confidence and activity, derive robust summaries later, and fit any winsorization limits on training only. Efficiency differs from TST/timeInBed in many episodes; [Fitbit documentation](https://dev.fitbit.com/build/reference/web-api/sleep/get-sleep-log-by-date/) says to ignore the efficiency field for staged logs. Exclude raw staged efficiency; a separately named asleep/bed fraction can be derived transparently. Zero latency does not prove instantaneous sleep onset. Check the metadata workbook for inconsistent demographics, corrupt gender text, unparseable test dates, a run date outside the collection period, and implausible stride values; do not use exercise-test outcomes or strides before documented measurement availability.

Zero-total recorded step-days: {len(zero)}. Sparse HR days (<3600 samples, only a proxy and not hours of wear): {len(sparse)}. Steps=0 can mean sedentary behavior, nonwear or export padding. The feature eligibility screen requires some positive steps, or >=1200 step records plus positive HR when steps total zero; even then true inactivity is uncertain. Do not turn a missing stream into zero activity. Steps quality screen is deliberately provisional; daily record counts and ranges support a stricter wear rule later.

There are 145 daily resting-HR entries with value 0.0, which cannot represent a living participant's resting heart rate. Treat them as invalid/missing features, not low physiological readings. They are preserved in the raw dictionary/range audit and excluded from RHR feature-day eligibility with the broad 25..220 BPM screen. This is separate from entirely missing RHR files and from within-field nulls. No ordinary instantaneous HR values fell outside that same broad screen, but 257376 HR records have confidence zero; good numerical range does not establish good measurement quality.

## Temporal alignment

PMSys ISO timestamps end in Z (UTC). They are effective event datetimes, with no independent server ingestion/report-submission datetime: entry may be retrospective. Fitbit dateTime/startTime/endTime are timezone-naive; retain seconds and subsecond fields actually present. Do not assign the user's Asia/Jakarta timezone. Scenarios UTC+0/+1/+2 apply only to wellness day assignment and are not a recovered timezone. DST, travel and device timezone changes remain unresolved; sample counts are therefore conditional, not deployment guarantees.

Sleep dateOfSleep equals end date in {int(sleep.date_end_match.sum())}/{len(sleep)} episodes and start date in {int(sleep.date_start_match.sum())}/{len(sleep)} episodes. Use end date for historical completed sleep and full timestamps for target selection across midnight. Device `mainSleep` distinguishes main/secondary sleep, not a proven nap diagnosis. Start/end interval midpoint handles crossing midnight without averaging clock strings. Overnight target window is (t 20:00,t+1 12:00); exact cutoff starts are excluded. No matching by the next available record across gaps.

Sleep-score rows: {len(score)}; unmatched log IDs: {int(matched.endTime.isna().sum())}; matched rows with identical encoded wall-clock timestamp and sleep end despite the score Z suffix: {int(matched.clock_delta_minutes.eq(0).sum())}. This comparison does not establish true UTC. Join by participant plus log ID and flag the timezone inconsistency instead of silently shifting.

Daily summaries dated midnight do not mean availability at midnight. Lag RHR and full-day activity to t-1. This audit also conservatively lags sleep and wellness features to t-1 to avoid assuming same-day synchronization. No ingestion timestamp is available, so even previous-day availability is an explicit engineering convention to validate. If later using day-t HR/activity, truncate raw event records at 20:00 only after timezone reconciliation; reconstruct summaries rather than including end-of-day totals. Apply exercise end<=cutoff and require confirmed report availability; startTime alone is insufficient.

Google reporting date and submission timestamp are parsed separately as DD/MM/YYYY; the date alone is not availability. Lag-hours distribution is retained in reporting_timestamp_audit.csv. Reports with submission >48 hours after event-day midnight: {int(reporting.lag_hours.gt(48).sum())}; negative lags: {int(reporting.lag_hours.lt(0).sum())}; unparseable dates: {int(reporting.invalid_date.sum())}. Repeated entries and month-scale lags must not be silently corrected; exclude Google reports from the MVP features pending reconciliation.

## Leakage and exclusions

Exclude future fatigue/readiness/stress and target-night sleep score/TST/stages from inputs. Exclude vendor thirtyDayAvgMinutes and static exercise tests until past availability is verified. No HRV/RMSSD from BPM; no beat-to-beat RR intervals were identified. Rolling 3/7-day features must reindex to calendar dates and use only days <=t-1; require >=2/3 and >=4/7 observed days and output counts/missing masks. Personal references need >=14 past observations, fitted/updated without future data. Split-dependent scaling, imputation and feature selection fit on training only. Participant ID is a grouping key, not a numeric physiological feature.

No participant is globally removed solely for incompleteness. Task-specific absent labels naturally exclude rows; subject_holdout_audit.csv identifies empty and single-class folds. Main-sleep targets exclude invalid consistency screens and ambiguous next-night episodes, not statistical outliers. Photos, injury/body codes and Google diet logs are out of MVP scope; retain inventory. FD-CSR is not used. The complete feature and split tables document the downstream decisions.

## Specific sparse sources and validation limits

p12 has only 8 main-sleep days and zero eligible sleep-supervision rows under the declared history/window rule. It contributes only 4 fatigue rows with sleep history, so do not claim reliable p12 personalized evaluation. p12 and p13 lack daily resting-HR files entirely; use missing-modality masks rather than globally dropping them from every task. p04 has only 35 daily resting-HR days. p03/p13 also have sparse sleep coverage. p08 lacks injury.csv and p15 lacks Google reporting.csv, neither of which is required for the recommended MVP inputs.

There are {int(sleep.duplicated(['participant_id','logId']).sum())} repeated sleep log IDs, but {int(sleep.conflicting_id.sum())} rows conflict on the primary label fields start/end/TST. Entries can differ in other vendor fields. Deduplicate by participant+logId before score joins, and validate the many-to-one relation; joining unfiltered repeated episodes would inflate score counts. Raw distributions explicitly retain raw episodes; target counts deduplicate IDs.

The chronological fatigue test set contains only negative labels for p02, p03 and p05; p12 has no validation/test rows. Subject-level performance estimates there are weak or one-class. Pooled validation/test sets contain both classes, but reporting only pooled AUC would conceal this limitation. Unseen-subject p12 sleep validation is not possible under this setup. Four subject-fold support and individual LOSO support are provided, without fitting any model.

Source schema variants:

{table(schema)}

Sleep log types: {json.dumps(sleep.type.value_counts().to_dict())}; infoCode counts: {json.dumps(sleep.infoCode.value_counts().to_dict())}. Fitbit documents 1 as insufficient HR and 2 as a short sleep; retain these flags for stratified sensitivity checks rather than assuming every classic/staged episode has identical measurement quality. Exercise loads are optional self-reports; absence is unknown rather than a verified zero session load. Per-person numerical summaries include activity sums, HR summaries, resting HR and session load as well as wellness and sleep. Clock-hour summaries require circular interpretation.

Figures: wellness distributions, per-person fatigue, main sleep/TST/timing, participant RHR/activity, missingness, transitions and temporal coverage in reports/figures. See participant_descriptive_statistics.csv for participant-specific numerical distributions. Autocorrelation, small subject count, healthy terrestrial convenience sampling and subjective label bias limit generalization to astronauts. Neither PVT nor biological circadian phase is present.
'''
    (out/'data_audit_report.md').write_text(report,encoding='utf-8')
    create_features(a,cov,base)
    spec=f'''# Recommended ML specification

## Decision

**CONDITIONAL GO** for next-day self-reported fatigue and next-main-sleep TST in a research/hackathon prototype. **NO-GO** for claims of cognitive impairment diagnosis, objective cognitive performance forecasting, or biological circadian phase. PMData only; FD-CSR deferred. No models have been trained.

## Labels and cutoff

One row per participant and calendar cutoff day t, at 20:00 participant local time after timezone resolution. Cognitive target: first valid fatigue report on calendar day t+1, elevated=1 for score 1/2, else 0 for 3/4/5. Do not impute target labels. Optional ordinal target preserves 1..5. Sleep target: minutesAsleep of unique, device-main episode starting strictly after t 20:00 and before t+1 12:00; check positive duration, TST consistency, conflicting IDs and multiple candidates. Optional sleep interval midpoint uses sine/cosine and circular error, with no circadian phase claim. Pre-20:00 main sleep is not the requested future target.

## Inputs and schema

Grouping metadata: participant_id:string; cutoff_datetime:timezone-aware ISO (blocked until timezone mapping agreed); cutoff_date:date; feature_window_end:date(t-1); source_available_at:nullable datetime with explicit status. Targets: target_fatigue_score:nullable ordered int1..5; target_elevated_fatigue:nullable bool; target_sleep_tst_minutes:nullable float; target_sleep_log_id:nullable string; optional target_midpoint_sin/cos:nullable float. Labels/target IDs must never enter the feature matrix.

Numeric feature columns: sleep_tst_prev, sleep_score_prev (join by log ID), sleep_midpoint_sin/cos_prev, sleep_tst_mean_3d/7d, sleep_tst_sd_7d, sleep_observed_n_3d/7d, rhr_prev, rhr_delta_past28d, steps_prev, active_minutes_prev, fatigue_prev, stress_prev, mood_prev, readiness_prev, each with *_missing and *_age_days where appropriate. Sparse optional exercise_load_prev = sum(RPE*duration_minutes) only when session timing/report availability is verified. Calendar weekday_sin/cos and elapsed-study-day may be included with drift checks. Global baselines are training-only; personal baselines use past records only. Do not input workbook post-baseline measurements.

Feature policy: lag full-day RHR/activity to t-1. Conservatively also lag sleep/wellness to t-1 pending availability verification. Use real calendar joins, not shift(-1) over available rows. Features are optional with masks; require at least one valid historical sleep episode ending on t-1 for the reported counts. Reindex rolling windows on actual dates. Features cannot be measured or reported after the cutoff. Offline files lack arrival logs, so exact online availability is unverified.

## Actual eligibility counts

Reference sensitivity scenario offset 0 (UTC wellness date vs naive Fitbit date): cognitive {len(target)} rows ({int(target.elevated_fatigue.eq(1).sum())} elevated), sleep {len(starget)} rows. Both use a valid main-sleep episode ending on t-1. These are correlated participant-days across <=16 participants, not thousands of independent subjects. Full-modality requirements reduce these counts as shown below.

{table(baseeff.drop(columns='offset_hours'))}

See reports/effective_sample_sizes.csv for UTC+1/+2 wellness-date sensitivity. No definitive 20:00-local eligible sample count can be certified until timezone and report arrival assumptions are settled.

## Evaluation

For seen participants use November-January training, February validation, March test, purging cutoff rows whose target horizon crosses split boundaries. Report per-person support, target diversity and metrics from validation_split_audit.csv. Freeze model/preprocessing before test; explicitly distinguish online past-only baseline updates from model refitting. For unseen participants use LOSO (16 folds, some may have no labels or one class) or grouped folds with no participant overlap; actual support in subject_holdout_audit.csv. Do not transfer a held-out person's future baseline into training. No random row splits. No hyperparameter tuning in this audit.

Binary metrics: balanced accuracy, macro F1, recall/specificity, PR-AUC, Brier/calibration; ROC-AUC undefined for one-class folds. Sleep: MAE/RMSE minutes and participant-macro errors. Timing: circular MAE minutes. Proposed simple baselines: training prevalence/majority, past-only participant median and persistence. Bootstrap participants for uncertainty. Compare each modality condition with identical target/split definitions.

## Required decisions before preprocessing/training

1. Resolve device timezone, DST/travel and PMSys effective-time versus actual-report availability; archive UTC offset scenarios are sensitivity analyses, not recovered truth.
2. Approve first next-day fatigue report as label and previous-completed-day features; consider a conservative extra lag if report latency cannot be bounded.
3. Review main sleep window and ambiguous episodes, minimum sensor-wear rule, and whether shift/day sleep belongs in a separate task.
4. Decide minimum history for rolling/personal features and missingness-mask policy; never impute targets.
5. Fix chronological and held-out-participant evaluation policies, treatment of one-class folds, calibration period for new participants and online baseline updates.
6. Resolve current CC BY versus original-paper CC BY-NC discrepancy before broader redistribution/commercial reuse. Cite the publication and applicable license. No participant data is uploaded or pushed.

Use research/data_dictionary.csv, reports/feature_feasibility.csv and reports/target_audit.md as the handoff contract. This is terrestrial wearable wellness research with no astronaut-specific validation, no objective cognitive ground truth and no circadian phase markers.
'''
    (research/'recommended_ml_spec.md').write_text(spec,encoding='utf-8')


def create_features(a,cov,base):
    definitions=[
        ('sleep_tst_prev','sleep.minutesAsleep','unique main episode ending t-1','minutes','include','sleep_days'),
        ('sleep_quality_prev','sleep_score.overall_score; wellness.sleep_quality','device score and self-report kept separate; episode ID join','score','include','sleep_days'),
        ('sleep_timing_prev','sleep.startTime; endTime','midpoint=start+(end-start)/2; sine/cosine of clock hour','unit circle','include','sleep_days'),
        ('sleep_roll_3d','sleep.minutesAsleep','calendar [t-3,t-1] mean; min 2 observed days; count/mask','minutes','include','sleep_days'),
        ('sleep_roll_7d','sleep.minutesAsleep','calendar [t-7,t-1] mean, sd; min 4 observed days; count/mask','minutes','include','sleep_days'),
        ('rhr_prev','resting_heart_rate.value.value','t-1 completed-day value','bpm','include','physiological_data_days'),
        ('rhr_personal_deviation','resting_heart_rate.value.value','subtract median in [t-28,t-1], min14 observations','bpm','optional','physiological_data_days'),
        ('hr_pre_cutoff','heart_rate.value.bpm; confidence','event-time truncation; robust mean/median/min/max and observed coverage','bpm','defer until timezone and availability validated','heart_rate_days'),
        ('activity_prev','steps.value; *_active_minutes.value','t-1 observed sum plus wear/coverage and missingness masks','steps/minutes','include','activity_data_days'),
        ('exercise_load_prev','srpe.perceived_exertion; duration_min','sum perceived_exertion * duration_min; day t-1; verify end/report time','arbitrary load units','optional','wellness_days'),
        ('wellness_history','wellness.fatigue; stress; mood; readiness','t-1 historical reports; never future label-day report','ordinal scores','include','wellness_days'),
        ('personal_sleep_reference','sleep.startTime; endTime','past28 calendar days ending t-1, min14; circular mean with resultant length','clock angle','optional','sleep_days'),
        ('calendar','cutoff date','weekday sine/cosine; time since study start','calendar','include','total_observation_days'),
        ('vendor_30day_average','sleep.levels.summary.*.thirtyDayAvgMinutes','opaque vendor window; recompute own past-only aggregate','minutes','exclude','sleep_days'),
        ('hrv_rmssd','ordinary heart_rate BPM','no valid RR intervals; no calculation','not available','exclude','heart_rate_days'),
        ('metadata_physical_test','participant-overview.xlsx','test results and strides measured during/after collection','mixed','exclude until measurement availability verified','total_observation_days'),
        ('google_diet_weight','reporting.date; timestamp; weight; meals','separate event date and submission; inconsistent dates/late reports','mixed','exclude MVP','wellness_days'),
    ]
    rows=[]
    feasible=collections.Counter()
    score_days=set()
    for r in a.scores:
        stamp=parse_time(r.get('timestamp'))
        if stamp and math.isfinite(numeric(r.get('overall_score'))):score_days.add((r['participant_id'],stamp.date()))
    exertion_days=set()
    for r in a.small['srpe']:
        stamp=parse_time(r.get('end_date_time'))
        if stamp and math.isfinite(numeric(r.get('perceived_exertion'))) and math.isfinite(numeric(r.get('duration_min'))):exertion_days.add((r['participant_id'],stamp.date()))
    for pid,g in base.groupby('participant_id'):
        g=g.sort_values('cutoff_date')
        hs=g.sleep_history.astype(int)
        feasible['sleep_tst_prev']+=hs.sum()
        feasible['sleep_timing_prev']+=hs.sum()
        feasible['sleep_roll_3d']+=hs.rolling(3,min_periods=1).sum().ge(2).sum()
        feasible['sleep_roll_7d']+=hs.rolling(7,min_periods=1).sum().ge(4).sum()
        feasible['rhr_prev']+=g.rhr_history.sum()
        feasible['rhr_personal_deviation']+=(g.rhr_history&g.rhr_history.astype(int).rolling(28,min_periods=1).sum().ge(14)).sum()
        feasible['activity_prev']+=g.activity_history.sum()
        feasible['wellness_history']+=g.wellness_history.sum()
        feasible['personal_sleep_reference']+=hs.rolling(28,min_periods=1).sum().ge(14).sum()
        for r in g.itertuples():
            prior=dt.date.fromisoformat(r.cutoff_date)-dt.timedelta(days=1)
            feasible['sleep_quality_prev']+=int((pid,prior) in score_days)
            feasible['exercise_load_prev']+=int((pid,prior) in exertion_days)
    feasible['calendar']=len(base)
    for name,src,transform,unit,include,col in definitions:
        measured=name in feasible
        rows.append(dict(feature=name,source_variables=src,transformation=transform,unit=unit,inference_availability='previous completed day <=t-1; ingestion lag unknown' if name!='hr_pre_cutoff' else 'must be measured and ingested <=t20:00 after timezone reconciliation',missingness=f'{100*(1-feasible[name]/len(base)):.3f}% unavailable cutoff-days under source/history gates; provisional timezone, no ingestion guarantee' if measured else 'not estimated: excluded or unverified availability',eligible_feature_days=int(feasible[name]) if measured else None,denominator_cutoff_days=len(base),quality_note='sleep_quality count uses device overall score presence; self-report separate; wellness group any report; circular baseline concentration may further reduce support',expected_relevance='past sleep/wellness and recovery/activity context; association not established by audit',leakage_risk='future/target-night data; unverified report latency; future baseline; train/test preprocessing contamination',recommendation=include))
    write_csv(rows,ROOT/'reports/feature_feasibility.csv')


def nested_schema(a):
    rows=[]
    # Nested arrays are small sleep/exercise objects; inspect every element, not just the first.
    stats=collections.defaultdict(lambda:dict(n=0,fields=collections.defaultdict(collections.Counter),nonmissing=collections.Counter(),mins={},maxs={}))
    def walk(value,path,source):
        if isinstance(value,list):
            for v in value:
                s=stats[(source,path)];s['n']+=1
                if isinstance(v,dict):
                    for k,x in flat(v).items():
                        s['fields'][k][type(x).__name__]+=1
                        s['nonmissing'][k]+=int(not missing(x))
                        num=numeric(x)
                        if math.isfinite(num):s['mins'][k]=min(s['mins'].get(k,num),num);s['maxs'][k]=max(s['maxs'].get(k,num),num)
                else:s['fields']['[]'][type(v).__name__]+=1
                walk(v,path+'[]',source)
        elif isinstance(value,dict):
            for k,v in value.items():
                if isinstance(v,(list,dict)):walk(v,path+'.'+k if path else k,source)
    for records in a.small.values():
        for record in records:walk(record,'',record['source'])
    for (source,path),s in stats.items():
        for field,types in s['fields'].items():
            rows.append(dict(source_file=source,array_path=path,field=field,element_count=s['n'],field_present=sum(types.values()),nonmissing=s['nonmissing'][field],types=json.dumps(types),missing_percentage=100*(s['n']-s['nonmissing'][field])/s['n'],observed_min=s['mins'].get(field),observed_max=s['maxs'].get(field)))
    write_csv(rows,ROOT/'reports/nested_array_schema.csv')
    dictionary=a.dictionary()
    entries=[]
    for r in rows:
        field=r['array_path']+'[].'+r['field']
        entries.append(dict(original_variable_name=field,source_file=r['source_file'],description='Nested array element: '+field,data_type=r['types'],unit='seconds' if r['field']=='seconds' else 'minutes' if r['field']=='minutes' else 'datetime' if r['field']=='dateTime' else 'source-specific / undocumented',valid_range_or_categories='see observed range',interpretation='element-level denominator, not parent sleep/exercise records',temporal_granularity='sleep stage interval or exercise subrecord',missing_value_percentage=r['missing_percentage'],record_denominator=r['element_count'],field_present=r['field_present'],nonmissing=r['nonmissing'],measurement_type='device-derived estimate',potential_role='optional historical feature / metadata; exclude pending semantic verification',leakage_risk='target-night levels and future exercise cannot enter features',scientific_relevance='sleep structure or activity intensity context',documentation_source=FITBIT if 'sleep' in r['source_file'] else 'raw schema; field units not independently verified',observed_min=r['observed_min'],observed_max=r['observed_max']))
    pd.concat([dictionary,pd.DataFrame(entries)],ignore_index=True).to_csv(ROOT/'research/data_dictionary.csv',index=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',default=str(ROOT/'data/raw/pmdata'))
    parser.add_argument('--offsets',default='0,1,2',help='Sensitivity UTC offsets for wellness only; not asserted participant zones')
    parser.add_argument('--reuse-scan',action='store_true',help='Reuse only a trusted locally generated pickle scan cache for the same input')
    args=parser.parse_args(argv)
    for d in ['research','reports','reports/figures','notebooks']:(ROOT/d).mkdir(parents=True,exist_ok=True)
    begin=time.time();a=Audit(Source(args.input))
    cache=ROOT/'.audit_cache';cache.mkdir(exist_ok=True)
    fingerprint=(str(Path(args.input).resolve()),Path(args.input).stat().st_size,Path(args.input).stat().st_mtime_ns)
    cachefile=cache/'scan.pkl'
    if args.reuse_scan and cachefile.exists():
        with cachefile.open('rb') as f:state=pickle.load(f)
        if state['fingerprint']!=fingerprint:raise ValueError('Scan cache input fingerprint mismatch')
        a.__dict__.update(state['audit'])
        print('Reused local scan cache',flush=True)
    else:
        a.scan()
        with cachefile.open('wb') as f:pickle.dump({'fingerprint':fingerprint,'audit':{k:v for k,v in a.__dict__.items() if k!='src'}},f)
    write_csv(a.inv,ROOT/'research/dataset_inventory.csv')
    a.dictionary().to_csv(ROOT/'research/data_dictionary.csv',index=False)
    nested_schema(a)
    result=build_analysis(a,[int(x) for x in args.offsets.split(',')])
    result.update(input_path=str(Path(args.input).resolve()),python=sys.version,platform=platform.platform(),seconds=time.time()-begin,parse_errors=a.errors,execution_utc=dt.datetime.now(dt.timezone.utc).isoformat(),input_size_bytes=a.src.path.stat().st_size if a.src.z else None,packages={x:__import__(x).__version__ for x in ['pandas','numpy','matplotlib','seaborn','ijson']},alignment_convention='t-1 features; UTC+0,+1,+2 wellness-date sensitivity; unzoned Fitbit')
    if a.src.z:
        sha=hashlib.sha256()
        with a.src.path.open('rb') as f:
            for chunk in iter(lambda:f.read(8*1024*1024),b''):sha.update(chunk)
        result['archive_sha256']=sha.hexdigest()
    (ROOT/'reports/audit_run.json').write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
    print(json.dumps(result,indent=2,default=str),flush=True)
    return result


if __name__=='__main__':main()
