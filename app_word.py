from flask import Flask, render_template_string, request, send_file, after_this_request
from werkzeug.utils import secure_filename
from pdf2docx import Converter
import os, tempfile, shutil
from threading import Timer

app = Flask(__name__)

# ---------------------- UI ----------------------
INDEX_HTML = r"""
<!doctype html>
<html lang="hi">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Mahamaya Stationery — PDF → Word Converter</title>
<style>
  body{font-family:Segoe UI,Roboto,Arial; margin:0; background:#0b1220; color:#fff; display:flex; justify-content:center; align-items:center; height:100vh}
  .card{background:#10182b; padding:24px; border-radius:16px; width:400px; text-align:center; box-shadow:0 10px 40px rgba(0,0,0,.35)}
  h1{color:#4f8cff; margin-bottom:10px}
  .muted{color:#aaa; font-size:14px; margin-bottom:20px}
  input[type=file]{margin:10px 0; padding:8px}
  button{background:#4f8cff; color:#fff; border:none; padding:10px 16px; border-radius:8px; cursor:pointer; font-weight:600}
  button:hover{background:#357ae8}
  .msg{margin-top:10px; font-size:14px}
</style>
</head>
<body>
  <div class="card">
    <h1>PDF → Word Converter</h1>
    <p class="muted">अपनी PDF अपलोड करें और Word (DOCX) डाउनलोड करें।</p>
    <form method="POST" action="/convert" enctype="multipart/form-data">
      <input type="file" name="pdf_file" accept="application/pdf" required>
      <br>
      <button type="submit">Convert & Download</button>
    </form>
  </div>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(INDEX_HTML)

@app.route("/healthz")
def health():
    return "OK: PDF→Word server running ✅"

@app.route("/convert", methods=["POST"])
def convert():
    pdf = request.files.get("pdf_file")
    if not pdf:
        return ("No file uploaded", 400)

    tmp = tempfile.mkdtemp(prefix="pdf2word_")
    try:
        fname = secure_filename(pdf.filename) or "input.pdf"
        pdf_path = os.path.join(tmp, fname)
        pdf.save(pdf_path)

        # Output DOCX
        docx_path = os.path.join(tmp, "output.docx")

        # Convert PDF → Word
        cv = Converter(pdf_path)
        cv.convert(docx_path, start=0, end=None)
        cv.close()

        @after_this_request
        def cleanup(response):
            Timer(5.0, shutil.rmtree, args=[tmp], kwargs={"ignore_errors": True}).start()
            return response

        return send_file(docx_path, as_attachment=True, download_name="converted.docx")

    except Exception as e:
        Timer(1.0, shutil.rmtree, args=[tmp], kwargs={"ignore_errors": True}).start()
        return (f"Error: {e}", 500)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
pdf2docx
