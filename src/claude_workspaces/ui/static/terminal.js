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

    safeFit();

    new QWebChannel(qt.webChannelTransport, function (channel) {
        const bridge = channel.objects.bridge;

        bridge.output_to_terminal.connect(function (data) {
            term.write(data);
        });

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

        sendSize();
        bridge.frontend_ready();
    });
})();
