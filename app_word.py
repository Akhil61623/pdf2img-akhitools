from flask import Flask, render_template_string, request, send_file, after_this_request, jsonify
from werkzeug.utils import secure_filename
import os, io, tempfile, zipfile, shutil, hmac, hashlib
from threading import Timer
from PIL import Image
import fitz  # PyMuPDF (only for optional password encryption)
import razorpay

# ------------ Config ------------
FREE_MAX_IMAGES = 25
FREE_MAX_MB = 25
PAID_AMOUNT_INR = 10
CURRENCY = "INR"

RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")

rz_client = None
if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
    rz_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

app = Flask(__name__)

# ------------ UI ------------
INDEX_HTML = r"""
<!doctype html>
<html lang="hi">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Mahamaya Stationery — JPG/PNG → PDF Converter</title>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<style>
  :root{--bg:#0b1220;--fg:#e7eaf1;--muted:#93a2bd;--card:#0f172a;--stroke:#213154;--accent:#4f8cff;--good:#22c55e;--bad:#ef4444}
  *{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;background:var(--bg);color:var(--fg)}
  .shell{min-height:100svh;display:grid;place-items:center;padding:22px}
  .card{width:min(900px,100%);background:linear-gradient(180deg,#0f172a,#0b1220);border:1px solid var(--stroke);border-radius:18px;padding:22px;box-shadow:0 14px 40px rgba(0,0,0,.35)}
  .top{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
  .brand{display:flex;align-items:center;gap:10px;font-weight:900}
  .badge{font-size:12px;padding:2px 8px;border:1px solid var(--stroke);border-radius:999px;color:var(--muted)}
  h1{margin:8px 0 6px;font-size:22px}
  p.muted{margin:0 0 12px;color:var(--muted)}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  @media (max-width:720px){.grid{grid-template-columns:1fr}}
  label{font-size:13px;margin-bottom:6px;display:block;color:#cfe1ff}
  input,select{width:100%;background:#0e1832;color:var(--fg);border:1px solid var(--stroke);border-radius:10px;padding:10px 12px;outline:none}
  .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  button{display:inline-flex;align-items:center;gap:8px;padding:10px 14px;border-radius:12px;border:1px solid var(--stroke);background:var(--accent);color:#fff;font-weight:700;cursor:pointer}
  button.ghost{background:#18233f}
  button:disabled{opacity:.6;cursor:not-allowed}
  .drop{border:2px dashed var(--stroke);border-radius:14px;padding:16px;background:#0d162d;text-align:center}
  .note{font-size:12px;color:var(--muted)}
  .alert{margin-top:10px;padding:10px 12px;border-radius:12px;font-weight:600;display:none}
  .ok{background:rgba(34,197,94,.1);color:var(--good);border:1px solid rgba(34,197,94,.25)}
  .err{background:rgba(239,68,68,.1);color:var(--bad);border:1px solid rgba(239,68,68,.25)}
  .pill{display:inline-flex;gap:6px;align-items:center;padding:4px 10px;border-radius:999px;border:1px solid var(--stroke);background:#0f1b38;color:#9fb4ff;font-size:12px}
  .loader{display:none;margin:10px 0 0;height:24px;position:relative}
  .loader>div{width:8px;height:8px;background:#9fb4ff;border-radius:50%;position:absolute;animation:bounce 1.2s infinite ease-in-out}
  .loader .d1{left:0;animation-delay:-.24s}
  .loader .d2{left:12px;animation-delay:-.12s}
  .loader .d3{left:24px;animation-delay:0s}
  @keyframes bounce{0%,80%,100%{transform:scale(0)}40%{transform:scale(1.0)}}
</style>
</head>
<body>
<div class="shell">
  <div class="card">
    <div class="top">
      <div class="brand">
        <div style="width:30px;height:30px;border-radius:8px;background:linear-gradient(135deg,#4f8cff,#22c55e)"></div>
        <div>Mahamaya Stationery</div>
      </div>
      <div class="badge">JPG/PNG → PDF · Free up to 25 images/25MB</div>
    </div>

    <h1>तेज़ और साफ़ इमेज → PDF कन्वर्टर</h1>
    <p class="muted">कुल 25 इमेज या 25MB तक फ्री। उसके ऊपर सिर्फ ₹10। चाहें तो आउटपुट PDF पर पासवर्ड भी लगाइए।</p>

    <div class="drop">
      <strong>इमेज चुनें (multiple)</strong> <span class="note">JPG/PNG</span><br/>
      <input id="files" type="file" accept="image/*" multiple />
      <div id="chosen" class="note" style="margin-top:8px"></div>
    </div>

    <div style="height:12px"></div>

    <div class="grid">
      <div>
        <label for="pdfpw">आउटपुट PDF पासवर्ड (optional)</label>
        <input id="pdfpw" type="password" placeholder="खाली छोड़ें तो बिना पासवर्ड"/>
      </div>
      <div>
        <label for="pagesize">पेज साइज़</label>
        <select id="pagesize">
          <option value="A4">A4 (auto fit)</option>
          <option value="LETTER">US Letter (auto fit)</option>
          <option value="AUTO">Auto (image size)</option>
        </select>
      </div>
    </div>

    <div style="height:12px"></div>

    <div class="row">
      <button id="checkBtn">Check & Convert</button>
      <button id="payBtn" class="ghost" style="display:none">Pay ₹10 & Convert</button>
      <span id="status" class="pill">Ready</span>
    </div>
    <div class="loader" id="loader"><div class="d1"></div><div class="d2"></div><div class="d3"></div></div>

    <div id="ok" class="alert ok">Download started.</div>
    <div id="err" class="alert err">Error</div>

    <p class="muted" style="margin-top:10px">टिप: बहुत बड़ी इमेज को पहले थोड़ा compress कर लें तो PDF छोटी बनेगी।</p>
  </div>
</div>

<script>
const files = document.getElementById('files');
const chosen = document.getElementById('chosen');
const checkBtn = document.getElementById('checkBtn');
const payBtn = document.getElementById('payBtn');
const statusEl = document.getElementById('status');
const ok = document.getElementById('ok');
const err = document.getElementById('err');
const loader = document.getElementById('loader');

let selected = [];
let pendingOrder = null;

function show(el,msg){ el.textContent=msg; el.style.display='block'; }
function hide(el){ el.style.display='none'; }
function busy(on){
  if(on){ loader.style.display='block'; statusEl.textContent='Working... please wait'; }
  else { loader.style.display='none'; statusEl.textContent='Ready'; }
}

files.addEventListener('change', ()=>{
  selected = Array.from(files.files || []);
  const totalMB = selected.reduce((s,f)=>s+f.size,0)/1024/1024;
  chosen.textContent = `${selected.length} files · ${totalMB.toFixed(2)} MB`;
});

async function precheck(){
  if(!selected.length){ show(err, "कृपया इमेज चुनें."); hide(ok); return; }
  hide(err); hide(ok); busy(true); payBtn.style.display='none'; pendingOrder=null;

  const fd = new FormData();
  selected.forEach(f => fd.append('images', f));

  const res = await fetch('/precheck', {method:'POST', body:fd});
  const data = await res.json().catch(()=>({error:"Server error"}));
  busy(false);

  if(!res.ok){
    show(err, data.error || 'Precheck failed.');
    return;
  }

  const { count, size_mb, chargeable, amount, order_id, key_id } = data;
  if(chargeable){
    show(err, `Free limit exceeded (images=${count}, size=${size_mb}MB). Please pay ₹${(amount/100).toFixed(0)}.`);
    payBtn.style.display='inline-flex';
    pendingOrder = {order_id, amount, key_id};
  }else{
    hide(err);
    await doConvert(); // free go
  }
}

async function doConvert(extra={}){
  hide(err); hide(ok); busy(true);
  const fd = new FormData();
  selected.forEach(f => fd.append('images', f));
  fd.append('pdf_password', document.getElementById('pdfpw').value || '');
  fd.append('page_size', document.getElementById('pagesize').value || 'A4');
  if(extra.razorpay_payment_id) fd.append('razorpay_payment_id', extra.razorpay_payment_id);
  if(extra.razorpay_order_id) fd.append('razorpay_order_id', extra.razorpay_order_id);
  if(extra.razorpay_signature) fd.append('razorpay_signature', extra.razorpay_signature);

  const res = await fetch('/convert', {method:'POST', body:fd});
  busy(false);

  if(!res.ok){
    const t = await res.text();
    show(err, t || 'Conversion failed.');
    return;
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'images_to_pdf.pdf';
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
  show(ok, 'Download started.');
}

checkBtn.addEventListener('click', precheck);

payBtn.addEventListener('click', async ()=>{
  if(!pendingOrder){ show(err, "Order not ready. कृपया फिर से Try करें."); return; }
  const {order_id, amount, key_id} = pendingOrder;

  const r = new Razorpay({
    key: key_id,
    amount: amount,
    currency: 'INR',
    name: 'Mahamaya Stationery',
    description: 'Images to PDF',
    order_id,
    theme: { color: '#4f8cff' },
    handler: async function (resp) {
      await doConvert(resp);
    }
  });
  r.on('payment.failed', function (response){
    show(err, response.error && response.error.description ? response.error.description : "Payment failed.");
  });
  r.open();
});
</script>
</body>
</html>
"""

