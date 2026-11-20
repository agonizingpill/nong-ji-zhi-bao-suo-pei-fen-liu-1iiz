"""离线复算评分凭证：只读凭证文件内的原输入与模型参数，不连数据库、不带其他索赔原文。
用法：python scripts/replay_voucher.py <凭证.json>"""
import json,sys,hashlib,math
NUM=('hours_at_failure','age_days','leak_flag')
def canonical(d):return json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(',',':'))
# 与 src/voucher_service.py 中 replay 为同一份纯函数实现，改动时两边同步
def replay(model,inputs):
    z=float(model['intercept'])
    for f in ('model','part'):z+=model['coef'][f].get(str(inputs[f]),0.0)
    for f in NUM:z+=model['coef']['numeric'][f]*((float(inputs[f])-model['mean'][f])/model['scale'][f])
    return 1.0/(1.0+math.exp(-z))
def main(path):
    with open(path,encoding='utf-8') as f:doc=json.load(f)
    digest=doc.pop('digest','')
    if hashlib.sha256(canonical(doc).encode()).hexdigest()!=digest:
        print('凭证摘要校验失败：内容未存妥或被改动');return 2
    p=replay(doc['model'],doc['inputs'])
    ok=abs(p-doc['risk'])<=1e-9
    print(f"索赔 {doc['claim_code']} · 第{doc['attempt']}次生成 · 签发 {doc['issued_at']}")
    print(f"原输入：机型 {doc['inputs']['model']} / 部位 {doc['inputs']['part']} / {doc['inputs']['hours_at_failure']}h / {doc['inputs']['age_days']}天 / 渗漏 {doc['inputs']['leak_flag']}")
    print(f"复算争议概率 {p:.6f} · 凭证记录 {doc['risk']:.6f} · {'一致' if ok else '不一致'}")
    return 0 if ok else 1
if __name__=='__main__':
    if len(sys.argv)!=2:print(__doc__);sys.exit(64)
    sys.exit(main(sys.argv[1]))
