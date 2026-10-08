import os
import re
import socket
import requests
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from flask import Flask, request, render_template_string, send_from_directory, redirect

app = Flask(__name__)

# Configuration
BASE_DIR = os.path.abspath('web')
os.makedirs(BASE_DIR, exist_ok=True)
MAX_WORKERS = 5  # Safe for mobile networks
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
}

session = requests.Session()
session.headers.update(HEADERS)


def get_local_ip():
    """Get the local IP address to access from other devices."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def url_to_local_path(url):
    """Convert a URL to a safe local file path."""
    parsed = urlparse(url)
    path = parsed.path or ''
    if not path or path.endswith('/'):
        path += 'index.html'
    path = path.lstrip('/')
    if parsed.query:
        name, ext = os.path.splitext(path)
        safe_q = re.sub(r'[^a-zA-Z0-9]', '_', parsed.query)[:30]
        path = f"{name}_{safe_q}{ext}"
    path = re.sub(r'//+', '/', path)
    return path or 'index.html'


def clone_site(start_url):
    """Main function to clone a website."""
    if not start_url.startswith(('http://', 'https://')):
        start_url = 'https://' + start_url

    parsed = urlparse(start_url)
    domain = parsed.netloc
    site_folder = os.path.join(BASE_DIR, domain)
    os.makedirs(site_folder, exist_ok=True)

    results = {
        'domain': domain,
        'downloaded': [],
        'errors': [],
        'total': 0,
    }

    downloaded_urls = set()

    def download_file(file_url, referer=None):
        """Download and save a single file."""
        if not file_url or file_url.startswith(('data:', 'javascript:', 'mailto:', '#', 'blob:')):
            return None

        try:
            full_url = urljoin(referer or start_url, file_url)
        except Exception:
            return None

        if full_url in downloaded_urls:
            return url_to_local_path(full_url)

        # Only download from the same domain (uncomment the next 2 lines to allow CDNs)
        # if urlparse(full_url).netloc != domain:
        #     return None

        downloaded_urls.add(full_url)

        try:
            resp = session.get(full_url, timeout=20, stream=True)
            resp.raise_for_status()

            local_path = url_to_local_path(full_url)
            full_local_path = os.path.join(site_folder, local_path)
            os.makedirs(os.path.dirname(full_local_path), exist_ok=True)

            with open(full_local_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=16384):
                    if chunk:
                        f.write(chunk)

            results['downloaded'].append(local_path)
            return local_path
        except Exception as e:
            results['errors'].append(f"{file_url[:50]} - {str(e)[:50]}")
            return None

    def process_css(css_url):
        """Download CSS and its embedded assets."""
        try:
            full_css_url = urljoin(start_url, css_url)
            resp = session.get(full_css_url, timeout=15)
            resp.raise_for_status()
            css_content = resp.text

            local_css_path = url_to_local_path(full_css_url)
            css_dir = os.path.dirname(local_css_path)

            url_pattern = re.compile(r'url\([\'"]?([^\'")]+)[\'"]?\)')

            def replace_css_url(match):
                css_res_url = match.group(1).strip()
                if css_res_url.startswith(('data:', '#')):
                    return match.group(0)
                full_res_url = urljoin(full_css_url, css_res_url)
                local = download_file(full_res_url, referer=full_css_url)
                if local:
                    rel = os.path.relpath(local, css_dir) if css_dir else local
                    rel = rel.replace('\\', '/')
                    return f"url('{rel}')"
                return match.group(0)

            new_css = url_pattern.sub(replace_css_url, css_content)

            full_css_path = os.path.join(site_folder, local_css_path)
            os.makedirs(os.path.dirname(full_css_path), exist_ok=True)
            with open(full_css_path, 'w', encoding='utf-8') as f:
                f.write(new_css)

            if local_css_path not in results['downloaded']:
                results['downloaded'].append(local_css_path)
            return local_css_path
        except Exception as e:
            results['errors'].append(f"CSS Error: {str(e)[:50]}")
            return None

    # --- Start Cloning ---
    try:
        main_resp = session.get(start_url, timeout=20)
        main_resp.raise_for_status()
        html = main_resp.text
    except Exception as e:
        results['errors'].append(f"Main page error: {str(e)[:100]}")
        return results

    soup = BeautifulSoup(html, 'html.parser')

    # 1. Process Stylesheets
    for link in soup.find_all('link'):
        href = link.get('href')
        if not href: continue
        rel = link.get('rel') or []
        if 'stylesheet' in rel:
            local = process_css(href)
            if local: link['href'] = local
        elif not href.startswith(('data:', '#', 'mailto:')):
            local = download_file(href)
            if local: link['href'] = local

    # 2. Process Scripts
    for script in soup.find_all('script'):
        src = script.get('src')
        if src:
            local = download_file(src)
            if local: script['src'] = local

    # 3. Process Images
    for img in soup.find_all('img'):
        for attr in ['src', 'data-src', 'data-original', 'data-lazy-src']:
            src = img.get(attr)
            if src and not src.startswith('data:'):
                local = download_file(src)
                if local:
                    img['src'] = local
                    if attr in img.attrs and attr != 'src':
                        del img[attr]
                    break

    # 4. Process Srcset
    for tag in soup.find_all(['img', 'source']):
        srcset = tag.get('srcset')
        if srcset:
            new_parts = []
            for part in srcset.split(','):
                part = part.strip()
                if not part: continue
                pieces = part.split()
                if pieces:
                    local = download_file(pieces[0])
                    if local: pieces[0] = local
                    new_parts.append(' '.join(pieces))
            if new_parts: tag['srcset'] = ', '.join(new_parts)

    # 5. Process Inline Styles
    for tag in soup.find_all(style=True):
        style = tag['style']
        def replace_style_url(match):
            u = match.group(1).strip()
            if u.startswith(('data:', '#')): return match.group(0)
            local = download_file(u)
            if local: return f"url('{local}')"
            return match.group(0)
        tag['style'] = re.sub(r'url\([\'"]?([^\'")]+)[\'"]?\)', replace_style_url, style)

    # Save the modified HTML
    index_path = os.path.join(site_folder, 'index.html')
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(str(soup))

    results['downloaded'].insert(0, 'index.html')
    results['total'] = len(results['downloaded'])
    return results


# ================= UI =================
HTML_UI = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>NAPO44 Web Cloner</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
        
        /* Prevent double-tap zoom on interactive elements */
        button, input, a { touch-action: manipulation; }

        body {
            background-color: #0a0a0a;
            color: #e0e0e0;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            padding: 20px;
        }

        .container {
            width: 100%;
            max-width: 700px;
        }

        .header {
            text-align: center;
            margin-bottom: 30px;
        }

        .header h1 {
            font-size: 2rem;
            font-weight: 700;
            color: #ffffff;
            letter-spacing: 1px;
        }

        .header p {
            color: #888;
            font-size: 0.9rem;
            margin-top: 5px;
        }

        .card {
            background: #111111;
            border: 1px solid #222222;
            border-radius: 12px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        }

        form {
            display: flex;
            flex-direction: column;
            gap: 15px;
        }

        input[type="text"] {
            width: 100%;
            padding: 15px;
            border-radius: 8px;
            border: 1px solid #333;
            background: #0a0a0a;
            color: #fff;
            font-size: 16px; /* Prevents zoom on focus in iOS */
            outline: none;
            transition: border-color 0.3s;
        }

        input[type="text"]:focus {
            border-color: #555;
        }

        button {
            padding: 15px;
            border-radius: 8px;
            border: none;
            background: #ffffff;
            color: #000000;
            font-weight: 700;
            font-size: 1rem;
            cursor: pointer;
            transition: background 0.3s, opacity 0.3s;
        }

        button:hover {
            background: #cccccc;
        }

        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .status-box {
            margin-top: 25px;
            padding: 20px;
            background: #0a0a0a;
            border: 1px solid #222;
            border-radius: 8px;
            display: none;
        }

        .status-box.show { display: block; }

        .status-box h3 {
            font-size: 1.1rem;
            margin-bottom: 15px;
            color: #fff;
        }

        .info-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-bottom: 20px;
        }

        .info-item {
            background: #111;
            padding: 12px;
            border-radius: 6px;
            text-align: center;
            border: 1px solid #222;
        }

        .info-item .label { font-size: 0.75rem; color: #888; text-transform: uppercase; }
        .info-item .value { font-size: 1.2rem; font-weight: 700; color: #fff; margin-top: 5px; }

        .btn-group {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-bottom: 20px;
        }

        .btn-view {
            flex: 1;
            padding: 12px;
            text-align: center;
            background: #222;
            color: #fff;
            text-decoration: none;
            border-radius: 6px;
            font-weight: 600;
            font-size: 0.9rem;
            transition: background 0.3s;
            min-width: 120px;
        }

        .btn-view:hover { background: #333; }

        .log-title {
            font-size: 0.9rem;
            color: #888;
            margin-bottom: 10px;
        }

        .log-area {
            max-height: 250px;
            overflow-y: auto;
            background: #050505;
            border: 1px solid #222;
            border-radius: 6px;
            padding: 10px;
            font-family: monospace;
            font-size: 0.8rem;
            line-height: 1.5;
        }

        .log-item { color: #aaa; word-break: break-all; border-bottom: 1px solid #111; padding: 4px 0; }
        .log-item.error { color: #ff5555; }

        .loading-overlay {
            display: none;
            position: fixed;
            top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0,0,0,0.85);
            z-index: 1000;
            justify-content: center;
            align-items: center;
            flex-direction: column;
            gap: 15px;
        }

        .loading-overlay.show { display: flex; }

        .spinner {
            width: 40px; height: 40px;
            border: 3px solid #333;
            border-top: 3px solid #fff;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }

        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }

        .loading-text { color: #fff; font-size: 1rem; }

        @media (max-width: 480px) {
            .header h1 { font-size: 1.6rem; }
            .card { padding: 15px; }
            .info-grid { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>

<div class="container">
    <div class="header">
        <h1>NAPO44 Cloner</h1>
        <p>Clone any website to your local server</p>
    </div>

    <div class="card">
        <form method="POST" action="/clone" onsubmit="showLoading()">
            <input type="text" name="url" id="urlInput"
                   placeholder="Enter website URL (e.g., example.com)"
                   value="{{ last_url or '' }}" required autocomplete="off">
            <button type="submit" id="cloneBtn">Start Cloning</button>
        </form>

        {% if result %}
        <div class="status-box show">
            {% if result.get('errors') and not result.get('total') %}
                <h3 style="color:#ff5555;">Cloning Failed</h3>
                <div class="log-area">
                    {% for err in result.errors %}
                    <div class="log-item error">{{ err }}</div>
                    {% endfor %}
                </div>
            {% else %}
                <h3>Cloning Complete</h3>
                <div class="info-grid">
                    <div class="info-item">
                        <div class="label">Files Downloaded</div>
                        <div class="value">{{ result.total }}</div>
                    </div>
                    <div class="info-item">
                        <div class="label">Errors</div>
                        <div class="value" style="color: {% if result.errors %}#ff5555{% else %}#55ff55{% endif %};">
                            {{ result.errors | length }}
                        </div>
                    </div>
                </div>

                <div class="btn-group">
                    <a class="btn-view" href="/site/{{ result.domain }}/index.html" target="_blank">View Website</a>
                    <a class="btn-view" href="/sites">All Clones</a>
                </div>

                <div class="log-title">Downloaded Files</div>
                <div class="log-area">
                    {% for f in result.downloaded %}
                    <div class="log-item">📄 {{ f }}</div>
                    {% endfor %}
                    {% if result.errors %}
                    <div class="log-item error" style="margin-top:10px; font-weight:bold;">--- Errors ---</div>
                    {% for err in result.errors %}
                    <div class="log-item error">⚠️ {{ err }}</div>
                    {% endfor %}
                    {% endif %}
                </div>
            {% endif %}
        </div>
        {% endif %}
    </div>
</div>

<div class="loading-overlay" id="loadingOverlay">
    <div class="spinner"></div>
    <div class="loading-text">Downloading files... Please wait.</div>
</div>

<script>
    function showLoading() {
        document.getElementById('loadingOverlay').classList.add('show');
        document.getElementById('cloneBtn').disabled = true;
        document.getElementById('cloneBtn').textContent = 'Cloning...';
    }
</script>

</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(HTML_UI)


@app.route('/clone', methods=['POST'])
def clone_route():
    url = request.form.get('url', '').strip()
    if not url:
        return render_template_string(HTML_UI, result={'errors': ['Please enter a URL'], 'total': 0}, last_url='')

    print(f"\n{'='*50}\n🚀 Starting clone: {url}\n{'='*50}")
    result = clone_site(url)
    print(f"{'='*50}\n✅ Finished: {result['total']} files\n{'='*50}\n")
    return render_template_string(HTML_UI, result=result, last_url=url)


@app.route('/site/<path:filepath>')
def serve_cloned(filepath):
    full_path = os.path.join(BASE_DIR, filepath)
    if os.path.isdir(full_path):
        return send_from_directory(full_path, 'index.html')
    return send_from_directory(BASE_DIR, filepath)


@app.route('/sites')
def list_sites():
    sites = []
    if os.path.isdir(BASE_DIR):
        for d in sorted(os.listdir(BASE_DIR)):
            full = os.path.join(BASE_DIR, d)
            if os.path.isdir(full) and os.path.exists(os.path.join(full, 'index.html')):
                count = sum(len(files) for _, _, files in os.walk(full))
                sites.append({'name': d, 'count': count})

    html = r"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Cloned Websites</title>
        <style>
            * { margin:0; padding:0; box-sizing:border-box; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
            body { background:#0a0a0a; color:#e0e0e0; padding:20px; min-height:100vh; }
            .container { max-width:600px; margin:0 auto; }
            h1 { text-align:center; color:#fff; margin-bottom:25px; font-size:1.5rem; }
            .site-item {
                background:#111; border:1px solid #222; border-radius:8px;
                padding:15px; margin-bottom:10px; display:flex;
                justify-content:space-between; align-items:center; gap:10px;
            }
            .site-item a { color:#fff; text-decoration:none; font-weight:600; word-break:break-all; }
            .site-item a:hover { text-decoration:underline; }
            .count { color:#888; font-size:0.8rem; white-space:nowrap; background:#222; padding:4px 8px; border-radius:4px; }
            .back { display:block; text-align:center; margin-top:25px; color:#888; text-decoration:none; font-size:0.9rem; }
            .empty { text-align:center; color:#555; padding:40px; }
        </style>
    </head>
    <body>
    <div class="container">
        <h1>Cloned Websites</h1>
        {% if sites %}
            {% for s in sites %}
            <div class="site-item">
                <a href="/site/{{ s.name }}/index.html" target="_blank">{{ s.name }}</a>
                <span class="count">{{ s.count }} files</span>
            </div>
            {% endfor %}
        {% else %}
            <div class="empty">No websites cloned yet.</div>
        {% endif %}
        <a class="back" href="/">← Back to Cloner</a>
    </div>
    </body>
    </html>
    """
    return render_template_string(html, sites=sites)


if __name__ == '__main__':
    local_ip = get_local_ip()
    print("="*50)
    print("✨ NAPO44 Web Cloner is Ready!")
    print(f"📁 Save Directory: {BASE_DIR}")
    print(f"👉 Local: http://127.0.0.1:8000")
    print(f"👉 Network: http://{local_ip}:8000")
    print("="*50)
    # host='0.0.0.0' makes it accessible from other devices on the same Wi-Fi
    app.run(host='0.0.0.0', port=8000, debug=False, threaded=True)