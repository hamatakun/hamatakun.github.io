import io, ssl, urllib.request
CTX = ssl.create_default_context(cafile='/root/.ccr/ca-bundle.crt')
class HTTPRangeFile(io.RawIOBase):
    """Seekable read-only file over HTTP range requests (for pyarrow.parquet)."""
    def __init__(self, url):
        self.url = url; self.pos = 0
        req = urllib.request.Request(url, method='HEAD')
        with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
            self.size = int(r.headers['Content-Length'])
        self.bytes_read = 0
    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos
    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos
    def read(self, n=-1):
        if n is None or n < 0: n = self.size - self.pos
        if n == 0 or self.pos >= self.size: return b''
        end = min(self.size, self.pos + n) - 1
        for attempt in range(5):
            try:
                req = urllib.request.Request(self.url, headers={'Range': f'bytes={self.pos}-{end}'})
                with urllib.request.urlopen(req, context=CTX, timeout=120) as r:
                    data = r.read()
                break
            except Exception:
                if attempt == 4: raise
        self.pos += len(data); self.bytes_read += len(data)
        return data
    def readinto(self, b):
        d = self.read(len(b)); b[:len(d)] = d; return len(d)
