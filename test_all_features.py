#!/usr/bin/env python3
"""
Test script for all ContractLens features
Run this to verify everything is working correctly
"""
import sys
import os

def test_imports():
    """Test all required imports"""
    print("🧪 Testing Imports...")
    
    try:
        import flask
        print("✅ Flask")
    except ImportError:
        print("❌ Flask not installed")
        return False
    
    try:
        import rag
        print("✅ RAG module")
    except ImportError:
        print("❌ RAG module import failed")
        return False
    
    try:
        from deep_translator import GoogleTranslator
        print("✅ Deep Translator")
    except ImportError:
        print("❌ deep-translator not installed")
        return False
    
    try:
        from gtts import gTTS
        print("✅ Google Text-to-Speech")
    except ImportError:
        print("❌ gTTS not installed")
        return False
    
    try:
        import offline_translator
        print("✅ Offline Translator module")
    except ImportError:
        print("❌ Offline translator module import failed")
        return False
    
    return True

def test_translation():
    """Test translation functionality"""
    print("\n🌍 Testing Translation...")
    
    try:
        from deep_translator import GoogleTranslator
        
        # Test Kannada translation
        translator = GoogleTranslator(source='kn', target='en')
        result = translator.translate('ನಮಸ್ಕಾರ')
        if result and 'hello' in result.lower():
            print("✅ Kannada translation working")
        else:
            print(f"⚠️  Kannada translation: {result}")
        
        return True
    except Exception as e:
        print(f"❌ Translation test failed: {e}")
        return False

def test_tts():
    """Test TTS functionality"""
    print("\n🔊 Testing Text-to-Speech...")
    
    try:
        from gtts import gTTS
        import tempfile
        
        # Test TTS generation
        tts = gTTS(text="ContractLens test", lang='en', slow=False)
        
        # Test with temporary file
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=True) as tmp:
            tts.save(tmp.name)
            print("✅ TTS generation working")
        
        return True
    except Exception as e:
        print(f"❌ TTS test failed: {e}")
        return False

def test_rag_functionality():
    """Test RAG functionality"""
    print("\n📝 Testing RAG Analysis...")
    
    try:
        from rag import ContractRAG, translate_to_english
        
        # Test with sample text
        sample_text = """
        SAMPLE AGREEMENT
        
        This Agreement is entered into between Party A and Party B.
        The effective date is January 1, 2024.
        Either party may terminate with 30 days notice.
        """
        
        # Test translation
        english_text, lang = translate_to_english(sample_text)
        print(f"✅ Translation: {lang}")
        
        # Test RAG creation
        rag = ContractRAG(english_text, "test_contract.txt")
        print("✅ RAG object creation")
        
        # Test analysis
        analysis = rag.run_contract_audit()
        if analysis and 'metadata' in analysis:
            print("✅ Contract audit working")
        else:
            print("⚠️  Contract audit returned incomplete data")
        
        # Test executive report
        report = rag.generate_executive_report(analysis)
        if report and len(report) > 100:
            print("✅ Executive report generation")
        else:
            print("⚠️  Executive report seems incomplete")
        
        return True
    except Exception as e:
        print(f"❌ RAG test failed: {e}")
        return False

def test_configuration():
    """Test configuration"""
    print("\n⚙️  Testing Configuration...")
    
    try:
        from dotenv import load_dotenv
        load_dotenv()
        
        provider = os.getenv('TRANSLATION_PROVIDER', 'auto')
        print(f"✅ Translation Provider: {provider}")
        
        if provider == 'offline':
            print("✅ Offline-only mode enabled")
        else:
            print("ℹ️  Auto mode (tries LLM first)")
        
        return True
    except Exception as e:
        print(f"❌ Configuration test failed: {e}")
        return False

def test_file_structure():
    """Test if all required files exist"""
    print("\n📁 Testing File Structure...")
    
    required_files = [
        'app.py',
        'rag.py',
        'offline_translator.py',
        'requirements.txt',
        '.env',
        'static/tts.js',
        'static/app.js',
        'static/style.css',
        'templates/index.html'
    ]
    
    all_exist = True
    for file in required_files:
        if os.path.exists(file):
            print(f"✅ {file}")
        else:
            print(f"❌ {file} missing")
            all_exist = False
    
    # Check cache directory
    if os.path.exists('tts_cache'):
        print("✅ tts_cache directory")
    else:
        print("ℹ️  tts_cache directory will be created on first use")
    
    return all_exist

def main():
    """Run all tests"""
    print("🎯 ContractLens Feature Test Suite")
    print("=" * 50)
    
    tests = [
        ("File Structure", test_file_structure),
        ("Imports", test_imports),
        ("Configuration", test_configuration),
        ("Translation", test_translation),
        ("Text-to-Speech", test_tts),
        ("RAG Analysis", test_rag_functionality)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} failed with exception: {e}")
            results.append((test_name, False))
    
    print("\n" + "=" * 50)
    print("📊 TEST RESULTS SUMMARY")
    print("=" * 50)
    
    passed = 0
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")
        if result:
            passed += 1
    
    print(f"\n🏆 Overall: {passed}/{len(results)} tests passed")
    
    if passed == len(results):
        print("\n🎉 ALL TESTS PASSED!")
        print("Your ContractLens application is ready to use!")
        print("\nTo start the application:")
        print("  python app.py")
    else:
        print(f"\n⚠️  {len(results) - passed} test(s) failed.")
        print("Please check the errors above and install missing dependencies.")
        print("\nTo install missing packages:")
        print("  pip install -r requirements.txt")
    
    return passed == len(results)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)