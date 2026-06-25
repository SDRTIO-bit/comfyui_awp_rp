import json, urllib.request, sys
sys.path.insert(0, ".")
from workflow_runner import load_workflow, convert_to_api_format

wf = load_workflow("rp_full_node_workflow.json")
prompt = convert_to_api_format(wf)
payload = json.dumps({"prompt": prompt["prompt"], "client_id": "test2"}, ensure_ascii=False).encode("utf-8")

req = urllib.request.Request(
    "http://127.0.0.1:8188/prompt",
    data=payload,
    headers={"Content-Type": "application/json"},
)
try:
    resp = urllib.request.urlopen(req, timeout=30)
    r = json.loads(resp.read().decode())
    print("OK - prompt_id:", r.get("prompt_id"))
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print("HTTP", e.code)
    if len(body) < 400:
        print(body)
    else:
        err = json.loads(body)
        node_errs = err.get("node_errors", {})
        for nid in list(node_errs.keys())[:5]:
            ne = node_errs[nid]
            ctype = ne.get("class_type", "?")
            errs = str(ne.get("errors", []))[:200]
            print(f"Node {nid} ({ctype}): {errs}")
        if len(node_errs) > 5:
            print(f"... and {len(node_errs)-5} more node errors")
