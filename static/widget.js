(function () {
  "use strict";

  // ── Duplicate load guard ─────────────────────────────────────
  if (window.__leadbotLoaded) return;
  window.__leadbotLoaded = true;

  // ── API base resolution ──────────────────────────────────────
  const scriptTag = document.currentScript;
  const scriptOrigin = scriptTag?.src ? new URL(scriptTag.src).origin : null;
  const API_BASE =
    scriptTag?.getAttribute("data-api") ||
    window.INTAKE_API ||
    scriptOrigin ||
    "http://localhost:8000";

  // ── Multi-tenant ─────────────────────────────────────────────
  const TENANT_ID = scriptTag?.getAttribute("data-tenant-id") || null;

  // ── Configurable z-index ─────────────────────────────────────
  const Z_INDEX = scriptTag?.getAttribute("data-z-index") || "99999";

  let config = { business_name: "", color: "#2563eb", greeting: "", has_calendar: false };
  let sessionId = null;
  let isOpen = false;
  let isListening = false;
  let isProcessing = false;
  let recognition = null;
  let speechSupported = false;
  let voiceMode = false;
  let audioContext = null;
  let preChatCompleted = false;
  let preChatData = {};
  let lastLeadId = null;
  let isAfterHours = false;
  let faqEntries = [];
  let pendingPhotoUrl = null;
  let firstMessageSent = false;

  // ── Translations ──────────────────────────────────────────────
  const TRANSLATIONS = {
    en: {
      welcome: "Welcome!",
      prechat_subtitle: "Before we chat, please share your details so we can serve you better.",
      name_placeholder: "Your name",
      email_placeholder: "Email or phone",
      address_placeholder: "Property address",
      service_label: "What type of cleaning?",
      start_chat: "Start Chat",
      send: "Send",
      speak_or_type: "Speak or type...",
      type_message: "Type a message...",
      listening: "Listening...",
      after_hours_default: "We're currently closed. Leave a message and we'll get back to you!",
      greeting_fallback: "Hi there! How can I help you today?",
    },
    es: {
      welcome: "¡Bienvenido!",
      prechat_subtitle: "Antes de chatear, comparta sus datos para poder atenderle mejor.",
      name_placeholder: "Su nombre",
      email_placeholder: "Correo o teléfono",
      address_placeholder: "Dirección de la propiedad",
      service_label: "¿Qué tipo de limpieza?",
      start_chat: "Iniciar Chat",
      send: "Enviar",
      speak_or_type: "Habla o escribe...",
      type_message: "Escribe un mensaje...",
      listening: "Escuchando...",
      after_hours_default: "Estamos cerrados. Deje un mensaje y nos comunicaremos con usted.",
      greeting_fallback: "¡Hola! ¿En qué puedo ayudarle hoy?",
    },
    fr: {
      welcome: "Bienvenue !",
      prechat_subtitle: "Avant de discuter, partagez vos coordonnées pour mieux vous servir.",
      name_placeholder: "Votre nom",
      email_placeholder: "E-mail ou téléphone",
      address_placeholder: "Adresse de la propriété",
      service_label: "Quel type de nettoyage ?",
      start_chat: "Démarrer le Chat",
      send: "Envoyer",
      speak_or_type: "Parlez ou tapez...",
      type_message: "Tapez un message...",
      listening: "Écoute...",
      after_hours_default: "Nous sommes actuellement fermés. Laissez un message et nous vous recontacterons !",
      greeting_fallback: "Bonjour ! Comment puis-je vous aider aujourd'hui ?",
    },
    pt: {
      welcome: "Bem-vindo!",
      prechat_subtitle: "Antes de conversar, compartilhe seus dados para podermos atendê-lo melhor.",
      name_placeholder: "Seu nome",
      email_placeholder: "E-mail ou telefone",
      address_placeholder: "Endereço do imóvel",
      service_label: "Que tipo de limpeza?",
      start_chat: "Iniciar Chat",
      send: "Enviar",
      speak_or_type: "Fale ou digite...",
      type_message: "Digite uma mensagem...",
      listening: "Ouvindo...",
      after_hours_default: "Estamos fechados no momento. Deixe uma mensagem e entraremos em contato!",
      greeting_fallback: "Olá! Como posso ajudá-lo hoje?",
    },
    zh: {
      welcome: "欢迎！",
      prechat_subtitle: "在我们聊天之前，请分享您的详细信息，以便我们更好地为您服务。",
      name_placeholder: "您的姓名",
      email_placeholder: "电子邮件或电话",
      address_placeholder: "物业地址",
      service_label: "需要什么类型的清洁？",
      start_chat: "开始聊天",
      send: "发送",
      speak_or_type: "说话或输入...",
      type_message: "输入消息...",
      listening: "正在听...",
      after_hours_default: "我们目前已关闭。请留言，我们会尽快回复您！",
      greeting_fallback: "您好！今天我能为您做些什么？",
    },
  };

  function t(key) {
    const lang = config.language || "en";
    return (TRANSLATIONS[lang] && TRANSLATIONS[lang][key]) || TRANSLATIONS.en[key] || key;
  }

  // ── After-hours check ─────────────────────────────────────────
  function checkAfterHours() {
    if (!config.business_hours) return false;
    const { start, end, days } = config.business_hours;
    if (!start || !end || !days) return false;

    // Get current time in business timezone
    const tz = config.timezone || "America/New_York";
    const now = new Date();
    const tzStr = now.toLocaleString("en-US", { timeZone: tz });
    const tzDate = new Date(tzStr);

    const currentDay = tzDate.getDay();
    const currentHour = tzDate.getHours();
    const currentMinute = tzDate.getMinutes();
    const currentTime = currentHour * 60 + currentMinute;

    const [startH, startM] = start.split(":").map(Number);
    const [endH, endM] = end.split(":").map(Number);
    const startTime = startH * 60 + startM;
    const endTime = endH * 60 + endM;

    if (!days.includes(currentDay)) return true;
    if (currentTime < startTime || currentTime >= endTime) return true;
    return false;
  }

  // ── FAQ matching ──────────────────────────────────────────────
  function matchFaq(userMessage) {
    if (!faqEntries || faqEntries.length === 0) return null;
    const userWords = userMessage.toLowerCase().split(/\s+/).filter(w => w.length > 2);
    if (userWords.length === 0) return null;

    for (const entry of faqEntries) {
      const faqWords = entry.q.toLowerCase().split(/\s+/).filter(w => w.length > 2);
      if (faqWords.length === 0) continue;
      let matchCount = 0;
      for (const fw of faqWords) {
        if (userWords.some(uw => uw.includes(fw) || fw.includes(uw))) {
          matchCount++;
        }
      }
      if (matchCount / faqWords.length >= 0.6) {
        return entry.a;
      }
    }
    return null;
  }

  // ── Shadow DOM host ──────────────────────────────────────────
  let shadowRoot = null;

  function $(id) {
    return shadowRoot.getElementById(id);
  }

  function autoResizeInput() {
    const el = $("leadbot-text-input");
    if (!el) return;
    el.style.setProperty("height", "auto", "important");
    const sh = el.scrollHeight;
    const h = Math.max(40, Math.min(sh, 120));
    el.style.setProperty("height", h + "px", "important");
    el.style.setProperty("overflow", h >= 120 ? "auto" : "hidden", "important");
  }

  // ── Styles ──────────────────────────────────────────────────
  function getStyles(color) {
    return `
    :host { all: initial; }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
    #leadbot-bubble { position: fixed; bottom: 24px; right: 24px; width: 64px; height: 64px; border-radius: 50%; background: ${color}; color: white; border: none; cursor: pointer; box-shadow: 0 4px 24px rgba(0,0,0,0.18); display: flex; align-items: center; justify-content: center; z-index: ${Z_INDEX}; transition: transform 0.2s; padding-bottom: env(safe-area-inset-bottom, 0px); }
    #leadbot-bubble:hover { transform: scale(1.08); }
    #leadbot-bubble svg { width: 28px; height: 28px; fill: white; }
    #leadbot-panel { position: fixed; bottom: 100px; right: 24px; width: 380px; max-width: calc(100vw - 32px); height: 520px; max-height: calc(100vh - 140px); background: #fff; border-radius: 16px; box-shadow: 0 8px 40px rgba(0,0,0,0.16); display: flex; flex-direction: column; z-index: ${Z_INDEX}; overflow: hidden; opacity: 0; transform: translateY(16px) scale(0.96); pointer-events: none; transition: opacity 0.25s, transform 0.25s; }
    #leadbot-panel.open { opacity: 1; transform: translateY(0) scale(1); pointer-events: all; }
    #leadbot-header { background: ${color}; color: white; padding: 16px 20px; display: flex; align-items: center; gap: 12px; }
    #leadbot-header-dot { width: 10px; height: 10px; background: #4ade80; border-radius: 50%; flex-shrink: 0; }
    #leadbot-header-text { font-size: 15px; font-weight: 600; flex: 1; }
    #leadbot-restart-btn { background: none; border: none; color: rgba(255,255,255,0.8); cursor: pointer; padding: 4px; border-radius: 6px; display: flex; align-items: center; justify-content: center; transition: color 0.2s, background 0.2s; }
    #leadbot-restart-btn:hover { color: white; background: rgba(255,255,255,0.15); }
    #leadbot-messages { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
    .leadbot-msg { max-width: 82%; padding: 10px 14px; border-radius: 16px; font-size: 14px; line-height: 1.45; word-wrap: break-word; animation: leadbot-fade 0.25s; }
    @keyframes leadbot-fade { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
    .leadbot-msg.bot { background: #f1f5f9; color: #1e293b; align-self: flex-start; border-bottom-left-radius: 4px; }
    .leadbot-msg.user { background: ${color}; color: white; align-self: flex-end; border-bottom-right-radius: 4px; }
    .leadbot-msg.bot.typing { color: #94a3b8; }
    /* Animated typing indicator */
    .typing-dots { display: inline-flex; gap: 4px; align-items: center; padding: 4px 0; }
    .typing-dots span { width: 8px; height: 8px; border-radius: 50%; background: #94a3b8; animation: leadbot-bounce 1.4s ease-in-out infinite; }
    .typing-dots span:nth-child(2) { animation-delay: 0.2s; }
    .typing-dots span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes leadbot-bounce { 0%, 60%, 100% { transform: translateY(0); } 30% { transform: translateY(-6px); } }
    #leadbot-input-area { padding: 12px 16px; border-top: 1px solid #e2e8f0; display: flex; gap: 8px; align-items: flex-end; background: #fff; flex-shrink: 0; padding-bottom: calc(12px + env(safe-area-inset-bottom, 0px)); }
    #leadbot-text-input { flex: 1; border: 1px solid #e2e8f0; border-radius: 18px; padding: 10px 16px; font-size: 14px; outline: none; transition: border-color 0.2s; resize: none; overflow: hidden; line-height: 1.4; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: block; box-sizing: border-box; background: #fff; color: #1e293b; }
    #leadbot-text-input:focus { border-color: ${color}; }
    #leadbot-send-btn, #leadbot-mic-btn { width: 44px; height: 44px; border-radius: 50%; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: background 0.2s; flex-shrink: 0; }
    #leadbot-send-btn { background: ${color}; }
    #leadbot-send-btn:hover { opacity: 0.9; }
    #leadbot-send-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    #leadbot-send-btn svg { width: 18px; height: 18px; fill: white; }
    #leadbot-mic-btn { background: #f1f5f9; }
    #leadbot-mic-btn.listening { background: #fee2e2; animation: leadbot-pulse 1.2s infinite; }
    @keyframes leadbot-pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(239,68,68,0.3); } 50% { box-shadow: 0 0 0 10px rgba(239,68,68,0); } }
    #leadbot-mic-btn svg { width: 20px; height: 20px; }
    #leadbot-interrupt-hint { text-align: center; font-size: 11px; color: #94a3b8; padding: 0 16px 4px; display: none; }
    #leadbot-interrupt-hint.visible { display: block; }
    #leadbot-lead-banner { background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 12px; padding: 12px 16px; margin: 8px 16px; text-align: center; font-size: 13px; color: #065f46; animation: leadbot-fade 0.4s; }
    #leadbot-unavailable { padding: 40px 20px; text-align: center; color: #64748b; font-size: 14px; }
    #leadbot-after-hours-banner { background: #fef3c7; border-bottom: 1px solid #fde68a; padding: 10px 16px; font-size: 13px; color: #92400e; text-align: center; line-height: 1.4; flex-shrink: 0; }
    #leadbot-attach-btn { width: 44px; height: 44px; border-radius: 50%; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: background 0.2s; flex-shrink: 0; background: #f1f5f9; }
    #leadbot-attach-btn:hover { background: #e2e8f0; }
    #leadbot-attach-btn svg { width: 20px; height: 20px; }
    .leadbot-photo-thumb { max-width: 180px; max-height: 140px; border-radius: 10px; margin-top: 4px; display: block; }
    .leadbot-photo-uploading { opacity: 0.5; }
    /* Pre-chat form */
    #leadbot-prechat { padding: 24px 20px; display: flex; flex-direction: column; gap: 12px; flex: 1; justify-content: center; }
    #leadbot-prechat h3 { font-size: 16px; font-weight: 600; color: #1e293b; }
    #leadbot-prechat p { font-size: 13px; color: #64748b; }
    .prechat-input { border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 14px; font-size: 14px; outline: none; width: 100%; font-family: inherit; }
    .prechat-input:focus { border-color: ${color}; }
    .prechat-btn { background: ${color}; color: white; border: none; border-radius: 10px; padding: 12px; font-size: 14px; font-weight: 600; cursor: pointer; transition: opacity 0.15s; }
    .prechat-btn:hover { opacity: 0.9; }
    /* Calendar slots */
    .slot-grid { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .slot-btn { background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 8px; padding: 6px 12px; font-size: 13px; cursor: pointer; transition: all 0.15s; }
    .slot-btn:hover { background: ${color}; color: white; border-color: ${color}; }

    /* Responsive breakpoints */
    @media (max-width: 480px) {
      #leadbot-panel { bottom: 0; right: 0; width: 100vw; height: 100vh; max-height: 100vh; border-radius: 0; }
      #leadbot-bubble { bottom: 16px; right: 16px; }
    }
    @media (min-width: 481px) and (max-width: 768px) {
      #leadbot-panel { width: 90vw; height: 80vh; }
    }
    `;
  }

  // ── Icons ───────────────────────────────────────────────────
  const ICON_CHAT = '<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.2L4 17.2V4h16v12z"/></svg>';
  const ICON_CLOSE = '<svg viewBox="0 0 24 24"><path d="M19 6.4L17.6 5 12 10.6 6.4 5 5 6.4l5.6 5.6L5 17.6 6.4 19l5.6-5.6 5.6 5.6 1.4-1.4-5.6-5.6z"/></svg>';
  const ICON_SEND = '<svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>';
  const ICON_MIC = '<svg viewBox="0 0 24 24"><path fill="#64748b" d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm-1-9c0-.55.45-1 1-1s1 .45 1 1v6c0 .55-.45 1-1 1s-1-.45-1-1V5zm6 6c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/></svg>';
  const ICON_RESTART = '<svg viewBox="0 0 24 24" width="20" height="20"><path fill="currentColor" d="M17.65 6.35A7.96 7.96 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>';
  const ICON_MIC_ON = '<svg viewBox="0 0 24 24"><path fill="#ef4444" d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm-1-9c0-.55.45-1 1-1s1 .45 1 1v6c0 .55-.45 1-1 1s-1-.45-1-1V5zm6 6c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/></svg>';
  const ICON_ATTACH = '<svg viewBox="0 0 24 24"><path fill="#64748b" d="M21.58 11.4l-9.17 9.17c-2.34 2.34-6.14 2.34-8.49 0-2.34-2.34-2.34-6.14 0-8.49l9.17-9.17c1.56-1.56 4.09-1.56 5.66 0 1.56 1.56 1.56 4.09 0 5.66l-9.17 9.17c-.78.78-2.05.78-2.83 0-.78-.78-.78-2.05 0-2.83l7.07-7.07 1.41 1.41-7.07 7.07 2.83-2.83 9.17-9.17c-.78-.78-.78-2.05 0-2.83l-9.17 9.17c-1.56 1.56-1.56 4.09 0 5.66 1.56 1.56 4.09 1.56 5.66 0l9.17-9.17-1.41-1.41z"/></svg>';
  const ICON_CAMERA = '<svg viewBox="0 0 24 24"><path fill="#64748b" d="M12 12m-3.2 0a3.2 3.2 0 1 0 6.4 0 3.2 3.2 0 1 0-6.4 0M9 2L7.17 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2h-3.17L15 2H9zm3 15c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5z"/></svg>';

  // ── iOS Audio Unlock ─────────────────────────────────────────
  function unlockAudio() {
    if (audioContext) return;
    try {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      audioContext.resume();
      const buffer = audioContext.createBuffer(1, 1, 22050);
      const source = audioContext.createBufferSource();
      source.buffer = buffer;
      source.connect(audioContext.destination);
      source.start(0);
    } catch (e) {}
  }

  // ── Init ────────────────────────────────────────────────────
  let configFailed = false;

  async function init() {
    try {
      const configUrl = TENANT_ID
        ? `${API_BASE}/api/config/${TENANT_ID}`
        : `${API_BASE}/api/config`;
      const res = await fetch(configUrl);
      if (!res.ok) throw new Error("Config fetch failed");
      config = await res.json();
    } catch (e) {
      console.warn("LeadBot: could not fetch config, using defaults");
      configFailed = true;
    }

    // Store FAQ entries and check after-hours
    faqEntries = config.faq_entries || [];
    isAfterHours = checkAfterHours();

    speechSupported =
      "webkitSpeechRecognition" in window || "SpeechRecognition" in window;

    createShadowDOM();
    setupEvents();
    setupViewportHandler();
  }

  function createShadowDOM() {
    const host = document.createElement("div");
    host.id = "leadbot-root";
    shadowRoot = host.attachShadow({ mode: "open" });

    const style = document.createElement("style");
    style.textContent = getStyles(config.color);
    shadowRoot.appendChild(style);

    const container = document.createElement("div");
    container.innerHTML = `
      <button id="leadbot-bubble" aria-label="Chat with us">${ICON_CHAT}</button>
      <div id="leadbot-panel">
        <div id="leadbot-header">
          <div id="leadbot-header-dot"></div>
          <div id="leadbot-header-text">${config.business_name}</div>
          <button id="leadbot-restart-btn" aria-label="Restart conversation" title="Start over">${ICON_RESTART}</button>
        </div>
        ${configFailed
          ? '<div id="leadbot-unavailable">Chat is temporarily unavailable. Please try again later.</div>'
          : `<div id="leadbot-prechat">
          <h3>${t("welcome")}</h3>
          <p>${t("prechat_subtitle")}</p>
          <input class="prechat-input" id="leadbot-prechat-name" placeholder="${t("name_placeholder")}" autocomplete="name">
          <input class="prechat-input" id="leadbot-prechat-email" placeholder="${t("email_placeholder")}" type="email" autocomplete="email">
          <input class="prechat-input" id="leadbot-prechat-address" placeholder="${t("address_placeholder")}" autocomplete="street-address">
          <select class="prechat-input" id="leadbot-prechat-service" style="color:#64748b">
            <option value="">${t("service_label")}</option>
            <option value="regular">Regular Cleaning</option>
            <option value="deep_clean">Deep Clean</option>
            <option value="move_in_out">Move In/Out</option>
            <option value="office">Office Cleaning</option>
            <option value="post_construction">Post-Construction</option>
          </select>
          <button class="prechat-btn" id="leadbot-prechat-btn">${t("start_chat")}</button>
        </div>
        ${isAfterHours ? `<div id="leadbot-after-hours-banner">${config.after_hours_message || t("after_hours_default")}</div>` : ""}
        <div id="leadbot-messages" style="display:none"></div>
        <div id="leadbot-interrupt-hint">Press Space or tap here to interrupt and speak</div>
        <div id="leadbot-input-area" style="display:none">
          ${speechSupported ? `<button id="leadbot-mic-btn" aria-label="Voice input">${ICON_MIC}</button>` : ""}
          <button id="leadbot-attach-btn" aria-label="Attach photo">${ICON_CAMERA}</button>
          <input type="file" id="leadbot-file-input" accept="image/*" style="display:none">
          <textarea id="leadbot-text-input" rows="1" placeholder="${speechSupported ? t("speak_or_type") : t("type_message")}" autocomplete="off"></textarea>
          <button id="leadbot-send-btn" aria-label="${t("send")}" disabled>${ICON_SEND}</button>
        </div>`
        }
      </div>
    `;
    shadowRoot.appendChild(container);
    document.body.appendChild(host);
  }

  // ── Mobile keyboard / viewport handling ─────────────────────
  function setupViewportHandler() {
    if (!window.visualViewport) return;
    window.visualViewport.addEventListener("resize", () => {
      if (!isOpen) return;
      const panel = $("leadbot-panel");
      if (!panel) return;
      const vvh = window.visualViewport.height;
      if (window.innerWidth <= 480) {
        panel.style.height = vvh + "px";
        panel.style.maxHeight = vvh + "px";
      }
      const messages = $("leadbot-messages");
      if (messages) messages.scrollTop = messages.scrollHeight;
    });
  }

  function startChat() {
    preChatCompleted = true;
    const prechatEl = $("leadbot-prechat");
    const messagesEl = $("leadbot-messages");
    const inputArea = $("leadbot-input-area");
    if (prechatEl) prechatEl.style.display = "none";
    if (messagesEl) messagesEl.style.display = "flex";
    if (inputArea) inputArea.style.display = "flex";

    addMessage(config.greeting, "bot");
    speak(config.greeting);

    const input = $("leadbot-text-input");
    if (input) input.focus();
  }

  function setupEvents() {
    if (configFailed) {
      const bubble = $("leadbot-bubble");
      const panel = $("leadbot-panel");
      bubble.addEventListener("click", () => {
        unlockAudio();
        isOpen = !isOpen;
        panel.classList.toggle("open", isOpen);
        bubble.innerHTML = isOpen ? ICON_CLOSE : ICON_CHAT;
      });
      return;
    }

    const bubble = $("leadbot-bubble");
    const panel = $("leadbot-panel");
    const input = $("leadbot-text-input");
    const sendBtn = $("leadbot-send-btn");
    const micBtn = $("leadbot-mic-btn");
    const restartBtn = $("leadbot-restart-btn");
    const messages = $("leadbot-messages");
    const interruptHint = $("leadbot-interrupt-hint");
    const prechatBtn = $("leadbot-prechat-btn");

    // ── Pre-chat form ──
    if (prechatBtn) {
      prechatBtn.addEventListener("click", () => {
        preChatData = {
          name: $("leadbot-prechat-name")?.value?.trim() || "",
          email: $("leadbot-prechat-email")?.value?.trim() || "",
          address: $("leadbot-prechat-address")?.value?.trim() || "",
          service: $("leadbot-prechat-service")?.value || "",
        };
        startChat();
      });
    }

    // ── Auto-resize textarea ──
    input.addEventListener("input", autoResizeInput);
    setInterval(autoResizeInput, 200);

    // ── Restart conversation ──
    restartBtn.addEventListener("click", resetConversation);

    bubble.addEventListener("click", () => {
      unlockAudio();
      isOpen = !isOpen;
      panel.classList.toggle("open", isOpen);
      bubble.innerHTML = isOpen ? ICON_CLOSE : ICON_CHAT;
      if (isOpen && preChatCompleted && !sessionId) {
        addMessage(config.greeting, "bot");
        speak(config.greeting);
      }
      if (isOpen && preChatCompleted) input.focus();
    });

    input.addEventListener("input", () => {
      sendBtn.disabled = !input.value.trim() || isProcessing;
      autoResizeInput();
    });

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && input.value.trim() && !isProcessing) {
        e.preventDefault();
        sendMessage(input.value.trim());
        input.style.height = "auto";
      } else if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
      }
    });

    sendBtn.addEventListener("click", () => {
      if (input.value.trim() && !isProcessing) sendMessage(input.value.trim());
    });

    if (micBtn && speechSupported) {
      setupSpeechRecognition();
      micBtn.addEventListener("click", toggleListening);
    }

    // ── Photo upload ──
    const attachBtn = $("leadbot-attach-btn");
    const fileInput = $("leadbot-file-input");
    if (attachBtn && fileInput) {
      attachBtn.addEventListener("click", () => fileInput.click());
      fileInput.addEventListener("change", async () => {
        const file = fileInput.files[0];
        if (!file) return;
        fileInput.value = "";

        // Show thumbnail preview immediately
        const messages = $("leadbot-messages");
        const thumbDiv = document.createElement("div");
        thumbDiv.className = "leadbot-msg user";
        const img = document.createElement("img");
        img.className = "leadbot-photo-thumb leadbot-photo-uploading";
        img.src = URL.createObjectURL(file);
        thumbDiv.appendChild(img);
        messages.appendChild(thumbDiv);
        messages.scrollTop = messages.scrollHeight;

        try {
          const formData = new FormData();
          formData.append("image", file);
          const res = await fetch(`${API_BASE}/api/upload`, {
            method: "POST",
            body: formData,
          });
          if (!res.ok) throw new Error("Upload failed");
          const data = await res.json();
          const photoUrl = data.url.startsWith("http") ? data.url : `${API_BASE}${data.url}`;
          img.src = photoUrl;
          img.classList.remove("leadbot-photo-uploading");
          pendingPhotoUrl = photoUrl;

          // If there's text in the input, send it with the photo; otherwise send standalone
          const currentText = input.value.trim();
          if (currentText) {
            sendMessage(currentText);
          } else {
            sendMessage("");
          }
        } catch (e) {
          console.error("Photo upload error:", e);
          img.classList.remove("leadbot-photo-uploading");
          thumbDiv.style.opacity = "0.5";
          const errMsg = document.createElement("div");
          errMsg.style.fontSize = "11px";
          errMsg.style.color = "#ef4444";
          errMsg.textContent = "Upload failed";
          thumbDiv.appendChild(errMsg);
        }
      });
    }

    // ── Interrupt: spacebar or click on messages area ──────
    document.addEventListener("keydown", (e) => {
      if (!isOpen || !voiceMode || !isSpeaking) return;
      if (e.code === "Space" && document.activeElement !== input) {
        e.preventDefault();
        interruptAndListen();
      }
    });

    messages.addEventListener("click", () => {
      if (voiceMode && isSpeaking) {
        interruptAndListen();
      }
    });

    if (interruptHint) {
      interruptHint.addEventListener("click", () => {
        if (voiceMode && isSpeaking) {
          interruptAndListen();
        }
      });
    }
  }

  // ── Interrupt TTS and start listening ─────────────────────
  function interruptAndListen() {
    if (currentAudio) {
      currentAudio.pause();
      currentAudio.onended = null;
      currentAudio = null;
    }
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    isSpeaking = false;
    setInterruptHint(false);
    restartRecognition();
  }

  function setInterruptHint(visible) {
    const hint = $("leadbot-interrupt-hint");
    if (hint) hint.classList.toggle("visible", visible);
  }

  // ── Speech Recognition ──────────────────────────────────────
  let silenceTimer = null;
  const SILENCE_DELAY = 1500;
  let resultIndexOffset = 0;

  function setupSpeechRecognition() {
    const SpeechRecognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    const input = $("leadbot-text-input");

    recognition.onresult = (event) => {
      let fullFinal = "";
      let currentInterim = "";
      for (let i = resultIndexOffset; i < event.results.length; i++) {
        if (event.results[i].isFinal) {
          fullFinal += event.results[i][0].transcript;
        } else {
          currentInterim += event.results[i][0].transcript;
        }
      }

      const display = fullFinal + currentInterim;
      input.value = display;
      autoResizeInput();
      $("leadbot-send-btn").disabled = !display.trim();

      clearTimeout(silenceTimer);

      if (fullFinal.trim() && !currentInterim) {
        silenceTimer = setTimeout(() => {
          const text = input.value.trim();
          if (text && !isProcessing) {
            resultIndexOffset = event.results.length;
            sendMessage(text);
            input.value = "";
          }
        }, SILENCE_DELAY);
      }
    };

    recognition.onerror = (e) => {
      if (e.error === "no-speech") return;
      if (e.error === "aborted") return;
      stopListening();
    };

    recognition.onend = () => {
      if (voiceMode && isListening && !isSpeaking) {
        try { recognition.start(); } catch (e) {}
      }
    };
  }

  function restartRecognition() {
    if (!recognition) return;
    try { recognition.stop(); } catch (e) {}
    resultIndexOffset = 0;
    isListening = true;
    const micBtn = $("leadbot-mic-btn");
    if (micBtn) {
      micBtn.classList.add("listening");
      micBtn.innerHTML = ICON_MIC_ON;
    }
    $("leadbot-text-input").placeholder = t("listening");
    setTimeout(() => {
      if (voiceMode && !isSpeaking) {
        try { recognition.start(); } catch (e) {}
      }
    }, 100);
  }

  function toggleListening() {
    if (isListening) {
      voiceMode = false;
      stopListening();
    } else {
      startListening();
    }
  }

  function startListening() {
    if (!recognition) return;
    voiceMode = true;
    isListening = true;
    const micBtn = $("leadbot-mic-btn");
    micBtn.classList.add("listening");
    micBtn.innerHTML = ICON_MIC_ON;
    $("leadbot-text-input").placeholder = t("listening");
    try {
      recognition.start();
    } catch (e) {
      stopListening();
    }
  }

  function stopListening() {
    isListening = false;
    clearTimeout(silenceTimer);
    const micBtn = $("leadbot-mic-btn");
    if (micBtn) {
      micBtn.classList.remove("listening");
      micBtn.innerHTML = ICON_MIC;
    }
    const input = $("leadbot-text-input");
    if (input) input.placeholder = speechSupported ? t("speak_or_type") : t("type_message");
    try {
      recognition?.stop();
    } catch (e) {}
  }

  // ── Text-to-Speech (Neural via backend) ─────────────────────
  let currentAudio = null;
  let isSpeaking = false;

  async function speak(text) {
    if (currentAudio) {
      currentAudio.pause();
      currentAudio.onended = null;
      currentAudio = null;
    }

    if (voiceMode && isListening) {
      try { recognition?.stop(); } catch (e) {}
      isListening = false;
    }
    isSpeaking = true;
    setInterruptHint(voiceMode);

    try {
      const res = await fetch(`${API_BASE}/api/tts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });

      if (!res.ok) throw new Error("TTS failed");

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      currentAudio = new Audio(url);
      currentAudio.onended = () => {
        URL.revokeObjectURL(url);
        currentAudio = null;
        isSpeaking = false;
        setInterruptHint(false);
        if (voiceMode) restartRecognition();
      };
      await currentAudio.play();
    } catch (e) {
      console.warn("TTS error, falling back to browser speech:", e);
      if ("speechSynthesis" in window) {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 1.05;
        utterance.onend = () => {
          isSpeaking = false;
          setInterruptHint(false);
          if (voiceMode) restartRecognition();
        };
        const voices = window.speechSynthesis.getVoices();
        const preferred = voices.find(
          (v) => v.lang.startsWith("en") && v.name.includes("Female")
        ) || voices.find((v) => v.lang.startsWith("en"));
        if (preferred) utterance.voice = preferred;
        window.speechSynthesis.speak(utterance);
      } else {
        isSpeaking = false;
        setInterruptHint(false);
        if (voiceMode) restartRecognition();
      }
    }
  }

  // ── Chat Logic ──────────────────────────────────────────────
  function addMessage(text, role) {
    const messages = $("leadbot-messages");
    const div = document.createElement("div");
    div.className = `leadbot-msg ${role}`;
    div.textContent = text;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
  }

  function addTypingIndicator() {
    const messages = $("leadbot-messages");
    const div = document.createElement("div");
    div.className = "leadbot-msg bot typing";
    div.innerHTML = '<div class="typing-dots"><span></span><span></span><span></span></div>';
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
  }

  function renderCalendarSlots(slots, leadId) {
    if (leadId) lastLeadId = leadId;
    const messages = $("leadbot-messages");
    const div = document.createElement("div");
    div.className = "leadbot-msg bot";

    // Group by date
    const byDate = {};
    for (const slot of slots) {
      const d = new Date(slot.start);
      const dateKey = d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
      if (!byDate[dateKey]) byDate[dateKey] = [];
      byDate[dateKey].push(slot);
    }

    const tz = config.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone;
    const tzLabel = tz.replace("America/", "").replace("Pacific/", "").replace(/_/g, " ");
    let html = `Pick a time (${tzLabel}):`;
    for (const [dateLabel, dateSlots] of Object.entries(byDate)) {
      html += `<div style="font-size:12px;font-weight:600;color:#64748b;margin-top:8px">${dateLabel}</div><div class='slot-grid'>`;
      for (const slot of dateSlots) {
        const start = new Date(slot.start);
        const label = start.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", timeZone: tz });
        html += `<button class="slot-btn" data-start="${slot.start}" data-end="${slot.end}">${label}</button>`;
      }
      html += "</div>";
    }
    div.innerHTML = html;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;

    // Wire up slot buttons to book directly
    div.querySelectorAll(".slot-btn").forEach((btn) => {
      btn.addEventListener("click", () => bookSlot(btn, div));
    });
  }

  async function bookSlot(btn, container) {
    const start = btn.getAttribute("data-start");
    const end = btn.getAttribute("data-end");
    const email = preChatData.email || "";

    if (!lastLeadId) {
      addMessage("Sorry, something went wrong with booking. Please call us directly.", "bot");
      return;
    }

    // Disable all slot buttons
    container.querySelectorAll(".slot-btn").forEach((b) => {
      b.disabled = true;
      b.style.opacity = "0.5";
      b.style.cursor = "default";
    });
    btn.style.opacity = "1";
    btn.textContent = "Booking...";

    try {
      const res = await fetch(`${API_BASE}/api/book`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: TENANT_ID || "default",
          lead_id: lastLeadId,
          start_time: start,
          end_time: end,
          attendee_email: email || "customer@example.com",
        }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      // Show confirmation
      const time = new Date(start).toLocaleString(undefined, {
        weekday: "short", month: "short", day: "numeric",
        hour: "2-digit", minute: "2-digit",
      });
      btn.textContent = "Booked!";
      btn.style.background = "#059669";
      btn.style.color = "white";
      btn.style.borderColor = "#059669";

      addMessage(`Your appointment is confirmed for ${time}. You'll receive a calendar invite at ${email || "your email"}. See you then!`, "bot");
    } catch (e) {
      console.error("Booking error:", e);
      btn.textContent = "Failed";
      addMessage("Sorry, I couldn't book that slot. Please try another time or call us directly.", "bot");
    }
  }

  // ── SSE retry with backoff ──────────────────────────────────
  let sseRetryCount = 0;
  const MAX_SSE_RETRIES = 3;

  async function sendMessage(text) {
    const input = $("leadbot-text-input");
    const sendBtn = $("leadbot-send-btn");

    clearTimeout(silenceTimer);
    input.value = "";
    sendBtn.disabled = true;
    isProcessing = true;

    if (voiceMode && recognition) {
      restartRecognition();
    }

    // Append photo URL if one is pending
    if (pendingPhotoUrl) {
      text = text ? `${text} [Photo: ${pendingPhotoUrl}]` : `[Photo: ${pendingPhotoUrl}]`;
      pendingPhotoUrl = null;
    }

    // Check FAQ before calling API
    const faqAnswer = matchFaq(text);
    if (faqAnswer) {
      addMessage(text, "user");
      addMessage(faqAnswer, "bot");
      isProcessing = false;
      return;
    }

    addMessage(text, "user");
    const typingEl = addTypingIndicator();

    try {
      let apiMessage = text;
      // Prepend after-hours tag
      if (isAfterHours) {
        apiMessage = "[After Hours] " + apiMessage;
      }

      const body = { session_id: sessionId, message: apiMessage };
      if (TENANT_ID) body.tenant_id = TENANT_ID;

      // Include source on first message
      if (!firstMessageSent) {
        body.source = window.location.href;
        firstMessageSent = true;
      }

      // Include pre-chat data in first message
      if (preChatData.name && !sessionId) {
        const parts = [`Name: ${preChatData.name}`];
        if (preChatData.email) parts.push(`Contact: ${preChatData.email}`);
        if (preChatData.address) parts.push(`Address: ${preChatData.address}`);
        if (preChatData.service) parts.push(`Service: ${preChatData.service.replace("_", " ")}`);
        body.message = `[${parts.join(", ")}] ${apiMessage}`;
      }

      const res = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      sseRetryCount = 0;

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let botText = "";
      let firstChunk = true;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split("\n");

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = JSON.parse(line.slice(6));

          if (!sessionId && data.session_id) sessionId = data.session_id;

          if (data.type === "text") {
            if (firstChunk) {
              typingEl.textContent = "";
              typingEl.classList.remove("typing");
              typingEl.innerHTML = "";
              firstChunk = false;
            }
            if (firstChunk === false && typingEl.textContent === "") {
              botText = data.content;
            } else {
              botText += data.content;
            }
            typingEl.textContent = botText;
            $("leadbot-messages").scrollTop = $("leadbot-messages").scrollHeight;
          }

          if (data.type === "lead_captured") {
            showLeadBanner();
            if (data.lead_id) lastLeadId = data.lead_id;
            console.log("Lead captured:", data.lead);
          }

          if (data.type === "calendar_slots" && data.slots) {
            renderCalendarSlots(data.slots, data.lead_id);
          }
        }
      }

      if (botText) {
        speak(botText);
      }
    } catch (e) {
      sseRetryCount++;
      if (sseRetryCount <= MAX_SSE_RETRIES) {
        typingEl.textContent = "Connection lost. Retrying...";
        typingEl.classList.remove("typing");
        typingEl.innerHTML = typingEl.textContent;
        const delay = Math.min(1000 * Math.pow(2, sseRetryCount - 1), 8000);
        await new Promise((r) => setTimeout(r, delay));
        isProcessing = false;
        sendMessage(text);
        const messages = $("leadbot-messages");
        const userMsgs = messages.querySelectorAll(".leadbot-msg.user");
        if (userMsgs.length > 1) {
          const last = userMsgs[userMsgs.length - 1];
          if (last.textContent === text) last.remove();
        }
        typingEl.remove();
        return;
      }
      typingEl.textContent = "Sorry, something went wrong. Please try again.";
      typingEl.classList.remove("typing");
      typingEl.innerHTML = typingEl.textContent;
      console.error("LeadBot error:", e);
    }

    isProcessing = false;
  }

  function resetConversation() {
    if (currentAudio) {
      currentAudio.pause();
      currentAudio.onended = null;
      currentAudio = null;
    }
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    isSpeaking = false;
    setInterruptHint(false);
    clearTimeout(silenceTimer);

    if (voiceMode && isListening) {
      stopListening();
      voiceMode = false;
    }

    if (sessionId) {
      const body = { session_id: sessionId };
      if (TENANT_ID) body.tenant_id = TENANT_ID;
      fetch(`${API_BASE}/api/reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).catch(() => {});
    }

    sessionId = null;
    isProcessing = false;
    sseRetryCount = 0;
    preChatCompleted = false;
    preChatData = {};
    firstMessageSent = false;
    pendingPhotoUrl = null;

    // Show pre-chat form again
    const prechatEl = $("leadbot-prechat");
    const messagesEl = $("leadbot-messages");
    const inputArea = $("leadbot-input-area");
    if (prechatEl) prechatEl.style.display = "flex";
    if (messagesEl) { messagesEl.style.display = "none"; messagesEl.innerHTML = ""; }
    if (inputArea) inputArea.style.display = "none";

    const nameInput = $("leadbot-prechat-name");
    const emailInput = $("leadbot-prechat-email");
    const addrInput = $("leadbot-prechat-address");
    const svcInput = $("leadbot-prechat-service");
    if (nameInput) nameInput.value = "";
    if (emailInput) emailInput.value = "";
    if (addrInput) addrInput.value = "";
    if (svcInput) svcInput.value = "";

    const input = $("leadbot-text-input");
    if (input) { input.value = ""; input.style.height = "auto"; }
    const sendBtn = $("leadbot-send-btn");
    if (sendBtn) sendBtn.disabled = true;
  }

  function showLeadBanner() {
    const messages = $("leadbot-messages");
    const banner = document.createElement("div");
    banner.id = "leadbot-lead-banner";
    banner.textContent = "Your info has been sent to the team — expect a call shortly!";
    messages.appendChild(banner);
    messages.scrollTop = messages.scrollHeight;
  }

  // ── Boot ────────────────────────────────────────────────────
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
