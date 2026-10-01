"""Local deployment boundary: DNS rebinding/CSRF protection and bounded bodies.
This does not authenticate other programs running as the local OS user.
"""
import asyncio
import json

HOSTS = {'127.0.0.1:8765', 'localhost:8765', '[::1]:8765'}
ORIGINS = {'http://' + host for host in HOSTS}
BRIDGE_PATHS = {'/api/bridge/pair', '/api/bridge/info', '/api/bridge/ping', '/api/bridge/unpair', '/api/bridge/glpi-origin', '/api/bridge/context', '/api/bridge/handoff'}


class LocalBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get('headers', [])}
        async def reject(code, detail):
            data = json.dumps({'detail': detail}).encode()
            await send({'type':'http.response.start','status':code,'headers':[(b'content-type',b'application/json'),(b'cache-control',b'no-store')]})
            await send({'type':'http.response.body','body':data})
        if headers.get('host', '').lower() not in HOSTS:
            return await reject(400, 'Host local inválido.')
        origin = headers.get('origin', '')
        path = scope.get('path', '')
        extension = origin.startswith(('moz-extension://', 'chrome-extension://')) and path in BRIDGE_PATHS
        if origin and origin not in ORIGINS and not extension:
            return await reject(403, 'Origem externa bloqueada.')
        if headers.get('sec-fetch-site') in ('cross-site', 'same-site') and not extension:
            return await reject(403, 'Requisição externa bloqueada.')
        # Base64 handoffs need overhead; multipart uploads have a lower binary cap.
        limit = (30 if path == '/api/bridge/handoff' else 24 if path in ('/api/execute', '/api/templates/plan', '/api/templates/apply') else 1) * 1024 * 1024
        try:
            if int(headers.get('content-length', '0')) > limit:
                return await reject(413, 'Envio excede o limite permitido.')
        except ValueError:
            return await reject(400, 'Tamanho de envio inválido.')
        parts, total = [], 0
        try:
            async with asyncio.timeout(20):
                while True:
                    message = await receive()
                    if message['type'] == 'http.disconnect':
                        return
                    body = message.get('body', b'')
                    total += len(body)
                    if total > limit:
                        return await reject(413, 'Envio excede o limite permitido.')
                    parts.append(body)
                    if not message.get('more_body'):
                        break
        except TimeoutError:
            return await reject(408, 'Tempo de recebimento excedido.')
        delivered = False
        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type':'http.request','body':b''.join(parts),'more_body':False}
            return await receive()
        return await self.app(scope, bounded_receive, send)
