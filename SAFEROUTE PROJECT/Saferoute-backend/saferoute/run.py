"""
SafeRoute Entry Point
======================
Run the Flask development server with:

    python run.py

For production, use a WSGI server such as gunicorn instead:

    gunicorn "run:app"
"""

import os
import socket

from app import create_app

app = create_app()


def find_available_port(preferred_port: int = 5001) -> int:
    """Finds an available TCP port starting from preferred_port."""
    candidates = [preferred_port, 5002, 5050, 8000, 8080]
    for p in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return preferred_port


if __name__ == "__main__":
    env_port = os.environ.get("PORT")
    if env_port:
        port = int(env_port)
    else:
        port = find_available_port(5001)

    print("\n" + "=" * 56)
    print(f"  SafeRoute Server running at: http://127.0.0.1:{port}")
    print("=" * 56 + "\n")

    # debug is controlled by app.config["DEBUG"], set via FLASK_ENV
    app.run(host="0.0.0.0", port=port, debug=app.config.get("DEBUG", False))

