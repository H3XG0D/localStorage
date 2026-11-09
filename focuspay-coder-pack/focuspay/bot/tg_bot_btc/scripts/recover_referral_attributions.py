"""Recover evidenced first-start referrals and missing commissions.

Read-only planning by default. --apply requires the exact --expected-plan digest.
Run from /tmp with the bot venv and --bot-root pointing at the deployed bot.
Backups and receipts contain customer data: keep them on the server, mode 0600.
"""
from __future__ import annotations
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import sys

CUTOFF = datetime.fromisoformat('2026-08-17T00:00:00+03:00')

def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

def obj(value):
    return json.loads(value) if isinstance(value, str) else value

def rebuild_economics(order, build):
    """Existing reprice_closed_buy_economics.py 20/21/22 historical policy.

    Only used if no saved service profit. Explicit operator spread wins.
    All monetary inputs come from the original order; no current spread lookup.
    """
    if order['direction'].lower() != 'buy':
        return None
    fee = float(order['card_fee_pct']) if order['card_fee_pct'] is not None else .12
    spread = order.get('manual_spread_pct')
    if spread is not None:
        markup, policy = 1 + float(spread) / 100, 'recorded_manual_spread'
    elif utc(order['created_at']) < CUTOFF:
        markup, policy = 1.20, 'historical_20'
    else:
        payment = obj(order.get('payment_snapshot')) or {}
        merchant = str(order.get('merchant_order_id') or '')
        auto = (abs(fee - .12) <= abs(fee - .14)) if order['card_fee_pct'] is not None else bool(
            payment.get('merchant_uuid') or (merchant != order['order_id'] and '-' in merchant)
        )
        markup, policy = (1.21, 'recent_auto_21') if auto else (1.22, 'recent_manual_22')
    if any(not math.isfinite(float(order.get(k) or 0)) for k in ('fiat_amount','crypto_amount','rate','cashback_applied_rub')):
        return None
    if float(order.get('fiat_amount') or 0) <= 0 or float(order.get('crypto_amount') or 0) <= 0 or float(order.get('rate') or 0) <= 0:
        return None
    snapshot = build('buy',order['crypto'],float(order['fiat_amount']),float(order['crypto_amount']),float(order['rate']),
        cashback_applied_rub=float(order.get('cashback_applied_rub') or 0),card_fee=fee,
        manual_buy=policy=='recent_manual_22',buy_markup_override=markup)
    snapshot['referral_recovery_policy'] = policy
    return snapshot

FIRSTS = '''WITH first_log AS (
 SELECT DISTINCT ON(user_id) user_id,ref_token,created_at,id
 FROM bot_start_ref_log ORDER BY user_id,created_at,id
) SELECT b.user_id,b.first_seen_at,b.captcha_passed_at,b.referral_locked,b.pending_ref_token,
 l.ref_token,l.created_at first_click,r.user_id referrer_user_id,
 pc.id campaign_id,pc.code promo_code,pc.is_active campaign_active,pc.campaign_kind,
 pa.telegram_user_id partner_user_id
 FROM first_log l JOIN bot_users b USING(user_id)
 LEFT JOIN bot_users r ON r.ref_token=l.ref_token
 LEFT JOIN promo_campaigns pc ON pc.ref_token=l.ref_token
 LEFT JOIN partner_accounts pa ON pa.promo_campaign_id=pc.id
 WHERE l.ref_token IS NOT NULL
 AND l.created_at BETWEEN b.first_seen_at AND b.first_seen_at+interval '5 seconds'
 AND NOT EXISTS(SELECT 1 FROM promo_attributions a WHERE a.user_id=b.user_id)
 AND NOT EXISTS(SELECT 1 FROM user_referral_attributions a WHERE a.user_id=b.user_id)
 ORDER BY b.user_id'''

