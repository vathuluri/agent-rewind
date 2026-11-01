"""Build a standalone public HTML simulation without copying local run data."""
from pathlib import Path
import shutil

root = Path(__file__).parent
source = root / 'agent_rewind' / 'web'
out = root / 'demo'
out.mkdir(exist_ok=True)
for name in ['app.js', 'style.css', 'demo-runtime.js']:
    shutil.copyfile(source / name, out / name)
html = (source / 'index.html').read_text(encoding='utf-8')
html = html.replace('href="/style.css"', 'href="./style.css"')
html = html.replace('LOCAL AGENT TOOLING', 'INTERACTIVE BROWSER DEMO')
html = html.replace('Synthetic demo · No LLM calls, production systems or credentials. Replay displays recorded state; it does not re-execute tools.', 'Browser simulation · Synthetic data only. No LLM calls or server. Runs stay in this tab and reset on refresh. Replay shows recorded snapshots; it does not undo tool actions.')
html = html.replace('<button id="demo">Restart walkthrough</button>', '<div class="header-actions"><a href="https://github.com/vathuluri/agent-rewind" target="_blank" rel="noopener noreferrer">View source ↗</a><button id="demo">Restart walkthrough</button></div>')
html = html.replace('<script src="/app.js" defer></script>', '<script src="./demo-runtime.js" defer></script><script src="./app.js" defer></script>')
(out / 'index.html').write_text(html, encoding='utf-8')
print('Built browser-only demo in demo/. No databases or recorded user data copied.')
