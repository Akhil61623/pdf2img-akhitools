from flask import Flask, render_template_string, request, send_file, after_this_request
from pdf2image import convert_from_path
from werkzeug.utils import secure_filename
import os, tempfile, zipfile, shutil, re
from threading import Timer

app = Flask(__name__)

# Render (Linux) पर poppler-utils PATH में होता है, इसलिए None रखें.
# लोकल Windows पर चाहें तो अपना Poppler bin path नीचे भरें:
POPPLER_BIN = None
# POPPLER_BIN = r"C:\Users\akhil\Downloads\Release-25.07.0-0\poppler-25.07.0\Library\bin"

# ---------------------- UI (HTML + CSS + JS) ----------------------
INDEX_HTML = r"""
<!doctype html>
<html lang="hi">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Mahamaya Stationery — PDF → Image Converter</title>
<style>
  :root{
    --bg:#0b1220; --fg:#e7eaf1; --muted:#93a2bd; --card:#10182b;
    --accent:#4f8cff; --accent2:#22c55e; --danger:#ef4444; --stroke:#203054;
  }
  *{box-sizing:border-box}
  body{margin:0; font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial; background:var(--bg); color:var(--fg)}
  .shell{min-height:100svh; display:grid; place-items:center; padding:24px}
  .card{width:min(900px,100%); background:linear-gradient(180deg,#0f172a 0,#0b1220 100%);
        border:1px solid var(--stroke); border-radius:20px; padding:24px; box-shadow:0 10px 40px rgba(0,0,0,.35)}
  .top{display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap}
  .brand{display:flex; align-items:center; gap:10px; font-weight:800; letter-spacing:.2px}
  .badge{font-size:12px; padding:2px 8px; border:1px solid var(--stroke); border-radius:999px; color:var(--muted)}
  h1{margin:6px 0 8px; font-size:24px}
  p.muted{color:var(--muted); margin:0 0 18px}
  .grid{display:grid; grid-template-columns:1fr 1fr; gap:14px}
  @media (max-width:720px){ .grid{grid-template-columns:1fr} }
  label{font-size:13px; color:#cdd6ea; margin-bottom:6px; display:block}
  select,input[type="text"]{
    width:100%; background:#0d162a; color:var(--fg); border:1px solid var(--stroke);
    border-radius:12px; padding:10px 12px; outline:none
  }
  .drop{border:2px dashed var(--stroke); border-radius:16px; padding:18px; background:#0e1830; text-align:center; transition:.2s}
  .drop.drag{border-color:var(--accent); background:#112042}
  .note{font-size:12px; color:var(--muted)}
  .row{display:flex; gap:10px; align-items:center; flex-wrap:wrap}
  button.btn{display:inline-flex; align-items:center; gap:8px; padding:10px 14px; border-radius:12px;
    border:1px solid var(--stroke); background:var(--accent); color:#fff; font-weight:700; cursor:pointer}
  button.ghost{background:#17233f}
  button:disabled{opacity:.6; cursor:not-allowed}
  .spinner{width:18px; height:18px; border:3px solid rgba(255,255,255,.25); border-top-color:white; border-radius:50%; animation:spin 1s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
  .alert{margin-top:10px; padding:10px 12px; border-radius:12px; font-weight:600; display:none}
  .alert.ok{background:rgba(34,197,94,.1); color:var(--accent2); border:1px solid rgba(34,197,94,.25)}
  .alert.err{background:rgba(239,68,68,.1); color:var(--danger); border:1px solid rgba(239,68,68,.25)}
  .footer{margin-top:14px; font-size:12px; color:var(--muted)}
</style>
</head>
<body>
<div class="shell">
  <div class="card">
    <div class="top">
      <div class="brand">
        <div style="width:30px;height:30px;border-radius:8px;background:linear-gradient(135deg,#4f8cff, #22c55e)"></div>
        <div>Mahamaya Stationery</div>
      </div>
      <div class="badge">PDF → JPG / PNG</div>
    </div>

    <h1>Mahamaya Stationery — तेज़ और साफ़ PDF → इमेज कन्वर्टर</h1>
    <p class="muted">अपनी PDF चुनें, क्वालिटी/फॉर्मेट सेट करें, पेज रेंज दें (यदि चाहिए) और एक क्लिक में ZIP फाइल डाउनलोड करें।</p>

    <div id="drop" class="drop" tabindex="0">
      <strong>Drag & Drop</strong> <span class="note">या क्लिक कर के PDF चुनें</span>
      <input id="file" type="file" accept="application/pdf" style="display:none" />
      <div id="chosen" class="note" style="margin-top:8px"></div>
    </div>

    <div style="height:12px"></div>

    <div class="grid">
      <div>
        <label for="dpi">क्वालिटी (DPI)</label>
        <select id="dpi">
          <option value="150">150 (तेज़, छोटा)</option>
          <option value="200">200</option>
          <option value="300">300 (शार्प, बड़ा)</option>
        </select>
      </div>
      <div>
        <label for="format">फॉर्मेट</label>
        <select id="format">
          <option value="JPEG">JPG</option>
          <option value="PNG">PNG</option>
        </select>
      </div>
      <div style="grid-column:1/-1">
        <label for="range">पेज रेंज (उदा. 1-3,5) — खाली छोड़ें = सभी</label>
        <input id="range" type="text" placeholder="1-3,5" />
      </div>
    </div>

    <div style="height:12px"></div>

    <div class="row">
      <button id="convertBtn" class="btn">
        <span id="spin" class="spinner" style="display:none"></span>
        Convert & Download
      </button>
      <button id="chooseBtn" class="btn ghost">Choose PDF</button>
      <div id="status" class="note"></div>
    </div>

    <div id="ok" class="alert ok">हो गया! डाउनलोड शुरू हो गया।</div>
    <div id="err" class="alert err">Error</div>

    <div class="footer">टिप: बहुत बड़े PDFs पर 150 DPI या पेज रेंज चुनना तेज़ रहता है।</div>
  </div>
</div>

<script>
const drop = document.getElementById('drop');
const file = document.getElementById('file');
const chooseBtn = document.getElementById('chooseBtn');
const chosen = document.getElementById('chosen');
const convertBtn = document.getElementById('convertBtn');
const spin = document.getElementById('spin');
const statusEl = document.getElementById('status');
const ok = document.getElementById('ok');
const err = document.getElementById('err');

let selected = null;
const MAX_MB = 25; // server पर भी check होगा

function showOK(msg){ ok.textContent=msg; ok.style.display='block'; err.style.display='none'; }
function showERR(msg){ err.textContent=msg; err.style.display='block'; ok.style.display='none'; }
function clearAlerts(){ ok.style.display='none'; err.style.display='none'; statusEl.textContent=''; }

drop.addEventListener('click', () => file.click());
chooseBtn.addEventListener('click', () => file.click());

['dragenter','dragover'].forEach(ev=>{
  drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('drag'); });
});
['dragleave','drop'].forEach(ev=>{
  drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('drag'); });
});
drop.addEventListener('drop', e=>{
  e.preventDefault();
  const f = e.dataTransfer.files?.[0];
  if (f) setFile(f);
});
file.addEventListener('change', ()=>{
  if (file.files.length) setFile(file.files[0]);
});

function setFile(f){
  clearAlerts();
  if (f.type !== 'application/pdf') return showERR("कृपया PDF फ़ाइल चुनें।");
  const mb = (f.size/1024/1024);
  if (mb > MAX_MB) return showERR(`फ़ाइल बहुत बड़ी है (Max ${MAX_MB} MB).`);
  selected = f;
  chosen.textContent = `चुनी गई फ़ाइल: ${f.name} · ${mb.toFixed(2)} MB`;
}

convertBtn.addEventListener('click', async ()=>{
  try{
    clearAlerts();
    if(!selected) return showERR("पहले PDF चुनें।");
    convertBtn.disabled = true; spin.style.display='inline-block'; statusEl.textContent = "Converting...";

    const fd = new FormData();
    fd.append('pdf_file', selected);
    fd.append('dpi', document.getElementById('dpi').value);
    fd.append('format', document.getElementById('format').value);
    fd.append('range', document.getElementById('range').value);

    const res = await fetch('/convert', { method:'POST', body: fd });
    if(!res.ok){
      const t = await res.text();
      throw new Error(t || ('HTTP ' + res.status));
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'converted_images.zip';
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    showOK('हो गया! डाउनलोड शुरू हो गया।');
  }catch(e){ showERR(e.message || 'Conversion failed.'); }
  finally{ convertBtn.disabled=false; spin.style.display='none'; statusEl.textContent=''; }
});
</script>
</body>
</html>
"""