async def plan(conn):
    from services.economics_snapshot import build_economics_snapshot
    from services.partner_tier import global_tier_from_runtime,resolve_tier_settings,tier_info
    from services.runtime_settings import partner_tier_global,user_referral_pct
    campaign_rows = [dict(r) for r in await conn.fetch("SELECT * FROM promo_campaigns WHERE campaign_kind='partner'")]
    campaigns = {r['code']:r for r in campaign_rows}
    partners = {r['telegram_user_id']:dict(r) for r in await conn.fetch('SELECT * FROM partner_accounts WHERE is_active=TRUE')}
    promos = {r['user_id']:dict(r) for r in await conn.fetch('SELECT * FROM promo_attributions')}
    personal = {r['user_id']:dict(r) for r in await conn.fetch('SELECT * FROM user_referral_attributions')}
    counts = Counter(r['promo_code'] for r in promos.values())
    result={'attributions':[],'pending':[],'credits':[],'economics':[],'skips':[], 'campaigns':campaign_rows}
    raw = await conn.fetch(FIRSTS)
    seen=set()
    for record in raw:
        r=dict(record);uid=r['user_id']
        if uid in seen: raise RuntimeError('Ambiguous token or multiple campaign owners')
        seen.add(uid)
        ref=r['referrer_user_id']; code=None
        if ref:
            if ref==uid: continue
            partner=partners.get(ref)
            if partner:
                found=[x for x in campaign_rows if x['id']==partner['promo_campaign_id'] and x['is_active']]
                if found: code=found[0]['code']
        elif r['campaign_kind']=='partner' and r['campaign_active'] and r['partner_user_id']!=uid:
            code=r['promo_code']
        else: continue
        if r['captcha_passed_at'] is None:
            if r['pending_ref_token'] != r['ref_token'] or r['referral_locked']:
                result['pending'].append(r)
            continue
        if r['captcha_passed_at'] < r['first_click']: continue
        r['target_code']=code
        result['attributions'].append(r)
        if ref: personal[uid]={'user_id':uid,'referrer_user_id':ref,'created_at':r['captcha_passed_at']}
        if code:
            promos[uid]={'user_id':uid,'promo_code':code,'assigned_at':r['captcha_passed_at']}
            counts[code]+=1
    # Repair missing partner side of existing personal attributions.
    for uid,a in list(personal.items()):
        if uid in promos: continue
        partner=partners.get(a['referrer_user_id'])
        if not partner:continue
        found=[x for x in campaign_rows if x['id']==partner['promo_campaign_id'] and x['is_active']]
        if not found:continue
        code=found[0]['code']
        result['attributions'].append({'user_id':uid,'referrer_user_id':None,'target_code':code,'captcha_passed_at':a['created_at'],'dual_only':True})
        promos[uid]={'user_id':uid,'promo_code':code,'assigned_at':a['created_at']};counts[code]+=1
    users=sorted(set(promos)|set(personal))
    orders=await conn.fetch("SELECT * FROM orders WHERE user_id=ANY($1::bigint[]) AND status IN ('PAID','COMPLETED') ORDER BY order_id",users)
    pl={r['order_id'] for r in await conn.fetch('SELECT order_id FROM partner_ledger WHERE order_id IS NOT NULL')}
    ul={r['order_id'] for r in await conn.fetch('SELECT order_id FROM user_referral_ledger WHERE order_id IS NOT NULL')}
    globals_=global_tier_from_runtime(partner_tier_global())
    for record in orders:
        o=dict(record);uid=o['user_id'];oid=o['order_id'];code=promos.get(uid,{}).get('promo_code');ref=personal.get(uid,{}).get('referrer_user_id')
        campaign=campaigns.get(code)
        if campaign:
            if oid in pl:continue
            if oid in ul:
                result['skips'].append({'order_id':oid,'reason':'already_personal_commission'});continue
            if not campaign['is_active']:
                result['skips'].append({'order_id':oid,'reason':'inactive_campaign'});continue
            if o['status']!='PAID':
                result['skips'].append({'order_id':oid,'reason':'not_paid_partner'});continue
            pct=tier_info(counts[code],resolve_tier_settings(globals_,campaign))['effective_percent']
            target={'kind':'partner','recipient':campaign['id'],'code':code}
            since=promos[uid]['assigned_at']
        elif ref and ref not in partners:
            if oid in ul:continue
            if oid in pl:
                result['skips'].append({'order_id':oid,'reason':'already_partner_commission'});continue
            pct=float(user_referral_pct());target={'kind':'personal','recipient':ref};since=personal[uid]['created_at']
        else:continue
        # Never compensate deals completed before their attributed first visit.
        # Legacy schema has no paid_at: created_at is a conservative lower bound.
        if utc(o['created_at']) < utc(since):
            result['skips'].append({'order_id':oid,'reason':'predates_attribution'});continue
        econ=obj(o['economics_snapshot'])
        rebuilt=False
        if not isinstance(econ,dict) or 'service_profit_rub' not in econ:
            econ=rebuild_economics(o,build_economics_snapshot);rebuilt=True
        if not econ or not math.isfinite(float(econ.get('service_profit_rub') or 0)):
            result['skips'].append({'order_id':oid,'reason':'unresolved_economics','direction':o['direction'],'fiat':o['fiat_amount'],'crypto_amount':o['crypto_amount'],'rate':o['rate']});continue
        profit=float(econ['service_profit_rub'] or 0)
        if rebuilt: result['economics'].append({'order_id':oid,'before':o['economics_snapshot'],'after':econ})
        amount=round(max(0,profit)*pct/100,2)
        if amount<=0:
            result['skips'].append({'order_id':oid,'reason':'nonpositive_or_rounds_zero'});continue
        result['credits'].append(dict(target,order_id=oid,amount=str(amount),pct=pct,profit=profit))
    return result

def digest(p):return hashlib.sha256(json.dumps(p,default=str,sort_keys=True).encode()).hexdigest()

def summary(p):
    by={}
    for r in p['credits']:
        key=r.get('code') or str(r['recipient'])
        by.setdefault(key,{'orders':0,'rub':Decimal('0')})
        by[key]['orders']+=1;by[key]['rub']+=Decimal(r['amount'])
    return {'plan':digest(p),'restored':len(p['attributions']),'pending':len(p['pending']),
        'credits':len(p['credits']),'rub':str(sum((Decimal(r['amount']) for r in p['credits']),Decimal('0'))),
        'economics_rebuilt':len(p['economics']),'skips':dict(Counter(r['reason'] for r in p['skips'])),'by_recipient':by}

