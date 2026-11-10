#!/usr/bin/env python3
"""Independent snapshot-based hard-constraint audit for DSS5105 Human20.
No Agent/API calls. No ranking or automatic human judgments.
Requires the exact frozen rental_data_v2.csv used by the evaluation.
"""
import argparse, ast, csv, hashlib, json
from pathlib import Path
from openpyxl import load_workbook

MISSING={'','unknown','not stated','not specified','nan','none','null','prefer not to say'}
TRUE={'yes','true','1','allowed'}
FALSE={'no','false','0','not_allowed'}

def val(x):
    if x is None: return None
    s=str(x).strip()
    return None if s.lower() in MISSING else s

def number(x):
    try: return float(str(x).replace(',','')) if val(x) is not None else None
    except (TypeError,ValueError): return None

def norm(x): return str(x).strip().removesuffix('.0')

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def load_profiles(path):
    wb=load_workbook(path,read_only=True,data_only=True)
    ws=wb['Registered Profiles 20'];ws.reset_dimensions(); rows=iter(ws.values); head=next(rows)
    initial={str(d['Case ID']):d for v in rows if (d:=dict(zip(head,v))).get('Case ID')}
    ws=wb['Per-turn Expected Profiles'];ws.reset_dimensions();rows=iter(ws.values);head=next(rows)
    turns={}
    for v in rows:
        d=dict(zip(head,v)); cid=d.get('Case ID')
        if not cid: continue
        cid=str(cid); t=int(d['Turn']); r=initial[cid]
        profile={'max_price_sgd':int(r['Registered Budget SGD']),'rental_scope':r['Registered Rental Scope']}
        if number(r['Registered Min Bedrooms']) and number(r['Registered Min Bedrooms'])>0: profile['min_bedrooms']=int(number(r['Registered Min Bedrooms']))
        if str(r.get('Registered Lease Length') or '').strip().lower()=='12 months': profile['lease_months']=12
        faculty=val(r.get('Registered Faculty'))
        if faculty and faculty.lower()=='not selected': faculty=None
        extra=d.get('Extra effective conditions / priority')
        if isinstance(extra,str) and extra.strip().startswith('{'):
            profile.update(ast.literal_eval(extra))
        else:
            profile['max_price_sgd']=int(d['Budget SGD'])
            scope=val(d['Scope'])
            if scope: profile['rental_scope']=scope
            if cid=='G03':
                profile['air_conditioning_required']=True
                if t==1: profile['cooking_required']=True
            if cid=='G05' and t==2: profile['max_commute_minutes']=30
            if cid=='G04':
                if t==1: profile['rental_scope']='entire_unit'
                else: profile.pop('rental_scope',None)  # accepts both scopes
        turns[(cid,t)]=(profile,faculty)
    return turns

def get(row,*keys):
    for k in keys:
        if k in row and val(row[k]) is not None: return row[k]
    return None

