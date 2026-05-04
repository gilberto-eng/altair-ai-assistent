const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const express = require('express');
const fs = require('fs');
const path = require('path');
const qrcode = require('qrcode-terminal');

const app = express();
app.use(express.json({ limit: '50mb' }));

let client = null;
let clientePronto = false;
let reiniciandoCliente = null;
let watchdogReautenticacao = null;
let servidorIniciado = false;
let envioDiretoDisparado = false;

const PROJECT_ROOT = path.resolve(__dirname, '..', '..');
const SESSION_DIR = path.join(PROJECT_ROOT, 'data', 'altair_session');
fs.mkdirSync(SESSION_DIR, { recursive: true });

function modoEnvioDireto() {
    return Boolean(process.argv[2] && process.argv[3]);
}

function iniciarServidorSeNecessario() {
    if (modoEnvioDireto()) return;
    if (servidorIniciado) return;

    servidorIniciado = true;
    app.listen(3000, () => {
        console.log('Servidor rodando na porta 3000');
    });
}

if (!modoEnvioDireto()) {
    iniciarServidorSeNecessario();
}

function criarCliente() {
    const resolveHeadless = () => {
        const env = String(process.env.WWEBJS_HEADLESS || '').trim().toLowerCase();
        if (env) return ['1', 'true', 'sim', 'yes'].includes(env);
        return false;
    };

    return new Client({
        authStrategy: new LocalAuth({
            dataPath: SESSION_DIR
        }),
        puppeteer: {
            headless: resolveHeadless(),
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu'
            ]
        }
    });
}

function erroTransitorioPuppeteer(err) {
    const msg = String((err && err.message) || err || '').toLowerCase();
    return (
        msg.includes('detached frame') ||
        msg.includes('execution context was destroyed') ||
        msg.includes('cannot find context with specified id') ||
        msg.includes('target closed')
    );
}

function sessaoPareceExpirada(texto) {
    const msg = String(texto || '').toLowerCase();
    return (
        msg.includes('auth_failure') ||
        msg.includes('logged out') ||
        msg.includes('logout') ||
        msg.includes('unpaired') ||
        msg.includes('unavailable') ||
        msg.includes('conflict') ||
        msg.includes('session') ||
        msg.includes('token')
    );
}

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function cancelarWatchdogReautenticacao() {
    if (watchdogReautenticacao) {
        clearTimeout(watchdogReautenticacao);
        watchdogReautenticacao = null;
    }
}

function limparSessaoWhatsApp() {
    try {
        fs.rmSync(SESSION_DIR, { recursive: true, force: true });
    } catch (_) {}

    try {
        fs.mkdirSync(SESSION_DIR, { recursive: true });
    } catch (_) {}
}

function formatarNumero(numero) {
    numero = String(numero || '').replace(/\D/g, '');
    if (!numero.endsWith('@c.us')) {
        numero = numero + '@c.us';
    }
    return numero;
}

function validarClientePronto(res) {
    if (!clientePronto) {
        res.status(503).json({ erro: 'WhatsApp ainda nao esta pronto. Aguarde reconexao.' });
        return false;
    }
    return true;
}

async function reinicializarClienteWhatsapp(motivo) {
    if (reiniciandoCliente) return reiniciandoCliente;

    reiniciandoCliente = (async () => {
        try {
            cancelarWatchdogReautenticacao();
            clientePronto = false;
            console.log('Sessao do WhatsApp invalida ou expirada. Pedindo nova autenticacao...', motivo || '');

            const antigo = client;
            client = null;

            try {
                if (antigo) await antigo.destroy();
            } catch (_) {}

            limparSessaoWhatsApp();
            await delay(1500);

            client = criarCliente();
            registrarEventosCliente(client);
            client.initialize().catch(err => {
                console.log('Erro ao reinicializar WhatsApp:', err);
            });
        } finally {
            reiniciandoCliente = null;
        }
    })();

    return reiniciandoCliente;
}

function buscarContatoEmLista(lista, termo) {
    return lista.find(c => {
        const nome = String(c && c.name ? c.name : '').toLowerCase();
        const push = String(c && c.pushname ? c.pushname : '').toLowerCase();
        return nome.includes(termo) || push.includes(termo);
    });
}

