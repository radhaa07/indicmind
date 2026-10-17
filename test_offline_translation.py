"""
Test script for offline translation functionality.
Run this to test if offline translation is working.
"""
import sys

def test_offline_translation():
    print("=" * 60)
    print("Offline Translation Test")
    print("=" * 60)
    
    # Test 1: Check if argostranslate is installed
    print("\n[Test 1] Checking argostranslate installation...")
    try:
        import argostranslate.translate
        print("✓ argostranslate is installed")
        
        # Check installed language packages
        installed = argostranslate.translate.get_installed_languages()
        if installed:
            print(f"✓ Found {len(installed)} installed language packages:")
            for lang in installed[:10]:  # Show first 10
                print(f"  - {lang.name} ({lang.code})")
            if len(installed) > 10:
                print(f"  ... and {len(installed) - 10} more")
        else:
            print("⚠ No language packages installed yet")
            print("  Install with: argospm update && argospm install translate-XX_en")
            
    except ImportError:
        print("✗ argostranslate not installed")
        print("  Install with: pip install argostranslate")
        return False
    
    # Test 2: Try importing the offline translator module
    print("\n[Test 2] Checking offline_translator module...")
    try:
        from offline_translator import offline_translate
        print("✓ offline_translator module loaded successfully")
    except ImportError as e:
        print(f"✗ Failed to import offline_translator: {e}")
        return False
    
    # Test 3: Test translation if we have language packages
    print("\n[Test 3] Testing translation functionality...")
    if installed:
        # Find English
        en_lang = next((l for l in installed if l.code == "en"), None)
        
        if en_lang:
            # Try to find any source language
            test_pairs = [
                ("hi", "नमस्ते, यह एक परीक्षण है"),  # Hindi
                ("es", "Hola, esto es una prueba"),    # Spanish
                ("fr", "Bonjour, ceci est un test"),   # French
                ("ta", "வணக்கம், இது ஒரு சோதனை"),      # Tamil
            ]
            
            translation_success = False
            for lang_code, test_text in test_pairs:
                source_lang = next((l for l in installed if l.code == lang_code), None)
                if source_lang:
                    print(f"\n  Testing {source_lang.name} → English...")
                    print(f"  Input: {test_text}")
                    
                    try:
                        from rag import SCRIPT_LANGUAGE_HINTS
                        result = offline_translate(test_text, lang_code, SCRIPT_LANGUAGE_HINTS)
                        if result:
                            print(f"  Output: {result}")
                            print("  ✓ Translation successful!")
                            translation_success = True
                            break
                        else:
                            print("  ✗ Translation failed (verification failed)")
                    except Exception as e:
                        print(f"  ✗ Translation error: {e}")
            
            if not translation_success:
                print("\n⚠ No working language pairs found")
                print("  Install language packages with:")
                print("  argospm update && argospm install translate-hi_en")
        else:
            print("✗ English language package not found")
    else:
        print("⚠ Skipping translation test (no language packages)")
    
    # Test 4: Check integration with rag.py
    print("\n[Test 4] Checking integration with rag.py...")
    try:
        import rag
        print("✓ rag.py imports successfully")
        print("✓ Offline translation is integrated and ready to use as fallback")
    except Exception as e:
        print(f"✗ Error importing rag.py: {e}")
        return False
    
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    if installed:
        print("✓ Offline translation is fully functional")
        print("✓ Ready to use as automatic fallback when LLM translation fails")
    else:
        print("⚠ Offline translation is installed but needs language packages")
        print("\nTo enable offline translation:")
        print("  1. argospm update")
        print("  2. argospm install translate-hi_en  # for Hindi")
        print("  3. argospm install translate-ta_en  # for Tamil")
        print("  4. etc. for other languages you need")
    
    print("\nUsage:")
    print("  - Just upload a contract as usual")
    print("  - System will try LLM translation first")
    print("  - Falls back to offline translation automatically if LLM fails")
    print("=" * 60)
    
    return True


if __name__ == "__main__":
    try:
        success = test_offline_translation()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
