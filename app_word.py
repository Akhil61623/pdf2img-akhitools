from flask import Flask, render_template_string, request, send_file, after_this_request
from werkzeug.utils import secure_filename
import fitz  # PyMuPDF
import tempfile, os, zipfile, shutil
from threading import Timer

app = Flask(__name__)

# ---------------------- UI ----------------------
INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>PDF → JPG Converter</title>
</head>
<body>
  <h1>PDF → JPG Converter (No Poppler)</h1>
  <form method="POST" action="/convert" enctype="multipart/form-data">
    <input type="file" name="pdf_file" accept="application/pdf" required><br><br>
    <label>DPI (Quality):</label>
    <select name="dpi">
      <option value="72">72 (Fast, Low)</option>
      <option value="150" selected>150 (Normal)</option>
      <option value="300">300 (High)</option>
    </select><br><br>
    <button type="submit">Convert & Download ZIP</button>
  </form>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(INDEX_HTML)

@app.route("/convert", methods=["POST"])
def convert():
    pdf = request.files.get("pdf_file")
    if not pdf:
        return ("No file uploaded", 400)

    dpi = int(request.form.get("dpi", "150"))

    tmp = tempfile.mkdtemp(prefix="pdf2img_")
    try:
        fname = secure_filename(pdf.filename) or "input.pdf"
        pdf_path = os.path.join(tmp, fname)
        pdf.save(pdf_path)

        # ---------------- PDF to Images with PyMuPDF ----------------
        doc = fitz.open(pdf_path)
        img_paths = []
        for i, page in enumerate(doc, 1):
            mat = fitz.Matrix(dpi/72, dpi/72)  # zoom factor (default 72dpi → scaled)
            pix = page.get_pixmap(matrix=mat)
            out_path = os.path.join(tmp, f"page_{i}.jpg")
            pix.save(out_path)
            img_paths.append(out_path)

        # ---------------- Create ZIP ----------------
        zip_path = os.path.join(tmp, "converted_images.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for img in img_paths:
                zf.write(img, os.path.basename(img))

        @after_this_request
        def cleanup(response):
            Timer(5.0, shutil.rmtree, args=[tmp], kwargs={"ignore_errors": True}).start()
            return response

        return send_file(zip_path, as_attachment=True, download_name="converted_images.zip")

    except Exception as e:
        return (f"Error: {e}", 500)

@app.route("/healthz")
def health():
    return "OK: Server running ✅"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
