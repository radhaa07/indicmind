/**
 * Voice Command & Speech-to-Text System for ContractLens AI
 * Supports Web Speech API (Chrome, Edge, Safari, Opera)
 * Handles input dictation and intelligent hands-free voice commands
 */

(function () {
  'use strict';

  // Check speech recognition support
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null;
  let isListening = false;
  let currentTargetInput = null;
  let activeMicButton = null;
  let hudElement = null;
  let audioCtx = null;
  // Per-session overrides set by startListening's options argument
  let sessionLang = null;
  let dictateOnly = false;
  // Continuous dictation (voice-note mic): stays on across pauses until the
  // user toggles it off; finals accumulate instead of replacing.
  let continuousMode = false;
  let wantListening = false;
  let finalAccum = '';

  // Sound cues via Web Audio API
  function playSoundCue(type) {
    try {
      if (!audioCtx) {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      }
      if (audioCtx.state === 'suspended') {
        audioCtx.resume();
      }
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.connect(gain);
      gain.connect(audioCtx.destination);

      if (type === 'start') {
        osc.frequency.setValueAtTime(440, audioCtx.currentTime);
        osc.frequency.exponentialRampToValueAtTime(880, audioCtx.currentTime + 0.15);
        gain.gain.setValueAtTime(0.1, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.15);
        osc.start();
        osc.stop(audioCtx.currentTime + 0.15);
      } else if (type === 'stop') {
        osc.frequency.setValueAtTime(880, audioCtx.currentTime);
        osc.frequency.exponentialRampToValueAtTime(440, audioCtx.currentTime + 0.12);
        gain.gain.setValueAtTime(0.1, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.12);
        osc.start();
        osc.stop(audioCtx.currentTime + 0.12);
      } else if (type === 'command') {
        osc.frequency.setValueAtTime(587.33, audioCtx.currentTime); // D5
        osc.frequency.setValueAtTime(880, audioCtx.currentTime + 0.08); // A5
        gain.gain.setValueAtTime(0.12, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.2);
        osc.start();
        osc.stop(audioCtx.currentTime + 0.2);
      }
    } catch (_) {}
  }

  // Create or retrieve Voice HUD overlay
  function getOrCreateHUD() {
    if (hudElement) return hudElement;

    hudElement = document.createElement('div');
    hudElement.id = 'voice-hud';
    hudElement.className = 'voice-hud';
    hudElement.innerHTML = `
      <div class="voice-hud-card">
        <div class="voice-hud-header">
          <div class="voice-hud-status">
            <span class="voice-hud-pulse"></span>
            <span class="voice-hud-title">Voice Listening Active</span>
          </div>
          <button type="button" class="voice-hud-close" id="voice-hud-close-btn" title="Stop listening">✕</button>
        </div>
        <div class="voice-hud-body">
          <div class="voice-hud-waves">
            <span></span><span></span><span></span><span></span><span></span>
          </div>
          <p class="voice-hud-preview" id="voice-hud-preview">Speak now (e.g. "What are the payment terms?", "Analyse", "Go to risks")...</p>
        </div>
        <div class="voice-hud-hints">
          <span class="hint-tag" onclick="window.executeVoiceCommand('Analyse')">💬 "Analyse"</span>
          <span class="hint-tag" onclick="window.executeVoiceCommand('Go to risks')">⚠️ "Go to risks"</span>
          <span class="hint-tag" onclick="window.executeVoiceCommand('Go to clauses')">📜 "Clauses"</span>
          <span class="hint-tag" onclick="window.executeVoiceCommand('Listen to summary')">🔊 "Listen to summary"</span>
          <span class="hint-tag" onclick="window.executeVoiceCommand('Clear')">🗑️ "Clear"</span>
        </div>
      </div>
    `;

    document.body.appendChild(hudElement);

    document.getElementById('voice-hud-close-btn').addEventListener('click', () => {
      stopListening();
    });

    return hudElement;
  }

  function showHUD(initialText) {
    const hud = getOrCreateHUD();
    const preview = document.getElementById('voice-hud-preview');
    if (preview) preview.textContent = initialText || 'Listening... Speak clearly into your microphone.';
    hud.classList.add('active');
  }

  function hideHUD() {
    if (hudElement) {
      hudElement.classList.remove('active');
    }
  }

  function updateHUDPreview(text, isCommand = false) {
    const preview = document.getElementById('voice-hud-preview');
    if (preview) {
      if (isCommand) {
        preview.innerHTML = `⚡ <strong style="color: #f6db48;">Command:</strong> ${text}`;
      } else {
        preview.textContent = text || 'Listening...';
      }
    }
  }

  // Voice Command Execution Engine
  window.executeVoiceCommand = function (rawCommand) {
    const cmd = rawCommand.toLowerCase().trim();
    if (!cmd) return false;

    // 1. Navigation Commands
    if (cmd.includes('summary') || cmd.includes('report') || cmd.includes('executive summary') || cmd.includes('go to summary') || cmd.includes('show summary') || cmd.includes('open summary')) {
      if (typeof window.switchTab === 'function') window.switchTab('tab-report');
      playSoundCue('command');
      updateHUDPreview('Switching to Executive Summary Report', true);
      return true;
    }

    if (cmd.includes('clause') || cmd.includes('clauses') || cmd.includes('go to clause') || cmd.includes('show clauses') || cmd.includes('key clauses')) {
      if (typeof window.switchTab === 'function') window.switchTab('tab-clauses');
      playSoundCue('command');
      updateHUDPreview('Switching to Key Clauses', true);
      return true;
    }

    if (cmd.includes('risk') || cmd.includes('risks') || cmd.includes('compliance') || cmd.includes('audit') || cmd.includes('go to risk') || cmd.includes('show risks')) {
      if (typeof window.switchTab === 'function') window.switchTab('tab-risks');
      playSoundCue('command');
      updateHUDPreview('Switching to Risks & Compliance Audit', true);
      return true;
    }

    if (cmd.includes('q&a') || cmd.includes('qa') || cmd.includes('ask') || cmd.includes('intelligent qa') || cmd.includes('questions') || cmd.includes('go to qa') || cmd.includes('go to q&a')) {
      if (typeof window.switchTab === 'function') window.switchTab('tab-qa');
      const qInput = document.getElementById('question');
      if (qInput) qInput.focus();
      playSoundCue('command');
      updateHUDPreview('Opening Intelligent Q&A', true);
      return true;
    }

    // 2. Chatbot Assistant Commands
    if (cmd === 'open chat' || cmd === 'open assistant' || cmd === 'chat' || cmd === 'show assistant' || cmd === 'start chat') {
      const widget = document.getElementById('chatbot-widget');
      if (widget) {
        widget.hidden = false;
        const cInput = document.getElementById('chatbot-input');
        if (cInput) cInput.focus();
      }
      playSoundCue('command');
      updateHUDPreview('Opened Contract AI Assistant', true);
      return true;
    }

    if (cmd === 'close chat' || cmd === 'close assistant' || cmd === 'hide chat') {
      const widget = document.getElementById('chatbot-widget');
      if (widget) widget.hidden = true;
      playSoundCue('command');
      updateHUDPreview('Closed Contract AI Assistant', true);
      return true;
    }

    // 3. Audio TTS Commands
    if (cmd.includes('listen to summary') || cmd.includes('read summary') || cmd.includes('play audio') || cmd.includes('listen summary') || cmd.includes('read report')) {
      const ttsBtn = document.getElementById('tts-summary-btn');
      if (ttsBtn && window.contractId && typeof window.playSummaryTTS === 'function') {
        window.playSummaryTTS(window.contractId, ttsBtn);
        playSoundCue('command');
        updateHUDPreview('Playing Audio Executive Summary', true);
        return true;
      }
    }

    if (cmd.includes('stop audio') || cmd.includes('stop reading') || cmd.includes('pause audio') || cmd.includes('stop listening') || cmd === 'stop') {
      if (typeof window.stopTTS === 'function') {
        window.stopTTS();
        playSoundCue('command');
        updateHUDPreview('Audio playback stopped', true);
        return true;
      }
    }

    // 4. Action & Submission Commands
    if (cmd === 'analyse' || cmd === 'analyze' || cmd === 'submit' || cmd === 'run analysis' || cmd === 'ask question') {
      // Check if Chatbot is open and focused
      const chatWidget = document.getElementById('chatbot-widget');
      const chatInput = document.getElementById('chatbot-input');
      if (chatWidget && !chatWidget.hidden && chatInput && chatInput.value.trim()) {
        const chatForm = document.getElementById('chatbot-form');
        if (chatForm) chatForm.requestSubmit();
        playSoundCue('command');
        updateHUDPreview('Sending question to AI Assistant...', true);
        return true;
      }

      // Check Intelligent Q&A
      const qInput = document.getElementById('question');
      if (qInput && qInput.value.trim()) {
        const askForm = document.getElementById('ask-form');
        if (askForm) askForm.requestSubmit();
        playSoundCue('command');
        updateHUDPreview('Analyzing question with AI Engine...', true);
        return true;
      }

      // Check Upload form
      const fileInput = document.getElementById('contract');
      if (fileInput && fileInput.files && fileInput.files.length > 0) {
        const upForm = document.getElementById('upload-form');
        if (upForm) upForm.requestSubmit();
        playSoundCue('command');
        updateHUDPreview('Analyzing uploaded contract...', true);
        return true;
      }
    }

    // 5. Input Clear / Reset Commands
    if (cmd === 'clear' || cmd === 'clear text' || cmd === 'clear question' || cmd === 'reset input') {
      if (currentTargetInput) {
        currentTargetInput.value = '';
        currentTargetInput.focus();
      } else {
        const qInput = document.getElementById('question');
        if (qInput) qInput.value = '';
        const cInput = document.getElementById('chatbot-input');
        if (cInput) cInput.value = '';
      }
      playSoundCue('command');
      updateHUDPreview('Cleared input field', true);
      return true;
    }

    // 6. Print Report Command
    if (cmd.includes('print report') || cmd === 'print') {
      const printBtn = document.getElementById('print-report-btn');
      if (printBtn) {
        printBtn.click();
        playSoundCue('command');
        updateHUDPreview('Opening print preview...', true);
        return true;
      }
    }

    // 7. Session Close Command
    if (cmd === 'close session' || cmd === 'new contract' || cmd === 'close contract') {
      const closeBtn = document.getElementById('new-contract');
      if (closeBtn) {
        closeBtn.click();
        playSoundCue('command');
        updateHUDPreview('Closed contract session', true);
        return true;
      }
    }

    // 8. Translation Commands (e.g. "translate to Tamil", "translate to Hindi")
    if (cmd.startsWith('translate to ') || cmd.startsWith('translate report to ')) {
      const langName = cmd.replace('translate report to ', '').replace('translate to ', '').trim();
      if (langName) {
        const capitalizedLang = langName.charAt(0).toUpperCase() + langName.slice(1);
        const langInput = document.getElementById('report-language');
        const transBtn = document.getElementById('translate-report-btn');
        if (langInput && transBtn) {
          langInput.value = capitalizedLang;
          transBtn.click();
          playSoundCue('command');
          updateHUDPreview(`Translating report to ${capitalizedLang}...`, true);
          return true;
        }
      }
    }

    // 9. Quick Suggestions
    if (cmd.includes('termination right') || cmd.includes('termination notice')) {
      if (typeof window.switchTab === 'function') window.switchTab('tab-qa');
      const qInput = document.getElementById('question');
      if (qInput) {
        qInput.value = 'What are the termination rights and notice periods?';
        const askForm = document.getElementById('ask-form');
        if (askForm) askForm.requestSubmit();
        playSoundCue('command');
        updateHUDPreview('Analyzing termination rights...', true);
        return true;
      }
    }

    if (cmd.includes('payment term') || cmd.includes('payment obligation')) {
      if (typeof window.switchTab === 'function') window.switchTab('tab-qa');
      const qInput = document.getElementById('question');
      if (qInput) {
        qInput.value = 'What are the payment obligations and deadlines?';
        const askForm = document.getElementById('ask-form');
        if (askForm) askForm.requestSubmit();
        playSoundCue('command');
        updateHUDPreview('Analyzing payment terms...', true);
        return true;
      }
    }

    if (cmd.includes('key risk') || cmd.includes('major risk') || cmd.includes('main risk')) {
      if (typeof window.switchTab === 'function') window.switchTab('tab-qa');
      const qInput = document.getElementById('question');
      if (qInput) {
        qInput.value = 'What are the major risks for the customer?';
        const askForm = document.getElementById('ask-form');
        if (askForm) askForm.requestSubmit();
        playSoundCue('command');
        updateHUDPreview('Analyzing key risks...', true);
        return true;
      }
    }

    return false;
  };

  // Initialize Speech Recognition
  function initSpeechRecognition() {
    if (!SpeechRecognition) {
      console.warn('SpeechRecognition API not available in this browser.');
      return null;
    }

    try {
      const rec = new SpeechRecognition();
      rec.continuous = false;
      rec.interimResults = true;
      rec.lang = 'en-US';

      rec.onstart = function () {
        isListening = true;
        wantListening = true;
        playSoundCue('start');
        showHUD(continuousMode
          ? 'Listening… speak freely, click the mic again to stop.'
          : (currentTargetInput ? `Dictating into ${currentTargetInput.id || 'field'}... Speak now.` : 'Listening for voice commands & questions...'));
        if (activeMicButton) {
          activeMicButton.classList.add('recording');
        }
        const statusInd = document.getElementById('voice-status-indicator');
        if (statusInd) statusInd.hidden = false;
      };

      rec.onresult = function (event) {
        let interimTranscript = '';
        let finalTranscript = '';

        for (let i = event.resultIndex; i < event.results.length; ++i) {
          const transcript = event.results[i][0].transcript;
          if (event.results[i].isFinal) {
            finalTranscript += transcript;
          } else {
            interimTranscript += transcript;
          }
        }

        const currentText = (finalTranscript || interimTranscript).trim();
        if (currentText) {
          if (continuousMode && finalTranscript.trim()) {
            finalAccum = (finalAccum + ' ' + finalTranscript.trim()).replace(/\s+/g, ' ').trim();
          }
          const shown = continuousMode
            ? (finalAccum + ' ' + interimTranscript).replace(/\s+/g, ' ').trim()
            : currentText;
          updateHUDPreview(shown);

          // Update target input if present
          if (currentTargetInput) {
            currentTargetInput.value = shown;
            // Dispatch input event for reactivity
            currentTargetInput.dispatchEvent(new Event('input', { bubbles: true }));
          }
        }

        // Check if final result is a command (skipped for pure dictation targets)
        if (finalTranscript.trim() && !dictateOnly) {
          const executed = window.executeVoiceCommand(finalTranscript);
          if (!executed && currentTargetInput) {
            // Keep the transcribed text in the input
            currentTargetInput.value = finalTranscript.trim();
            currentTargetInput.dispatchEvent(new Event('change', { bubbles: true }));
          }
        }
      };

      rec.onerror = function (event) {
        console.warn('Speech recognition error:', event.error);
        if (event.error === 'not-allowed') {
          alert('Microphone access was denied. Please allow microphone permissions in your browser settings to use voice input.');
        }
        stopListening();
      };

      rec.onend = function () {
        // Continuous mode: the browser ends recognition after each pause —
        // restart it until the user toggles the mic off.
        if (wantListening && continuousMode && recognition) {
          try {
            recognition.start();
            return;
          } catch (_) {}
        }
        stopListening();
      };

      return rec;
    } catch (e) {
      console.error('Error initializing SpeechRecognition:', e);
      return null;
    }
  }

  // Start voice listening.
  // options: { lang: BCP-47 tag for this session,
  //            commands: false for pure dictation (transcript is data),
  //            continuous: true to stay on across pauses until toggled off }
  function startListening(targetInput = null, button = null, options = {}) {
    if (!SpeechRecognition) {
      alert('Voice recognition is not supported in this browser. Please use Google Chrome, Microsoft Edge, or Safari.');
      return;
    }

    if (isListening) {
      stopListening();
      return;
    }

    currentTargetInput = targetInput;
    activeMicButton = button;
    sessionLang = (options && options.lang) || null;
    dictateOnly = !!(options && options.commands === false);
    continuousMode = !!(options && options.continuous);
    finalAccum = targetInput && targetInput.value ? targetInput.value.trim() : '';

    if (!recognition) {
      recognition = initSpeechRecognition();
    }

    if (recognition) {
      try {
        try {
          recognition.lang = sessionLang || 'en-US';
          recognition.continuous = continuousMode;
        } catch (_) {}
        recognition.start();
      } catch (err) {
        console.error('Error starting recognition:', err);
        // Retry with fresh instance
        recognition = initSpeechRecognition();
        try {
          recognition.lang = sessionLang || 'en-US';
          recognition.continuous = continuousMode;
        } catch (_) {}
        recognition.start();
      }
    }
  }

  // Stop voice listening
  function stopListening() {
    isListening = false;
    wantListening = false;
    sessionLang = null;
    dictateOnly = false;
    continuousMode = false;
    finalAccum = '';
    playSoundCue('stop');
    hideHUD();

    if (activeMicButton) {
      activeMicButton.classList.remove('recording');
      activeMicButton = null;
    }

    const allMics = document.querySelectorAll('.mic-btn, .voice-cmd-toggle-btn');
    allMics.forEach(btn => btn.classList.remove('recording'));

    const statusInd = document.getElementById('voice-status-indicator');
    if (statusInd) statusInd.hidden = true;

    if (recognition) {
      try {
        recognition.stop();
      } catch (_) {}
    }
  }

  // Bind to DOM elements
  function setupVoiceButtons() {
    // 1. Q&A Textarea Mic Button
    const qaMicBtn = document.getElementById('qa-mic-btn');
    const questionInput = document.getElementById('question');
    if (qaMicBtn && questionInput) {
      qaMicBtn.addEventListener('click', (e) => {
        e.preventDefault();
        startListening(questionInput, qaMicBtn);
      });
    }

    // 2. Chatbot Input Mic Button
    const chatMicBtn = document.getElementById('chatbot-mic-btn');
    const chatInput = document.getElementById('chatbot-input');
    if (chatMicBtn && chatInput) {
      chatMicBtn.addEventListener('click', (e) => {
        e.preventDefault();
        startListening(chatInput, chatMicBtn);
      });
    }

    // 3. Translation Language Input Mic Button
    const langMicBtn = document.getElementById('lang-mic-btn');
    const langInput = document.getElementById('report-language');
    if (langMicBtn && langInput) {
      langMicBtn.addEventListener('click', (e) => {
        e.preventDefault();
        startListening(langInput, langMicBtn);
      });
    }

    // 4. Global Voice Command Toggle Button
    const globalVoiceBtn = document.getElementById('global-voice-cmd-btn');
    if (globalVoiceBtn) {
      globalVoiceBtn.addEventListener('click', (e) => {
        e.preventDefault();
        // Listen globally for commands/Q&A
        const activeInput = document.activeElement && (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA')
          ? document.activeElement
          : (document.getElementById('question') || null);
        startListening(activeInput, globalVoiceBtn);
      });
    }

    // 5. In-form Stop button
    const stopBtn = document.getElementById('voice-stop-btn');
    if (stopBtn) {
      stopBtn.addEventListener('click', (e) => {
        e.preventDefault();
        stopListening();
      });
    }
  }

  // Initialize on DOM load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupVoiceButtons);
  } else {
    setupVoiceButtons();
  }

  // Expose global functions
  window.startVoiceInput = startListening;
  window.stopVoiceInput = stopListening;
})();
