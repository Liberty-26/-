# -*- coding: utf-8 -*-
import json, sys, os, asyncio, base64
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ocr import call_qwen
from calibrate import calibrate_items, structural_decompose
UPLOADS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads')

def b64(p):
    with open(p,'rb') as f: return base64.b64encode(f.read()).decode()

async def main():
    cases = json.load(open('cases.json',encoding='utf-8'))
    total_fields = 0
    match_fields = 0
    for c in cases:
        img = b64(os.path.join(UPLOADS, os.path.basename(c['image'])))
        raw = await call_qwen('data:image/jpeg;base64,' + img)
        if not raw.get('success'): print('SKIP ' + c['image'] + ': fail'); continue
        structured = structural_decompose(raw.get('items',[]))
        cal = calibrate_items(structured)
        act = cal.get('items',[])
        exp = c['expected']
        n = min(len(act), len(exp))
        print('=== ' + c['image'] + ' ' + str(len(exp)) + ' exp vs ' + str(len(act)) + ' act ===')
        for i in range(n):
            a,e = act[i], exp[i]
            flags = []
            for f in ('name','spec','unit'):
                total_fields += 1
                if (a.get(f) or '').strip() == (e.get(f) or '').strip(): match_fields += 1
                else: flags.append(f + ': ' + str(a.get(f)) + ' != ' + str(e.get(f)))
            for f in ('qty','price'):
                total_fields += 1
                if abs((a.get(f) or 0) - (e.get(f) or 0)) < 0.01: match_fields += 1
                else: flags.append(f + ': ' + str(a.get(f)) + ' != ' + str(e.get(f)))
            if flags: print('  row' + str(i) + ': ' + ' | '.join(flags))
        for i in range(n, max(len(act),len(exp))):
            total_fields += 5
            if i < len(act): print('  row' + str(i) + ': extra ' + str(act[i].get('name')))
            else: print('  row' + str(i) + ': missing ' + str(exp[i].get('name')))
    rate = match_fields / total_fields * 100 if total_fields else 0
    print('Accuracy: ' + str(match_fields) + '/' + str(total_fields) + ' = ' + str(round(rate,1)) + '%')

asyncio.run(main())
