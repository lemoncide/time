from app import create_app

app = create_app("default")

if __name__ == "__main__":
    # threaded=True is required: each SSE connection holds an open HTTP request
    app.run(debug=True, threaded=True, host="0.0.0.0", port=5000)
