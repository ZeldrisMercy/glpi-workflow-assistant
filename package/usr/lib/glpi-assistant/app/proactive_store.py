"""Durable per-draft execution journal. Reservations precede remote writes."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from store import DATA_DIR

@contextmanager
def database(path=None):
    path=Path(path or DATA_DIR/'proactive.db')
    path.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(path,timeout=10)
    con.execute('PRAGMA synchronous=FULL')
    con.execute('CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, scope TEXT NOT NULL, ref TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(scope,ref))')
    con.execute('CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
    try:
        yield con
        con.commit()
    finally: con.close()
    path.chmod(0o600)

def save_operation(plan:dict,path=None)->dict:
    with database(path) as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT data FROM operations WHERE scope=? AND ref=?',(plan['scope'],plan['draft_ref'])).fetchone()
        if row:
            value=json.loads(row[0])
            if value['plan']['digest'] != plan['digest']: raise ValueError('Este proativo já iniciou execução com outro conteúdo; continue a operação existente.')
            return value
        value={'operation_id':uuid.uuid4().hex,'plan':plan,'ticket_id':None,'status':'reviewed','steps':{},'error':None}
        con.execute('INSERT INTO operations VALUES(?,?,?,?)',(value['operation_id'],plan['scope'],plan['draft_ref'],json.dumps(value)))
        return value

def get_operation(operation_id:str,path=None)->dict:
    with database(path) as con:
        row=con.execute('SELECT data FROM operations WHERE id=?',(operation_id,)).fetchone()
    if not row: raise ValueError('Operação não encontrada')
    return json.loads(row[0])

def update_operation(operation_id:str,changes:dict,path=None)->dict:
    with database(path) as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT data FROM operations WHERE id=?',(operation_id,)).fetchone()
        if not row: raise ValueError('Operação não encontrada')
        value=json.loads(row[0]); value.update(changes)
        con.execute('UPDATE operations SET data=? WHERE id=?',(json.dumps(value),operation_id))
    return value

def save_draft(identity:str,value:dict,path=None)->None:
    with database(path) as con:
        con.execute('INSERT INTO drafts VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(identity,json.dumps(value)))

def list_drafts(path=None)->list:
    with database(path) as con: rows=con.execute('SELECT id,data FROM drafts ORDER BY rowid').fetchall()
    return [{'id':r[0],**json.loads(r[1])} for r in rows]