async function buscarContatoPorNome(nome) {
    const termo = String(nome || '').toLowerCase();

    try {
        const contatos = await client.getContacts();
        const contato = buscarContatoEmLista(contatos, termo);
        if (contato && contato.id && contato.id._serialized) {
            return contato.id._serialized;
        }
    } catch (_) {}

    const chats = await client.getChats();
    const chat = chats.find(ch => {
        const nomeChat = String((ch && ch.name) || '').toLowerCase();
        if (nomeChat.includes(termo)) return true;
        const push = String((ch && ch.contact && ch.contact.pushname) || '').toLowerCase();
        if (push.includes(termo)) return true;
        const nomeContato = String((ch && ch.contact && ch.contact.name) || '').toLowerCase();
        return nomeContato.includes(termo);
    });

    if (!chat || !chat.id || !chat.id._serialized) return null;
    return chat.id._serialized;
}

async function executarComRetry(fn, tentativas = 3, esperaMs = 500) {
    let ultimoErro = null;

    for (let i = 1; i <= tentativas; i++) {
        try {
            return await fn();
        } catch (err) {
            ultimoErro = err;
            const mensagem = String((err && err.message) || err || '');
            if (!erroTransitorioPuppeteer(err) && !sessaoPareceExpirada(mensagem)) {
                throw err;
            }

            if (sessaoPareceExpirada(mensagem)) {
                await reinicializarClienteWhatsapp(mensagem).catch(() => {});
            }

            await delay(esperaMs * i);
        }
    }

    throw ultimoErro;
}

async function enviarTexto(nome, numero, mensagem) {
    let chatId = null;
    if (numero) {
        chatId = formatarNumero(numero);
    } else if (nome) {
        chatId = await buscarContatoPorNome(nome);
    }

    if (!chatId) {
        return { ok: false, erro: 'Contato nao encontrado', status: 404 };
    }

    await executarComRetry(() => client.sendMessage(chatId, mensagem), 3, 700);
    return { ok: true };
}

async function enviarMidia(nome, numero, arquivo, legenda = '', opcoes = {}) {
    let chatId = null;
    if (numero) {
        chatId = formatarNumero(numero);
    } else if (nome) {
        chatId = await buscarContatoPorNome(nome);
    }

    if (!chatId) {
        return { ok: false, erro: 'Contato nao encontrado', status: 404 };
    }

    const media = MessageMedia.fromFilePath(path.resolve(arquivo));
    await executarComRetry(() => client.sendMessage(chatId, media, opcoes), 3, 800);
    return { ok: true };
}

function registrarEventosCliente(cli) {
    cli.on('qr', qr => {
        console.log('Escaneie o QR Code abaixo:\n');
        qrcode.generate(qr, { small: true });

        cancelarWatchdogReautenticacao();
        watchdogReautenticacao = setTimeout(() => {
            if (!clientePronto) {
                reinicializarClienteWhatsapp('timeout-qr').catch(err => {
                    console.error('Falha ao reiniciar WhatsApp apos timeout do QR:', err);
                });
            }
        }, 60000);
    });

    cli.on('ready', async () => {
        cancelarWatchdogReautenticacao();
        clientePronto = true;
        console.log('WhatsApp pronto!');
        iniciarServidorSeNecessario();
        await executarEnvioDiretoAoFicarPronto();
    });

    cli.on('auth_failure', msg => {
        cancelarWatchdogReautenticacao();
        clientePronto = false;
        console.error('Falha na autenticacao:', msg);
        reinicializarClienteWhatsapp(msg).catch(err => {
            console.error('Falha ao pedir nova autenticacao:', err);
        });
    });

    cli.on('disconnected', reason => {
        cancelarWatchdogReautenticacao();
        clientePronto = false;
        console.log('Desconectado:', reason);
        if (sessaoPareceExpirada(reason)) {
            reinicializarClienteWhatsapp(reason).catch(err => {
                console.error('Falha ao reconectar WhatsApp:', err);
            });
        }
    });

    cli.on('change_state', state => {
        if (state === 'CONNECTED') {
            clientePronto = true;
        }
        if (state === 'CONFLICT' || state === 'UNPAIRED' || state === 'UNPAIRED_IDLE') {
            clientePronto = false;
        }
        console.log('Estado do cliente:', state);
    });
}

