import os, io, re, uuid, tempfile, zipfile, shutil
from threading import Timer
from flask import Flask, render_template_string, request, send_file, after_this_request, jsonify
from werkzeug.utils import secure_filename
import fitz  # PyMuPDF
from PIL import Image
import razorpay

# ====== Config ======
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_live_RARsbcBzkpvQL6")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "0NOMVQw0d8JuiPXMb0TycrNO")
PAID_RATE_PER_PAGE_INR = 1   # उदाहरण: ₹1 प्रति पेज (26+)
FREE_PAGE_LIMIT = 25

# Razorpay client (only if keys present)
rz_client = None
if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
    rz_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

app = Flask(__name__)

# इन-मेमाेरी स्टोरेज: token -> file path, pages, paid?
SLOTS = {}  # token: {"pdf_path":..., "tmpdir":..., "pages": int, "paid": bool}

# ====== UI (Simple) ======
INDEX_HTML = """
<!doctype html>
<html lang="hi">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Mahamaya Stationery — PDF → JPG (with Paywall)</title>
<style>
  body{font-family:Segoe UI,Roboto,Arial;background:#0b1220;color:#fff;min-height:100vh;display:grid;place-items:center;margin:0}
  .card{width:min(780px,95%);background:#10182b;border:1px solid #213357;border-radius:16px;padding:20px 18px}
  h1{margin:0 0 8px;color:#4f8cff}
  .muted{color:#b6bfd4;font-size:14px;margin:0 0 16px}
  .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
  input,select,button{padding:10px 12px;border-radius:10px;border:1px solid #2a3c63;outline:none}
  input,select{background:#0d1730;color:#fff}
  button{background:#4f8cff;color:#fff;border:none;font-weight:700;cursor:pointer}
  #payWrap{display:none;margin-top:10px;padding:10px;border:1px dashed #345}
  #result, #err{margin-top:10px}
  #err{color:#ff7777;font-weight:700}
  #result{color:#22c55e;font-weight:700}
</style>
</head>
<body>
<div class="card">
  <h1>PDF → JPG (Free ≤25 pages, Paid for more)</h1>
  <p class="muted">1–25 पेज फ्री कन्वर्ज़न। 26+ पेज के लिए पेमेंट जरूरी होगा।</p>

  <div class="row">
    <input type="file" id="pdf" accept="application/pdf"/>
    <label for="dpi">DPI</label>
    <select id="dpi">
      <option value="150" selected>150</option>
      <option value="200">200</option>
      <option value="300">300</option>
    </select>
    <button id="checkBtn">Check Pages</button>
  </div>

  <div id="info" class="muted" style="margin-top:8px"></div>

  <div id="payWrap">
    <div class="muted">यह PDF {{FREE_PAGE_LIMIT}} से अधिक पेज की है। भुगतान के बाद कन्वर्ट कर पाएँगे।</div>
    <div class="row" style="margin-top:6px">
      <button id="payBtn">Pay & Convert</button>
    </div>
  </div>

  <div class="row" style="margin-top:10px">
    <button id="convertFreeBtn" style="display:none">Convert Free & Download</button>
  </div>

  <div id="result"></div>
  <div id="err"></div>
</div>

<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<script>
let token = null;
let needsPayment = false;
let orderId = null;
let amount = 0; // paisa
let key_id = null;

const pdf = document.getElementById('pdf');
const dpiEl = document.getElementById('dpi');
const info = document.getElementById('info');
const err = document.getElementById('err');
const result = document.getElementById('result');
const payWrap = document.getElementById('payWrap');
const payBtn = document.getElementById('payBtn');
const checkBtn = document.getElementById('checkBtn');
const convertFreeBtn = document.getElementById('convertFreeBtn');

function msg(e, ok=false){ err.textContent=''; result.textContent=''; (ok?result:err).textContent=e; }

checkBtn.onclick = async () => {
  try{
    msg('');
    if(!pdf.files.length) return msg("कृपया PDF चुनें।");
    const fd = new FormData();
    fd.append('pdf_file', pdf.files[0]);
    const res = await fetch('/precheck', { method:'POST', body:fd });
    const data = await res.json();
    if(!res.ok) throw new Error(data.error || ('HTTP '+res.status));
    token = data.token;
    needsPayment = data.needs_payment;
    info.textContent = `Pages: ${data.pages}. ${needsPayment ? 'Payment required for full convert.' : 'Free convert available.'}`;
    if(needsPayment){
      // Create order
      const orq = await fetch('/create_order', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ token })
      });
      const ord = await orq.json();
      if(!orq.ok) throw new Error(ord.error || ('HTTP '+orq.status));
      orderId = ord.order_id;
      amount = ord.amount;
      key_id = ord.key_id;
      payWrap.style.display = 'block';
      convertFreeBtn.style.display = 'none';
    }else{
      payWrap.style.display = 'none';
      convertFreeBtn.style.display = 'inline-block';
    }
  }catch(e){ msg(e.message || e, false); }
};

payBtn.onclick = async () => {
  if(!orderId || !key_id) return msg("Order not ready.");
  const options = {
    key: key_id,
    amount: amount,
    currency: "INR",
    name: "Mahamaya Stationery",
    description: "PDF > JPG (26+ pages)",
    order_id: orderId,
    handler: async function (response) {
      try{
        const vr = await fetch('/verify_payment', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({
            order_id: response.razorpay_order_id,
            payment_id: response.razorpay_payment_id,
            signature: response.razorpay_signature,
            token
          })
        });
        const data = await vr.json();
        if(!vr.ok) throw new Error(data.error || ('HTTP '+vr.status));
        // Payment verified → trigger download
        const url = '/convert_paid?token=' + encodeURIComponent(token) + '&dpi=' + encodeURIComponent(dpiEl.value);
        window.location = url;
        msg('Payment verified. Download starting…', true);
      }catch(e){ msg(e.message || e, false); }
    },
    theme: { color: "#4f8cff" }
  };
  const rzp = new Razorpay(options);
  rzp.open();
};

convertFreeBtn.onclick = () => {
  if(!token) return msg("Token missing. पहले Check Pages करें।");
  const url = '/convert_free?token=' + encodeURIComponent(token) + '&dpi=' + encodeURIComponent(dpiEl.value);
  window.location = url;
};
</script>
</body>
</html>
""".replace("{{FREE_PAGE_LIMIT}}", str(FREE_PAGE_LIMIT))

