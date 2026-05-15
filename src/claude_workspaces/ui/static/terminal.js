(function () {
    const term = new Terminal({
        fontFamily: '"JetBrains Mono", "Hack", "Fira Code", "DejaVu Sans Mono", monospace',
        fontSize: 13,
        cursorBlink: true,
        allowProposedApi: true,
        scrollback: 5000,
        theme: {
            background: '#0e0e0e',
            foreground: '#e0e0e0',
            cursor: '#e0e0e0',
            selectionBackground: '#3a3a3a',
        },
    });

    const fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open(document.getElementById('terminal'));

    function safeFit() {
        try {
            fitAddon.fit();
        } catch (e) {
            // Ignored: occurs when the host widget is still 0-sized during initial layout.
        }
    }

    // Tenta refitar várias vezes nos primeiros segundos — Qt pode demorar
    // pra finalizar layout (especialmente em splitters) e fontes podem
    // ainda estar carregando quando o init roda
    function aggressiveFit() {
        safeFit();
        const delays = [50, 150, 300, 600, 1200];
        delays.forEach(ms => setTimeout(safeFit, ms));
    }
    aggressiveFit();

    if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(safeFit);
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

        term.onData(function (data) {
            bridge.input_from_terminal(data);
        });

        function sendSize() {
            bridge.resize_terminal(term.cols, term.rows);
        }
        term.onResize(sendSize);

        window.addEventListener('resize', safeFit);
        const ro = new ResizeObserver(safeFit);
        ro.observe(document.getElementById('terminal'));
        ro.observe(document.body);

        sendSize();
        bridge.frontend_ready();
        // Mais uma rodada depois que o bridge tá pronto — alguns sizes
        // do Qt só se estabilizam após o channel conectar
        aggressiveFit();
    });
})();