app.get('/status', (req, res) => {
    res.json({
        servidor: true,
        pronto: clientePronto,
        reautenticando: Boolean(reiniciandoCliente) || Boolean(watchdogReautenticacao)
    });
});

app.post('/enviar-mensagem', async (req, res) => {
    try {
        if (!validarClientePronto(res)) return;
        const { nome, numero, mensagem } = req.body;
        const resultado = await enviarTexto(nome, numero, mensagem);
        if (!resultado.ok) {
            return res.status(resultado.status || 500).json({ erro: resultado.erro || 'Erro interno' });
        }
        res.json({ sucesso: true });
    } catch (err) {
        console.log('Erro ao enviar mensagem:', err);
        res.status(500).json({ erro: 'Erro interno' });
    }
});

app.post('/enviar-audio', async (req, res) => {
    try {
        if (!validarClientePronto(res)) return;
        const { nome, numero, caminhoAudio } = req.body;

        if (!caminhoAudio || !fs.existsSync(caminhoAudio)) {
            return res.status(404).json({ erro: 'Arquivo nao encontrado' });
        }

        const resultado = await enviarMidia(nome, numero, caminhoAudio, '', { sendAudioAsVoice: true });
        if (!resultado.ok) {
            return res.status(resultado.status || 500).json({ erro: resultado.erro || 'Erro interno' });
        }

        res.json({ sucesso: true });
    } catch (err) {
        console.log('Erro ao enviar audio:', err);
        res.status(500).json({ erro: 'Erro interno' });
    }
});

app.post('/enviar-arquivo', async (req, res) => {
    try {
        if (!validarClientePronto(res)) return;
        const { nome, numero, caminhoArquivo, legenda } = req.body;

        if (!caminhoArquivo || !fs.existsSync(caminhoArquivo)) {
            return res.status(404).json({ erro: 'Arquivo nao encontrado' });
        }

        const resultado = await enviarMidia(nome, numero, caminhoArquivo, legenda || '', { caption: legenda || '' });
        if (!resultado.ok) {
            return res.status(resultado.status || 500).json({ erro: resultado.erro || 'Erro interno' });
        }

        res.json({ sucesso: true });
    } catch (err) {
        console.log('Erro ao enviar arquivo:', err);
        res.status(500).json({ erro: 'Erro interno' });
    }
});

async function executarEnvioDiretoAoFicarPronto() {
    if (envioDiretoDisparado) return;
    envioDiretoDisparado = true;

    const nome = process.argv[2];
    const caminhoAudio = process.argv[3];
    if (!nome || !caminhoAudio) return;

    console.log('Enviando audio para:', nome);
    console.log('Arquivo:', caminhoAudio);

    try {
        const resultado = await enviarMidia(nome, null, caminhoAudio, '', { sendAudioAsVoice: true });
        if (!resultado.ok) {
            console.log('Contato nao encontrado');
            process.exit(1);
            return;
        }

        console.log('Audio enviado com sucesso!');
        process.exit(0);
    } catch (err) {
        console.log('Erro ao enviar audio:', err);
        process.exit(1);
    }
}

async function iniciarClienteWhatsapp() {
    while (true) {
        try {
            if (reiniciandoCliente) {
                await reiniciandoCliente;
                continue;
            }

            if (!client) {
                client = criarCliente();
                registrarEventosCliente(client);
            }

            await client.initialize();
            return;
        } catch (err) {
            const mensagem = String((err && err.message) || err || '');
            console.log('Falha ao inicializar WhatsApp:', err);

            if (sessaoPareceExpirada(mensagem)) {
                await reinicializarClienteWhatsapp(mensagem);
                continue;
            }

            if (erroTransitorioPuppeteer(err)) {
                try { if (client) await client.destroy(); } catch (_) {}
                client = null;
                await delay(1500);
                continue;
            }

            try { if (client) await client.destroy(); } catch (_) {}
            client = null;
            await delay(5000);
        }
    }
}

iniciarClienteWhatsapp().catch(err => {
    console.log('Erro fatal ao iniciar WhatsApp:', err);
});




