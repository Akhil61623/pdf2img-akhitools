from flask import Flask, render_template_string, request, send_file, after_this_request
import fitz, tempfile, os, zipfile, shutil
from threading import Timer

app = Flask(__name__)

FREE_PAGE_LIMIT = 25
FREE_SIZE_MB = 25

# ---------------------- UI ----------------------
INDEX_HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Mahamaya Stationery — PDF → Image Converter</title>
<style>
  body{margin:0; font-family:sans-serif; background:#0b1220; color:#eee; display:flex; justify-content:center; align-items:center; height:100vh;}
  .card{background:#10182b; padding:24px; border-radius:16px; width:100%; max-width:500px; box-shadow:0 10px 30px rgba(0,0,0,.4);}
  h1{margin:0 0 10px; font-size:22px;}
  p{font-size:14px; color:#bbb;}
  .drop{border:2px dashed #334; border-radius:12px; padding:20px; text-align:center; margin:15px 0; cursor:pointer;}
  .drop.drag{border-color:#4f8cff; background:#162544;}
  button{background:#4f8cff; color:#fff; border:none; padding:12px 18px; border-radius:10px; font-weight:600; cursor:pointer;}
  button:disabled{opacity:.6}
  .note{margin-top:8px; font-size:13px; color:#aaa;}
  .loader{border:4px solid rgba(255,255,255,.2); border-top:4px solid #fff; border-radius:50%; width:26px; height:26px; animation:spin 1s linear infinite; margin:10px auto; display:none;}
  @keyframes spin{to{transform:rotate(360deg)}}
  .alert{margin-top:10px; padding:10px; border-radius:10px; font-weight:600; display:none;}
  .alert.ok{background:rgba(34,197,94,.1); color:#22c55e;}
  .alert.err{background:rgba(239,68,68,.1); color:#ef4444;}
</style>
</head>
<body>
  <div class="card">
    <h1>PDF → JPG Converter</h1>
    <p>Free up to {{ FREE_PAGE_LIMIT }} pages or {{ FREE_SIZE_MB }} MB.<br>Above that, ₹10 charge.</p>
    <div id="drop" class="drop">Drag & Drop PDF<br><small>or click to choose</small>
      <input type="file" id="file" accept="application/pdf" style="display:none">
    </div>
    <div id="chosen" class="note"></div>
    <button id="convertBtn">Convert & Download</button>
    <div class="loader" id="loader"></div>
    <div id="ok" class="alert ok">Done! Download started.</div>
    <div id="err" class="alert err"></div>
  </div>

<script>
const drop=document.getElementById('drop');
const file=document.getElementById('file');
const chosen=document.getElementById('chosen');
const convertBtn=document.getElementById('convertBtn');
const loader=document.getElementById('loader');
const ok=document.getElementById('ok');
const err=document.getElementById('err');
let selected=null;

drop.addEventListener('click',()=>file.click());
drop.addEventListener('dragover',e=>{e.preventDefault(); drop.classList.add('drag');});
drop.addEventListener('dragleave',()=>drop.classList.remove('drag'));
drop.addEventListener('drop',e=>{
  e.preventDefault(); drop.classList.remove('drag');
  if(e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
});
file.addEventListener('change',()=>{if(file.files.length) setFile(file.files[0]);});

function setFile(f){
  if(f.type!=='application/pdf'){showErr("Please upload a PDF");return;}
  selected=f; chosen.textContent="Selected: "+f.name+" ("+(f.size/1024/1024).toFixed(2)+" MB)";
}
function showErr(msg){err.textContent=msg; err.style.display='block'; ok.style.display='none';}
function showOk(msg){ok.textContent=msg; ok.style.display='block'; err.style.display='none';}

convertBtn.addEventListener('click',async()=>{
  if(!selected){showErr("Choose a PDF first");return;}
  convertBtn.disabled=true; loader.style.display='block'; err.style.display='none'; ok.style.display='none';
  try{
    const fd=new FormData(); fd.append('pdf_file',selected);
    const res=await fetch('/convert',{method:'POST',body:fd});
    if(!res.ok){throw new Error(await res.text());}
    const blob=await res.blob();
    const url=URL.createObjectURL(blob);
    const a=document.createElement('a'); a.href=url; a.download="converted_images.zip"; a.click(); URL.revokeObjectURL(url);
    showOk("Done! Download started.");
  }catch(e){showErr(e.message);}
  finally{convertBtn.disabled=false; loader.style.display='none';}
});
</script>
</body>
</html>
"""

# ---------------------- Routes ----------------------
@app.route("/")
def home():
    return render_template_string(INDEX_HTML,
        FREE_PAGE_LIMIT=FREE_PAGE_LIMIT,
        FREE_SIZE_MB=FREE_SIZE_MB
    )

@app.route("/convert", methods=["POST"])
def convert():
    pdf = request.files.get("pdf_file")
    if not pdf: return "No file uploaded", 400
    tmp = tempfile.mkdtemp()
    pdf_path = os.path.join(tmp, pdf.filename)
    pdf.save(pdf_path)

    # size check
    if os.path.getsize(pdf_path) > FREE_SIZE_MB*1024*1024:
        return f"File too large (Free limit {FREE_SIZE_MB}MB)", 402

    doc = fitz.open(pdf_path)
    if doc.page_count > FREE_PAGE_LIMIT:
        return f"Too many pages (Free limit {FREE_PAGE_LIMIT})", 402

    zip_path=os.path.join(tmp,"images.zip")
    with zipfile.ZipFile(zip_path,"w") as zf:
        for i,page in enumerate(doc,start=1):
            pix=page.get_pixmap(dpi=150)
            img_path=os.path.join(tmp,f"page_{i}.jpg")
            pix.save(img_path); zf.write(img_path,f"page_{i}.jpg")

    @after_this_request
    def cleanup(resp):
        Timer(5.0, shutil.rmtree, args=[tmp], kwargs={"ignore_errors": True}).start()
        return resp

    return send_file(zip_path, as_attachment=True, download_name="converted_images.zip")

if __name__=="__main__":
    app.run(debug=True,host="0.0.0.0")
