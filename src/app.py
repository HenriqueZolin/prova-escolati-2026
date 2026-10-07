import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, request

PREFIXO = "C"
RAZAO_PREFERENCIAL = 2
FUSO = timezone(timedelta(hours=-3))
DATA_DIR = "/data"
TIPOS_VALIDOS = ("normal", "preferencial")

SCHEMA = """
CREATE TABLE IF NOT EXISTS senhas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL,
    dia TEXT NOT NULL,
    tipo TEXT NOT NULL,
    emissao TEXT NOT NULL,
    status TEXT NOT NULL,
    chamada_em TEXT,
    ordem_painel INTEGER,
    UNIQUE (dia, codigo)
);
CREATE TABLE IF NOT EXISTS estado (
    chave TEXT PRIMARY KEY,
    valor INTEGER NOT NULL
);
"""

app = Flask(__name__)
LOCK = threading.Lock()
conn = None


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok"}), 200

def criar_schema(c):
    c.executescript(SCHEMA)
    c.execute("INSERT OR IGNORE INTO estado (chave, valor) VALUES ('prefs_seguidas', 0)")
    c.commit()


def init_db():
    global conn
    caminho = os.path.join(DATA_DIR, "fila.db")
    try:
        if not (os.path.isdir(DATA_DIR) and os.access(DATA_DIR, os.W_OK)):
            raise OSError(f"{DATA_DIR} inexistente ou sem permissao de escrita")
        c = sqlite3.connect(caminho, check_same_thread=False)
        criar_schema(c)
        print(f"persistencia: {caminho}")
    except (OSError, sqlite3.Error) as e:
        print(f"persistencia: memoria ({e})")
        c = sqlite3.connect(":memory:", check_same_thread=False)
        criar_schema(c)
    c.row_factory = sqlite3.Row
    conn = c


def agora():
    return datetime.now(FUSO).replace(microsecond=0)


def senha_json(row):
    dados = {
        "codigo": row["codigo"],
        "tipo": row["tipo"],
        "emissao": row["emissao"],
        "status": row["status"],
    }
    if row["chamada_em"] is not None:
        dados["chamada_em"] = row["chamada_em"]
    return dados


def erro(codigo_erro, http_status):
    return jsonify({"erro": codigo_erro}), http_status


@app.post("/senhas")
def emitir_senha():
    corpo = request.get_json(force=True, silent=True)
    tipo = corpo.get("tipo") if isinstance(corpo, dict) else None
    if tipo not in TIPOS_VALIDOS:
        return erro("tipo_invalido", 422)

    with LOCK, conn:
        momento = agora()
        dia = momento.date().isoformat()
        total_hoje = conn.execute(
            "SELECT COUNT(*) FROM senhas WHERE dia = ?", (dia,)
        ).fetchone()[0]
        codigo = f"{PREFIXO}{total_hoje + 1:03d}"
        conn.execute(
            "INSERT INTO senhas (codigo, dia, tipo, emissao, status) "
            "VALUES (?, ?, ?, ?, 'aguardando')",
            (codigo, dia, tipo, momento.isoformat()),
        )
        row = conn.execute(
            "SELECT * FROM senhas WHERE dia = ? AND codigo = ?", (dia, codigo)
        ).fetchone()

    return jsonify(senha_json(row)), 201


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), threaded=True)