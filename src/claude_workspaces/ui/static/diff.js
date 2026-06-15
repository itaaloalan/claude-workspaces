(function () {
    'use strict';

    const placeholder = document.getElementById('placeholder');
    const wrap = document.getElementById('diff-wrap');

    function render(unified, fmt, filename) {
        // Mensagens de erro / avisos do backend (começam com '(')
        if (!unified || !unified.trim() || unified.trimStart().startsWith('(')) {
            wrap.style.display = 'none';
            placeholder.style.display = 'flex';
            placeholder.textContent = (unified && unified.trim())
                ? unified.trim()
                : (filename
                    ? 'Nenhuma diferença — arquivo idêntico ou binário.'
                    : 'Clique num arquivo para ver o diff.');
            return;
        }

        placeholder.style.display = 'none';
        wrap.style.display = 'block';
        wrap.innerHTML = '';

        try {
            const ui = new Diff2HtmlUI(wrap, unified, {
                outputFormat: fmt || 'line-by-line',
                drawFileList: false,
                highlight: true,
                synchronisedScroll: true,
                fileContentToggle: false,
                matching: 'lines',
                diffStyle: 'word',
            });
            ui.draw();
            ui.highlightCode();
        } catch (err) {
            wrap.textContent = '(erro ao renderizar diff: ' + err + ')';
        }
    }

    new QWebChannel(qt.webChannelTransport, function (channel) {
        const bridge = channel.objects.bridge;

        bridge.render_diff.connect(function (unified, fmt, filename) {
            render(unified, fmt, filename);
        });

        // Sinaliza ao Python que o frontend está pronto pra receber diffs
        bridge.frontend_ready();
    });
})();
