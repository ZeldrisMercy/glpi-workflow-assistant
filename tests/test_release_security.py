import importlib.machinery, importlib.util, sqlite3, tarfile
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
loader=importlib.machinery.SourceFileLoader('backup_tool',str(ROOT/'package/usr/bin/glpi-assistant-backup'))
spec=importlib.util.spec_from_loader(loader.name,loader);module=importlib.util.module_from_spec(spec);loader.exec_module(module)


def test_backup_captures_wal_and_excludes_external_symlinks(tmp_path):
    source=tmp_path/'data';source.mkdir();dest=tmp_path/'backups'
    (source/'config.json').write_text('{"user_token":"test-only"}')
    outside=tmp_path/'outside';outside.write_text('must-not-include')
    (source/'link').symlink_to(outside)
    with sqlite3.connect(source/'app.db') as con:
        con.execute('PRAGMA journal_mode=WAL');con.execute('CREATE TABLE proof(value TEXT)');con.execute("INSERT INTO proof VALUES ('reserved')");con.commit()
        result=module.backup(source,dest)
        assert result.stat().st_mode & 0o777 == 0o600
        with tarfile.open(result) as archive:
            assert 'data/link' not in archive.getnames()
            assert 'data/app.db-wal' not in archive.getnames()
            snapshot=tmp_path/'snapshot.db';snapshot.write_bytes(archive.extractfile('data/app.db').read())
        with sqlite3.connect(snapshot) as saved:assert saved.execute('SELECT value FROM proof').fetchone()[0]=='reserved'


def test_backup_rejects_recursive_destination(tmp_path):
    with pytest.raises(ValueError):module.backup(tmp_path,tmp_path/'nested')
