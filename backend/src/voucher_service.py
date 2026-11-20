import json,hashlib,math,os
from datetime import datetime,timezone
from pathlib import Path
from sqlalchemy import select
from .models import Claim,Machine
from .voucher_models import ScoreVoucher
from .risk_model import train,params_of,risk_of,NUM

ART=Path(os.getenv('ARTIFACTS_DIR','/artifacts'))

def now():return datetime.now(timezone.utc).isoformat()
def canonical(d):return json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest_of(payload):return hashlib.sha256(canonical(payload).encode()).hexdigest()

def snapshot(c,m):
    return {'claim_code':c.code,'machine_serial':m.serial,'model':m.model,'part':c.part,'hours_at_failure':c.hours_at_failure,'age_days':c.age_days,'leak_flag':int(c.leak_flag)}

# 离线复算入口：scripts/replay_voucher.py 内置同一份纯函数实现，改动时两边同步
def replay(model,inputs):
    z=float(model['intercept'])
    for f in ('model','part'):z+=model['coef'][f].get(str(inputs[f]),0.0)
    for f in NUM:z+=model['coef']['numeric'][f]*((float(inputs[f])-model['mean'][f])/model['scale'][f])
    return 1.0/(1.0+math.exp(-z))

def get_voucher(s,claim_id):
    return s.scalar(select(ScoreVoucher).where(ScoreVoucher.claim_id==claim_id))

def payload_of(v):
    inputs=json.loads(v.inputs_json);model=json.loads(v.model_json);metrics=json.loads(v.metrics_json)
    return {'voucher':'score-voucher/v1','claim_code':inputs['claim_code'],'attempt':v.attempt,'inputs':inputs,'model':model,'metrics':metrics,'risk':v.risk,'issued_at':v.updated_at}

def document_of(v):
    p=payload_of(v)
    if digest_of(p)!=v.digest:raise ValueError('凭证摘要与内容不符，未存妥或被改动')
    return p|{'digest':v.digest}

def ensure_pending(s,c):
    v=get_voucher(s,c.id)
    if not v:
        v=ScoreVoucher(claim_id=c.id,attempt=0,state='pending',updated_at=now());s.add(v);s.flush()
    elif v.state=='failed':
        v.state='pending';v.error='';v.updated_at=now()
    return v

def begin_issue(s,c,m):
    v=get_voucher(s,c.id) or ensure_pending(s,c)
    if v.state=='ready':return v,'ready'
    if v.inputs_json and v.model_json:return v,'resume'
    v.attempt+=1
    model,metrics=train(s)
    inputs=snapshot(c,m)
    v.inputs_json=canonical(inputs);v.model_json=canonical(params_of(model));v.metrics_json=canonical(metrics)
    v.risk=risk_of(model,inputs);v.state='scoring';v.error='';v.updated_at=now()
    s.flush();return v,'trained'

def publish(s,c,v):
    if v.state=='ready':return
    if not (v.inputs_json and v.model_json):raise ValueError('凭证缺少输入快照或模型参数，无法发布')
    v.updated_at=now()
    payload=payload_of(v);digest=digest_of(payload)
    v.digest=digest;v.state='ready';v.error=''
    c.risk=payload['risk'];c.status='assessed';c.assessment_note=json.dumps(payload['metrics'],ensure_ascii=False)
    doc=canonical(payload|{'digest':digest})
    art=ART/f'claim-{c.id}-voucher.json'
    if not art.exists():art.write_text(doc)
    met=ART/f'claim-{c.id}-model.json'
    if not met.exists():met.write_text(json.dumps(payload['metrics']))

def recover(s):
    out=[]
    for v in s.scalars(select(ScoreVoucher).where(ScoreVoucher.state.in_(['pending','scoring']))).all():
        c=s.get(Claim,v.claim_id)
        if not c or c.status!='queued':continue
        if v.state=='scoring':v.state='pending';v.updated_at=now()
        out.append(c.id)
    return out

def mark_failed(s,cid,err):
    c=s.get(Claim,cid)
    if c:c.status='failed';c.assessment_note=str(err)
    v=get_voucher(s,cid)
    if v and v.state!='ready':v.state='failed';v.error=str(err)[:500];v.updated_at=now()

def inspect_voucher(s,c):
    v=get_voucher(s,c.id)
    if not v:return {'claim_code':c.code,'state':'missing','attempt':0,'digest':'','consistent':False,'problems':['未生成评分凭证，无法复算'],'recomputed':None,'voucher_risk':None,'claim_risk':c.risk}
    problems=[];rep=None;risk=None
    if v.state!='ready':problems.append(f'凭证未生成完成（当前状态 {v.state}）')
    else:
        try:
            payload=payload_of(v);risk=payload['risk']
            if digest_of(payload)!=v.digest:problems.append('凭证摘要与内容不符，可能未存妥或被改动')
            rep=replay(payload['model'],payload['inputs'])
            if abs(rep-risk)>1e-9:problems.append('以原输入复算的概率与凭证评分不一致')
            if c.risk is None or abs(c.risk-risk)>1e-5:problems.append('凭证评分与索赔原评分不一致')
        except Exception as e:problems.append(f'凭证内容无法解析：{e}')
    return {'claim_code':c.code,'state':v.state,'attempt':v.attempt,'digest':v.digest,'consistent':not problems,'problems':problems,'recomputed':rep,'voucher_risk':risk,'claim_risk':c.risk}
