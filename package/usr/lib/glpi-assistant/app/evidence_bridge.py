"""Bounded image handoff; never fetch a URL supplied by an AI/web page."""
import base64
import hashlib
import re
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse
from store import DATA_DIR, delete_meta, get_meta, list_meta_prefix, set_meta


def validate_images(images):
    if len(images) > 30:
        raise HTTPException(413, 'Limite de 30 imagens por envio')
    seen, total, result = set(), 0, []
    for item in images:
        eid = str(item.get('id', '')).upper()
        if not re.fullmatch(r'E[0-9]{2,3}', eid) or eid in seen:
            raise HTTPException(400, 'Cada imagem deve ter um ID único E01, E02…')
        seen.add(eid)
        try:
            data = base64.b64decode(item['data'], validate=True)
        except Exception as exc:
            raise HTTPException(400, 'Imagem base64 inválida') from exc
        total += len(data)
        if len(data) > 8*1024*1024 or total > 20*1024*1024:
            raise HTTPException(413, 'Limite de 8 MiB por imagem e 20 MiB por envio')
        ext = image_type(data)
        if not ext:
            raise HTTPException(400, 'Somente PNG, JPEG ou WebP são aceitos')
        digest = hashlib.sha256(data).hexdigest()
        result.append({'id': eid, 'name': f'{eid}.{ext}', 'hash': digest, 'data': data, 'type': 'image/' + ('jpeg' if ext == 'jpg' else ext)})
    return sorted(result, key=lambda i: int(i['id'][1:]))


def image_type(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'webp'
    return None


def _referenced_hashes():
    referenced = set()
    for items in list_meta_prefix('bridge_images_').values():
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and item.get('hash'):
                referenced.add(str(item['hash']))
    return referenced


def _delete_unreferenced(hashes):
    referenced = _referenced_hashes()
    directory = DATA_DIR / 'bridge-images'
    for digest in set(hashes) - referenced:
        if not re.fullmatch(r'[0-9a-f]{64}', str(digest)):
            continue
        try:
            (directory / str(digest)).unlink(missing_ok=True)
        except OSError:
            # Cleanup is best-effort; never break a handoff because an old file
            # could not be removed.
            pass


def save_images(handoff_id, images):
    """Merge evidence updates by E-ID instead of replacing the whole set.

    Bridge uploads can arrive in stages (text first, E01/E02 later). A later
    request containing only the newly captured print must never delete evidence
    that was already persisted for the same handoff. Re-sending the same E-ID
    intentionally replaces that one evidence, which is how manual correction
    through the clips stays supported.
    """
    directory = DATA_DIR / 'bridge-images'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    old = get_meta(f'bridge_images_{handoff_id}', []) or []
    old_hashes = {str(item.get('hash')) for item in old if isinstance(item, dict) and item.get('hash')}
    merged = {str(item.get('id') or '').upper(): dict(item) for item in old if isinstance(item, dict) and item.get('id')}
    for item in images:
        path = directory / item['hash']
        if not path.exists():
            path.write_bytes(item['data'])
            path.chmod(0o600)
        merged[item['id']] = {k: v for k, v in item.items() if k != 'data'}
    metadata = sorted(merged.values(), key=lambda item: int(str(item['id'])[1:]))
    set_meta(f'bridge_images_{handoff_id}', metadata)
    _delete_unreferenced(old_hashes)
    return metadata


def delete_images(handoff_id):
    key = f'bridge_images_{handoff_id}'
    old = get_meta(key, []) or []
    old_hashes = {str(item.get('hash')) for item in old if isinstance(item, dict) and item.get('hash')}
    delete_meta(key)
    _delete_unreferenced(old_hashes)


def register(app):
    @app.get('/api/bridge/images/{handoff_id}/{evidence_id}')
    def image(handoff_id: int, evidence_id: str):
        metadata = get_meta(f'bridge_images_{handoff_id}', []) or []
        item = next((x for x in metadata if x['id'] == evidence_id), None)
        if not item:
            raise HTTPException(404, 'Imagem não encontrada')
        path = DATA_DIR / 'bridge-images' / item['hash']
        return FileResponse(path, media_type=item['type'], filename=item['name'], headers={'Cache-Control': 'no-store', 'Cross-Origin-Resource-Policy': 'same-origin', 'X-Content-Type-Options': 'nosniff'})