def private_json(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,default=str,ensure_ascii=False);f.flush();os.fsync(f.fileno())

async def main(args):
    sys.path.insert(0,args.bot_root)
    import asyncpg
    from services import db
    from services.runtime_settings import refresh_settings
    from services.partner_commission import accrue_partner_commission
    from services.user_referral_commission import accrue_user_referral_commission
    dsn=next(x.split('=',1)[1].strip().strip('\"\x27') for x in Path(args.env_file).read_text().splitlines() if x.startswith('DATABASE_DSN='))
    db.DB_POOL=await asyncpg.create_pool(dsn,min_size=1,max_size=2)
    await refresh_settings(force=True)
    c=await asyncpg.connect(dsn)
    try:
        async with c.transaction(readonly=not args.apply):
            await c.execute("SET LOCAL lock_timeout='5s'")
            await c.execute("SET LOCAL statement_timeout='60s'")
            if args.apply:
                await c.execute('LOCK TABLE promo_attributions,user_referral_attributions,partner_ledger,user_referral_ledger IN SHARE ROW EXCLUSIVE MODE')
            p=await plan(c);s=summary(p)
            print(json.dumps(s,default=str,ensure_ascii=False),flush=True)
            if not args.apply:
                print('unresolved',json.dumps([r for r in p['skips'] if r['reason']=='unresolved_economics'],default=str))
                return
            if not args.expected_plan or digest(p)!=args.expected_plan:raise RuntimeError('Plan changed; run read-only planning again')
            backup_dir=Path(args.backup_dir);backup_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
            run=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            path=backup_dir/('all-referrals-'+run+'.json')
            # Includes before-state for each mutated row, plus full plan and monetary inputs.
            uids=[r['user_id'] for r in p['attributions']+p['pending']]
            oids=[r['order_id'] for r in p['credits']+p['economics']]
            users=[dict(r) for r in await c.fetch('SELECT * FROM bot_users WHERE user_id=ANY($1::bigint[]) FOR UPDATE',uids)]
            orders=[dict(r) for r in await c.fetch('SELECT * FROM orders WHERE order_id=ANY($1::text[]) FOR UPDATE',oids)]
            # Re-plan after row locks to catch changing order inputs.
            if digest(await plan(c))!=digest(p):raise RuntimeError('Inputs changed under lock')
            private_json(path,{'plan':p,'users_before':users,'orders_before':orders})
            print('backup',str(path),flush=True)
            for r in p['attributions']:
                if r['referrer_user_id']:
                    await c.execute('INSERT INTO user_referral_attributions(user_id,referrer_user_id,created_at) VALUES($1,$2,$3)',r['user_id'],r['referrer_user_id'],r['captcha_passed_at'])
                if r['target_code']:
                    await c.execute('INSERT INTO promo_attributions(user_id,promo_code,assigned_at) VALUES($1,$2,$3)',r['user_id'],r['target_code'],r['captcha_passed_at'])
            for r in p['pending']:
                await c.execute('UPDATE bot_users SET pending_ref_token=$2,referral_locked=FALSE WHERE user_id=$1',r['user_id'],r['ref_token'])
            for r in p['economics']:
                after=dict(r['after'],referral_recovery_run=run)
                await c.execute('UPDATE orders SET economics_snapshot=$2::jsonb WHERE order_id=$1',r['order_id'],json.dumps(after))
            for r in p['credits']:
                fn=accrue_partner_commission if r['kind']=='partner' else accrue_user_referral_commission
                if not await fn(r['order_id'],conn=c):raise RuntimeError('Accrual unexpectedly skipped '+r['order_id'])
                table='partner_ledger' if r['kind']=='partner' else 'user_referral_ledger'
                field='campaign_id' if r['kind']=='partner' else 'referrer_user_id'
                row=await c.fetchrow(f'SELECT amount_rub,{field} recipient FROM {table} WHERE order_id=$1',r['order_id'])
                assert Decimal(str(row['amount_rub']))==Decimal(r['amount']) and row['recipient']==r['recipient']
            private_json(backup_dir/('all-referrals-'+run+'-receipt.json'),s)
        print('COMMITTED',flush=True)
        # Fresh transaction confirms durable result and idempotency.
        async with c.transaction(readonly=True):
            remaining=await plan(c)
            print('after',json.dumps(summary(remaining),default=str,ensure_ascii=False))
            assert not remaining['attributions'] and not remaining['pending'] and not remaining['credits']
    finally:
        await c.close();await db.DB_POOL.close()

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bot-root',default='/opt/tg_bot_btc')
    ap.add_argument('--env-file',default='/opt/exchange-backend/.env')
    ap.add_argument('--backup-dir',default='/root/focuspay-backups')
    ap.add_argument('--apply',action='store_true')
    ap.add_argument('--expected-plan')
    asyncio.run(main(ap.parse_args()))