def check(p,row,faculty,commute_minutes=None):
    checks=[]
    def add(field,status,actual,expected): checks.append({'field':field,'status':status,'actual':actual,'expected':expected})
    def cmpnum(field,keys,op,limit):
        actual=number(get(row,*keys)); status='UNKNOWN' if actual is None else ('PASS' if op(actual,float(limit)) else 'FAIL')
        add(field,status,actual,limit)
    def eq(field,keys,expected,allowed=None):
        raw=get(row,*keys); actual=str(raw).strip().lower() if raw is not None else None
        exp=str(expected).strip().lower()
        status='UNKNOWN' if actual is None else ('PASS' if (actual in allowed if allowed is not None else actual==exp) else 'FAIL')
        add(field,status,raw,expected)
    def boolfield(field,keys,positive,negative):
        raw=get(row,*keys); s=str(raw).lower() if raw is not None else None
        status='UNKNOWN' if s is None or s not in positive|negative else ('PASS' if s in positive else 'FAIL')
        add(field,status,raw,'required')
    if 'max_price_sgd' in p: cmpnum('max_price_sgd',['rent_monthly_sgd_now','rent_monthly_sgd','rent_sgd','rent_monthly_sgd_current'],lambda a,b:a<=b,p['max_price_sgd'])
    if p.get('rental_scope'): eq('rental_scope',['rental_scope'],p['rental_scope'])
    if p.get('room_type'): eq('room_type',['room_type'],p['room_type'])
    if p.get('district_code'): eq('district_code',['district_code'],p['district_code'])
    if p.get('property_types'): eq('property_types',['property_type'],p['property_types'],{str(x).lower() for x in p['property_types']})
    for key,columns,op in [('min_bedrooms',['bedrooms'],lambda a,b:a>=b),('min_bathrooms',['bathrooms'],lambda a,b:a>=b),('min_area_sqm',['area_sqm'],lambda a,b:a>=b),('max_mrt_minutes',['mrt_minutes_reported','mrt_minutes'],lambda a,b:a<=b),('max_mrt_distance_m',['mrt_distance_m'],lambda a,b:a<=b),('min_food_places',['food_places_1km'],lambda a,b:a>=b)]:
        if key in p: cmpnum(key,columns,op,p[key])
    if p.get('max_commute_minutes') is not None:
        minutes = commute_minutes
        status = ('UNKNOWN' if minutes is None else
                  ('PASS' if minutes <= float(p['max_commute_minutes']) else 'FAIL'))
        add('max_commute_minutes', status, minutes,
            f"<= {p['max_commute_minutes']} min to {faculty or 'unspecified faculty'}")
    if p.get('furnished_required'):
        eq('furnished_required',['furnishing'],'furnished',{'fully_furnished','partially_furnished','furnished'})
    if p.get('air_conditioning_required'):
        boolfield('air_conditioning_required',['air_conditioning'],{'yes','true','1'},{'no','false','0'})
    if p.get('cooking_required') or p.get('cooking_level'):
        raw=get(row,'cooking_policy');s=str(raw).lower() if raw is not None else None
        if p.get('cooking_level')=='full': good={'cooking_any_cooking','full_cooking','unrestricted_cooking'}
        else: good={'cooking_any_cooking','full_cooking','unrestricted_cooking','light_cooking','cooking_allowed'}
        bad={'cooking_not_allowed','no_cooking','not_allowed'}
        add('cooking', 'UNKNOWN' if s not in good|bad else ('PASS' if s in good else 'FAIL'),raw,p.get('cooking_level','allowed'))
    if p.get('landlord_not_living_in'): boolfield('landlord_not_living_in',['landlord_lives_in'],{'no','false','0'},{'yes','true','1'})
    if p.get('pets_allowed_required'):
        raw=get(row,'pets_policy');s=str(raw).lower() if raw is not None else None
        add('pets_allowed_required','UNKNOWN' if s not in {'pets_allowed','allowed','yes','no_pets','not_allowed','no'} else ('FAIL' if s in {'no_pets','not_allowed','no'} else 'PASS'),raw,'pets allowed')
    if p.get('tenant_gender'):
        raw=get(row,'gender_restriction');s=str(raw).lower() if raw is not None else None
        expected=p['tenant_gender'].lower(); allowed={'no_restriction',expected+'_only'}
        add('tenant_gender','UNKNOWN' if s is None else ('PASS' if s in allowed else 'FAIL'),raw,expected)
    if p.get('lease_months'):
        raw=get(row,'lease_term');s=str(raw).lower() if raw is not None else None
        # Only a clearly numeric minimum term can be verified; do not assume 'Flexible' means 12 months.
        months=None
        if s:
            import re
            m=re.fullmatch(r'(\d+)\s*(year|years|month|months)',s)
            if m: months=int(m.group(1))*(12 if m.group(2).startswith('year') else 1)
        add('lease_months','UNKNOWN' if months is None else ('PASS' if months<=int(p['lease_months']) else 'FAIL'),raw,p['lease_months'])
    # Occupancy capacity and MRT operational status require additional semantics; flag instead of guessing.
    if p.get('occupant_count'): add('occupant_count','UNKNOWN',get(row,'max_occupants','occupant_capacity'),p['occupant_count'])
    if 'max_mrt_minutes' in p or 'max_mrt_distance_m' in p:
        raw=get(row,'mrt_operation_status');s=str(raw).lower() if raw is not None else None
        add('mrt_operation_status','UNKNOWN' if s is None else ('PASS' if s=='operational' else 'FAIL'),raw,'operational')
    result='FAIL' if any(x['status']=='FAIL' for x in checks) else ('UNKNOWN' if any(x['status']=='UNKNOWN' for x in checks) else ('PASS' if checks else 'UNKNOWN'))
    return result,checks

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--agent',required=True,help='agent_profile20_*.jsonl')
    ap.add_argument('--profiles',default='DSS5105_20_Initial_Registered_Profiles_Defined.xlsx')
    ap.add_argument('--listings',required=True,help='Frozen active listings CSV')
    ap.add_argument('--commute',required=True,help='commute_faculty.csv with listing_id, faculty, minutes')
    ap.add_argument('--out-dir',default='gold_audit20')
    args=ap.parse_args(); profiles=load_profiles(args.profiles)
    with open(args.listings,encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        if not reader.fieldnames or 'listing_id' not in reader.fieldnames: ap.error('Listings CSV must contain listing_id')
        listings={norm(r['listing_id']):r for r in reader}
    if len(listings)<100: ap.error('Expected full frozen listings snapshot, not a tiny candidate extract')
    commute={}
    with open(args.commute,encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        if not {'listing_id','faculty','minutes'}.issubset(set(reader.fieldnames or [])):
            ap.error('Commute CSV must contain listing_id, faculty, minutes')
        for r in reader:
            key=(norm(r['listing_id']),str(r['faculty']).strip().casefold())
            minutes=number(r['minutes'])
            if minutes is not None:
                if key in commute and commute[key]!=minutes:
                    raise ValueError(f'Conflicting commute minutes for {key}')
                commute[key]=minutes
    records=[json.loads(line) for line in Path(args.agent).read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    out=Path(args.out_dir);out.mkdir(exist_ok=True,parents=True)
    details=[]; summary=[]
    for rec in records:
        cid=rec['case_id'];turn=int(rec['turn']);key=(cid,turn)
        if key not in profiles: raise ValueError(f'Missing effective profile {key}')
        p,faculty=profiles[key];counts={'PASS':0,'UNKNOWN':0,'FAIL':0,'MISSING_ID':0}
        ids=rec.get('listing_ids') or []
        for rank,lid in enumerate(ids,1):
            lid=norm(lid)
            if lid not in listings: status='MISSING_ID';checks=[]
            else: status,checks=check(p,listings[lid],faculty,commute.get((lid,str(faculty or '').strip().casefold())))
            counts[status]+=1
            details.append({'case_id':cid,'run':rec.get('run',1),'turn':turn,'rank':rank,'listing_id':lid,'status':status,'checks':json.dumps(checks,ensure_ascii=False),'effective_profile':json.dumps(p,ensure_ascii=False),'faculty':faculty or ''})
        summary.append({'case_id':cid,'run':rec.get('run',1),'turn':turn,'agent_status':rec.get('status'),'recommendation_count':len(ids),**counts,'confirmed_precision':round(counts['PASS']/len(ids),4) if ids else '', 'note':'No recommendation IDs; review no-match response' if not ids else ''})
    def write(name,rows):
        with (out/name).open('w',encoding='utf-8-sig',newline='') as f:
            if rows:
                w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    write('constraint_audit_details.csv',details);write('constraint_audit_summary.csv',summary)
    manifest={'agent_sha256':sha(args.agent),'profiles_sha256':sha(args.profiles),'listings_sha256':sha(args.listings),'commute_sha256':sha(args.commute),'commute_records':len(commute),'snapshot_listing_count':len(listings),'records':len(records),'scope':'recommended listing hard constraints only; not full pass set, recall, ranking or human judgments','caveats':['Faculty commute is joined by listing_id and exact faculty name; missing pairs remain UNKNOWN','Unknown and missing fields are never treated as PASS','Registered-profile and query-derived conditions taken from independently defined Excel, not Agent parsed preferences','Agent link activity/availability not independently checked','C relaxation cases evaluated against original strict requirements; alternatives may intentionally FAIL']}
    (out/'audit_manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    print('Wrote',out/'constraint_audit_summary.csv',out/'constraint_audit_details.csv',out/'audit_manifest.json',sep='\n')
    print('Rows:',len(details),'Turns:',len(summary),'Snapshot listings:',len(listings))
if __name__=='__main__': main()
