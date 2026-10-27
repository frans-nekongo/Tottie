# Tottie — build & run targets
# Docs use XeLaTeX (fontspec/Arial). The Beamer deck uses pdfLaTeX.

.PHONY: docs deck db core-install core ui-install ui mcp verify clean

# ---------- documents ----------
docs:
	cd docs && latexmk -xelatex -interaction=nonstopmode master.tex

deck:
	cd docs/presentation && pdflatex -interaction=nonstopmode -halt-on-error presentation.tex && pdflatex -interaction=nonstopmode -halt-on-error presentation.tex

# ---------- memory engine ----------
db:
	cd core && ./scripts/init_db.sh

core-install:
	cd core && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt

core:
	cd core && ./venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765

# ---------- MCP (imports core in-process; needs venv python + core on the path) ----------
mcp:
	cd mcp && PYTHONPATH=../core ../core/venv/bin/python server.py

# ---------- UI ----------
ui-install:
	cd ui && npm install

ui:
	cd ui && npm run dev

# ---------- verification (one command, Joel #2; fails loud, never || true) ----------
verify: docs deck
	cd ui && npm run build
	cd core && ./venv/bin/python -m pytest tests -q

clean:
	cd docs && latexmk -C master.tex
	cd docs/presentation && latexmk -C presentation.tex
	rm -f docs/*.aux docs/*.log docs/*.toc docs/*.out docs/*.fls docs/*.fdb_latexmk docs/*.xdv docs/*.synctex.gz
