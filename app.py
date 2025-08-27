import os, io, re, uuid, tempfile, zipfile, shutil
from threading import Timer
from flask import Flask, render_template_string, request, send_file, after_this_request, jsonify
from werkzeug.utils import secure_filename
import fitz  # PyMuPDF
import razorpay

# ---------- SETTINGS ----------
FREE_PAGE_LIMIT = 25
MAX_UPLOAD_MB   = 25
FLAT_PRICE_INR  = 10  # 26+ pages या >25MB पर

RAZORPAY_KEY_ID     = os.environ.get("RAZORPAY_KEY_ID", "rzp_live_RARsbcBzkpvQL6")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "0NOMVQw0d8JuiPXMb0TycrNO")
rz_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)) if (RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET) else None

app = Flask(__name__)
SLOTS = {}  # token -> {pdf_path, tmpdir, pages, size, paid?, order_id?, amount?}

# ---------- UI ----------
INDEX_HTML = f"""
<!doctype html>
<html lang="hi">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Mahamaya Stationery — PDF → Image</title>
<style>
  :root {{
    --bg:#0b1220; --fg:#e7eaf1; --muted:#9aa4b2; --card:#10182b;
    --accent:#4f8cff; --accent2:#22c55e; --danger:#ef4444; --stroke:#1f2a44;
  }}
  *{{box-sizing:border-box}}
  body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;background:var(--bg);color:var(--fg)}}
  .wrap{{min-height:100svh;display:grid;place-items:center;padding:24px}}
  .card{{width:min(860px,100%);background:linear-gradient(180deg,#0f172a 0,#0b1220 100%);
        border:1px solid var(--stroke);border-radius:18px;padding:22px;box-shadow:0 10px 40px rgba(0,0,0,.35)}}
  .top{{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}}
  .brand{{display:flex;align-items:center;gap:10px;font-weight:800}}
  .dot{{width:26px;height:26px;border-radius:8px;background:linear-gradient(135deg,#4f8cff,#22c55e)}}
  .muted{{color:var(--muted);font-size:14px}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
  @media (max-width:720px){{.grid{{grid-template-columns:1fr}}}}
  label{{font-size:13px;color:#cdd6ea;display:block;margin-bottom:6px}}
  input[type=file],select{{width:100%;background:#0d162a;color:var(--fg);border:1px solid var(--stroke);border-radius:12px;padding:10px 12px;outline:none}}
  .row{{display:flex;gap:10px;flex-wrap:wrap;align-items:center}}
  button.btn{{display:inline-flex;align-items:center;gap:8px;padding:10px 14px;border-radius:12px;border:1px solid var(--stroke);background:var(--accent);color:#fff;font-weight:700;cursor:pointer}}
  button.ghost{{background:#18233b}}
  button:disabled{{opacity:.6;cursor:not-allowed}}
  .loader-wrap{{margin-top:12px;display:none}}
  .pulse{{width:100%;height:12px;border-radius:999px;background:rgba(79,140,255,.15);overflow:hidden;position:relative}}
  .pulse::after{{content:"";position:absolute;inset:0;transform:translateX(-100%);background:linear-gradient(90deg,transparent,rgba(79,140,255,.55),transparent);animation:shine 1.6s infinite}}
  @keyframes shine{{to{{transform:translateX(100%)}}}}
  .bubbles{{display:flex;gap:8px;margin-top:10px}}
  .bubbles span{{width:8px;height:8px;border-radius:50%;background:#4f8cff;opacity:.5;animation:bounce 1.2s infinite alternate}}
  .bubbles span:nth-child(2){{animation-delay:.2s}}
  .bubbles span:nth-child(3){{animation-delay:.4s}}
  @keyframes bounce{{to{{transform:translateY(-8px);opacity:1}}}}
  .alert{{margin-top:10px;padding:10px 12px;border-radius:12px;font-weight:700;display:none}}
  .ok{{background:rgba(34,197,94,.12);color:#22c55e;border:1px solid rgba(34,197,94,.25)}}
  .err{{background:rgba(239,68,68,.12);color:#ef4444;border:1px solid rgba(239,68,68,.25)}}
  .note{{font-size:12px;color:var(--muted);margin-top:6px}}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <div class="top">
      <div class="brand"><div class="dot"></div><div>Mahamaya Stationery</div></div>
      <div class="muted">फ्री: ≤ {FREE_PAGE_LIMIT} पेज & ≤ {MAX_UPLOAD_MB} MB • वरना ₹{FLAT_PRICE_INR}</div>
    </div>

    <h2 style="margin:10px 0 6px">तेज़ और साफ़ PDF → इमेज कन्वर्टर</h2>
    <p class="muted">PDF चुनें, dpi सेट करें, और सेकंडों में ZIP फाइल डाउनलोड करें।</p>

    <div class="grid">
      <div>
        <label>PDF फ़ाइल चुनें</label>
        <input id="pdf" type="file" accept="application/pdf"/>
        <div class="note">Max {MAX_UPLOAD_MB} MB</div>
      </div>
      <div>
        <label>क्वालिटी (DPI)</label>
        <select id="dpi">
          <option value="150" selected>150 (तेज़)</option>
          <option value="200">200</option>
          <option value="300">300 (शार्प)</option>
        </select>
      </div>
    </div>

    <div class="row" style="margin-top:12px">
      <button id="checkBtn" class="btn">Check Pages</button>
      <button id="freeBtn" class="btn ghost" style="display:none">Convert Free & Download</button>
      <button id="payBtn" class="btn" style="display:none">Pay ₹{FLAT_PRICE_INR} & Convert</button>
    </div>

    <div class="loader-wrap" id="loader">
      <div class="pulse"></div>
      <div class="bubbles"><span></span><span></span><span></span></div>
      <div class="note" id="loaderMsg">Processing… कृपया विंडो बंद न करें</div>
    </div>

    <div id="info" class="note" style="margin-top:10px"></div>
    <div id="ok" class="alert ok"></div>
    <div id="err" class="alert err"></div>

    <p class="note">टिप: भारी PDFs पर 150/200 DPI तेज़ रहता है।</p>
  </div>
</div>

<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<script>
let token=null, pages=0, fileMB=0, needsPayment=false, orderId=null, key_id=null, amount=0;

const pdf=document.getElementById('pdf');
const dpi=document.getElementById('dpi');
const checkBtn=document.getElementById('checkBtn');
const freeBtn=document.getElementById('freeBtn');
const payBtn=document.getElementById('payBtn');
const info=document.getElementById('info');
const ok=document.getElementById('ok');
const err=document.getElementById('err');
const loader=document.getElementById('loader');
const loaderMsg=document.getElementById('loaderMsg');

function show(el,msg){ el.textContent=msg; el.style.display='block'; }
function hide(el){ el.style.display='none'; }
function clearAlerts(){ hide(ok); hide(err); }
function on(){ loader.style.display='block'; }
function off(){ loader.style.display='none'; }

checkBtn.onclick=async()=>{
  try{
    clearAlerts(); info.textContent='';
    if(!pdf.files.length) return (show(err,'कृपया PDF चुनें'),0);

    on(); loaderMsg.textContent='पेज/साइज़ चेक कर रहे हैं…';
    const fd=new FormData(); fd.append('pdf_file', pdf.files[0]);
    const r=await fetch('/precheck',{method:'POST',body:fd});
    const d=await r.json(); off();
    if(!r.ok) return show(err,d.error||('HTTP '+r.status));

    token=d.token; pages=d.pages; fileMB=d.size; needsPayment=d.needs_payment;
    info.textContent = `Pages: ${pages}, Size: ${fileMB} MB. `
      + (needsPayment ? 'Limit cross — पेमेंट चाहिए (₹10).' : 'Free conversion available.');

    freeBtn.style.display = needsPayment ? 'none' : 'inline-flex';
    payBtn.style.display  = needsPayment ? 'inline-flex' : 'none';

    if(needsPayment){
      on(); loaderMsg.textContent='पेमेंट ऑर्डर बना रहे हैं…';
      const rr=await fetch('/create_order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})});
      const oo=await rr.json(); off();
      if(!rr.ok) return show(err,oo.error||('HTTP '+rr.status));
      orderId=oo.order_id; key_id=oo.key_id; amount=oo.amount;
    }
  }catch(e){ off(); show(err,e.message||e); }
};

freeBtn.onclick=()=>{
  if(!token) return show(err,'पहले Check Pages करें।');
  on(); loaderMsg.textContent='कन्वर्ट हो रहा है…';
  const url='/convert_free?token='+encodeURIComponent(token)+'&dpi='+encodeURIComponent(dpi.value);
  window.location=url;
  setTimeout(()=>off(),5000);
};

payBtn.onclick=()=>{
  if(!orderId||!key_id) return show(err,'Order not ready.');
  const opts={
    key:key_id, amount:amount, currency:"INR",
    name:"Mahamaya Stationery", description:"PDF→Image (Paid)",
    order_id:orderId, theme:{color:"#4f8cff"},
    handler: async function (rsp){
      try{
        on(); loaderMsg.textContent='पेमेंट verify कर रहे हैं…';
        const v=await fetch('/verify_payment',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({
            order_id:rsp.razorpay_order_id,
            payment_id:rsp.razorpay_payment_id,
            signature:rsp.razorpay_signature,
            token
          })
        });
        const d=await v.json(); if(!v.ok) throw new Error(d.error||('HTTP '+v.status));
        loaderMsg.textContent='कन्वर्ज़न शुरू…';
        const url='/convert_paid?token='+encodeURIComponent(token)+'&dpi='+encodeURIComponent(dpi.value);
        window.location=url;
        show(ok,'Payment Verified ✓ Download starting…');
        setTimeout(()=>off(),6000);
      }catch(e){ off(); show(err,e.message||e); }
    }
  };
  const rzp=new Razorpay(opts); rzp.open();
};
</script>
</body>
</html>
"""

