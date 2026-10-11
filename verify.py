"""Small live functional check; does not replace instructor-client evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import requests

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    base=args.url.rstrip('/')
    cases=[('GET','/0.html',{},200), ('POST','/',{'json':{'file':'0.html'}},200),
           ('GET','/hw4-deliberately-missing-file.html',{},404)]
    cases += [(m,'/0.html',{},501) for m in ['PUT','DELETE','HEAD','CONNECT','OPTIONS','TRACE','PATCH']]
    cases += [('GET','/0.html',{'headers':{'X-country':c}},400) for c in
              ['North Korea','Iran','Cuba','Myanmar','Iraq','Libya','Sudan','Zimbabwe','Syria']]
    results=[]
    for method,path,kwargs,expected in cases:
        response=requests.request(method,base+path,timeout=60,**kwargs)
        result={'method':method, 'path':path, 'country':kwargs.get('headers',{}).get('X-country'),
                'expected':expected,'actual':response.status_code,
                'request_id':response.headers.get('X-Request-ID'),
                'body_sha256':hashlib.sha256(response.content).hexdigest(),
                'body_bytes':len(response.content)}
        results.append(result)
        print(json.dumps(result),flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(results,indent=2)+'\n')
    if any(r['actual'] != r['expected'] for r in results):
        raise SystemExit('Unexpected HTTP status; inspect results.')
    if results[0]['body_sha256'] != results[1]['body_sha256']:
        raise SystemExit('GET and POST bodies differ.')

if __name__ == '__main__':
    main()