# ------------ Helpers ------------
def total_size_mb(file_list):
    total = 0
    for fs in file_list:
        pos = fs.stream.tell()
        fs.stream.seek(0, os.SEEK_END)
        total += fs.stream.tell()
        fs.stream.seek(pos)
    return round(total / (1024*1024), 2)

def verify_razorpay_signature(order_id: str, payment_id: str, signature: str) -> bool:
    if not (RAZORPAY_KEY_SECRET and order_id and payment_id and signature):
        return False
    msg = f"{order_id}|{payment_id}".encode("utf-8")
    hm = hmac.new(RAZORPAY_KEY_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(hm, signature)

def page_rect_for(name):
    name = (name or "").upper()
    if name == "A4":
        # 595 x 842 pt (portrait)
        return fitz.Rect(0, 0, 595, 842)
    if name == "LETTER":
        # 612 x 792 pt
        return fitz.Rect(0, 0, 612, 792)
    return None  # AUTO

# ------------ Routes ------------
@app.route("/")
def home():
    return render_template_string(INDEX_HTML)

@app.route("/healthz")
def health():
    return "OK", 200

@app.route("/precheck", methods=["POST"])
def precheck():
    images = request.files.getlist("images")
    if not images:
        return jsonify(error="No images uploaded"), 400

    cnt = len(images)
    size_mb = total_size_mb(images)
    chargeable = (cnt > FREE_MAX_IMAGES) or (size_mb > FREE_MAX_MB)

    payload = {
        "count": cnt,
        "size_mb": size_mb,
        "chargeable": chargeable,
        "amount": 0,
        "order_id": None,
        "key_id": RAZORPAY_KEY_ID if RAZORPAY_KEY_ID else None
    }

    if chargeable:
        if not rz_client:
            return jsonify(error="Payment required but Razorpay not configured"), 500
        amount_paise = PAID_AMOUNT_INR * 100
        order = rz_client.order.create({
            "amount": amount_paise,
            "currency": CURRENCY,
            "payment_capture": 1
        })
        payload.update({
            "amount": amount_paise,
            "order_id": order.get("id"),
            "key_id": RAZORPAY_KEY_ID
        })

    return jsonify(payload), 200

@app.route("/convert", methods=["POST"])
def convert_route():
    images = request.files.getlist("images")
    if not images:
        return "No images uploaded", 400

    pdf_password = request.form.get("pdf_password", "").strip()
    page_size = request.form.get("page_size", "A4").upper()

    r_order_id = request.form.get("razorpay_order_id", "")
    r_payment_id = request.form.get("razorpay_payment_id", "")
    r_signature = request.form.get("razorpay_signature", "")

    # free vs paid check again (server-side)
    cnt = len(images)
    size_mb = total_size_mb(images)
    needs_payment = (cnt > FREE_MAX_IMAGES) or (size_mb > FREE_MAX_MB)
    if needs_payment:
        if not (r_order_id and r_payment_id and r_signature):
            return "Payment required. Please complete payment.", 402
        if not verify_razorpay_signature(r_order_id, r_payment_id, r_signature):
            return "Payment signature invalid.", 403

    tmp = tempfile.mkdtemp(prefix="img2pdf_")
    try:
        # Load PIL images in memory (as RGB)
        pil_list = []
        for fs in images:
            fs.stream.seek(0)
            im = Image.open(fs.stream)
            if im.mode in ("RGBA", "P"):  # remove alpha
                im = im.convert("RGB")
            else:
                im = im.convert("RGB")

            # Optional: fit to selected page size (if A4/LETTER). If AUTO, keep original.
            rect = page_rect_for(page_size)
            if rect:
                # convert page points to pixels at 72 dpi
                target_px = (int(rect.width), int(rect.height))
                im = im.copy()
                im.thumbnail(target_px, Image.LANCZOS)  # keep aspect ratio
                # paste centered on white canvas
                canvas = Image.new("RGB", target_px, (255,255,255))
                x = (target_px[0] - im.width)//2
                y = (target_px[1] - im.height)//2
                canvas.paste(im, (x,y))
                im = canvas

            pil_list.append(im)

        # Save PIL → single PDF in memory
        pdf_bytes = io.BytesIO()
        if len(pil_list) == 1:
            pil_list[0].save(pdf_bytes, format="PDF", save_all=False)
        else:
            first, rest = pil_list[0], pil_list[1:]
            first.save(pdf_bytes, format="PDF", save_all=True, append_images=rest)
        pdf_bytes.seek(0)

        # Optional password encryption via PyMuPDF
        out_stream = io.BytesIO()
        if pdf_password:
            src = fitz.open(stream=pdf_bytes.getvalue(), filetype="pdf")
            src.save(out_stream,
                     encryption=fitz.PDF_ENCRYPT_AES_256,
                     owner_pw=pdf_password,
                     user_pw=pdf_password,
                     permissions=fitz.PDF_PERM_ACCESSIBILITY
                                 | fitz.PDF_PERM_PRINT
                                 | fitz.PDF_PERM_COPY
                                 | fitz.PDF_PERM_ANNOTATE)
            src.close()
        else:
            out_stream = pdf_bytes

        out_stream.seek(0)

        @after_this_request
        def cleanup(response):
            Timer(3.0, shutil.rmtree, args=[tmp], kwargs={"ignore_errors": True}).start()
            return response

        return send_file(out_stream, as_attachment=True, download_name="images_to_pdf.pdf", mimetype="application/pdf")

    except Exception as e:
        Timer(1.0, shutil.rmtree, args=[tmp], kwargs={"ignore_errors": True}).start()
        return (f"Error: {e}", 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)