# ---------- Helpers ----------
def count_pages(pdf_path: str) -> int:
    with fitz.open(pdf_path) as doc:
        return len(doc)

def render_pages_to_zip(pdf_path: str, dpi: int, pages: list[int], out_zip: str, fmt="jpg"):
    with fitz.open(pdf_path) as doc, zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for pno in pages:
            page = doc[pno-1]
            mat = fitz.Matrix(dpi/72, dpi/72)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            tmp_img = tempfile.NamedTemporaryFile(delete=False, suffix=f".{fmt}")
            tmp_img.close()
            pix.save(tmp_img.name)  # suffix से फॉर्मेट detect
            zf.write(tmp_img.name, f"page_{pno}.{fmt}")
            os.unlink(tmp_img.name)

def _finalize_and_send(token: str, dpi: int, free: bool):
    slot = SLOTS.get(token)
    if not slot:
        return ("invalid token", 400)
    pages = slot["pages"]
    size  = slot.get("size", 0)

    # फ्री तभी जब दोनों लिमिट पास हों
    within_free = (pages <= FREE_PAGE_LIMIT) and (size <= MAX_UPLOAD_MB * 1024 * 1024)

    if free and not within_free:
        return ("free limit exceeded", 403)
    if (not free) and not slot.get("paid"):
        return ("payment required", 402)

    pdf_path = slot["pdf_path"]
    tmpdir   = slot["tmpdir"]
    try:
        # Paid: सारे pages; Free: सिर्फ़ free limit के भीतर के pages
        page_list = list(range(1, pages+1)) if not free else list(range(1, min(pages, FREE_PAGE_LIMIT)+1))
        zip_path = os.path.join(tmpdir, "images.zip")
        render_pages_to_zip(pdf_path, dpi, page_list, zip_path, fmt="jpg")

        @after_this_request
        def cleanup(response):
            def _rm():
                try: shutil.rmtree(tmpdir, ignore_errors=True)
                except: pass
                SLOTS.pop(token, None)
            Timer(10.0, _rm).start()
            return response

        return send_file(zip_path, as_attachment=True, download_name="converted_images.zip")
    except Exception as e:
        return (f"Error: {e}", 500)

