from flask import Flask, render_template_string, request, send_file, after_this_request
import fitz, tempfile, os, zipfile, shutil
from threading import Timer

app = Flask(__name__)

FREE_PAGE_LIMIT = 25
FREE_SIZE_MB = 25

# ---- Raw HTML string (safe for JS/CSS { }) ----
INDEX_HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Mahamaya Stationery — PDF → Image Converter</title>
</head>
<body>
  <h1>PDF → JPG Converter</h1>
  <p>Free up to {{ FREE_PAGE_LIMIT }} pages or {{ FREE_SIZE_MB }} MB. Above that, ₹10 charge.</p>
  <form method="post" action="/convert" enctype="multipart/form-data">
    <input type="file" name="pdf_file" accept="application/pdf" />
    <button type="submit">Convert</button>
  </form>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(INDEX_HTML,
        FREE_PAGE_LIMIT=FREE_PAGE_LIMIT,
        FREE_SIZE_MB=FREE_SIZE_MB
    )

@app.route("/convert", methods=["POST"])
def convert():
    pdf = request.files.get("pdf_file")
    if not pdf:
        return "No file", 400
    
    tmp = tempfile.mkdtemp()
    pdf_path = os.path.join(tmp, pdf.filename)
    pdf.save(pdf_path)

    # check size
    if os.path.getsize(pdf_path) > FREE_SIZE_MB * 1024 * 1024:
        return f"File too big! Free limit is {FREE_SIZE_MB} MB.", 402

    doc = fitz.open(pdf_path)
    if doc.page_count > FREE_PAGE_LIMIT:
        return f"Too many pages! Free limit is {FREE_PAGE_LIMIT}.", 402

    zip_path = os.path.join(tmp, "images.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(dpi=150)
            img_path = os.path.join(tmp, f"page_{i}.jpg")
            pix.save(img_path)
            zf.write(img_path, f"page_{i}.jpg")

    @after_this_request
    def cleanup(resp):
        Timer(5.0, shutil.rmtree, args=[tmp], kwargs={"ignore_errors": True}).start()
        return resp

    return send_file(zip_path, as_attachment=True, download_name="converted_images.zip")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