# ---------------------- Helpers ----------------------
def parse_range(range_text: str, total_pages: int):
    if not range_text:
        return list(range(1, total_pages + 1))
    pages = set()
    tokens = re.split(r"\s*,\s*", range_text.strip())
    for t in tokens:
        if not t: continue
        if "-" in t:
            a, b = t.split("-", 1)
            if a.isdigit() and b.isdigit():
                start, end = int(a), int(b)
                if 1 <= start <= total_pages and start <= end:
                    for p in range(start, min(end, total_pages) + 1):
                        pages.add(p)
        elif t.isdigit():
            p = int(t)
            if 1 <= p <= total_pages: pages.add(p)
    return sorted(pages) if pages else list(range(1, total_pages + 1))

# ---------------------- Routes ----------------------
@app.route("/")
def home():
    # सुंदर UI
    return render_template_string(INDEX_HTML)

@app.route("/healthz")
def health():
    return "OK: Mahamaya Stationery server is running ✅"

@app.route("/convert", methods=["POST"])
def convert():
    pdf = request.files.get("pdf_file")
    if not pdf:
        return ("No file uploaded", 400)

    # सर्वर-साइड 25MB लिमिट (UI में भी 25MB set है)
    try:
        pdf.stream.seek(0, os.SEEK_END)
        size = pdf.stream.tell()
        pdf.stream.seek(0)
    except Exception:
        size = 0
    if size and size > 25 * 1024 * 1024:
        return ("File too large (max 25 MB).", 400)

    dpi = int(request.form.get("dpi", "150"))
    fmt = request.form.get("format", "JPEG").upper()
    rng = request.form.get("range", "").strip()

    tmp = tempfile.mkdtemp(prefix="pdf2img_")
    try:
        fname = secure_filename(pdf.filename) or "input.pdf"
        pdf_path = os.path.join(tmp, fname)
        pdf.save(pdf_path)

        kwargs = {"dpi": dpi}
        if POPPLER_BIN:
            kwargs["poppler_path"] = POPPLER_BIN

        images_all = convert_from_path(pdf_path, **kwargs)
        total = len(images_all)
        pages_to_keep = parse_range(rng, total)

        # चुने हुए पेज ही रखें
        images = [images_all[i - 1] for i in pages_to_keep]

        # ZIP बनाएं
        zip_path = os.path.join(tmp, "converted_images.zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for i, img in enumerate(images, 1):
                ext = "jpg" if fmt == "JPEG" else "png"
                out_name = f"page_{i}.{ext}"
                out_path = os.path.join(tmp, out_name)
                img.save(out_path, fmt)
                zf.write(out_path, out_name)

        @after_this_request
        def cleanup(response):
            Timer(5.0, shutil.rmtree, args=[tmp], kwargs={"ignore_errors": True}).start()
            return response

        return send_file(zip_path, as_attachment=True, download_name="converted_images.zip")

    except Exception as e:
        Timer(1.0, shutil.rmtree, args=[tmp], kwargs={"ignore_errors": True}).start()
        return (f"Error: {e}", 500)

if __name__ == "__main__":
    # लोकल टेस्ट: python app.py
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