# ---------- Routes ----------
@app.route("/")
def home():
    return render_template_string(INDEX_HTML)

@app.route("/healthz")
def health():
    return "OK"

@app.route("/precheck", methods=["POST"])
def precheck():
    pdf = request.files.get("pdf_file")
    if not pdf:
        return jsonify({"error":"no file"}), 400

    # size निकालें (best-effort)
    try:
        pdf.stream.seek(0, os.SEEK_END); size = pdf.stream.tell(); pdf.stream.seek(0)
    except Exception:
        size = 0

    tmpdir = tempfile.mkdtemp(prefix="slot_")
    fname = secure_filename(pdf.filename) or "input.pdf"
    pdf_path = os.path.join(tmpdir, fname)
    pdf.save(pdf_path)

    pages = count_pages(pdf_path)
    token = uuid.uuid4().hex
    SLOTS[token] = {"pdf_path": pdf_path, "tmpdir": tmpdir, "pages": pages, "size": size, "paid": False}

    # ✅ नई पॉलिसी: pages>25 OR size>25MB ⇒ payment
    needs_payment = (pages > FREE_PAGE_LIMIT) or (size > MAX_UPLOAD_MB * 1024 * 1024)

    return jsonify({
        "token": token,
        "pages": pages,
        "size": round(size/1024/1024, 2),
        "needs_payment": needs_payment
    })

@app.route("/create_order", methods=["POST"])
def create_order():
    if rz_client is None:
        return jsonify({"error":"Razorpay not configured"}), 500
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    slot = SLOTS.get(token)
    if not slot:
        return jsonify({"error":"invalid token"}), 400

    amount_in_paise = FLAT_PRICE_INR * 100
    order = rz_client.order.create({
        "amount": amount_in_paise,
        "currency": "INR",
        "receipt": f"rcpt_{token[:10]}",
        "payment_capture": 1
    })
    slot["order_id"] = order["id"]
    slot["amount"]   = amount_in_paise
    return jsonify({"order_id": order["id"], "amount": amount_in_paise, "key_id": RAZORPAY_KEY_ID})

@app.route("/verify_payment", methods=["POST"])
def verify_payment():
    if rz_client is None:
        return jsonify({"error":"Razorpay not configured"}), 500
    data = request.get_json(silent=True) or {}
    order_id  = data.get("order_id")
    payment_id= data.get("payment_id")
    signature = data.get("signature")
    token     = data.get("token")
    slot = SLOTS.get(token)
    if not slot or slot.get("order_id") != order_id:
        return jsonify({"error":"invalid token/order"}), 400
    try:
        rz_client.utility.verify_payment_signature({
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature
        })
        slot["paid"] = True
        return jsonify({"status":"ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/convert_free")
def convert_free():
    token = request.args.get("token","")
    dpi   = int(request.args.get("dpi","150"))
    return _finalize_and_send(token, dpi, free=True)

@app.route("/convert_paid")
def convert_paid():
    token = request.args.get("token","")
    dpi   = int(request.args.get("dpi","150"))
    return _finalize_and_send(token, dpi, free=False)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
INDEX_HTML = f"""
...
function show(el,msg){{ el.textContent=msg; el.style.display='block'; }}
...
"""
