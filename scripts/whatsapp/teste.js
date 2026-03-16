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
let servidorIniciado = false;
let envioDiretoDisparado = false;

const PROJECT_ROOT = path.resolve(__dirname, '..', '..');
const SESSION_DIR = path.join(PROJECT_ROOT, 'data', 'altair_session');
fs.mkdirSync(SESSION_DIR, { recursive: true });

function criarCliente() {
    const resolveHeadless = () => {
        const env = String(process.env.WWEBJS_HEADLESS || '').trim().toLowerCase();
        if (env) return ['1','true','sim','yes'].includes(env);
        try {
            const itens = fs.readdirSync(SESSION_DIR).filter(n => !n.startsWith('.'));
            if (!itens || itens.length === 0) return false;
        } catch (_) {
            return false;
        }
        return true;
    };
    const headless = resolveHeadless();
    return new Client({
        authStrategy: new LocalAuth({
            dataPath: SESSION_DIR
        }),
        puppeteer: {
            headless,
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

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function formatarNumero(numero) {
    numero = String(numero || '').replace(/\D/g, '');
    if (!numero.endsWith('@c.us')) {
        numero = numero + '@c.us';
    }
    return numero;
}

function iniciarServidorSeNecessario() {
    const nome = process.argv[2];
    const caminhoAudio = process.argv[3];
    if (nome && caminhoAudio) return;
    if (servidorIniciado) return;

    servidorIniciado = true;
    app.listen(3000, () => {
        console.log('Servidor rodando na porta 3000');
    });
}

function validarClientePronto(res) {
    if (!clientePronto) {
        res.status(503).json({ erro: 'WhatsApp ainda nao esta pronto. Aguarde reconexao.' });
        return false;
    }
    return true;
}

function aguardarEventoReady(timeoutMs = 60000) {
    if (clientePronto) return Promise.resolve();
    const clienteAtual = client;

    return new Promise((resolve, reject) => {
        if (!clienteAtual) {
            reject(new Error('Cliente WhatsApp nao inicializado.'));
            return;
        }

        const timer = setTimeout(() => {
            try { clienteAtual.off('ready', onReady); } catch (_) {}
            reject(new Error('Timeout aguardando cliente pronto.'));
        }, timeoutMs);

        const onReady = () => {
            clearTimeout(timer);
            resolve();
        };

        clienteAtual.once('ready', onReady);
    });
}

async function reinicializarClienteWhatsapp() {
    if (reiniciandoCliente) return reiniciandoCliente;

    reiniciandoCliente = (async () => {
        try {
            clientePronto = false;
            console.log('Reconectando cliente WhatsApp...');

            const antigo = client;
            client = null;

            try { if (antigo) await antigo.destroy(); } catch (_) {}
            await delay(1200);

            client = criarCliente();
            registrarEventosCliente(client);
            client.initialize();

            await aguardarEventoReady(90000);
            console.log('Cliente WhatsApp reconectado.');
        } finally {
            reiniciandoCliente = null;
        }
    })();

    return reiniciandoCliente;
}

async function executarComRetry(fn, tentativas = 4, esperaMs = 400) {
    let ultimoErro = null;

    for (let i = 1; i <= tentativas; i++) {
        try {
            return await fn();
        } catch (err) {
            ultimoErro = err;
            if (!erroTransitorioPuppeteer(err)) {
                throw err;
            }

            console.log(`Erro transitorio do WhatsApp Web (tentativa ${i}/${tentativas}). Repetindo...`);
            try { await reinicializarClienteWhatsapp(); } catch (errReconexao) {
                console.log('Falha ao reconectar WhatsApp durante retry:', errReconexao && errReconexao.message ? errReconexao.message : errReconexao);
            }

            await delay(esperaMs * i);
        }
    }

    throw ultimoErro;
}

async function buscarContatoPorNome(nome) {
    const termo = String(nome || '').toLowerCase();

    let contato = null;
    try {
        const contatos = await executarComRetry(() => client.getContacts());
        contato = contatos.find(c =>
            (c.name && c.name.toLowerCase().includes(termo)) ||
            (c.pushname && c.pushname.toLowerCase().includes(termo))
        );
    } catch (err) {
        if (!erroTransitorioPuppeteer(err)) {
            throw err;
        }
    }

    if (contato && contato.id && contato.id._serialized) {
        return contato.id._serialized;
    }

    const chats = await executarComRetry(() => client.getChats());
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

async function executarEnvioDiretoAoFicarPronto() {
    if (envioDiretoDisparado) return;
    envioDiretoDisparado = true;

    const nome = process.argv[2];
    const caminhoAudio = process.argv[3];
    if (!nome || !caminhoAudio) return;

    console.log('Enviando audio para:', nome);
    console.log('Arquivo:', caminhoAudio);

    try {
        const chatId = await buscarContatoPorNome(nome);
        if (!chatId) {
            console.log('Contato nao encontrado');
            process.exit(1);
        }

        const media = MessageMedia.fromFilePath(path.resolve(caminhoAudio));
        await executarComRetry(() => client.sendMessage(chatId, media, { sendAudioAsVoice: true }));

        console.log('Audio enviado com sucesso!');
        process.exit(0);
    } catch (err) {
        console.log('Erro ao enviar audio:', err);
        process.exit(1);
    }
}

function registrarEventosCliente(cli) {
    cli.on('qr', qr => {
        console.log('Escaneie o QR Code abaixo:\n');
        qrcode.generate(qr, { small: true });
    });

    cli.on('ready', async () => {
        clientePronto = true;
        console.log('WhatsApp pronto!');
        iniciarServidorSeNecessario();
        await executarEnvioDiretoAoFicarPronto();
    });

    cli.on('auth_failure', msg => {
        clientePronto = false;
        console.error('Falha na autenticacao:', msg);
    });

    cli.on('disconnected', reason => {
        clientePronto = false;
        console.log('Desconectado:', reason);
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

app.post('/enviar-mensagem', async (req, res) => {
    try {
        if (!validarClientePronto(res)) return;
        const { nome, numero, mensagem } = req.body;

        let chatId = null;
        if (numero) {
            chatId = formatarNumero(numero);
        } else if (nome) {
            chatId = await buscarContatoPorNome(nome);
        }

        if (!chatId) {
            return res.status(404).json({ erro: 'Contato nao encontrado' });
        }

        await executarComRetry(() => client.sendMessage(chatId, mensagem));
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

        let chatId = null;
        if (numero) {
            chatId = formatarNumero(numero);
        } else if (nome) {
            chatId = await buscarContatoPorNome(nome);
        }

        if (!chatId) {
            return res.status(404).json({ erro: 'Contato nao encontrado' });
        }

        const media = MessageMedia.fromFilePath(path.resolve(caminhoAudio));
        await executarComRetry(() => client.sendMessage(chatId, media, { sendAudioAsVoice: true }));

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

        let chatId = null;
        if (numero) {
            chatId = formatarNumero(numero);
        } else if (nome) {
            chatId = await buscarContatoPorNome(nome);
        }

        if (!chatId) {
            return res.status(404).json({ erro: 'Contato nao encontrado' });
        }

        const media = MessageMedia.fromFilePath(path.resolve(caminhoArquivo));
        await executarComRetry(() => client.sendMessage(chatId, media, { caption: legenda || '' }));

        res.json({ sucesso: true });
    } catch (err) {
        console.log('Erro ao enviar arquivo:', err);
        res.status(500).json({ erro: 'Erro interno' });
    }
});

async function iniciarClienteWhatsapp() {
    const maxTentativas = 4;
    for (let tentativa = 1; tentativa <= maxTentativas; tentativa++) {
        try {
            client = criarCliente();
            registrarEventosCliente(client);
            await client.initialize();
            await aguardarEventoReady(90000);
            return;
        } catch (err) {
            console.log(`Falha ao inicializar WhatsApp (tentativa ${tentativa}/${maxTentativas}):`, err);
            if (!erroTransitorioPuppeteer(err) || tentativa === maxTentativas) {
                throw err;
            }
            try { if (client) await client.destroy(); } catch (_) {}
            await delay(1500 * tentativa);
        }
    }
}

iniciarClienteWhatsapp().catch(err => {
    console.log('Erro fatal ao iniciar WhatsApp:', err);
    process.exit(1);
});