# ====== Helpers ======
def count_pages(pdf_path: str) -> int:
    with fitz.open(pdf_path) as doc:
        return len(doc)

def render_pages_to_zip(pdf_path: str, dpi: int, pages: list[int], out_zip: str):
    with fitz.open(pdf_path) as doc, zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for pno in pages:
            page = doc[pno-1]
            mat = fitz.Matrix(dpi/72, dpi/72)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            # save to temp and zip
            tmp_img = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            tmp_img.close()
            pix.save(tmp_img.name)
            zf.write(tmp_img.name, f"page_{pno}.jpg")
            os.unlink(tmp_img.name)

# ====== Routes ======
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
    tmpdir = tempfile.mkdtemp(prefix="slot_")
    fname = secure_filename(pdf.filename) or "input.pdf"
    pdf_path = os.path.join(tmpdir, fname)
    pdf.save(pdf_path)
    pages = count_pages(pdf_path)
    token = uuid.uuid4().hex
    SLOTS[token] = {"pdf_path": pdf_path, "tmpdir": tmpdir, "pages": pages, "paid": False}
    needs_payment = pages > FREE_PAGE_LIMIT
    return jsonify({"token": token, "pages": pages, "needs_payment": needs_payment})

@app.route("/create_order", methods=["POST"])
def create_order():
    if rz_client is None:
        return jsonify({"error":"Razorpay not configured"}), 500
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    slot = SLOTS.get(token)
    if not slot:
        return jsonify({"error":"invalid token"}), 400
    pages = slot["pages"]
    extra_pages = max(0, pages - FREE_PAGE_LIMIT)
    amount_in_paisa = max(200, extra_pages * PAID_RATE_PER_PAGE_INR * 100)  # min ₹2.00 example
    order = rz_client.order.create({
        "amount": amount_in_paisa,
        "currency": "INR",
        "receipt": f"rcpt_{token[:10]}",
        "payment_capture": 1
    })
    slot["order_id"] = order["id"]
    slot["amount"] = amount_in_paisa
    return jsonify({"order_id": order["id"], "amount": amount_in_paisa, "key_id": RAZORPAY_KEY_ID})

@app.route("/verify_payment", methods=["POST"])
def verify_payment():
    if rz_client is None:
        return jsonify({"error":"Razorpay not configured"}), 500
    data = request.get_json(silent=True) or {}
    order_id = data.get("order_id")
    payment_id = data.get("payment_id")
    signature = data.get("signature")
    token = data.get("token")
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

def _finalize_and_send(token: str, dpi: int, free: bool):
    slot = SLOTS.get(token)
    if not slot: return ("invalid token", 400)
    pages = slot["pages"]
    pdf_path = slot["pdf_path"]
    tmpdir = slot["tmpdir"]
    try:
        if free and pages > FREE_PAGE_LIMIT:
            return ("free limit exceeded", 403)
        if (not free) and not slot.get("paid"):
            return ("payment required", 402)

        page_list = list(range(1, pages+1)) if not free else list(range(1, min(pages, FREE_PAGE_LIMIT)+1))
        zip_path = os.path.join(tmpdir, "images.zip")
        render_pages_to_zip(pdf_path, dpi, page_list, zip_path)

        @after_this_request
        def cleanup(response):
            # clean slot a bit later
            def _rm():
                try: shutil.rmtree(tmpdir, ignore_errors=True)
                except: pass
                SLOTS.pop(token, None)
            Timer(10.0, _rm).start()
            return response

        return send_file(zip_path, as_attachment=True, download_name="converted_images.zip")
    except Exception as e:
        return (f"Error: {e}", 500)

@app.route("/convert_free")
def convert_free():
    token = request.args.get("token","")
    dpi = int(request.args.get("dpi","150"))
    return _finalize_and_send(token, dpi, free=True)

@app.route("/convert_paid")
def convert_paid():
    token = request.args.get("token","")
    dpi = int(request.args.get("dpi","150"))
    return _finalize_and_send(token, dpi, free=False)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
