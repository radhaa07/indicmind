/**
 * Text-to-Speech functionality for ContractLens
 */

let currentAudio = null;
let currentButton = null;

/**
 * Play text using TTS
 * @param {string} text - Text to convert to speech
 * @param {string} section - Section name (for caching)
 * @param {HTMLElement} button - The button element that triggered TTS
 */
async function playTTS(text, section, button) {
  try {
    // If audio is currently playing, stop it
    if (currentAudio && !currentAudio.paused) {
      stopTTS();
      // If clicking the same button, just stop (toggle behavior)
      if (currentButton === button) {
        return;
      }
    }

    // Update button state to loading
    button.disabled = true;
    const originalHTML = button.innerHTML;
    button.innerHTML = 'Generating...';

    // Request TTS generation
    const response = await fetch('/api/tts/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: text,
        language: 'en',
        section: section
      })
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'TTS generation failed');
    }

    const data = await response.json();

    // Create audio element and play
    currentAudio = new Audio(data.audio_url);
    currentButton = button;

    // Update button to show playing state
    button.innerHTML = '⏸️ Pause';
    button.disabled = false;

    // Play audio
    await currentAudio.play();

    // Handle audio events
    currentAudio.addEventListener('ended', () => {
      button.innerHTML = originalHTML;
      currentAudio = null;
      currentButton = null;
    });

    currentAudio.addEventListener('error', (e) => {
      console.error('Audio playback error:', e);
      button.innerHTML = originalHTML;
      button.disabled = false;
      alert('Audio playback failed. Please try again.');
    });

  } catch (error) {
    console.error('TTS Error:', error);
    button.disabled = false;
    button.innerHTML = 'Listen';
    alert(`TTS Error: ${error.message}`);
  }
}

/**
 * Stop current audio playback
 */
function stopTTS() {
  if (currentAudio) {
    currentAudio.pause();
    currentAudio.currentTime = 0;
    currentAudio = null;
  }
  if (currentButton) {
    currentButton.innerHTML = 'Listen';
    currentButton.disabled = false;
    currentButton = null;
  }
}

/**
 * Play executive summary TTS
 * @param {string} contractId - Contract ID
 * @param {HTMLElement} button - The button element
 */
async function playSummaryTTS(contractId, button) {
  try {
    // Stop any playing audio
    if (currentAudio && !currentAudio.paused) {
      stopTTS();
      if (currentButton === button) {
        return;
      }
    }

    button.disabled = true;
    const originalHTML = button.innerHTML;
    button.innerHTML = 'Generating...';

    // Speak the report's current language: when the report view is translated
    // the restore button is visible and the translate button reads "Translated: X".
    let reportLanguage = '';
    const restoreBtn = document.getElementById('restore-report-btn');
    const translateBtn = document.getElementById('translate-report-btn');
    if (restoreBtn && !restoreBtn.hidden && translateBtn) {
      const m = (translateBtn.textContent || '').match(/Translated:\s*(.+)/i);
      if (m) reportLanguage = m[1].trim();
    }

    const response = await fetch(`/api/contracts/${contractId}/tts/summary`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(reportLanguage ? { language: reportLanguage } : {})
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'TTS generation failed');
    }

    const data = await response.json();

    currentAudio = new Audio(data.audio_url);
    currentButton = button;

    button.innerHTML = '⏸️ Pause';
    button.disabled = false;

    await currentAudio.play();

    currentAudio.addEventListener('ended', () => {
      button.innerHTML = originalHTML;
      currentAudio = null;
      currentButton = null;
    });

    currentAudio.addEventListener('error', (e) => {
      console.error('Audio playback error:', e);
      button.innerHTML = originalHTML;
      button.disabled = false;
      alert('Audio playback failed.');
    });

  } catch (error) {
    console.error('Summary TTS Error:', error);
    button.disabled = false;
    button.innerHTML = 'Listen to Summary';
    alert(`TTS Error: ${error.message}`);
  }
}

// Export functions for use in app.js
window.playTTS = playTTS;
window.stopTTS = stopTTS;
window.playSummaryTTS = playSummaryTTS;
