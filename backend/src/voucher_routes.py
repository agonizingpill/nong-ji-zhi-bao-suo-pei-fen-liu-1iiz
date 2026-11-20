import os
from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from redis import Redis
from .database import Session
from .security import current,allow
from .claim_service import get,audit
from .models import Claim
from .voucher_models import ScoreVoucher
from . import voucher_service as vs
router=APIRouter()
r=Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/0'),decode_responses=True)
def view(s,v):
    c=s.get(Claim,v.claim_id)
    return {'id':v.id,'claim_id':v.claim_id,'claim_code':c.code if c else '','state':v.state,'attempt':v.attempt,'risk':v.risk,'digest':v.digest,'error':v.error,'updated_at':v.updated_at,'model_ready':bool(v.model_json)}
@router.get('/vouchers')
def list_vouchers(u=Depends(current)):
    with Session() as s:return [view(s,v) for v in s.scalars(select(ScoreVoucher).order_by(ScoreVoucher.id.desc()))]
@router.get('/vouchers/{id}/download')
def download(id:int,u=Depends(current)):
    with Session() as s:
        v=get(s,ScoreVoucher,id)
        if v.state!='ready':raise HTTPException(409,'凭证尚未生成完成，不能下载')
        c=s.get(Claim,v.claim_id)
        try:doc=vs.document_of(v)
        except ValueError as e:raise HTTPException(409,str(e))
        return JSONResponse(doc,headers={'Content-Disposition':f'attachment; filename="voucher-{c.code}.json"'})
@router.post('/vouchers/{id}/retry')
def retry(id:int,u=Depends(current)):
    allow(u,'admin','assessor')
    with Session.begin() as s:
        v=get(s,ScoreVoucher,id)
        if v.state!='failed':raise HTTPException(409,'仅生成失败的凭证需要重试')
        c=s.get(Claim,v.claim_id)
        if not c or c.historical:raise HTTPException(404,'索赔不存在')
        if c.status not in ['failed','queued']:raise HTTPException(409,'当前索赔状态不可重试分流')
        v.state='pending';v.error='';v.updated_at=vs.now()
        c.status='queued';audit(s,u,'voucher_retried',c.code);cid=c.id
        result=view(s,v)
    r.rpush('claim-risk',cid)
    return result
@router.get('/claims/{id}/voucher-check')
def check(id:int,u=Depends(current)):
    with Session() as s:return vs.inspect_voucher(s,get(s,Claim,id))
@router.post('/claims/{id}/recompute')
def recompute(id:int,u=Depends(current)):
    with Session.begin() as s:
        c=get(s,Claim,id)
        v=vs.get_voucher(s,c.id)
        if not v or v.state!='ready':raise HTTPException(409,'该索赔缺少已生成的评分凭证，无法复算')
        payload=vs.payload_of(v);rep=vs.replay(payload['model'],payload['inputs'])
        ok=abs(rep-payload['risk'])<=1e-9 and c.risk is not None and abs(c.risk-payload['risk'])<=1e-5
        audit(s,u,'voucher_recomputed',f'{c.code}:{rep:.6f}')
        return {'claim_code':c.code,'recomputed':rep,'voucher_risk':payload['risk'],'claim_risk':c.risk,'consistent':ok,'inputs':payload['inputs']}
