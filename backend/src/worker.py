import json,time,os
from pathlib import Path
from redis import Redis
from .database import Session
from .models import Claim,Machine
from .voucher_service import begin_issue,publish,recover,mark_failed,get_voucher,ART,now as voucher_now
r=Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/0'),decode_responses=True)
def handle(cid):
    with Session.begin() as s:
        c=s.get(Claim,cid)
        if not c or c.status!='queued':return
        m=s.get(Machine,c.machine_id)
        if c.hours_at_failure>m.warranty_hours:
            c.status='out_of_warranty';c.assessment_note='超出质保工时'
            v=get_voucher(s,cid)
            if v and v.state in('pending','scoring'):v.state='failed';v.error='超出质保工时，未生成分流评分';v.updated_at=voucher_now()
            return
        begin_issue(s,c,m)
    with Session.begin() as s:
        c=s.get(Claim,cid)
        if not c or c.status!='queued':return
        v=get_voucher(s,cid)
        if v:publish(s,c,v)
def requeue_interrupted():
    with Session.begin() as s:ids=recover(s)
    for cid in ids:r.rpush('claim-risk',cid)
    return ids
def main():
    requeue_interrupted();last=time.time()
    while True:
        (ART/'worker-heartbeat').write_text(str(time.time()))
        item=r.blpop('claim-risk',timeout=2)
        if not item:
            if time.time()-last>30:
                last=time.time()
                try:requeue_interrupted()
                except Exception:pass
            continue
        cid=int(item[1])
        try:handle(cid)
        except Exception as e:
            with Session.begin() as s:mark_failed(s,cid,e)
if __name__=='__main__':main()
