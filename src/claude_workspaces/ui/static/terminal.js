(function () {
    const term = new Terminal({
        fontFamily: '"JetBrains Mono", "Hack", "Fira Code", "DejaVu Sans Mono", monospace',
        fontSize: 13,
        cursorBlink: true,
        allowProposedApi: true,
        scrollback: 1000,
        theme: {
            background: '#121110',
            foreground: '#e3e1dd',
            cursor: '#d4a04a',
            selectionBackground: '#4a3a20',
        },
    });

    const fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open(document.getElementById('terminal'));

    // Renderer acelerado: webgl > canvas > DOM (fallback). O DOM renderer
    // (default sem addon) recria nós a cada redraw do TUI do Claude —
    // churn de heap de ~130MB/min no renderer Chromium compartilhado, que
    // virava swap. WebGL/canvas desenham em textura estável.
    // Carregar DEPOIS do open() (os addons de renderer exigem terminal
    // aberto). Se o contexto WebGL morrer (driver/gpu), volta pro canvas.
    //
    // `rendererAddon` guarda o addon ativo (webgl OU canvas) pra poder
    // limpar o texture atlas assim que as fontes terminarem de carregar
    // (ver document.fonts.ready abaixo) — glyphs rasterizados no atlas
    // antes da fonte real estar pronta (ex: negrito acentuado caindo no
    // fallback) ficam corrompidos (blocos pretos) e nunca são re-rasterizados
    // sozinhos.
    let rendererAddon = null;
    (function () {
        function tryCanvas() {
            try {
                if (typeof CanvasAddon !== 'undefined') {
                    rendererAddon = new CanvasAddon.CanvasAddon();
                    term.loadAddon(rendererAddon);
                    return true;
                }
            } catch (e) { /* segue no DOM */ }
            return false;
        }
        try {
            if (typeof WebglAddon !== 'undefined') {
                const webgl = new WebglAddon.WebglAddon();
                webgl.onContextLoss(function () {
                    try { webgl.dispose(); } catch (e) { }
                    rendererAddon = null;
                    tryCanvas();
                });
                term.loadAddon(webgl);
                rendererAddon = webgl;
                return;
            }
        } catch (e) { /* webgl indisponível */ }
        tryCanvas();
    })();

    // Ctrl+V cola (igual ao Konsole). Por padrão o xterm.js intercepta Ctrl+V e
    // manda \x16 (literal-next), então só Ctrl+Shift+V — o paste nativo do
    // navegador — colava. Retornar false faz o xterm não tratar a tecla e deixa
    // o navegador disparar seu paste nativo (mesmo caminho do Ctrl+Shift+V,
    // incluindo bracketed-paste). Ctrl+Shift+V e Ctrl+Alt+V seguem inalterados.
    term.attachCustomKeyEventHandler(function (e) {
        if (
            e.type === 'keydown' &&
            e.ctrlKey && !e.shiftKey && !e.altKey &&
            e.code === 'KeyV'
        ) {
            return false;
        }
        return true;
    });

    const termEl = document.getElementById('terminal');

    function safeFit() {
        try {
            // Força o elemento a exatamente (viewport - padding) antes de
            // medir — impede o loop inflate onde xterm renderiza mais largo
            // que o viewport, expande o body e o próximo fit mede ainda mais.
            const vw = window.innerWidth;
            if (vw > 0) {
                termEl.style.width = Math.max(0, vw - 8) + 'px';
            }
            fitAddon.fit();
            termEl.style.width = '';
        } catch (e) {
            termEl.style.width = '';
        }
    }

    // Tenta refitar várias vezes nos primeiros segundos — Qt pode demorar
    // pra finalizar layout (especialmente em splitters) e fontes podem
    // ainda estar carregando quando o init roda. Cancela a fila anterior
    // antes de agendar a nova pra evitar acúmulo de fits durante drag.
    let pendingFitTimers = [];
    function aggressiveFit() {
        pendingFitTimers.forEach(id => clearTimeout(id));
        pendingFitTimers = [];
        safeFit();
        [50, 200, 500].forEach(ms => {
            pendingFitTimers.push(setTimeout(safeFit, ms));
        });
    }
    aggressiveFit();

    if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(function () {
            safeFit();
            // Descarta qualquer glyph rasterizado no atlas do renderer
            // acelerado ANTES das fontes estabilizarem — sem isso, um
            // glyph "errado" (ex: negrito acentuado com fallback de fonte)
            // fica cacheado pro resto da sessão do terminal.
            if (rendererAddon && typeof rendererAddon.clearTextureAtlas === 'function') {
                try { rendererAddon.clearTextureAtlas(); } catch (e) { /* renderer já caiu pro DOM */ }
            }
        });
    }

    new QWebChannel(qt.webChannelTransport, function (channel) {
        const bridge = channel.objects.bridge;

        bridge.output_to_terminal.connect(function (data) {
            // data chega como ArrayBuffer (QByteArray) — xterm.js aceita
            // Uint8Array diretamente e faz a decodificação UTF-8 internamente
            if (data instanceof ArrayBuffer) {
                term.write(new Uint8Array(data));
            } else if (data && data.buffer instanceof ArrayBuffer) {
                term.write(new Uint8Array(data.buffer));
            } else {
                term.write(data);
            }
        });

        // Sinal explícito do Qt quando o widget redimensiona (resizeEvent)
        if (bridge.force_fit_requested) {
            bridge.force_fit_requested.connect(function () {
                aggressiveFit();
            });
        }

        if (bridge.clear_requested) {
            bridge.clear_requested.connect(function () {
                term.reset();
            });
        }

        // Limite de scrollback configurável (Settings → Console). Emitido no
        // frontend_ready (valor inicial) e ao vivo quando o usuário muda.
        if (bridge.scrollback_changed) {
            bridge.scrollback_changed.connect(function (n) {
                if (typeof n === 'number' && n > 0) {
                    term.options.scrollback = n;
                }
            });
        }

        term.onData(function (data) {
            bridge.input_from_terminal(data);
        });

        function sendSize() {
            bridge.resize_terminal(term.cols, term.rows);
        }
        term.onResize(sendSize);

        window.addEventListener('resize', safeFit);
        const ro = new ResizeObserver(safeFit);
        ro.observe(termEl);
        ro.observe(document.body);

        sendSize();
        bridge.frontend_ready();
        // Mais uma rodada depois que o bridge tá pronto — alguns sizes
        // do Qt só se estabilizam após o channel conectar
        aggressiveFit();
    });
})();
