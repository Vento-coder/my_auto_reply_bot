import json
import os
from typing import Dict

class LanguageManager:
    def __init__(self):
        self.translations: Dict[str, Dict] = {}
        self.available_languages = ['uz', 'ru', 'en', 'tr', 'kz']
        self.load_translations()
    
    def load_translations(self):
        """Load all language files"""
        lang_dir = os.path.join(os.path.dirname(__file__), 'languages')
        for lang in self.available_languages:
            file_path = os.path.join(lang_dir, f"{lang}.json")
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.translations[lang] = json.load(f)
            except FileNotFoundError:
                print(f"Warning: Language file not found: {file_path}")
                self.translations[lang] = {}
    
    def get(self, lang: str, key_path: str, *args) -> str:
        """
        Get translation text by key path
        Example: get('uz', 'start.welcome')
        """
        if lang not in self.translations:
            lang = 'uz'  # Default to Uzbek
        
        keys = key_path.split('.')
        value = self.translations.get(lang, {})
        
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key, key_path)
            else:
                return key_path
        
        if isinstance(value, str):
            if args:
                return value.format(*args)
            return value
        
        return key_path
    
    def get_user_language(self, user_data) -> str:
        """Get user's preferred language"""
        if hasattr(user_data, 'language'):
            return user_data.language
        return 'uz'  # Default

# Global language manager instance
lang_manager = LanguageManager()
