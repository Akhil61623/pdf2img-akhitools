from flask import Flask
app = Flask(__name__)

@app.route("/")
def home():
    return "OK: Akhi server is running ✅"

if __name__ == "__main__":
    print("Starting minimal server…")
    app.run(
        debug=False,
        host="0.0.0.0",  # सभी इंटरफेस पर bind
        port=7000,       # नया साफ पोर्ट
        use_reloader=False,
        threaded=False
    )
