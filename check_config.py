import os
from dotenv import load_dotenv

load_dotenv()

provider = os.getenv('TRANSLATION_PROVIDER', 'auto')

print()
print('Current Configuration:')
print(f'  TRANSLATION_PROVIDER = {provider}')
print()

if provider == 'offline':
    print('✅ Offline-only mode ENABLED')
    print('   Gemini/Ollama will be skipped for translation')
    print()
    print('⚠️  Next step: Install language packages')
    print('   Run: .\\FIX_TRANSLATION_NOW.bat')
else:
    print('⚠️  Auto mode (tries LLM first, then offline fallback)')
    print()
    print('To enable offline-only mode:')
    print('  Edit .env and set: TRANSLATION_PROVIDER=offline')

print()
print('Status: Configuration loaded successfully!')
