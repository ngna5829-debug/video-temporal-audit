"""Local preview server with single HTTP byte-range support; bind loopback only."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial
import os
import re
import argparse


class RangeHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Accept-Ranges', 'bytes')
        super().end_headers()

    def send_head(self):
        self.range_remaining = None
        requested = self.headers.get('Range')
        path = self.translate_path(self.path)
        if not requested or not os.path.isfile(path):
            return super().send_head()
        size = os.path.getsize(path)
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested.strip())
        try:
            if not match or not any(match.groups()) or size == 0:
                raise ValueError()
            left, right = match.groups()
            if left:
                start = int(left)
                end = min(int(right), size - 1) if right else size - 1
            else:
                suffix = int(right)
                if suffix <= 0:
                    raise ValueError()
                start, end = max(0, size - suffix), size - 1
            if start >= size or end < start:
                raise ValueError()
        except ValueError:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{size}')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return None
        stream = open(path, 'rb')
        stream.seek(start)
        self.range_remaining = end - start + 1
        self.send_response(206)
        self.send_header('Content-Type', self.guess_type(path))
        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length', str(self.range_remaining))
        self.end_headers()
        return stream

    def copyfile(self, source, outputfile):
        if self.range_remaining is None:
            return super().copyfile(source, outputfile)
        remaining = self.range_remaining
        while remaining:
            data = source.read(min(1024 * 1024, remaining))
            if not data:
                break
            outputfile.write(data)
            remaining -= len(data)


def serve_directory(directory, port=8765):
    """Serve explicitly selected report folder on loopback, with bounded range IO."""
    from pathlib import Path
    directory=Path(directory).resolve()
    if not directory.is_dir(): raise ValueError("Report directory does not exist")
    if not 1 <= port <= 65535: raise ValueError("Port must be 1–65535")
    server=ThreadingHTTPServer(('127.0.0.1',port),partial(RangeHandler,directory=str(directory)))
    print(f"本机报告服务：http://127.0.0.1:{port}/ （支持视频 Range 跳转，Ctrl+C 退出）",flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
